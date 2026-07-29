"""Contract tests for the permanent dynamic MA API catalog."""

from __future__ import annotations

import ast
import contextvars
import inspect
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken
from fastmcp.tools import Tool

from provider.command_profiles import (
    COMMAND_PROFILES,
    CURATED_PROFILE_MAPPINGS,
    CURATED_RECIPE_SOURCES,
    CommandProfile,
)
from provider.dynamic_api import DynamicAPIAdapter, DynamicEntry, DynamicPolicy, DynamicRisk
from provider.meta_discovery import register_meta_discovery
from provider.server import build_tag_lookup

_META_NAMES = {"search_tools", "call_tool", "get_tool_schema"}


@dataclass
class _FakeAdapter:
    """Small adapter implementing the transform-facing dynamic API contract."""

    calls: list[tuple[str, dict[str, Any]]]

    async def visible_entries(self) -> list[DynamicEntry]:
        """Return one discoverable command."""
        return [
            DynamicEntry(
                name="ma_api:players/cmd/play",
                command="players/cmd/play",
                description="Start playback on a player.",
                input_schema={
                    "type": "object",
                    "properties": {"player_id": {"type": "string"}},
                    "required": ["player_id"],
                    "additionalProperties": False,
                },
                risk=DynamicRisk.CONTROL,
                required_scope="players.control",
                allow_impersonation=False,
                handler=object(),
                search_aliases=("playback_play", "start music"),
                output_schema={"type": "object"},
                annotations={"readOnlyHint": False, "destructiveHint": False},
            )
        ]

    async def get_visible_entry(self, name: str) -> DynamicEntry | None:
        """Resolve the fake command by name."""
        return next((entry for entry in await self.visible_entries() if entry.name == name), None)

    async def call(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        response_mode: str,
        fields: list[str] | None,
        max_items: int | None,
        ctx: Any,
    ) -> dict[str, Any]:
        """Record and acknowledge a fake call."""
        del fields, max_items, ctx
        self.calls.append((name, arguments))
        return {
            "command": name,
            "data": {"ok": True},
            "truncated": False,
            "returned_count": 1,
            "bytes": 11,
            "applied": {"mode": response_mode},
        }


def _server() -> tuple[FastMCP, _FakeAdapter]:
    """Build a root server with one legacy tool and one dynamic command."""
    mcp: FastMCP = FastMCP(name="dynamic-test")

    @mcp.tool(name="playback_play")
    async def legacy_play(player_id: str) -> None:
        """Legacy curated tool that must not remain callable."""
        del player_id

    adapter = _FakeAdapter(calls=[])
    register_meta_discovery(
        mcp,
        allowed_tags_provider=lambda: set(),
        lookup_component_tags=build_tag_lookup(mcp),
        dynamic_adapter=adapter,
    )
    return mcp, adapter


async def test_tools_list_is_always_three_meta_tools() -> None:
    """The target surface never exposes the underlying curated catalog."""
    mcp, _adapter = _server()
    async with Client(mcp) as client:
        tools = await client.list_tools()
    assert {tool.name for tool in tools} == _META_NAMES


async def test_search_uses_alias_but_returns_canonical_ma_name() -> None:
    """Legacy terminology improves ranking without preserving the old name."""
    mcp, _adapter = _server()
    async with Client(mcp) as client:
        result = await client.call_tool("search_tools", {"query": "playback_play"})
    assert result.data == [
        {"name": "ma_api:players/cmd/play", "description": "Start playback on a player."}
    ]


async def test_dynamic_schema_is_returned_on_demand() -> None:
    """A dynamic command exposes its real input schema only when requested."""
    mcp, _adapter = _server()
    async with Client(mcp) as client:
        result = await client.call_tool("get_tool_schema", {"tool_name": "ma_api:players/cmd/play"})
    assert result.data["name"] == "ma_api:players/cmd/play"
    assert result.data["kind"] == "ma_api"
    assert result.data["inputSchema"]["required"] == ["player_id"]
    assert result.data["risk"] == "control"
    assert result.data["outputSchema"] == {"type": "object"}
    assert result.data["annotations"]["readOnlyHint"] is False


async def test_call_tool_routes_dynamic_name() -> None:
    """The meta proxy forwards canonical names and response options."""
    mcp, adapter = _server()
    async with Client(mcp) as client:
        result = await client.call_tool(
            "call_tool",
            {
                "name": "ma_api:players/cmd/play",
                "arguments": {"player_id": "kitchen"},
            },
        )
    assert result.data["data"] == {"ok": True}
    assert adapter.calls == [("ma_api:players/cmd/play", {"player_id": "kitchen"})]


