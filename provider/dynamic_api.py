"""Dynamic Music Assistant API catalog and guarded command dispatcher."""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import heapq
import inspect
import json
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from fastmcp.exceptions import ToolError
from mcp.shared.exceptions import McpError
from mcp.types import INVALID_REQUEST, METHOD_NOT_FOUND

from .command_policy import (
    CommandDecision,
    Confirmation,
    DynamicPolicy,
    DynamicRisk,
    ResultProjector,
    command_tags_visible,
    preflight_command,
    resolve_command_policy,
)
from .command_profiles import (
    COMMAND_PROFILES,
    LEGACY_COMMAND_MAPPINGS,
    CommandProfile,
    LegacyMigration,
    aliases_by_command,
)
from .dynamic_serialization import json_value
from .dynamic_signatures import (
    CompiledSignature,
    UnsupportedSignatureError,
    compile_signature,
)

if TYPE_CHECKING:
    from fastmcp import Context
    from fastmcp.server.auth import AccessToken

_ALIASES_BY_COMMAND = aliases_by_command()

_DENIED_COMMANDS = frozenset({"dashboard/register", "dashboard/unregister"})
_DENIED_COMMAND_PREFIXES = ("auth/",)
_COMPACT_ITEMS = 25
_FULL_ITEMS = 200
_COMPACT_BYTES = 12_288
_FULL_BYTES = 65_536
_COMPACT_STRING = 2_048
_FULL_STRING = 8_192
_CALL_TIMEOUT_SECONDS = 60
CATALOG_REVISION = 1

type CatalogFingerprint = tuple[int, str, tuple[tuple[str, int], ...]]


def _command_error(command: str, exc: Exception) -> ToolError:
    """Return an actionable execution error for a canonical command."""
    detail = str(exc).strip() or type(exc).__name__
    return ToolError(f"Command {command!r} failed: {detail}")


async def confirm_or_raise(ctx: Context | None, prompt: str, *, required: bool) -> None:
    """Ask the MCP client to confirm an operation when elicitation is available."""
    if ctx is None:
        if required:
            raise ToolError("Client confirmation is required for this operation")
        return
    try:
        result = await ctx.elicit(prompt, response_type=bool)  # type: ignore[arg-type, unused-ignore]
    except NotImplementedError:
        if required:
            raise ToolError("Client confirmation is required for this operation") from None
        return
    except McpError as exc:
        if exc.error.code in (INVALID_REQUEST, METHOD_NOT_FOUND):
            if required:
                raise ToolError("Client confirmation is required for this operation") from exc
            return
        raise
    if getattr(result, "action", None) != "accept" or not getattr(result, "data", None):
        raise ToolError("Operation cancelled by user")


@dataclass(frozen=True, slots=True)
class DynamicEntry:
    """One visible dynamic MA command."""

    name: str
    command: str
    description: str
    input_schema: dict[str, Any]
    risk: DynamicRisk
    required_scope: str | None
    allow_impersonation: bool
    handler: Any
    search_aliases: tuple[str, ...] = ()
    output_schema: dict[str, Any] | None = None
    annotations: dict[str, bool] = dataclasses.field(default_factory=dict)
    profile: CommandProfile | None = None
    compiled_signature: CompiledSignature | None = None
    decision: CommandDecision | None = None


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    """Compiled descriptors for one live command-registry generation."""

    fingerprint: CatalogFingerprint
    entries: tuple[DynamicEntry, ...]


@dataclass(frozen=True, slots=True)
class CatalogView:
    """Request-filtered catalog entries from one base snapshot."""

    fingerprint: CatalogFingerprint
    entries: tuple[DynamicEntry, ...]


@dataclass(slots=True)
class DynamicCatalogDiagnostics:
    """Last live-registry inspection state exposed through debug health."""

    available: bool = False
    registry_type: str = "missing"
    handlers_seen: int = 0
    handlers_visible: int = 0
    incompatible_handlers: tuple[str, ...] = ()
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class _SnapshotDiagnostics:
    """Cached compatibility results from one base snapshot build."""

    available: bool
    registry_type: str
    handlers_seen: int
    handlers_visible: int
    incompatible_handlers: tuple[str, ...]
    last_error: str | None


