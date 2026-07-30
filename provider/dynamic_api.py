"""Dynamic Music Assistant API catalog and guarded command dispatcher."""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastmcp.exceptions import ToolError

from .command_profiles import (
    COMMAND_PROFILES,
    CURATED_RECIPE_SCOPES,
    CURATED_RECIPE_SOURCES,
    CommandProfile,
    aliases_by_command,
    legacy_migrations,
)
from .dynamic_serialization import json_value
from .dynamic_signatures import (
    CompiledSignature,
    UnsupportedSignatureError,
    compile_signature,
)
from .middleware import tags_visible
from .tools._common import confirm_or_raise

if TYPE_CHECKING:
    from fastmcp import Context
    from fastmcp.server.auth import AccessToken
    from fastmcp.tools import Tool

_ALIASES_BY_COMMAND = aliases_by_command()

_DENIED_TRANSPORT_COMMANDS = frozenset({"dashboard/register", "dashboard/unregister"})
_SYSTEM_PREFIXES = frozenset(
    {"auth", "config", "diagnostics", "logging", "tasks", "audio_analysis", "dashboard"}
)
_COMPACT_ITEMS = 25
_FULL_ITEMS = 200
_COMPACT_BYTES = 12_288
_FULL_BYTES = 65_536
_COMPACT_STRING = 2_048
_FULL_STRING = 8_192
_CALL_TIMEOUT_SECONDS = 60
_SAFE_UNSCOPED_COMMANDS = frozenset({"info", "translations/locales"})


class DynamicRisk(StrEnum):
    """Provider-side risk classes for dynamically discovered commands."""

    READ = "read"
    CONTROL = "control"
    WRITE = "write"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class DynamicEntry:
    """One visible dynamic command or provider-local recipe."""

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


@dataclass(frozen=True, slots=True)
class DynamicPolicy:
    """Independent exposure switches for the four dynamic risk classes."""

    read: bool = True
    control: bool = False
    write: bool = False
    system: bool = False

    def allows(self, risk: DynamicRisk) -> bool:
        """Return whether a risk class is enabled."""
        return bool(getattr(self, risk.value))


@dataclass(frozen=True, slots=True)
class RecipeBinding:
    """A provider-local recipe backed by one or more former curated tools."""

    tools: Mapping[str, Tool]
    scopes: Mapping[str, Any]