async def test_old_curated_name_is_not_callable() -> None:
    """Legacy public names are a breaking migration, not hidden aliases."""
    mcp, _adapter = _server()
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="ma_api:players/cmd/play"):
            await client.call_tool("call_tool", {"name": "playback_play", "arguments": {}})
        with pytest.raises(ToolError):
            await client.call_tool("playback_play", {"player_id": "kitchen"})


async def test_meta_catalog_stays_under_three_kib() -> None:
    """The permanent public schemas stay inside the agreed context budget."""
    mcp, _adapter = _server()
    async with Client(mcp) as client:
        tools = await client.list_tools()
    payload = "".join(tool.model_dump_json() for tool in tools).encode()
    assert len(payload) <= 3072


def test_fake_handler_signature_is_stable() -> None:
    """Guard accidental widening of the fake adapter call contract."""
    assert list(inspect.signature(_FakeAdapter.call).parameters) == [
        "self",
        "name",
        "arguments",
        "response_mode",
        "fields",
        "max_items",
        "ctx",
    ]


def _handler(command: str, target: Any, scope: str = "library.read") -> Any:
    """Build the stable subset of MA's APICommandHandler contract."""
    return SimpleNamespace(
        command=command,
        signature=inspect.signature(target),
        type_hints=target.__annotations__,
        target=target,
        authenticated=True,
        required_scope=scope,
        allow_impersonation=False,
        alias=False,
    )


def _real_adapter(
    handler: Any,
    *,
    policy: DynamicPolicy | None = None,
    scope_checker: Any = None,
    allowed_tags: set[str] | None = None,
    user: Any = None,
) -> DynamicAPIAdapter:
    """Build an authenticated adapter around one fake MA handler."""
    mass = MagicMock()
    mass.command_handlers = {handler.command: handler}
    user = user or MagicMock(user_id="u1", enabled=True, role="admin")
    mass.webserver.auth.get_user = AsyncMock(return_value=user)
    token = AccessToken(token="secret", client_id="u1", scopes=[])
    return DynamicAPIAdapter(
        mass,
        policy_provider=lambda: policy or DynamicPolicy(),
        auth_required_provider=lambda: True,
        confirmation_provider=lambda: True,
        token_provider=lambda: token,
        scope_checker=scope_checker or (lambda _user, _scope: True),
        allowed_tags_provider=lambda: allowed_tags or set(),
    )


async def test_adapter_discovers_handler_and_compiles_schema() -> None:
    """The runtime registry becomes a canonical ma_api catalog entry."""

    async def search(query: str, limit: int = 5) -> list[str]:
        """Search the library."""
        return [query] * limit

    adapter = _real_adapter(_handler("music/search", search))
    entries = await adapter.visible_entries()
    assert [entry.name for entry in entries] == ["ma_api:music/search"]
    assert entries[0].risk is DynamicRisk.READ
    assert entries[0].input_schema["required"] == ["query"]
    assert entries[0].input_schema["properties"]["limit"]["default"] == 5


async def test_adapter_hides_disabled_risk_class() -> None:
    """Control commands remain absent until their independent flag is enabled."""

    async def play(player_id: str) -> None:
        del player_id

    handler = _handler("players/cmd/play", play, "players.control")
    assert await _real_adapter(handler).visible_entries() == []
    enabled = DynamicPolicy(control=True)
    assert len(await _real_adapter(handler, policy=enabled).visible_entries()) == 1


async def test_adapter_observes_registry_changes_without_restart() -> None:
    """Registering and replacing handlers updates the same live adapter."""

    async def first() -> str:
        return "first"

    async def second(value: int) -> int:
        return value

    adapter = _real_adapter(_handler("music/first", first))
    assert [entry.name for entry in await adapter.visible_entries()] == ["ma_api:music/first"]
    adapter.mass.command_handlers = {"music/second": _handler("music/second", second)}
    entries = await adapter.visible_entries()
    assert [entry.name for entry in entries] == ["ma_api:music/second"]
    assert entries[0].input_schema["required"] == ["value"]


async def test_adapter_skips_structurally_incompatible_handlers() -> None:
    """One malformed registry entry cannot disable the MCP endpoint."""
    adapter = _real_adapter(SimpleNamespace(command="broken", target=lambda: None))
    assert await adapter.visible_entries() == []


