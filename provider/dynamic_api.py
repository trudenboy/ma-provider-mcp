"""Dynamic Music Assistant API catalog and guarded command dispatcher."""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum, StrEnum
from types import UnionType
from typing import TYPE_CHECKING, Any, Union, get_args, get_origin

from fastmcp.exceptions import ToolError
from pydantic import TypeAdapter

from .command_profiles import CURATED_RECIPE_SOURCES, aliases_by_command, legacy_migrations
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
    ) -> None:
        """Initialise the adapter with request-aware policy providers."""
        self.mass = mass
        self._policy_provider = policy_provider
        self._auth_required_provider = auth_required_provider
        self._confirmation_provider = confirmation_provider
        self._token_provider = token_provider
        self._scope_checker = scope_checker or self._default_scope_checker
        self._curated_tools: dict[str, Tool] = {}
        self._entry_cache: dict[str, tuple[int, DynamicEntry]] = {}

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
        handlers = getattr(self.mass, "command_handlers", {})
        if not isinstance(handlers, Mapping):
            return []

        policy = self._policy_provider()
        entries: list[DynamicEntry] = []
        live_commands: set[str] = set()
        for command, handler in sorted(handlers.items()):
            if not self._handler_is_discoverable(command, handler):
                continue
            live_commands.add(command)
            scope = getattr(handler, "required_scope", None)
            if user is not None and scope is not None and not self._scope_checker(user, scope):
                continue
            risk = self._classify_risk(command, scope)
            if policy.allows(risk):
                cached = self._entry_cache.get(command)
                if cached is None or cached[0] != id(handler):
                    cached = (id(handler), self._compile_entry(command, handler, risk))
                    self._entry_cache[command] = cached
                entries.append(cached[1])
        self._entry_cache = {
            command: cached
            for command, cached in self._entry_cache.items()
            if command in live_commands
        }
        entries.extend(self._recipe_entries(policy))
        return sorted(entries, key=lambda entry: entry.name)

    async def get_visible_entry(self, name: str) -> DynamicEntry | None:
        """Resolve one visible entry by canonical public name."""
        return next((entry for entry in await self.visible_entries() if entry.name == name), None)

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
            result = await self._execute_recipe(entry.handler, arguments)
            return self._bounded_envelope(
                name,
                result,
                response_mode=response_mode,
                fields=fields,
                max_items=max_items,
            )

        call_arguments = dict(arguments)
        impersonated = call_arguments.pop("user", None) if entry.allow_impersonation else None
        try:
            from music_assistant.helpers.api import parse_arguments  # noqa: PLC0415

            parsed = parse_arguments(
                entry.handler.signature,
                entry.handler.type_hints,
                call_arguments,
                strict=True,
            )
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
        if scope_value in {"library.read", "players.read", "queues.read", "providers.read"}:
            return DynamicRisk.READ
        if scope_value.endswith(".control"):
            return DynamicRisk.CONTROL
        if scope_value.endswith((".write", ".manage")):
            return DynamicRisk.WRITE
        if scope_value.endswith(".read"):
            return DynamicRisk.READ
        return DynamicRisk.SYSTEM

    @classmethod
    def _compile_entry(cls, command: str, handler: Any, risk: DynamicRisk) -> DynamicEntry:
        """Compile a live MA handler into a catalog entry."""
        scope = getattr(handler, "required_scope", None)
        return DynamicEntry(
            name=f"ma_api:{command}",
            command=command,
            description=cls._description(handler.target, command),
            input_schema=cls._input_schema(handler),
            risk=risk,
            required_scope=str(getattr(scope, "value", scope)) if scope is not None else None,
            allow_impersonation=bool(getattr(handler, "allow_impersonation", False)),
            handler=handler,
            search_aliases=_ALIASES_BY_COMMAND.get(command, ()),
        )

    def _recipe_entries(self, policy: DynamicPolicy) -> list[DynamicEntry]:
        """Compile available curated executors into the sixteen recipe entries."""
        entries: list[DynamicEntry] = []
        for name, sources in CURATED_RECIPE_SOURCES.items():
            tools = {
                source: self._curated_tools[source]
                for source in sources
                if source in self._curated_tools
            }
            if len(tools) != len(sources):
                continue
            risk = self._recipe_risk(name)
            if not policy.allows(risk):
                continue
            entries.append(
                DynamicEntry(
                    name=name,
                    command=name.split(":", 1)[1],
                    description=self._recipe_description(name, tools),
                    input_schema=self._recipe_schema(tools),
                    risk=risk,
                    required_scope=None,
                    allow_impersonation=False,
                    handler=RecipeBinding(tools),
                    search_aliases=tuple(sorted(tools)),
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
    def _recipe_schema(tools: Mapping[str, Tool]) -> dict[str, Any]:
        """Merge source schemas and add an operation discriminator when needed."""
        properties: dict[str, Any] = {}
        required_by_tool: list[set[str]] = []
        for tool in tools.values():
            tool_schema = tool.parameters or {}
            properties.update(tool_schema.get("properties", {}))
            required_by_tool.append(set(tool_schema.get("required", [])))
        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        }
        if len(tools) == 1:
            required = required_by_tool[0]
        else:
            operations = [source.split("_", 1)[1] for source in tools]
            schema["properties"] = {
                "operation": {"type": "string", "enum": operations},
                **properties,
            }
            required = {"operation"}
        if required:
            schema["required"] = sorted(required)
        return schema

    @staticmethod
    async def _execute_recipe(binding: RecipeBinding, arguments: dict[str, Any]) -> Any:
        """Select and invoke the retained curated executor for a recipe."""
        call_arguments = dict(arguments)
        if len(binding.tools) == 1:
            tool = next(iter(binding.tools.values()))
        else:
            operation = call_arguments.pop("operation", None)
            by_operation = {
                source.split("_", 1)[1]: candidate for source, candidate in binding.tools.items()
            }
            selected = by_operation.get(str(operation))
            if selected is None:
                valid = ", ".join(sorted(by_operation))
                raise ToolError(f"Invalid recipe operation {operation!r}; choose: {valid}")
            tool = selected
        try:
            result = await tool.run(call_arguments)
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"Recipe operation {tool.name!r} failed: {exc}") from exc
        if result.is_error:
            raise ToolError(f"Recipe operation {tool.name!r} failed")
        structured = result.structured_content
        if isinstance(structured, dict) and set(structured) == {"result"}:
            return structured["result"]
        return structured if structured is not None else result.content

    @staticmethod
    def _description(target: Callable[..., Any], command: str) -> str:
        """Extract a compact first paragraph from the handler docstring."""
        doc = inspect.getdoc(target) or ""
        paragraph = doc.split("\n\n", 1)[0].replace("\n", " ").strip()
        return paragraph or f"Music Assistant API command {command}."

    @classmethod
    def _input_schema(cls, handler: Any) -> dict[str, Any]:
        """Generate a strict JSON schema from the MA handler signature."""
        properties: dict[str, Any] = {}
        required: list[str] = []
        for name, parameter in handler.signature.parameters.items():
            if name in {"self", "return_type"}:
                continue
            annotation = handler.type_hints.get(name, Any)
            if cls._is_static_type_hint(annotation):
                continue
            properties[name] = cls._type_schema(annotation)
            if parameter.default is inspect.Parameter.empty:
                required.append(name)
            else:
                properties[name]["default"] = cls._json_value(parameter.default)
        if getattr(handler, "allow_impersonation", False):
            properties["user"] = {
                "type": "string",
                "description": "Optional MA user id or username to impersonate.",
            }
        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        }
        if required:
            schema["required"] = required
        return schema

    @staticmethod
    def _is_static_type_hint(annotation: Any) -> bool:
        """Return whether an annotation contains a non-input ``type[X]``."""
        origin = get_origin(annotation)
        if origin is type:
            return True
        return origin in {Union, UnionType} and any(
            get_origin(arg) is type for arg in get_args(annotation)
        )

    @staticmethod
    def _type_schema(annotation: Any) -> dict[str, Any]:
        """Convert a Python annotation to JSON schema with safe fallbacks."""
        if annotation is Any or isinstance(annotation, str):
            return {}
        try:
            return TypeAdapter(annotation).json_schema(mode="validation")
        except Exception:
            return {"type": "string", "x-python-type": str(annotation)}

    @classmethod
    def _json_value(cls, value: Any) -> Any:
        """Convert signature defaults to JSON-safe values."""
        if value is None or isinstance(value, str | int | float | bool):
            return value
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
            return [cls._json_value(item) for item in value]
        if isinstance(value, Mapping):
            return {str(key): cls._json_value(item) for key, item in value.items()}
        return str(value)

    async def _confirm(
        self, entry: DynamicEntry, ctx: Context, *, impersonating: bool = False
    ) -> None:
        """Require confirmation for system calls and configured writes."""
        enabled = (
            impersonating
            or entry.risk is DynamicRisk.SYSTEM
            or (entry.risk is DynamicRisk.WRITE and self._confirmation_provider())
        )
        await confirm_or_raise(ctx, f"Run {entry.name} ({entry.risk.value})?", enabled=enabled)

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
    ) -> dict[str, Any]:
        """Return a deterministic, JSON-safe response inside the mode budget."""
        compact = response_mode == "compact"
        item_cap = _COMPACT_ITEMS if compact else _FULL_ITEMS
        if max_items is not None:
            item_cap = max(1, min(item_cap, int(max_items)))
        byte_cap = _COMPACT_BYTES if compact else _FULL_BYTES
        string_cap = _COMPACT_STRING if compact else _FULL_STRING
        raw = cls._json_value_deep(result)
        total_count = len(raw) if isinstance(raw, list) else None
        data = cls._project_fields(raw, fields)
        truncated = False
        if isinstance(data, list) and len(data) > item_cap:
            data = data[:item_cap]
            truncated = True
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
            cls._fit_bytes(envelope, byte_cap)
            cls._set_measured_bytes(envelope)
        return envelope

    @classmethod
    def _json_value_deep(cls, value: Any) -> Any:
        """Serialize MA models, dataclasses and common containers."""
        if value is None or isinstance(value, str | int | float | bool):
            return value
        if isinstance(value, bytes | bytearray):
            return value.decode(errors="replace")
        if isinstance(value, datetime | date):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return cls._json_value_deep(dataclasses.asdict(value))
        if hasattr(value, "to_dict"):
            return cls._json_value_deep(value.to_dict())
        if hasattr(value, "model_dump"):
            return cls._json_value_deep(value.model_dump(mode="json"))
        if isinstance(value, Mapping):
            return {str(key): cls._json_value_deep(item) for key, item in value.items()}
        if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
            return [cls._json_value_deep(item) for item in value]
        try:
            return json.loads(json.dumps(value, default=str))
        except TypeError, ValueError:
            return str(value)

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


LEGACY_MIGRATIONS: dict[str, str] = {
    **legacy_migrations(),
    # Historical pre-profile alias retained only for an actionable error.
    "playback_play": "ma_api:players/cmd/play",
}