@dataclass(slots=True)
class DynamicCatalogDiagnostics:
    """Last live-registry inspection state exposed through debug health."""

    available: bool = False
    registry_type: str = "missing"
    handlers_seen: int = 0
    handlers_visible: int = 0
    incompatible_handlers: tuple[str, ...] = ()
    last_error: str | None = None


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
        self._curated_tools: dict[str, Tool] = {}
        self._entry_cache: dict[str, tuple[int, DynamicEntry]] = {}
        self._diagnostics = DynamicCatalogDiagnostics()

    def diagnostics(self) -> dict[str, Any]:
        """Return a JSON-safe snapshot of dynamic-catalog compatibility."""
        return dataclasses.asdict(self._diagnostics)

    def ingest_curated(self, tools: Sequence[Tool]) -> None:
        """Capture internal curated executors before the public surface collapses."""
        self._curated_tools = {
            tool.name: tool
            for tool in tools
            if not tool.name.startswith(("ma_api:", "mcp_api:"))
            and tool.name not in {"search_tools", "get_tool_schema", "call_tool"}
        }

    async def visible_entries(self) -> list[DynamicEntry]:
        """Return canonical commands visible to the current authenticated user."""
        auth = await self._authentication()
        if not self._auth_required_provider() or auth is None:
            return []
        user = auth[1] if auth is not None else None
        policy = self._policy_provider()
        handlers = getattr(self.mass, "command_handlers", {})
        if not isinstance(handlers, Mapping):
            recipes = self._recipe_entries(policy, user)
            self._diagnostics = DynamicCatalogDiagnostics(
                registry_type=type(handlers).__name__,
                handlers_visible=len(recipes),
                last_error="mass.command_handlers is not a mapping",
            )
            return sorted(recipes, key=lambda entry: entry.name)

        entries: list[DynamicEntry] = []
        live_commands: set[str] = set()
        incompatible: list[str] = []
        for command, handler in sorted(handlers.items()):
            if not self._handler_is_discoverable(command, handler):
                incompatible.append(str(command))
                continue
            live_commands.add(command)
            scope = getattr(handler, "required_scope", None)
            if (
                user is not None
                and scope is not None
                and not self._scope_checker(user, scope)
            ):
                continue
            profile = COMMAND_PROFILES.get(command)
            risk = self._classify_risk(command, scope)
            if profile is not None and profile.risk_override is not None:
                risk = DynamicRisk(profile.risk_override)
            if policy.allows(risk):
                cached = self._entry_cache.get(command)
                try:
                    if cached is None or cached[0] != id(handler):
                        cached = (
                            id(handler),
                            self._compile_entry(command, handler, risk),
                        )
                        self._entry_cache[command] = cached
                except UnsupportedSignatureError:
                    incompatible.append(str(command))
                    continue
                entries.append(cached[1])
        self._entry_cache = {
            command: cached
            for command, cached in self._entry_cache.items()
            if command in live_commands
        }
        entries.extend(self._recipe_entries(policy, user))
        self._diagnostics = DynamicCatalogDiagnostics(
            available=True,
            registry_type=type(handlers).__name__,
            handlers_seen=len(handlers),
            handlers_visible=len(entries),
            incompatible_handlers=tuple(sorted(incompatible)),
            last_error=(
                f"{len(incompatible)} incompatible handler(s) skipped"
                if incompatible
                else None
            ),
        )
        return sorted(entries, key=lambda entry: entry.name)

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
        impersonating = bool(entry.allow_impersonation and arguments.get("user"))
        await self._confirm(entry, ctx, impersonating=impersonating)

        if isinstance(entry.handler, RecipeBinding):
            result = await self._execute_recipe(entry.handler, arguments, auth)
            return self._bounded_envelope(
                name,
                result,
                response_mode=response_mode,
                fields=fields,
                max_items=max_items,
            )

        call_arguments = dict(arguments)
        if entry.profile is not None:
            try:
                call_arguments = entry.profile.convert_arguments(call_arguments)
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
        impersonated = (
            call_arguments.pop("user", None) if entry.allow_impersonation else None
        )
        try:
            if entry.compiled_signature is None:
                raise ValueError(f"Tool {entry.name!r} has no compiled signature")
            parsed = entry.compiled_signature.parse(call_arguments)
        except (KeyError, TypeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

        try:
            async with asyncio.timeout(_CALL_TIMEOUT_SECONDS):
                result = await self._execute(entry, parsed, auth, impersonated)
        except TimeoutError as exc:
            raise ToolError(f"Command {entry.command!r} timed out") from exc
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"Command {entry.command!r} failed: {exc}") from exc
        return self._bounded_envelope(
            name,
            result,
            response_mode=response_mode,
            fields=fields,
            max_items=max_items,
            profile=entry.profile,
        )

    async def _authentication(self) -> tuple[AccessToken, Any] | None:
        """Resolve the MCP access token to an enabled MA user."""
        token = self._token_provider()
        if token is None:
            return None
        user = self.mass.webserver.auth.get_user(token.client_id)
        if inspect.isawaitable(user):
            user = await user
        if user is None or getattr(user, "enabled", True) is False:
            return None
        return token, user

    @staticmethod
    def _handler_is_discoverable(command: str, handler: Any) -> bool:
        """Reject aliases, unauthenticated endpoints and transport internals."""
        return bool(
            command not in _DENIED_TRANSPORT_COMMANDS
            and getattr(handler, "authenticated", True)
            and not getattr(handler, "alias", False)
            and callable(getattr(handler, "target", None))
            and isinstance(getattr(handler, "signature", None), inspect.Signature)
            and isinstance(getattr(handler, "type_hints", None), Mapping)
        )

    @staticmethod
    def _classify_risk(command: str, scope: Any) -> DynamicRisk:
        """Map MA scopes and command families to a conservative risk class."""
        prefix = command.split("/", 1)[0]
        scope_value = str(getattr(scope, "value", scope) or "").casefold()
        if command in _SAFE_UNSCOPED_COMMANDS:
            return DynamicRisk.READ
        if prefix in _SYSTEM_PREFIXES or scope is None:
            return DynamicRisk.SYSTEM
        if scope_value in {
            "library.read",
            "players.read",
            "queues.read",
            "providers.read",
        }:
            return DynamicRisk.READ
        if scope_value.endswith(".control"):
            return DynamicRisk.CONTROL
        if scope_value.endswith((".write", ".manage")):
            return DynamicRisk.WRITE
        if scope_value.endswith(".read"):
            return DynamicRisk.READ
        return DynamicRisk.SYSTEM

    @classmethod
    def _compile_entry(
        cls, command: str, handler: Any, risk: DynamicRisk
    ) -> DynamicEntry:
        """Compile a live MA handler into a catalog entry."""
        scope = getattr(handler, "required_scope", None)
        profile = COMMAND_PROFILES.get(command)
        annotations = (
            dict(profile.annotations) if profile is not None else cls._annotations(risk)
        )
        compiled_signature = compile_signature(
            handler.signature,
            handler.type_hints,
            allow_extra_kwargs=profile.allow_extra_kwargs
            if profile is not None
            else False,
        )
        return DynamicEntry(
            name=f"ma_api:{command}",
            command=command,
            description=cls._description(handler.target, command),
            input_schema=cls._entry_input_schema(
                compiled_signature.input_schema,
                profile,
                allow_impersonation=bool(
                    getattr(handler, "allow_impersonation", False)
                ),
            ),
            risk=risk,
            required_scope=str(getattr(scope, "value", scope))
            if scope is not None
            else None,
            allow_impersonation=bool(getattr(handler, "allow_impersonation", False)),
            handler=handler,
            search_aliases=(
                profile.search_aliases
                if profile is not None
                else _ALIASES_BY_COMMAND.get(command, ())
            ),
            output_schema=compiled_signature.output_schema(),
            annotations=annotations,
            profile=profile,
            compiled_signature=compiled_signature,
        )

    def _recipe_entries(self, policy: DynamicPolicy, user: Any) -> list[DynamicEntry]:
        """Compile available curated executors into the sixteen recipe entries."""
        entries: list[DynamicEntry] = []
        allowed_tags = self._allowed_tags_provider()
        for name, sources in CURATED_RECIPE_SOURCES.items():
            tools: dict[str, Tool] = {}
            scopes: dict[str, Any] = {}
            for source in sources:
                tool = self._curated_tools.get(source)
                if tool is None:
                    continue
                tags = {str(tag) for tag in (getattr(tool, "tags", None) or set())}
                if not tags_visible(tags, allowed_tags):
                    continue
                scope = self._resolve_scope(CURATED_RECIPE_SCOPES[source])
                if user is not None and not self._scope_checker(user, scope):
                    continue
                tools[source] = tool
                scopes[source] = scope
            if not tools:
                continue
            risk = self._recipe_risk(name)
            if not policy.allows(risk):
                continue
            required_scopes = sorted(
                {str(getattr(scope, "value", scope)) for scope in scopes.values()}
            )
            entries.append(
                DynamicEntry(
                    name=name,
                    command=name.split(":", 1)[1],
                    description=self._recipe_description(name, tools),
                    input_schema=self._recipe_schema(tools, scopes),
                    risk=risk,
                    required_scope=required_scopes[0]
                    if len(required_scopes) == 1
                    else None,
                    allow_impersonation=False,
                    handler=RecipeBinding(tools, scopes),
                    search_aliases=tuple(sorted(tools)),
                    annotations=self._annotations(risk),
                )
            )
        return entries

    @staticmethod
    def _recipe_risk(name: str) -> DynamicRisk:
        """Classify provider-local recipes conservatively."""
        if name.startswith(("mcp_api:config/", "mcp_api:debug/")):
            return DynamicRisk.SYSTEM
        if name in {"mcp_api:players/summary", "mcp_api:queue/snapshot"}:
            return DynamicRisk.READ
        if name in {"mcp_api:queue/add", "mcp_api:queue/move"}:
            return DynamicRisk.CONTROL
        return DynamicRisk.WRITE

    @staticmethod
    def _recipe_description(name: str, tools: Mapping[str, Tool]) -> str:
        """Build a concise recipe description from its retained operations."""
        operations = ", ".join(source.split("_", 1)[1] for source in tools)
        return f"Provider recipe {name.split(':', 1)[1]}. Operations: {operations}."

    @staticmethod
    def _recipe_schema(
        tools: Mapping[str, Tool], scopes: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Preserve per-operation required arguments with discriminator branches."""
        if len(tools) == 1:
            source, tool = next(iter(tools.items()))
            schema = dict(tool.parameters or {})
            schema["x-required-scope"] = str(
                getattr(scopes[source], "value", scopes[source])
            )
            schema["x-required-tags"] = sorted(
                str(tag) for tag in (getattr(tool, "tags", None) or set())
            )
            return schema
        branches: list[dict[str, Any]] = []
        for source, tool in tools.items():
            operation = source.split("_", 1)[1]
            tool_schema = tool.parameters or {}
            properties = dict(tool_schema.get("properties", {}))
            properties["operation"] = {"type": "string", "const": operation}
            required = sorted({"operation", *tool_schema.get("required", [])})
            branches.append(
                {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                    "x-required-scope": str(
                        getattr(scopes[source], "value", scopes[source])
                    ),
                    "x-required-tags": sorted(
                        str(tag) for tag in (getattr(tool, "tags", None) or set())
                    ),
                }
            )
        return {
            "type": "object",
            "oneOf": branches,
            "discriminator": {"propertyName": "operation"},
        }

    @staticmethod
    def _resolve_scope(value: str) -> Any:
        """Use MA's current Scope enum when available, retaining dev compatibility."""
        try:
            from music_assistant_models.auth import Scope  # noqa: PLC0415

            return Scope(value)
        except ImportError, ValueError:
            return value

    @staticmethod
    def _annotations(risk: DynamicRisk) -> dict[str, bool]:
        """Return conservative MCP behavior hints for a risk class."""
        return {
            "readOnlyHint": risk is DynamicRisk.READ,
            "destructiveHint": risk in {DynamicRisk.WRITE, DynamicRisk.SYSTEM},
            "idempotentHint": risk is DynamicRisk.READ,
            "openWorldHint": False,
        }

    async def _execute_recipe(
        self,
        binding: RecipeBinding,
        arguments: dict[str, Any],
        auth: tuple[AccessToken, Any] | None = None,
    ) -> Any:
        """Select and invoke a retained executor under MA's auth context."""
        call_arguments = dict(arguments)
        if len(binding.tools) == 1:
            source, tool = next(iter(binding.tools.items()))
        else:
            operation = call_arguments.pop("operation", None)
            by_operation = {
                source.split("_", 1)[1]: (source, candidate)
                for source, candidate in binding.tools.items()
            }
            selected = by_operation.get(str(operation))
            if selected is None:
                valid = ", ".join(sorted(by_operation))
                raise ToolError(
                    f"Invalid recipe operation {operation!r}; choose: {valid}"
                )
            source, tool = selected
        if auth is None:
            raise ToolError("Authentication is required")
        if not self._scope_checker(auth[1], binding.scopes[source]):
            raise ToolError(f"Recipe operation {tool.name!r} is not permitted")
        context_tokens = self._set_auth_context(auth)
        try:
            result = await tool.run(call_arguments)
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"Recipe operation {tool.name!r} failed: {exc}") from exc
        else:
            if result.is_error:
                raise ToolError(f"Recipe operation {tool.name!r} failed")
            structured = result.structured_content
            if isinstance(structured, dict) and set(structured) == {"result"}:
                return structured["result"]
            return structured if structured is not None else result.content
        finally:
            for variable, token in reversed(context_tokens):
                variable.reset(token)

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
        self, entry: DynamicEntry, ctx: Context, *, impersonating: bool = False
    ) -> None:
        """Require confirmation for system calls and configured writes."""
        enabled = (
            impersonating
            or entry.risk is DynamicRisk.SYSTEM
            or (entry.risk is DynamicRisk.WRITE and self._confirmation_provider())
        )
        await confirm_or_raise(
            ctx, f"Run {entry.name} ({entry.risk.value})?", enabled=enabled
        )

    async def _execute(
        self,
        entry: DynamicEntry,
        parsed: dict[str, Any],
        auth: tuple[AccessToken, Any] | None,
        impersonated: str | None,
    ) -> Any:
        """Execute under MA's own request context and collect generators."""
        context_tokens = self._set_auth_context(auth)
        try:
            if impersonated:
                from music_assistant.controllers.webserver.helpers import (  # noqa: PLC0415
                    auth_middleware,
                )

                target_user = await auth_middleware.resolve_impersonated_user(
                    self.mass, impersonated
                )
                variable = auth_middleware.impersonated_user
                context_tokens.append((variable, variable.set(target_user)))
            result = entry.handler.target(**parsed)
            if inspect.isawaitable(result):
                result = await result
            if inspect.isasyncgen(result):
                return await self._collect_generator(result)
            return result
        finally:
            for variable, token in reversed(context_tokens):
                variable.reset(token)

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
        data, value_truncated = cls._truncate_value(
            data, string_cap, depth=6 if compact else 12
        )
        truncated |= value_truncated
        envelope: dict[str, Any] = {
            "command": name,
            "data": data,
            "truncated": truncated,
            "returned_count": len(data)
            if isinstance(data, list)
            else (0 if data is None else 1),
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
            cls._fit_bytes(envelope, byte_cap)
            cls._set_measured_bytes(envelope)
        return envelope

    @classmethod
    def _limit_nested_items(cls, value: Any, item_cap: int) -> tuple[Any, bool]:
        """Apply the mode item cap to every nested list, not only the root."""
        if isinstance(value, list):
            kept = value[:item_cap]
            list_nested = [cls._limit_nested_items(item, item_cap) for item in kept]
            return [item for item, _changed in list_nested], len(
                value
            ) > item_cap or any(changed for _item, changed in list_nested)
        if isinstance(value, dict):
            dict_nested = {
                key: cls._limit_nested_items(item, item_cap)
                for key, item in value.items()
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
    def _truncate_value(
        cls, value: Any, string_cap: int, *, depth: int
    ) -> tuple[Any, bool]:
        """Bound nested depth and leaf strings while preserving JSON shape."""
        if depth <= 0 and isinstance(value, dict | list):
            return "[truncated]", True
        if isinstance(value, str) and len(value) > string_cap:
            return value[:string_cap] + "…", True
        if isinstance(value, list):
            list_items = [
                cls._truncate_value(item, string_cap, depth=depth - 1) for item in value
            ]
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
        """Shrink list results until the complete envelope fits the byte cap."""
        data = envelope["data"]
        if isinstance(data, list):
            while data and cls._encoded_size(envelope) > byte_cap:
                data.pop()
                envelope["truncated"] = True
            envelope["returned_count"] = len(data)
        if cls._encoded_size(envelope) > byte_cap:
            envelope["data"] = "[response exceeded byte budget]"
            envelope["returned_count"] = 1
            envelope["truncated"] = True

    @staticmethod
    def _encoded_size(value: Any) -> int:
        """Measure the compact UTF-8 JSON representation."""
        return len(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        )

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


LEGACY_MIGRATIONS: dict[str, str] = {
    **legacy_migrations(),
    # Historical pre-profile alias retained only for an actionable error.
    "playback_play": "ma_api:players/cmd/play",
}