async def test_adapter_executes_strictly_and_bounds_result() -> None:
    """Calls reject extra args and cap list/string output in compact mode."""

    async def values(prefix: str) -> list[str]:
        return [prefix * 3000 for _index in range(40)]

    adapter = _real_adapter(_handler("music/values", values))
    ctx = MagicMock(session_id="session-1")
    with pytest.raises(ToolError, match="Invalid parameter"):
        await adapter.call(
            "ma_api:music/values",
            {"prefix": "x", "typo": True},
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=ctx,
        )
    result = await adapter.call(
        "ma_api:music/values",
        {"prefix": "x"},
        response_mode="compact",
        fields=None,
        max_items=None,
        ctx=ctx,
    )
    assert result["truncated"] is True
    assert result["returned_count"] <= 25
    assert result["bytes"] <= 12_288


async def test_adapter_hides_catalog_when_mcp_auth_is_disabled() -> None:
    """Disabling endpoint auth must not accidentally expose MA internals."""

    async def values() -> list[str]:
        return []

    handler = _handler("music/values", values)
    mass = MagicMock(command_handlers={handler.command: handler})
    adapter = DynamicAPIAdapter(
        mass,
        policy_provider=DynamicPolicy,
        auth_required_provider=lambda: False,
        confirmation_provider=lambda: True,
        token_provider=lambda: None,
        scope_checker=lambda _user, _scope: True,
    )
    assert await adapter.visible_entries() == []


async def test_recipe_keeps_curated_executor_behind_canonical_name() -> None:
    """A consolidated recipe preserves the existing curated implementation."""

    async def list_players(include_unavailable: bool = False) -> list[dict[str, Any]]:
        return [{"player_id": "p1", "unavailable": include_unavailable}]

    async def get_player(player_id: str) -> dict[str, str]:
        return {"player_id": player_id}

    async def values() -> list[str]:
        return []

    adapter = _real_adapter(_handler("music/values", values))
    adapter.ingest_curated(
        [
            Tool.from_function(fn=list_players, name="players_list_players"),
            Tool.from_function(fn=get_player, name="players_get_player"),
        ]
    )
    entries = await adapter.visible_entries()
    recipe = next(entry for entry in entries if entry.name == "mcp_api:players/summary")
    operations = {
        branch["properties"]["operation"]["const"] for branch in recipe.input_schema["oneOf"]
    }
    assert operations == {"list_players", "get_player"}
    get_branch = next(
        branch
        for branch in recipe.input_schema["oneOf"]
        if branch["properties"]["operation"]["const"] == "get_player"
    )
    assert get_branch["required"] == ["operation", "player_id"]
    result = await adapter.call(
        recipe.name,
        {"operation": "get_player", "player_id": "p1"},
        response_mode="compact",
        fields=None,
        max_items=None,
        ctx=MagicMock(),
    )
    assert result["data"] == {"player_id": "p1"}


def test_curated_migration_matrix_covers_every_registered_tool() -> None:
    """Every curated tool is represented by exactly one profile or recipe."""
    registered: set[str] = set()
    tools_dir = Path(__file__).parents[1] / "provider" / "tools"
    if not tools_dir.is_dir():
        return
    for path in tools_dir.glob("*.py"):
        if path.name.startswith("_"):
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            public_name = node.name
            decorated = False
            for decorator in node.decorator_list:
                call = decorator if isinstance(decorator, ast.Call) else None
                target = call.func if call is not None else decorator
                if not isinstance(target, ast.Attribute) or target.attr != "tool":
                    continue
                decorated = True
                if call is not None:
                    for keyword in call.keywords:
                        if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                            public_name = str(keyword.value.value)
            if decorated:
                registered.add(f"{path.stem}_{public_name}")
    recipe_sources = {source for sources in CURATED_RECIPE_SOURCES.values() for source in sources}
    mapped = set(CURATED_PROFILE_MAPPINGS) | recipe_sources
    assert registered == mapped
    assert set(CURATED_PROFILE_MAPPINGS).isdisjoint(recipe_sources)


def test_every_migrated_command_has_an_executable_profile() -> None:
    """The migration matrix is backed by profiles, not aliases alone."""
    assert set(COMMAND_PROFILES) == set(CURATED_PROFILE_MAPPINGS.values())
    for legacy, command in CURATED_PROFILE_MAPPINGS.items():
        profile = COMMAND_PROFILES[command]
        assert isinstance(profile, CommandProfile)
        assert legacy in profile.search_aliases
        assert profile.annotations
        assert profile.risk_override in {"read", "control", "write", "system"}