@dataclass(slots=True)
class _ListReductionCandidate:
    """Mutable heap state for one list in a response-reduction trial."""

    items: list[Any]
    depth: int
    order: int
    active: bool = True
    revision: int = 0


class DynamicAPIAdapter:
    """Discover, authorize and execute MA command handlers at request time."""

    def __init__(
        self,
        mass: Any,
        *,
        policy_provider: Callable[[], DynamicPolicy],
        auth_required_provider: Callable[[], bool],
        confirmation_provider: Callable[[], bool],
        token_provider: Callable[[], AccessToken | None],
        scope_checker: Callable[[Any, Any], bool] | None = None,
        allowed_tags_provider: Callable[[], set[str]] | None = None,
    ) -> None:
        """Initialise the adapter with request-aware policy providers."""
        self.mass = mass
        self._policy_provider = policy_provider
        self._auth_required_provider = auth_required_provider
        self._confirmation_provider = confirmation_provider
        self._token_provider = token_provider
        self._scope_checker = scope_checker or self._default_scope_checker
        self._allowed_tags_provider = allowed_tags_provider or (lambda: set())
        self._snapshot: CatalogSnapshot | None = None
        self._snapshot_diagnostics: _SnapshotDiagnostics | None = None
        self._snapshot_lock = asyncio.Lock()
        self._diagnostics = DynamicCatalogDiagnostics()

    def diagnostics(self) -> dict[str, Any]:
        """Return a JSON-safe snapshot of dynamic-catalog compatibility."""
        return dataclasses.asdict(self._diagnostics)

    async def base_snapshot(self) -> CatalogSnapshot:
        """Return the compiled snapshot for the current live command registry."""
        fingerprint = self._registry_fingerprint()
        if self._snapshot is not None and self._snapshot.fingerprint == fingerprint:
            return self._snapshot
        async with self._snapshot_lock:
            fingerprint = self._registry_fingerprint()
            if self._snapshot is None or self._snapshot.fingerprint != fingerprint:
                snapshot, diagnostics = self._compile_snapshot(fingerprint)
                self._snapshot = snapshot
                self._snapshot_diagnostics = diagnostics
                self._publish_snapshot_diagnostics()
            return self._snapshot

    async def visible_catalog(self) -> CatalogView:
        """Return a request-filtered view of the current base snapshot."""
        snapshot = await self.base_snapshot()
        auth = await self._authentication()
        if not self._auth_required_provider() or auth is None:
            return CatalogView(snapshot.fingerprint, ())

        user = auth[1]
        policy = self._policy_provider()
        allowed_tags = self._allowed_tags_provider()
        entries = [
            entry
            for entry in snapshot.entries
            if (
                entry.required_scope is None
                or self._scope_checker(user, getattr(entry.handler, "required_scope", None))
            )
            and policy.allows(entry.risk)
            and entry.decision is not None
            and command_tags_visible(entry.decision, allowed_tags)
        ]
        visible = tuple(sorted(entries, key=lambda entry: entry.name))
        return CatalogView(snapshot.fingerprint, visible)

    async def visible_entries(self) -> list[DynamicEntry]:
        """Return canonical commands visible to the current authenticated user."""
        return list((await self.visible_catalog()).entries)

    async def get_visible_entry(self, name: str) -> DynamicEntry | None:
        """Resolve one visible entry by canonical public name."""
        return next(
            (entry for entry in await self.visible_entries() if entry.name == name),
            None,
        )

    async def call(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        response_mode: str,
        fields: list[str] | None,
        max_items: int | None,
        ctx: Context,
    ) -> dict[str, Any]:
        """Strictly parse, execute and bound one visible MA API command."""
        if response_mode not in {"compact", "full"}:
            raise ToolError("response_mode must be 'compact' or 'full'")
        entry = await self.get_visible_entry(name)
        if entry is None:
            raise ToolError(f"Tool {name!r} not found or not permitted")
        auth = await self._authentication()
        if auth is None and self._auth_required_provider():
            raise ToolError("Authentication is required")

        call_arguments = dict(arguments)
        if entry.profile is not None:
            try:
                call_arguments = entry.profile.convert_arguments(call_arguments)
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
        impersonated = call_arguments.pop("user", None) if entry.allow_impersonation else None
        impersonating = bool(impersonated)
        try:
            if entry.compiled_signature is None:
                raise ValueError(f"Tool {entry.name!r} has no compiled signature")
            parsed = entry.compiled_signature.parse(call_arguments)
        except (KeyError, TypeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

        entry, impersonated_user, _result_projector = await self._authorize_call(
            entry,
            auth,
            parsed,
            impersonated=impersonated,
        )
        await self._confirm(entry, ctx, impersonating=impersonating)
        auth = await self._authentication(revalidate=True)
        if auth is None and self._auth_required_provider():
            raise ToolError("Authentication is required")
        entry, impersonated_user, result_projector = await self._authorize_call(
            entry,
            auth,
            parsed,
            impersonated=impersonated,
        )

        try:
            async with asyncio.timeout(_CALL_TIMEOUT_SECONDS):
                result = await self._execute(entry, parsed, auth, impersonated_user)
                if result_projector is not None:
                    result = result_projector(result)
        except TimeoutError as exc:
            raise ToolError(f"Command {entry.command!r} timed out") from exc
        except ToolError:
            raise
        except Exception as exc:
            raise _command_error(entry.command, exc) from exc
        return self._bounded_envelope(
            name,
            result,
            response_mode=response_mode,
            fields=fields,
            max_items=max_items,
            profile=entry.profile,
        )

    def _registry_fingerprint(self) -> CatalogFingerprint:
        """Fingerprint the actual live command-handler registry."""
        handlers = getattr(self.mass, "command_handlers", {})
        registry_type = type(handlers)
        registry_kind = (
            f"{'mapping' if isinstance(handlers, Mapping) else 'invalid'}:"
            f"{registry_type.__module__}.{registry_type.__qualname__}"
        )
        if not isinstance(handlers, Mapping):
            return CATALOG_REVISION, registry_kind, ()
        return (
            CATALOG_REVISION,
            registry_kind,
            tuple(sorted((command, id(handler)) for command, handler in handlers.items())),
        )

    def _compile_snapshot(
        self, fingerprint: CatalogFingerprint
    ) -> tuple[CatalogSnapshot, _SnapshotDiagnostics]:
        """Compile the base descriptors and compatibility errors atomically."""
        handlers = getattr(self.mass, "command_handlers", {})
        if not isinstance(handlers, Mapping):
            return CatalogSnapshot(fingerprint, ()), _SnapshotDiagnostics(
                available=False,
                registry_type=type(handlers).__name__,
                handlers_seen=0,
                handlers_visible=0,
                incompatible_handlers=(),
                last_error="mass.command_handlers is not a mapping",
            )

        entries: list[DynamicEntry] = []
        incompatible: list[str] = []
        for command, handler in sorted(handlers.items()):
            if self._command_is_denied(command):
                continue
            if not self._handler_is_discoverable(command, handler):
                incompatible.append(str(command))
                continue
            scope = getattr(handler, "required_scope", None)
            profile = COMMAND_PROFILES.get(command)
            decision = resolve_command_policy(command, scope, profile)
            try:
                entries.append(self._compile_entry(command, handler, decision))
            except UnsupportedSignatureError:
                incompatible.append(str(command))
        incompatible_handlers = tuple(sorted(incompatible))
        diagnostics = _SnapshotDiagnostics(
            available=True,
            registry_type=type(handlers).__name__,
            handlers_seen=len(handlers),
            handlers_visible=len(entries),
            incompatible_handlers=incompatible_handlers,
            last_error=(
                f"{len(incompatible)} incompatible handler(s) skipped" if incompatible else None
            ),
        )
        return CatalogSnapshot(
            fingerprint,
            tuple(sorted(entries, key=lambda entry: entry.name)),
        ), diagnostics

    def _publish_snapshot_diagnostics(self) -> None:
        """Expose only caller-independent compatibility diagnostics."""
        diagnostics = self._snapshot_diagnostics
        if diagnostics is None:
            return
        self._diagnostics = DynamicCatalogDiagnostics(
            available=diagnostics.available,
            registry_type=diagnostics.registry_type,
            handlers_seen=diagnostics.handlers_seen,
            handlers_visible=diagnostics.handlers_visible,
            incompatible_handlers=diagnostics.incompatible_handlers,
            last_error=diagnostics.last_error,
        )

    async def _authentication(
        self,
        *,
        revalidate: bool = False,
    ) -> tuple[AccessToken, Any] | None:
        """Resolve the MCP access token to an enabled MA user."""
        token = self._token_provider()
        if token is None:
            return None
        if revalidate:
            try:
                user = await self.mass.webserver.auth.authenticate_with_token(token.token)
            except Exception:
                return None
            if getattr(user, "user_id", None) != token.client_id:
                return None
        else:
            user = self.mass.webserver.auth.get_user(token.client_id)
            if inspect.isawaitable(user):
                user = await user
        if user is None or getattr(user, "enabled", True) is False:
            return None
        return token, user

    @staticmethod
    def _command_is_denied(command: str) -> bool:
        """Return whether a command crosses an intentionally hidden boundary."""
        return command in _DENIED_COMMANDS or command.startswith(_DENIED_COMMAND_PREFIXES)

    @classmethod
    def _handler_is_discoverable(cls, command: str, handler: Any) -> bool:
        """Reject aliases, auth boundaries, and transport internals."""
        return bool(
            not cls._command_is_denied(command)
            and getattr(handler, "authenticated", True)
            and not getattr(handler, "alias", False)
            and callable(getattr(handler, "target", None))
            and isinstance(getattr(handler, "signature", None), inspect.Signature)
            and isinstance(getattr(handler, "type_hints", None), Mapping)
        )

    @classmethod
    def _compile_entry(cls, command: str, handler: Any, decision: CommandDecision) -> DynamicEntry:
        """Compile a live MA handler into a catalog entry."""
        scope = getattr(handler, "required_scope", None)
        profile = COMMAND_PROFILES.get(command)
        compiled_signature = compile_signature(
            handler.signature,
            handler.type_hints,
            allow_extra_kwargs=profile.allow_extra_kwargs if profile is not None else False,
        )
        return DynamicEntry(
            name=f"ma_api:{command}",
            command=command,
            description=cls._description(handler.target, command),
            input_schema=cls._entry_input_schema(
                compiled_signature.input_schema,
                profile,
                allow_impersonation=bool(getattr(handler, "allow_impersonation", False)),
            ),
            risk=decision.risk,
            required_scope=str(getattr(scope, "value", scope)) if scope is not None else None,
            allow_impersonation=bool(getattr(handler, "allow_impersonation", False)),
            handler=handler,
            search_aliases=(
                profile.search_aliases
                if profile is not None
                else _ALIASES_BY_COMMAND.get(command, ())
            ),
            output_schema=compiled_signature.output_schema(),
            annotations=dict(decision.annotations),
            profile=profile,
            compiled_signature=compiled_signature,
            decision=decision,
        )

    @staticmethod
    def _description(target: Callable[..., Any], command: str) -> str:
        """Extract a compact first paragraph from the handler docstring."""
        doc = inspect.getdoc(target) or ""
        paragraph = doc.split("\n\n", 1)[0].replace("\n", " ").strip()
        return paragraph or f"Music Assistant API command {command}."

    @staticmethod
    def _entry_input_schema(
        input_schema: Mapping[str, Any],
        profile: CommandProfile | None,
        *,
        allow_impersonation: bool,
    ) -> dict[str, Any]:
        """Add provider-owned aliases and impersonation to a compiled input schema."""
        schema = dict(input_schema)
        properties = dict(schema["properties"])
        schema["properties"] = properties
        required = list(schema.get("required", []))
        alias_requirements: list[dict[str, Any]] = []
        if profile is not None:
            for alias, canonical in profile.argument_aliases.items():
                canonical_schema = properties.get(canonical)
                if canonical_schema is None:
                    continue
                properties[alias] = {
                    **canonical_schema,
                    "description": f"Compatibility alias for {canonical!r}.",
                }
                if canonical in required:
                    required.remove(canonical)
                    alias_requirements.append(
                        {"anyOf": [{"required": [canonical]}, {"required": [alias]}]}
                    )
        if allow_impersonation:
            properties["user"] = {
                "type": "string",
                "description": "Optional MA user id or username to impersonate.",
            }
        if required:
            schema["required"] = required
        else:
            schema.pop("required", None)
        if alias_requirements:
            schema["allOf"] = alias_requirements
        return schema

    async def _confirm(
        self,
        entry: DynamicEntry,
        ctx: Context,
        *,
        impersonating: bool = False,
        confirmation: Confirmation | None = None,
    ) -> None:
        """Apply the resolved confirmation mode and impersonation guard."""
        confirmation = confirmation or (
            entry.decision.confirmation
            if entry.decision is not None
            else Confirmation.ALWAYS
            if entry.risk is DynamicRisk.SYSTEM
            else Confirmation.CONFIGURED
            if entry.risk is DynamicRisk.WRITE
            else Confirmation.NEVER
        )
        required = impersonating or confirmation is Confirmation.ALWAYS
        optional = confirmation is Confirmation.CONFIGURED and self._confirmation_provider()
        if required:
            await confirm_or_raise(ctx, f"Run {entry.name} ({entry.risk.value})?", required=True)
        elif optional:
            await confirm_or_raise(ctx, f"Run {entry.name} ({entry.risk.value})?", required=False)

    async def _execute(
        self,
        entry: DynamicEntry,
        parsed: dict[str, Any],
        auth: tuple[AccessToken, Any] | None,
        impersonated_user: Any | None,
    ) -> Any:
        """Execute under MA's own request context and collect generators."""
        context_tokens = self._set_auth_context(auth)
        try:
            if impersonated_user is not None:
                from music_assistant.controllers.webserver.helpers import (  # noqa: PLC0415
                    auth_middleware,
                )

                variable = auth_middleware.impersonated_user
                context_tokens.append((variable, variable.set(impersonated_user)))
            result = entry.handler.target(**parsed)
            if inspect.isawaitable(result):
                result = await result
            if inspect.isasyncgen(result):
                return await self._collect_generator(result)
            return result
        finally:
            for variable, token in reversed(context_tokens):
                variable.reset(token)

    def _reauthorize_entry(
        self,
        entry: DynamicEntry,
        auth: tuple[AccessToken, Any] | None,
    ) -> DynamicEntry:
        """Repeat live handler, scope, policy and tag checks before execution."""
        handlers = getattr(self.mass, "command_handlers", {})
        handler = handlers.get(entry.command) if isinstance(handlers, Mapping) else None
        if handler is None or handler is not entry.handler:
            raise ToolError(f"Tool {entry.name!r} not found or not permitted")
        if not self._handler_is_discoverable(entry.command, handler):
            raise ToolError(f"Tool {entry.name!r} not found or not permitted")
        if auth is None:
            raise ToolError("Authentication is required")
        scope = getattr(handler, "required_scope", None)
        if scope is not None and not self._scope_checker(auth[1], scope):
            raise ToolError(f"Tool {entry.name!r} not found or not permitted")
        profile = COMMAND_PROFILES.get(entry.command)
        decision = resolve_command_policy(entry.command, scope, profile)
        if not self._policy_provider().allows(decision.risk) or not command_tags_visible(
            decision, self._allowed_tags_provider()
        ):
            raise ToolError(f"Tool {entry.name!r} not found or not permitted")
        return dataclasses.replace(
            entry,
            risk=decision.risk,
            annotations=dict(decision.annotations),
            decision=decision,
        )

    async def _preflight(
        self,
        decision: CommandDecision,
        arguments: Mapping[str, Any],
        auth: tuple[AccessToken, Any] | None,
    ) -> ResultProjector | None:
        """Run request-dependent policy checks under the current MA auth context."""
        context_tokens = self._set_auth_context(auth)
        try:
            return await preflight_command(
                self.mass,
                decision,
                arguments,
                self._allowed_tags_provider(),
            )
        finally:
            for variable, token in reversed(context_tokens):
                variable.reset(token)

    async def _authorize_call(
        self,
        entry: DynamicEntry,
        auth: tuple[AccessToken, Any] | None,
        arguments: Mapping[str, Any],
        *,
        impersonated: Any,
    ) -> tuple[DynamicEntry, Any | None, ResultProjector | None]:
        """Refresh authorization, impersonation, target filters and request preflight."""
        entry = self._reauthorize_entry(entry, auth)
        impersonated_user = (
            await self._resolve_impersonated_user(auth, str(impersonated)) if impersonated else None
        )
        if impersonated_user is not None:
            self._enforce_target_filters(impersonated_user, arguments)
        elif auth is not None:
            self._enforce_target_filters(auth[1], arguments)
        decision = entry.decision
        if decision is None:
            decision = resolve_command_policy(entry.command, entry.required_scope, entry.profile)
        result_projector = await self._preflight(decision, arguments, auth)
        return entry, impersonated_user, result_projector

    async def _resolve_impersonated_user(
        self,
        auth: tuple[AccessToken, Any] | None,
        requested_user: str,
    ) -> Any:
        """Resolve and authorize an impersonated identity before elicitation."""
        context_tokens = self._set_auth_context(auth)
        try:
            from music_assistant.controllers.webserver.helpers import (  # noqa: PLC0415
                auth_middleware,
            )

            return await auth_middleware.resolve_impersonated_user(self.mass, requested_user)
        except Exception as exc:
            raise ToolError(f"Unable to impersonate requested user: {exc}") from exc
        finally:
            for variable, token in reversed(context_tokens):
                variable.reset(token)

    @staticmethod
    def _enforce_target_filters(user: Any, arguments: Mapping[str, Any]) -> None:
        """Reject direct target identifiers outside the current user's filters."""
        if str(getattr(user, "role", "")).casefold() == "admin":
            return
        targets = (
            (
                getattr(user, "player_filter", None),
                ("player_id", "queue_id", "target_player", "source_player"),
                ("player_ids", "queue_ids"),
            ),
            (
                getattr(user, "provider_filter", None),
                (
                    "instance_id",
                    "provider_instance_id",
                    "provider_instance_or_domain",
                    "provider_filter",
                ),
                ("providers", "provider_instance_ids"),
            ),
        )
        for allowed, scalar_keys, sequence_keys in targets:
            if not isinstance(allowed, list | tuple | set | frozenset) or not allowed:
                continue
            allowed_values = {str(value) for value in allowed}
            requested = {
                str(arguments[key]) for key in scalar_keys if arguments.get(key) is not None
            }
            for key in sequence_keys:
                value = arguments.get(key)
                if isinstance(value, str):
                    requested.add(value)
                elif isinstance(value, Sequence):
                    requested.update(str(item) for item in value)
            if not requested.issubset(allowed_values):
                raise ToolError("Command target is not permitted for the current user")

    @staticmethod
    def _set_auth_context(
        auth: tuple[AccessToken, Any] | None,
    ) -> list[tuple[Any, Any]]:
        """Set task-local MA authentication context variables."""
        try:
            from music_assistant.controllers.webserver.helpers import (  # noqa: PLC0415
                auth_middleware,
            )
        except ImportError:
            return []
        token, user = auth if auth is not None else (None, None)
        values = {
            "current_user": user,
            "current_token": getattr(token, "token", None),
            "current_client_id": getattr(token, "client_id", None),
        }
        context_tokens: list[tuple[Any, Any]] = []
        for name, value in values.items():
            variable = getattr(auth_middleware, name, None)
            if variable is not None and hasattr(variable, "set"):
                context_tokens.append((variable, variable.set(value)))
        return context_tokens

    @staticmethod
    async def _collect_generator(generator: AsyncGenerator[Any, Any]) -> list[Any]:
        """Collect an API async generator; response bounding happens afterwards."""
        values: list[Any] = []
        try:
            async for value in generator:
                values.append(value)
                if len(values) > _FULL_ITEMS:
                    break
        finally:
            await generator.aclose()
        return values

    @classmethod
    def _bounded_envelope(
        cls,
        name: str,
        result: Any,
        *,
        response_mode: str,
        fields: list[str] | None,
        max_items: int | None,
        profile: CommandProfile | None = None,
    ) -> dict[str, Any]:
        """Return a deterministic, JSON-safe response inside the mode budget."""
        compact = response_mode == "compact"
        item_cap = _COMPACT_ITEMS if compact else _FULL_ITEMS
        if max_items is not None:
            item_cap = max(1, min(item_cap, int(max_items)))
        byte_cap = _COMPACT_BYTES if compact else _FULL_BYTES
        string_cap = _COMPACT_STRING if compact else _FULL_STRING
        raw = json_value(result)
        total_count = len(raw) if isinstance(raw, list) else None
        if compact and profile is not None:
            raw = profile.project_compact(raw)
        data = cls._project_fields(raw, fields)
        data, truncated = cls._limit_nested_items(data, item_cap)
        data, value_truncated = cls._truncate_value(data, string_cap, depth=6 if compact else 12)
        truncated |= value_truncated
        envelope: dict[str, Any] = {
            "command": name,
            "data": data,
            "truncated": truncated,
            "returned_count": len(data) if isinstance(data, list) else (0 if data is None else 1),
            "bytes": 0,
            "applied": {
                "mode": response_mode,
                "fields": fields or [],
                "max_items": item_cap,
            },
        }
        if total_count is not None:
            envelope["total_count"] = total_count
        cls._fit_bytes(envelope, byte_cap)
        cls._set_measured_bytes(envelope)
        if envelope["bytes"] > byte_cap:
            mode = str(envelope["applied"]["mode"])
            raise ToolError(f"Response exceeds the {mode} byte budget")
        return envelope

    @classmethod
    def _limit_nested_items(cls, value: Any, item_cap: int) -> tuple[Any, bool]:
        """Apply the mode item cap to every nested list, not only the root."""
        if isinstance(value, list):
            kept = value[:item_cap]
            list_nested = [cls._limit_nested_items(item, item_cap) for item in kept]
            return [item for item, _changed in list_nested], len(value) > item_cap or any(
                changed for _item, changed in list_nested
            )
        if isinstance(value, dict):
            dict_nested = {
                key: cls._limit_nested_items(item, item_cap) for key, item in value.items()
            }
            return (
                {key: item for key, (item, _changed) in dict_nested.items()},
                any(changed for _item, changed in dict_nested.values()),
            )
        return value, False

    @staticmethod
    def _project_fields(value: Any, fields: list[str] | None) -> Any:
        """Retain requested top-level fields from dicts or list items."""
        if not fields:
            return value
        selected = set(fields)
        if isinstance(value, dict):
            return {key: item for key, item in value.items() if key in selected}
        if isinstance(value, list):
            return [
                {key: item for key, item in row.items() if key in selected}
                if isinstance(row, dict)
                else row
                for row in value
            ]
        return value

    @classmethod
    def _truncate_value(cls, value: Any, string_cap: int, *, depth: int) -> tuple[Any, bool]:
        """Bound nested depth and leaf strings while preserving JSON shape."""
        if depth <= 0 and isinstance(value, dict | list):
            return "[truncated]", True
        if isinstance(value, str) and len(value) > string_cap:
            return value[:string_cap] + "…", True
        if isinstance(value, list):
            list_items = [cls._truncate_value(item, string_cap, depth=depth - 1) for item in value]
            return [item for item, _changed in list_items], any(
                changed for _item, changed in list_items
            )
        if isinstance(value, dict):
            dict_items = {
                key: cls._truncate_value(item, string_cap, depth=depth - 1)
                for key, item in value.items()
            }
            return (
                {key: item for key, (item, _changed) in dict_items.items()},
                any(changed for _item, changed in dict_items.values()),
            )
        return value, False

    @classmethod
    def _fit_bytes(cls, envelope: dict[str, Any], byte_cap: int) -> None:
        """Apply the original global list-reduction policy within the byte cap."""
        envelope["bytes"] = byte_cap
        if cls._encoded_size(envelope) <= byte_cap:
            return

        original_data = envelope["data"]
        max_removals = cls._count_list_items(original_data)
        if max_removals:
            envelope["truncated"] = True
            smallest_data = cls._simulate_list_removals(original_data, max_removals)
            envelope["data"] = smallest_data
            cls._set_returned_count(envelope)
            if cls._encoded_size(envelope) <= byte_cap:
                low = 1
                high = max_removals
                best_data = smallest_data
                while low < high:
                    midpoint = (low + high) // 2
                    candidate_data = cls._simulate_list_removals(original_data, midpoint)
                    envelope["data"] = candidate_data
                    cls._set_returned_count(envelope)
                    if cls._encoded_size(envelope) <= byte_cap:
                        high = midpoint
                        best_data = candidate_data
                    else:
                        low = midpoint + 1
                envelope["data"] = best_data
                cls._set_returned_count(envelope)
                return

        envelope["data"] = cls._minimal_json_shape(original_data)
        envelope["truncated"] = True
        cls._set_returned_count(envelope)
        envelope.pop("total_count", None)
        if cls._encoded_size(envelope) <= byte_cap:
            return
        envelope["applied"]["fields"] = []
        if cls._encoded_size(envelope) <= byte_cap:
            return
        mode = str(envelope["applied"]["mode"])
        raise ToolError(f"Response exceeds the {mode} byte budget")

    @classmethod
    def _simulate_list_removals(cls, value: Any, removals: int) -> Any:
        """Return a copy after a bounded number of original-policy list removals."""
        reduced = copy.deepcopy(value)
        candidates: list[_ListReductionCandidate] = []
        candidates_by_id: dict[int, _ListReductionCandidate] = {}
        heap: list[tuple[int, int, int, int, int]] = []

        def collect(item: Any, depth: int) -> None:
            if isinstance(item, list):
                candidate_index = len(candidates)
                candidate = _ListReductionCandidate(item, depth, candidate_index)
                candidates.append(candidate)
                candidates_by_id[id(item)] = candidate
                if item:
                    heap.append(
                        (-len(item), depth, candidate.order, candidate.revision, candidate_index)
                    )
                for child in item:
                    collect(child, depth + 1)
            elif isinstance(item, dict):
                for child in item.values():
                    collect(child, depth + 1)

        def invalidate(item: Any) -> None:
            if isinstance(item, list):
                candidate = candidates_by_id.get(id(item))
                if candidate is not None:
                    candidate.active = False
                    candidate.revision += 1
                for child in item:
                    invalidate(child)
            elif isinstance(item, dict):
                for child in item.values():
                    invalidate(child)

        collect(reduced, 0)
        heapq.heapify(heap)
        removed = 0
        while removed < removals and heap:
            negative_length, _depth, _order, revision, candidate_index = heapq.heappop(heap)
            candidate = candidates[candidate_index]
            if (
                not candidate.active
                or candidate.revision != revision
                or len(candidate.items) != -negative_length
            ):
                continue
            removed_item = candidate.items.pop()
            removed += 1
            invalidate(removed_item)
            candidate.revision += 1
            if candidate.items:
                heapq.heappush(
                    heap,
                    (
                        -len(candidate.items),
                        candidate.depth,
                        candidate.order,
                        candidate.revision,
                        candidate_index,
                    ),
                )
        return reduced

    @classmethod
    def _count_list_items(cls, value: Any) -> int:
        """Return a safe upper bound on logical removals for a JSON tree."""
        if isinstance(value, list):
            return len(value) + sum(cls._count_list_items(item) for item in value)
        if isinstance(value, dict):
            return sum(cls._count_list_items(item) for item in value.values())
        return 0

    @staticmethod
    def _minimal_json_shape(value: Any) -> Any:
        """Return the smallest JSON value retaining the result's top-level type."""
        if isinstance(value, dict):
            return {}
        if isinstance(value, list):
            return []
        if isinstance(value, str):
            return ""
        if isinstance(value, bool):
            return False
        if isinstance(value, int | float):
            return 0
        return None

    @staticmethod
    def _set_returned_count(envelope: dict[str, Any]) -> None:
        """Refresh the envelope's top-level returned item count."""
        data = envelope["data"]
        envelope["returned_count"] = (
            len(data) if isinstance(data, list) else (0 if data is None else 1)
        )

    @staticmethod
    def _encoded_size(value: Any) -> int:
        """Measure the compact UTF-8 JSON representation."""
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())

    @classmethod
    def _set_measured_bytes(cls, envelope: dict[str, Any]) -> None:
        """Stabilize the self-referential encoded byte count."""
        for _attempt in range(3):
            measured = cls._encoded_size(envelope)
            if envelope["bytes"] == measured:
                return
            envelope["bytes"] = measured

    @staticmethod
    def _default_scope_checker(user: Any, scope: Any) -> bool:
        """Delegate authorization to MA's current scope implementation."""
        from music_assistant.controllers.webserver.helpers.auth_middleware import (  # noqa: PLC0415
            has_scope,
        )

        return bool(has_scope(user, scope))


LEGACY_MIGRATIONS: Mapping[str, LegacyMigration] = MappingProxyType(
    {
        **LEGACY_COMMAND_MAPPINGS,
    }
)