async def test_profile_converts_arguments_and_projects_only_compact_mode() -> None:
    """Compatibility aliases parse strictly and full mode remains lossless."""
    seen: list[tuple[str, list[str] | None]] = []

    async def search(
        search_query: str, media_types: list[str] | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        seen.append((search_query, media_types))
        return {"tracks": [{"uri": "track://1", "name": "One", "provider_mappings": [1, 2, 3]}]}

    adapter = _real_adapter(_handler("music/search", search))
    compact = await adapter.call(
        "ma_api:music/search",
        {"query": "one", "media_types": "track"},
        response_mode="compact",
        fields=None,
        max_items=None,
        ctx=MagicMock(),
    )
    full = await adapter.call(
        "ma_api:music/search",
        {"search_query": "one", "media_types": ["track"]},
        response_mode="full",
        fields=None,
        max_items=None,
        ctx=MagicMock(),
    )
    assert seen == [("one", ["track"]), ("one", ["track"])]
    assert "provider_mappings" not in compact["data"]["tracks"][0]
    assert full["data"]["tracks"][0]["provider_mappings"] == [1, 2, 3]


def test_nested_response_lists_are_bounded_deterministically() -> None:
    """Nested collections obey the same compact item budget as root lists."""
    payload = {"groups": [{"items": list(range(40))} for _index in range(40)]}
    first = DynamicAPIAdapter._bounded_envelope(
        "ma_api:test", payload, response_mode="compact", fields=None, max_items=None
    )
    second = DynamicAPIAdapter._bounded_envelope(
        "ma_api:test", payload, response_mode="compact", fields=None, max_items=None
    )
    assert len(first["data"]["groups"]) == 25
    assert len(first["data"]["groups"][0]["items"]) == 25
    assert first == second
    assert first["truncated"] is True


async def test_registry_incompatibility_is_reported_without_breaking_catalog() -> None:
    """Structural MA drift is isolated and leaves actionable diagnostics."""

    async def values() -> list[str]:
        return []

    valid = _handler("music/values", values)
    adapter = _real_adapter(valid)
    adapter.mass.command_handlers["broken"] = SimpleNamespace(target=None)
    assert [entry.name for entry in await adapter.visible_entries()] == ["ma_api:music/values"]
    diagnostics = adapter.diagnostics()
    assert diagnostics["available"] is True
    assert diagnostics["incompatible_handlers"] == ("broken",)
    assert diagnostics["last_error"] == "1 incompatible handler(s) skipped"
    adapter.mass.command_handlers = []
    assert await adapter.visible_entries() == []
    assert adapter.diagnostics()["last_error"] == "mass.command_handlers is not a mapping"


async def test_recipe_requires_both_enabled_tag_and_ma_scope() -> None:
    """Recipes cannot bypass provider permissions or MA domain scopes."""

    async def list_players() -> list[str]:
        return []

    async def values() -> list[str]:
        return []

    tool = Tool.from_function(fn=list_players, name="players_list_players")
    tool = tool.model_copy(update={"tags": {"query:players"}})
    denied_tag = _real_adapter(
        _handler("music/values", values),
        scope_checker=lambda _user, _scope: True,
        allowed_tags=set(),
    )
    denied_tag.ingest_curated([tool])
    assert not any(
        entry.name == "mcp_api:players/summary" for entry in await denied_tag.visible_entries()
    )

    denied_scope = _real_adapter(
        _handler("music/values", values),
        scope_checker=lambda _user, scope: str(getattr(scope, "value", scope)) != "players.read",
        allowed_tags={"query:players"},
    )
    denied_scope.ingest_curated([tool])
    assert not any(
        entry.name == "mcp_api:players/summary" for entry in await denied_scope.visible_entries()
    )


async def test_execution_sets_and_restores_ma_auth_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Native and recipe execution share MA's request-local identity context."""
    current_user: contextvars.ContextVar[Any] = contextvars.ContextVar("current_user")
    current_token: contextvars.ContextVar[Any] = contextvars.ContextVar("current_token")
    auth_middleware = SimpleNamespace(current_user=current_user, current_token=current_token)
    helpers = SimpleNamespace(auth_middleware=auth_middleware)
    monkeypatch.setitem(sys.modules, "music_assistant.controllers.webserver.helpers", helpers)

    async def whoami() -> str:
        return str(current_user.get().user_id)

    adapter = _real_adapter(_handler("music/whoami", whoami))
    result = await adapter.call(
        "ma_api:music/whoami",
        {},
        response_mode="compact",
        fields=None,
        max_items=None,
        ctx=MagicMock(),
    )
    assert result["data"] == "u1"
    with pytest.raises(LookupError):
        current_user.get()


async def test_schema_covers_enum_union_collections_and_impersonation() -> None:
    """Live type hints remain the source of truth for rich command schemas."""

    class Mode(StrEnum):
        ONE = "one"
        TWO = "two"

    async def typed(mode: Mode, values: list[int], optional: str | None = None) -> dict[str, int]:
        return {str(mode): len(values) + bool(optional)}

    handler = _handler("music/typed", typed)
    handler.type_hints = {
        "mode": Mode,
        "values": list[int],
        "optional": str | None,
        "return": dict[str, int],
    }
    handler.allow_impersonation = True
    entry = (await _real_adapter(handler).visible_entries())[0]
    assert entry.input_schema["properties"]["mode"]["enum"] == ["one", "two"]
    assert entry.input_schema["properties"]["values"]["items"]["type"] == "integer"
    assert entry.input_schema["properties"]["optional"]["anyOf"]
    assert entry.input_schema["properties"]["user"]["type"] == "string"
    assert entry.output_schema is not None


@pytest.mark.parametrize(
    ("command", "scope", "risk", "policy"),
    [
        ("music/read", "library.read", DynamicRisk.READ, DynamicPolicy()),
        (
            "players/cmd/play",
            "players.control",
            DynamicRisk.CONTROL,
            DynamicPolicy(control=True),
        ),
        ("music/add_item", "library.write", DynamicRisk.WRITE, DynamicPolicy(write=True)),
        ("config/read", "system.read", DynamicRisk.SYSTEM, DynamicPolicy(system=True)),
    ],
)
async def test_all_risk_classes_require_their_independent_gate(
    command: str, scope: str, risk: DynamicRisk, policy: DynamicPolicy
) -> None:
    """Read, control, write and system gates do not imply one another."""

    async def operation() -> None:
        return None

    handler = _handler(command, operation, scope)
    entries = await _real_adapter(handler, policy=policy).visible_entries()
    assert len(entries) == 1
    assert entries[0].risk is risk
    blocked = DynamicPolicy(read=False)
    assert await _real_adapter(handler, policy=blocked).visible_entries() == []


async def test_disabled_user_and_transport_commands_are_hidden() -> None:
    """Authentication state and transport exclusions are fail-closed."""

    async def operation() -> None:
        return None

    disabled = SimpleNamespace(user_id="u1", enabled=False)
    adapter = _real_adapter(_handler("music/read", operation), user=disabled)
    assert await adapter.visible_entries() == []
    transport = _real_adapter(_handler("dashboard/register", operation))
    assert await transport.visible_entries() == []


async def test_sync_coroutine_and_generator_handlers_close_cleanly() -> None:
    """The dispatcher supports all MA execution shapes and closes generators."""
    closed = False

    def sync_value() -> str:
        return "sync"

    async def coroutine_value() -> str:
        return "async"

    async def generated() -> Any:
        nonlocal closed
        try:
            for index in range(250):
                yield index
        finally:
            closed = True

    for name, target, expected in (
        ("music/sync", sync_value, "sync"),
        ("music/async", coroutine_value, "async"),
    ):
        adapter = _real_adapter(_handler(name, target))
        result = await adapter.call(
            f"ma_api:{name}",
            {},
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=MagicMock(),
        )
        assert result["data"] == expected

    adapter = _real_adapter(_handler("music/generated", generated))
    result = await adapter.call(
        "ma_api:music/generated",
        {},
        response_mode="full",
        fields=None,
        max_items=None,
        ctx=MagicMock(),
    )
    assert result["returned_count"] == 200
    assert closed is True


async def test_confirmation_policy_is_mandatory_for_system_and_impersonation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """System and impersonated calls elicit even when write confirmation is off."""
    confirmation = AsyncMock()
    monkeypatch.setattr("provider.dynamic_api.confirm_or_raise", confirmation)
    adapter = _real_adapter(_handler("music/read", lambda: None))
    handler = object()
    ctx = MagicMock()
    read = DynamicEntry("ma_api:read", "read", "read", {}, DynamicRisk.READ, None, False, handler)
    write = DynamicEntry(
        "ma_api:write", "write", "write", {}, DynamicRisk.WRITE, None, False, handler
    )
    system = DynamicEntry(
        "ma_api:system", "system", "system", {}, DynamicRisk.SYSTEM, None, False, handler
    )
    adapter._confirmation_provider = lambda: False
    await adapter._confirm(read, ctx)
    await adapter._confirm(write, ctx)
    await adapter._confirm(system, ctx)
    await adapter._confirm(read, ctx, impersonating=True)
    assert [call.kwargs["enabled"] for call in confirmation.await_args_list] == [
        False,
        False,
        True,
        True,
    ]
