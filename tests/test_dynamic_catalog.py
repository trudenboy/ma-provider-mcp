"""Contract tests for the permanent dynamic MA API catalog."""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import sys
from dataclasses import dataclass, replace
from enum import StrEnum
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import Client, Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken
from mcp.shared.exceptions import McpError
from mcp.types import INVALID_REQUEST, METHOD_NOT_FOUND, ErrorData
from music_assistant_models.config_entries import ConfigEntry
from music_assistant_models.enums import ConfigEntryType

from provider import meta_discovery
from provider.catalog_pagination import (
    PaginationError,
    decode_cursor,
    encode_cursor,
)
from provider.command_policy import Confirmation, DynamicPolicy, DynamicRisk
from provider.command_profiles import (
    COMMAND_PROFILES,
    CURATED_PROFILE_MAPPINGS,
    CommandProfile,
)
from provider.dynamic_api import (
    CatalogSnapshot,
    CatalogView,
    DynamicAPIAdapter,
    DynamicEntry,
    confirm_or_raise,
)
from provider.meta_discovery import DynamicAdapter, register_meta_discovery
from provider.server import build_tag_lookup
from provider.tags import Tag

_META_NAMES = {"search_tools", "call_tool", "get_tool_schema"}


@dataclass
class _FakeAdapter:
    """Small adapter implementing the transform-facing dynamic API contract."""

    calls: list[tuple[str, dict[str, Any]]]

    async def base_snapshot(self) -> CatalogSnapshot:
        """Return the fake command as the immutable base catalog."""
        return CatalogSnapshot((1, "fake", ()), tuple(await self.visible_entries()))

    async def visible_catalog(self) -> CatalogView:
        """Return the fake command as visible to every request."""
        snapshot = await self.base_snapshot()
        return CatalogView(snapshot.fingerprint, snapshot.entries)

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
    assert result.structured_content is not None
    assert result.structured_content["mode"] == "search"
    assert result.structured_content["items"] == [
        {
            "name": "ma_api:players/cmd/play",
            "description": "Start playback on a player.",
        }
    ]
    assert result.structured_content["total"] == 1
    assert result.structured_content["next_cursor"] is None
    assert result.structured_content["catalog_revision"]


async def test_search_tool_rejects_invalid_limit_with_stable_code() -> None:
    """The wire contract exposes invalid page-size errors without transport detail."""
    mcp, _adapter = _server()
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="invalid_limit"):
            await client.call_tool("search_tools", {"query": "music", "limit": 0})


@pytest.mark.parametrize("limit", ["2", 2.0, True])
async def test_search_tool_rejects_non_integer_limits_with_stable_code(limit: object) -> None:
    """The MCP boundary must not coerce non-integer page sizes."""
    mcp, _adapter = _server()
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="invalid_limit"):
            await client.call_tool("search_tools", {"query": "music", "limit": limit})


async def test_search_tool_rejects_malformed_cursor_with_stable_code() -> None:
    """The wire contract exposes malformed cursor errors with a stable code."""
    mcp, _adapter = _server()
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="invalid_cursor"):
            await client.call_tool("search_tools", {"cursor": "not-json"})


async def test_search_tools_schema_advertises_pagination() -> None:
    """Clients can discover the complete paginated input and output contract."""
    mcp, _adapter = _server()
    async with Client(mcp) as client:
        tool = next(item for item in await client.list_tools() if item.name == "search_tools")
    assert set(tool.inputSchema["properties"]) == {"query", "cursor", "limit"}
    assert tool.outputSchema is not None
    assert {"mode", "items", "total", "next_cursor", "catalog_revision"} <= set(
        tool.outputSchema["properties"]
    )


async def test_call_tool_rejects_retired_name_with_concrete_migration() -> None:
    """Legacy names remain actionable hints but never redirect to executable recipes."""
    mcp, _adapter = _server()
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="ma_api:players/all"):
            await client.call_tool("call_tool", {"name": "players_list_players"})


async def test_search_returns_retired_alias_as_non_executable_migration_hint() -> None:
    """Even aggregate retirements are discoverable but cannot redirect execution."""
    mcp, _adapter = _server()
    async with Client(mcp) as client:
        search = await client.call_tool("search_tools", {"query": "config_list_targets"})
        with pytest.raises(ToolError, match="Use search_tools"):
            await client.call_tool("call_tool", {"name": "config_list_targets"})
    assert search.structured_content is not None
    assert search.structured_content["items"][0]["name"] == "config_list_targets"
    assert "Use search_tools" in search.structured_content["items"][0]["description"]


def _meta_service(adapter: DynamicAdapter) -> Any:
    """Construct the direct discovery service after proving it is exported."""
    service_type = getattr(meta_discovery, "MetaDiscoveryService", None)
    assert service_type is not None
    return service_type(adapter)


def _catalog_entry(name: str, description: str) -> DynamicEntry:
    """Build a minimal entry for direct discovery-index tests."""
    return DynamicEntry(
        name=name,
        command=name.removeprefix("ma_api:"),
        description=description,
        input_schema={"type": "object", "properties": {}},
        risk=DynamicRisk.READ,
        required_scope=None,
        allow_impersonation=False,
        handler=object(),
    )


def _catalog_snapshot(count: int = 7) -> CatalogSnapshot:
    """Build a deterministically ordered discovery catalog."""
    entries = tuple(
        _catalog_entry(f"ma_api:music/command_{index:02d}", f"Music command {index}")
        for index in range(count)
    )
    return CatalogSnapshot(
        (1, "test", tuple((entry.command, index) for index, entry in enumerate(entries))),
        entries,
    )


class _SnapshotAdapter:
    """Expose one immutable base snapshot and matching visible view."""

    def __init__(self, snapshot: CatalogSnapshot) -> None:
        self.snapshot = snapshot

    async def base_snapshot(self) -> CatalogSnapshot:
        """Return the test snapshot."""
        return self.snapshot

    async def visible_catalog(self) -> CatalogView:
        """Make all test entries visible."""
        return CatalogView(self.snapshot.fingerprint, self.snapshot.entries)

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
        """Satisfy the discovery adapter protocol; these tests never execute calls."""
        del name, arguments, response_mode, fields, max_items, ctx
        raise NotImplementedError


async def test_empty_query_browses_alphabetical_catalog_without_descriptions() -> None:
    """Catalog pages expose every visible command name in stable order."""
    service = _meta_service(_SnapshotAdapter(_catalog_snapshot()))
    first = await service.discover("", limit=3)
    second = await service.discover(cursor=first["next_cursor"], limit=3)
    third = await service.discover(cursor=second["next_cursor"], limit=3)
    assert first["mode"] == second["mode"] == third["mode"] == "catalog"
    assert first["total"] == second["total"] == third["total"] == 7
    assert [item["name"] for page in (first, second, third) for item in page["items"]] == [
        f"ma_api:music/command_{index:02d}" for index in range(7)
    ]
    assert all(set(item) == {"name"} for page in (first, second, third) for item in page["items"])
    assert third["next_cursor"] is None


async def test_ranked_search_pages_have_no_duplicates_or_gaps() -> None:
    """Search continuations preserve the ranked result sequence."""
    service = _meta_service(_SnapshotAdapter(_catalog_snapshot()))
    first = await service.discover("music command", limit=2)
    second = await service.discover(cursor=first["next_cursor"], limit=2)
    assert first["mode"] == second["mode"] == "search"
    assert first["total"] == 7
    assert len({item["name"] for item in first["items"] + second["items"]}) == 4
    assert all("description" in item for item in first["items"] + second["items"])


async def test_cursor_accepts_matching_query_and_rejects_conflicting_query() -> None:
    """A continuation accepts normalized text but rejects another search."""
    service = _meta_service(_SnapshotAdapter(_catalog_snapshot()))
    first = await service.discover("music", limit=2)
    resumed = await service.discover(" MUSIC ", cursor=first["next_cursor"], limit=2)
    assert resumed["items"]
    with pytest.raises(PaginationError) as exc_info:
        await service.discover("players", cursor=first["next_cursor"])
    assert exc_info.value.code == "invalid_cursor"


async def test_catalog_change_invalidates_cursor() -> None:
    """A base-catalog revision cannot resume an earlier page sequence."""
    adapter = _SnapshotAdapter(_catalog_snapshot())
    service = _meta_service(adapter)
    first = await service.discover(limit=2)
    adapter.snapshot = _catalog_snapshot(8)
    with pytest.raises(PaginationError) as exc_info:
        await service.discover(cursor=first["next_cursor"])
    assert exc_info.value.code == "catalog_changed"


async def test_impossible_cursor_offset_is_rejected() -> None:
    """A validly encoded but out-of-range offset cannot yield an empty page."""
    service = _meta_service(_SnapshotAdapter(_catalog_snapshot(2)))
    first = await service.discover(limit=1)
    state = decode_cursor(cast("str", first["next_cursor"]))
    forged = encode_cursor(replace(state, offset=99))
    with pytest.raises(PaginationError) as exc_info:
        await service.discover(cursor=forged)
    assert exc_info.value.code == "invalid_cursor"


async def test_visibility_change_invalidates_cursor_without_leaking_hidden_name() -> None:
    """Visibility changes invalidate pages while the next browse hides removed commands."""

    class _VisibilityAdapter(_SnapshotAdapter):
        restricted = False

        async def visible_catalog(self) -> CatalogView:
            entries = self.snapshot.entries[:-1] if self.restricted else self.snapshot.entries
            return CatalogView(self.snapshot.fingerprint, entries)

    adapter = _VisibilityAdapter(_catalog_snapshot())
    service = _meta_service(adapter)
    first = await service.discover(limit=2)
    hidden_name = adapter.snapshot.entries[-1].name
    adapter.restricted = True
    with pytest.raises(PaginationError) as exc_info:
        await service.discover(cursor=first["next_cursor"])
    assert exc_info.value.code == "catalog_changed"
    restricted = await service.discover(limit=50)
    assert hidden_name not in {item["name"] for item in restricted["items"]}


async def test_search_retries_when_registry_changes_between_catalog_reads() -> None:
    """Search retries so metadata and returned descriptions share one generation."""
    first = CatalogSnapshot(
        (1, "test", (("music/first", 1),)),
        (_catalog_entry("ma_api:music/first", "Original collection."),),
    )
    second = CatalogSnapshot(
        (1, "test", (("music/replacement", 2),)),
        (_catalog_entry("ma_api:music/replacement", "Replacement collection."),),
    )

    class _ChangingAdapter(_SnapshotAdapter):
        def __init__(self) -> None:
            super().__init__(first)
            self.changed = False

        async def base_snapshot(self) -> CatalogSnapshot:
            """Replace the live registry after the first visible-catalog read."""
            self.changed = True
            return second

        async def visible_catalog(self) -> CatalogView:
            """Return whichever generation is visible at this instant."""
            snapshot = second if self.changed else first
            return CatalogView(snapshot.fingerprint, snapshot.entries)

    service = _meta_service(_ChangingAdapter())
    assert (await service.discover("replacement"))["items"] == [
        {"name": "ma_api:music/replacement", "description": "Replacement collection."}
    ]


async def test_parallel_searches_contend_for_one_awaitable_index_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Followers wait on the cold-build lock instead of starting duplicate builds."""
    snapshot = CatalogSnapshot(
        (1, "test", (("music/search", 1),)),
        (_catalog_entry("ma_api:music/search", "Search music."),),
    )
    service = _meta_service(_SnapshotAdapter(snapshot))
    build_index = getattr(service, "_build_index", None)
    assert build_index is not None
    started = asyncio.Event()
    release = asyncio.Event()
    attempts = 0

    async def delayed_build(candidate: CatalogSnapshot) -> Any:
        nonlocal attempts
        attempts += 1
        started.set()
        await release.wait()
        return await build_index(candidate)

    monkeypatch.setattr(service, "_build_index", delayed_build)
    leader = asyncio.create_task(service.discover("search"))
    await started.wait()
    followers = [asyncio.create_task(service.discover("search")) for _index in range(19)]
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(leader, *followers)
    assert attempts == 1
    assert service.index_build_count == 1


async def test_failed_index_build_releases_waiters_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient index failure does not poison later discovery searches."""
    snapshot = CatalogSnapshot(
        (1, "test", (("music/search", 1),)),
        (_catalog_entry("ma_api:music/search", "Search music."),),
    )
    service = _meta_service(_SnapshotAdapter(snapshot))
    build_index = getattr(service, "_build_index", None)
    assert build_index is not None
    attempts = 0

    async def fail_once(candidate: CatalogSnapshot) -> Any:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient index failure")
        return await build_index(candidate)

    monkeypatch.setattr(service, "_build_index", fail_once)
    outcomes = await asyncio.gather(
        service.discover("search"), service.discover("search"), return_exceptions=True
    )
    first, second = outcomes
    assert isinstance(first, RuntimeError)
    assert not isinstance(second, BaseException)
    assert second["items"] == [{"name": "ma_api:music/search", "description": "Search music."}]
    assert await service.discover("search") == second
    assert attempts == 2


def test_search_index_does_not_expose_mutable_token_counters() -> None:
    """Callers cannot mutate cached BM25 term frequencies between requests."""
    snapshot = CatalogSnapshot(
        (1, "test", (("music/search", 1),)),
        (_catalog_entry("ma_api:music/search", "Search music."),),
    )
    index = meta_discovery._build_search_index(snapshot)
    with pytest.raises(TypeError):
        cast("dict[str, tuple[str, ...]]", index.documents)["ma_api:other"] = ()
    frequencies = cast("dict[str, dict[str, int]]", index.frequencies)
    with pytest.raises(TypeError):
        frequencies["ma_api:music/search"]["search"] = 99


async def test_parallel_search_builds_one_index() -> None:
    """Concurrent searches share one immutable base-snapshot index."""

    async def search(album: str) -> list[str]:
        """Search albums."""
        return [album]

    adapter = _real_adapter(_handler("music/search", search))
    service = _meta_service(adapter)
    await asyncio.gather(*(service.discover("album") for _index in range(20)))
    assert service.index_build_count == 1


async def test_registry_change_rebuilds_discovery_index_immediately() -> None:
    """A new registry fingerprint invalidates the cached search index."""

    async def existing() -> None:
        """Existing endpoint."""
        return

    async def new_command() -> None:
        """Expose a new endpoint."""
        return

    adapter = _real_adapter(_handler("music/existing", existing))
    service = _meta_service(adapter)
    before = await service.discover("new command")
    adapter.mass.command_handlers["music/new_command"] = _handler("music/new_command", new_command)
    after = await service.discover("new command")
    assert before["items"] == []
    assert after["items"][0]["name"] == "ma_api:music/new_command"
    assert service.index_build_count == 2


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
    mass.webserver.auth.authenticate_with_token = AsyncMock(return_value=user)
    token = AccessToken(token="secret", client_id="u1", scopes=[])
    return DynamicAPIAdapter(
        mass,
        policy_provider=lambda: policy or DynamicPolicy(),
        auth_required_provider=lambda: True,
        confirmation_provider=lambda: True,
        token_provider=lambda: token,
        scope_checker=scope_checker or (lambda _user, _scope: True),
        allowed_tags_provider=lambda: (
            allowed_tags if allowed_tags is not None else {str(tag) for tag in Tag}
        ),
    )


class _UnsupportedElicitationContext:
    """Raise the configured protocol-level unsupported elicitation result."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    async def elicit(self, _prompt: str, *, response_type: type[bool]) -> None:
        """Simulate a client that cannot receive elicitation requests."""
        del response_type
        raise self.error


def _bypass_ma_argument_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep authorization tests independent of MA parser optional dependencies."""
    monkeypatch.setattr(
        "provider.dynamic_api.CompiledSignature.parse",
        lambda _signature, arguments: dict(arguments),
    )


async def test_required_confirmation_rejects_missing_context() -> None:
    """Mandatory confirmation fails closed when no MCP context is available."""
    with pytest.raises(ToolError, match="confirmation is required"):
        await confirm_or_raise(None, "Confirm", required=True)


@pytest.mark.parametrize(
    "error",
    [
        NotImplementedError(),
        McpError(ErrorData(code=INVALID_REQUEST, message="unsupported")),
        McpError(ErrorData(code=METHOD_NOT_FOUND, message="unsupported")),
    ],
)
async def test_required_confirmation_rejects_unsupported_elicitation(error: Exception) -> None:
    """Mandatory confirmation cannot silently skip unsupported client elicitation."""
    with pytest.raises(ToolError, match="confirmation is required"):
        await confirm_or_raise(
            cast("Context", _UnsupportedElicitationContext(error)),
            "Confirm",
            required=True,
        )


@pytest.mark.parametrize(
    "error",
    [
        NotImplementedError(),
        McpError(ErrorData(code=INVALID_REQUEST, message="unsupported")),
        McpError(ErrorData(code=METHOD_NOT_FOUND, message="unsupported")),
    ],
)
async def test_configured_confirmation_skips_unsupported_elicitation(error: Exception) -> None:
    """Configured prompts retain compatibility with clients without elicitation."""
    await confirm_or_raise(
        cast("Context", _UnsupportedElicitationContext(error)),
        "Confirm",
        required=False,
    )


async def test_configured_confirmation_skips_missing_context() -> None:
    """Configured prompts retain compatibility when no elicitation context is injected."""
    await confirm_or_raise(None, "Confirm", required=False)


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


async def test_concurrent_catalog_reads_compile_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent cold readers share one compiled registry snapshot."""

    async def search(search_query: str) -> list[str]:
        return [search_query]

    adapter = _real_adapter(_handler("music/search", search))
    compile_spy = MagicMock(wraps=adapter._compile_entry)
    monkeypatch.setattr(adapter, "_compile_entry", compile_spy)
    snapshots = await asyncio.gather(*(adapter.base_snapshot() for _index in range(20)))
    assert all(snapshot is snapshots[0] for snapshot in snapshots)
    assert snapshots[0].entries[0].name == "ma_api:music/search"
    assert compile_spy.call_count == 1


async def test_registry_replacement_changes_fingerprint_without_restart() -> None:
    """Replacing a live handler invalidates the cached base snapshot."""

    async def search(search_query: str) -> list[str]:
        return [search_query]

    async def replacement(search_query: str, limit: int = 5) -> list[str]:
        return [search_query] * limit

    adapter = _real_adapter(_handler("music/search", search))
    first = await adapter.base_snapshot()
    replacement_handler = _handler("music/search", replacement)
    adapter.mass.command_handlers["music/search"] = replacement_handler
    second = await adapter.base_snapshot()
    assert second.fingerprint != first.fingerprint
    assert second.entries[0].handler is replacement_handler


async def test_registry_validity_changes_fingerprint_and_base_diagnostics() -> None:
    """Empty valid and invalid registries never share cached availability state."""

    async def search(search_query: str) -> list[str]:
        return [search_query]

    adapter = _real_adapter(_handler("music/search", search))
    adapter.mass.command_handlers = {}
    valid = await adapter.base_snapshot()
    assert await adapter.visible_entries() == []
    assert adapter.diagnostics() == {
        "available": True,
        "registry_type": "dict",
        "handlers_seen": 0,
        "handlers_visible": 0,
        "incompatible_handlers": (),
        "last_error": None,
    }

    adapter.mass.command_handlers = []
    invalid = await adapter.base_snapshot()
    assert invalid.fingerprint != valid.fingerprint
    assert await adapter.visible_entries() == []
    assert adapter.diagnostics() == {
        "available": False,
        "registry_type": "list",
        "handlers_seen": 0,
        "handlers_visible": 0,
        "incompatible_handlers": (),
        "last_error": "mass.command_handlers is not a mapping",
    }

    adapter.mass.command_handlers = {}
    restored = await adapter.base_snapshot()
    assert restored.fingerprint == valid.fingerprint
    assert restored is not valid
    assert await adapter.visible_entries() == []
    assert adapter.diagnostics()["available"] is True


async def test_cached_snapshot_keeps_visibility_request_specific() -> None:
    """A shared descriptor never leaks one user's scope visibility to another."""

    async def search(search_query: str) -> list[str]:
        return [search_query]

    handler = _handler("music/search", search)
    allowed = SimpleNamespace(user_id="allowed", enabled=True, scopes={"library.read"})
    denied = SimpleNamespace(user_id="denied", enabled=True, scopes=set())
    users = {user.user_id: user for user in (allowed, denied)}
    current_token: contextvars.ContextVar[AccessToken] = contextvars.ContextVar("current_token")
    mass = MagicMock(command_handlers={handler.command: handler})
    mass.webserver.auth.get_user = AsyncMock(side_effect=users.__getitem__)
    adapter = DynamicAPIAdapter(
        mass,
        policy_provider=DynamicPolicy,
        auth_required_provider=lambda: True,
        confirmation_provider=lambda: True,
        token_provider=current_token.get,
        scope_checker=lambda user, scope: scope in user.scopes,
        allowed_tags_provider=lambda: {str(tag) for tag in Tag},
    )

    async def catalog_for(user_id: str) -> Any:
        token = current_token.set(AccessToken(token="secret", client_id=user_id, scopes=[]))
        try:
            return await adapter.visible_catalog()
        finally:
            current_token.reset(token)

    allowed_view, denied_view = await asyncio.gather(catalog_for("allowed"), catalog_for("denied"))
    snapshot = await adapter.base_snapshot()
    assert allowed_view.fingerprint == denied_view.fingerprint == snapshot.fingerprint
    assert allowed_view.entries == snapshot.entries
    assert allowed_view.entries[0] is snapshot.entries[0]
    assert denied_view.entries == ()
    base_diagnostics = adapter.diagnostics()
    assert base_diagnostics["handlers_visible"] == 1
    await catalog_for("denied")
    assert adapter.diagnostics() == base_diagnostics


async def test_failed_snapshot_build_does_not_poison_future_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exceptional cold build releases concurrent readers and remains retryable."""

    async def search(search_query: str) -> list[str]:
        return [search_query]

    adapter = _real_adapter(_handler("music/search", search))
    compile_entry = adapter._compile_entry
    attempts = 0

    def fail_once(command: str, handler: Any, decision: Any) -> DynamicEntry:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient compile failure")
        return compile_entry(command, handler, decision)

    monkeypatch.setattr(adapter, "_compile_entry", fail_once)
    outcomes = await asyncio.gather(
        adapter.base_snapshot(), adapter.base_snapshot(), return_exceptions=True
    )
    assert isinstance(outcomes[0], RuntimeError)
    assert isinstance(outcomes[1], CatalogSnapshot)
    assert outcomes[1].entries[0].name == "ma_api:music/search"
    assert (await adapter.base_snapshot()) is outcomes[1]
    assert attempts == 2


async def test_cancelled_snapshot_builder_and_waiter_leave_later_reads_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation never leaves the catalog lock held or poisons its next reader."""

    async def search(search_query: str) -> list[str]:
        return [search_query]

    adapter = _real_adapter(_handler("music/search", search))
    compile_snapshot = adapter._compile_snapshot
    attempts = 0

    def cancel_once(fingerprint: Any) -> Any:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise asyncio.CancelledError
        return compile_snapshot(fingerprint)

    monkeypatch.setattr(adapter, "_compile_snapshot", cancel_once)
    with pytest.raises(asyncio.CancelledError):
        await adapter.base_snapshot()

    await adapter._snapshot_lock.acquire()
    waiter = asyncio.create_task(adapter.base_snapshot())
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    adapter._snapshot_lock.release()

    snapshot = await adapter.base_snapshot()
    assert snapshot.entries[0].name == "ma_api:music/search"
    assert attempts == 2


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
    with pytest.raises(ToolError, match="Unexpected argument\\(s\\): typo"):
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


async def test_empty_upstream_exception_names_type_and_command() -> None:
    """Empty upstream messages still produce an actionable command error."""

    async def search(search_query: str) -> list[str]:
        del search_query
        raise IndexError

    adapter = _real_adapter(_handler("music/search", search))
    with pytest.raises(ToolError, match=r"music/search.*IndexError"):
        await adapter.call(
            "ma_api:music/search",
            {"search_query": "missing"},
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=MagicMock(),
        )


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


def test_every_migrated_command_has_an_executable_profile() -> None:
    """The migration matrix is backed by profiles, not aliases alone."""
    assert set(CURATED_PROFILE_MAPPINGS.values()).issubset(COMMAND_PROFILES)
    for legacy, command in CURATED_PROFILE_MAPPINGS.items():
        profile = COMMAND_PROFILES[command]
        assert isinstance(profile, CommandProfile)
        assert legacy in profile.search_aliases
        assert profile.annotations
        assert profile.risk_override in {"read", "control", "write", "system"}
    assert COMMAND_PROFILES["providers"].compact_fields == (
        "instance_id",
        "domain",
        "type",
        "name",
        "available",
        "enabled",
        "last_error",
    )


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


def test_large_search_envelope_keeps_mapping_shape_within_byte_budget() -> None:
    """Large SearchResults mappings shrink nested rows instead of becoming a string."""
    payload = {
        "tracks": [
            {
                "uri": f"provider://track/{index}",
                "name": f"Track {index} " + ("x" * 900),
                "media_type": "track",
                "artists": [{"uri": "provider://artist/1", "name": "Artist"}],
            }
            for index in range(30)
        ],
        "albums": [],
    }

    result = DynamicAPIAdapter._bounded_envelope(
        "ma_api:music/search",
        payload,
        response_mode="compact",
        fields=None,
        max_items=None,
        profile=COMMAND_PROFILES["music/search"],
    )

    assert isinstance(result["data"], dict)
    assert 0 < len(result["data"]["tracks"]) < 30
    assert result["data"]["albums"] == []
    assert result["truncated"] is True
    assert result["bytes"] <= 12_288


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


async def test_execution_sets_and_restores_ma_auth_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Native execution sets and restores MA's request-local identity context."""
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
        (
            "music/add_item",
            "library.write",
            DynamicRisk.WRITE,
            DynamicPolicy(write=True),
        ),
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


async def test_native_command_requires_its_live_permission_tag() -> None:
    """Native handlers cannot bypass the provider's existing permission toggles."""

    async def operation() -> None:
        return None

    handler = _handler("music/search", operation, "library.read")
    assert await _real_adapter(handler, allowed_tags=set()).visible_entries() == []
    visible = await _real_adapter(handler, allowed_tags={str(Tag.QUERY_LIBRARY)}).visible_entries()
    assert [entry.name for entry in visible] == ["ma_api:music/search"]


@pytest.mark.parametrize(
    ("command", "parameter", "user_filter"),
    [
        ("players/get", "player_id", "player_filter"),
        ("config/providers/get", "instance_id", "provider_filter"),
    ],
)
async def test_invocation_rejects_targets_outside_user_filters(
    command: str, parameter: str, user_filter: str
) -> None:
    """Direct dynamic invocation preserves MA player and provider filters."""
    called = False

    async def operation(**kwargs: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        return kwargs

    operation.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        [inspect.Parameter(parameter, inspect.Parameter.POSITIONAL_OR_KEYWORD)]
    )
    handler = _handler(command, operation, "players.read")
    handler.type_hints = {parameter: str, "return": dict[str, Any]}
    filters: dict[str, list[str]] = {"player_filter": [], "provider_filter": []}
    filters[user_filter] = [f"allowed-{user_filter.removesuffix('_filter')}"]
    user = SimpleNamespace(
        user_id="u1",
        username="limited",
        enabled=True,
        role="user",
        **filters,
    )
    adapter = _real_adapter(
        handler,
        policy=DynamicPolicy(read=True, system=True),
        user=user,
    )
    with pytest.raises(ToolError, match="not permitted"):
        await adapter.call(
            f"ma_api:{command}",
            {parameter: "blocked-target"},
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=MagicMock(),
        )
    assert called is False


async def test_admin_scope_is_not_restricted_by_user_filters() -> None:
    """Admin calls retain MA's Scope.ALL exemption from target filters."""

    async def get_player(player_id: str) -> str:
        return player_id

    admin = SimpleNamespace(
        user_id="u1",
        username="admin",
        enabled=True,
        role="admin",
        player_filter=["other-player"],
        provider_filter=["other-provider"],
    )
    adapter = _real_adapter(_handler("players/get", get_player, "players.read"), user=admin)
    result = await adapter.call(
        "ma_api:players/get",
        {"player_id": "kitchen"},
        response_mode="compact",
        fields=None,
        max_items=None,
        ctx=MagicMock(),
    )
    assert result["data"] == "kitchen"


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
        "ma_api:system",
        "system",
        "system",
        {},
        DynamicRisk.SYSTEM,
        None,
        False,
        handler,
    )
    adapter._confirmation_provider = lambda: True
    await adapter._confirm(read, ctx)
    await adapter._confirm(write, ctx)
    await adapter._confirm(system, ctx)
    await adapter._confirm(read, ctx, impersonating=True)
    assert [call.kwargs["required"] for call in confirmation.await_args_list] == [
        False,
        True,
        True,
    ]


async def test_queue_delete_always_confirms_before_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disabling configured write prompts cannot bypass destructive queue elicitation."""
    confirmation = AsyncMock()
    monkeypatch.setattr("provider.dynamic_api.confirm_or_raise", confirmation)
    called = False

    async def clear(queue_id: str) -> None:
        nonlocal called
        del queue_id
        called = True

    adapter = _real_adapter(
        _handler("player_queues/clear", clear, "queues.control"),
        policy=DynamicPolicy(write=True),
        allowed_tags={str(Tag.DELETE_QUEUE)},
    )
    adapter._confirmation_provider = lambda: False
    entry = (await adapter.visible_entries())[0]
    assert entry.risk is DynamicRisk.WRITE
    assert entry.decision is not None
    assert entry.decision.confirmation is Confirmation.ALWAYS
    await adapter.call(
        "ma_api:player_queues/clear",
        {"queue_id": "kitchen"},
        response_mode="compact",
        fields=None,
        max_items=None,
        ctx=MagicMock(),
    )
    await_args = confirmation.await_args
    assert await_args is not None
    assert await_args.kwargs["required"] is True
    assert called is True


async def test_playlist_provider_alias_is_filtered_before_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Profile alias conversion cannot bypass a restricted provider filter."""
    confirmation = AsyncMock()
    monkeypatch.setattr("provider.dynamic_api.confirm_or_raise", confirmation)
    called = False

    async def create_playlist(name: str, provider_instance_or_domain: str) -> dict[str, str]:
        nonlocal called
        called = True
        return {"name": name, "provider": provider_instance_or_domain}

    user = SimpleNamespace(
        user_id="u1",
        username="limited",
        enabled=True,
        role="user",
        player_filter=[],
        provider_filter=["allowed-provider"],
    )
    adapter = _real_adapter(
        _handler(
            "music/playlists/create_playlist",
            create_playlist,
            "library.write",
        ),
        policy=DynamicPolicy(write=True),
        allowed_tags={str(Tag.EDIT_PLAYLISTS)},
        user=user,
    )
    with pytest.raises(ToolError, match="not permitted"):
        await adapter.call(
            "ma_api:music/playlists/create_playlist",
            {"name": "Blocked", "provider_instance_id": "blocked-provider"},
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=MagicMock(),
        )
    confirmation.assert_not_awaited()
    assert called is False


@pytest.mark.parametrize("revoked", ["policy", "tag", "scope"])
async def test_native_live_authorization_revocation_prevents_elicitation(
    revoked: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Native live policy, tag and scope revocation all fail before elicitation."""
    confirmation = AsyncMock()
    monkeypatch.setattr("provider.dynamic_api.confirm_or_raise", confirmation)
    called = False
    policy_checks = 0
    tag_checks = 0
    scope_checks = 0

    async def write() -> None:
        nonlocal called
        called = True

    adapter = _real_adapter(
        _handler("music/write", write, "library.write"),
        policy=DynamicPolicy(write=True),
        allowed_tags={str(Tag.EDIT_LIBRARY)},
    )

    def policy_provider() -> DynamicPolicy:
        nonlocal policy_checks
        policy_checks += 1
        return DynamicPolicy(write=revoked != "policy" or policy_checks == 1)

    def tags_provider() -> set[str]:
        nonlocal tag_checks
        tag_checks += 1
        return {str(Tag.EDIT_LIBRARY)} if revoked != "tag" or tag_checks == 1 else set()

    def scope_checker(_user: Any, _scope: Any) -> bool:
        nonlocal scope_checks
        scope_checks += 1
        return revoked != "scope" or scope_checks == 1

    adapter._policy_provider = policy_provider
    adapter._allowed_tags_provider = tags_provider
    adapter._scope_checker = scope_checker
    with pytest.raises(ToolError, match="not permitted"):
        await adapter.call(
            "ma_api:music/write",
            {},
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=MagicMock(),
        )
    confirmation.assert_not_awaited()
    assert called is False


@pytest.mark.parametrize("revoked", ["handler", "policy", "tag", "scope"])
async def test_native_authorization_revoked_during_confirmation_prevents_execution(
    revoked: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Authorization changes while eliciting are rechecked before invocation."""
    called: list[str] = []
    state = {"policy": True, "tag": True, "scope": True}

    async def write() -> None:
        called.append("stale")

    async def replacement() -> None:
        called.append("replacement")

    handler = _handler("music/write", write, "library.write")
    adapter = _real_adapter(
        handler,
        policy=DynamicPolicy(write=True),
        allowed_tags={str(Tag.EDIT_LIBRARY)},
    )
    adapter._policy_provider = lambda: DynamicPolicy(write=state["policy"])
    adapter._allowed_tags_provider = lambda: {str(Tag.EDIT_LIBRARY)} if state["tag"] else set()
    adapter._scope_checker = lambda _user, _scope: state["scope"]

    async def revoke_during_confirmation(*_args: Any, **_kwargs: Any) -> None:
        if revoked == "handler":
            adapter.mass.command_handlers[handler.command] = _handler(
                handler.command, replacement, "library.write"
            )
        else:
            state[revoked] = False

    confirmation = AsyncMock(side_effect=revoke_during_confirmation)
    monkeypatch.setattr("provider.dynamic_api.confirm_or_raise", confirmation)

    with pytest.raises(ToolError, match="not permitted"):
        await adapter.call(
            "ma_api:music/write",
            {},
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=MagicMock(),
        )
    confirmation.assert_awaited_once()
    assert called == []


@pytest.mark.parametrize("replacement", [None, "disabled"])
async def test_fresh_authentication_rejects_removed_or_disabled_user_after_confirmation(
    replacement: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user that changes while confirming cannot execute with stale authentication."""
    _bypass_ma_argument_parser(monkeypatch)
    called = False
    initial_user = SimpleNamespace(user_id="u1", enabled=True, role="admin")
    current_user: Any = initial_user

    async def reload_provider() -> None:
        nonlocal called
        called = True

    adapter = _real_adapter(
        _handler("config/providers/reload", reload_provider, "config.providers.write"),
        policy=DynamicPolicy(write=True),
        allowed_tags={str(Tag.CONFIG_WRITE_PROVIDER)},
        user=initial_user,
    )
    adapter.mass.webserver.auth.get_user = AsyncMock(side_effect=lambda _user_id: current_user)
    adapter.mass.webserver.auth.authenticate_with_token = AsyncMock(
        side_effect=lambda _token: current_user
    )

    async def change_user(*_args: Any, **_kwargs: Any) -> None:
        nonlocal current_user
        current_user = (
            None
            if replacement is None
            else SimpleNamespace(user_id="u1", enabled=False, role="admin")
        )

    monkeypatch.setattr(
        "provider.dynamic_api.confirm_or_raise",
        AsyncMock(side_effect=change_user),
    )

    with pytest.raises(ToolError, match="Authentication is required"):
        await adapter.call(
            "ma_api:config/providers/reload",
            {},
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=MagicMock(),
        )
    assert called is False


async def test_revoked_bearer_token_after_confirmation_prevents_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Post-confirm authorization rejects a token that MA no longer accepts."""
    _bypass_ma_argument_parser(monkeypatch)
    called = False

    async def reload_provider() -> None:
        nonlocal called
        called = True

    adapter = _real_adapter(
        _handler("config/providers/reload", reload_provider, "config.providers.write"),
        policy=DynamicPolicy(write=True),
        allowed_tags={str(Tag.CONFIG_WRITE_PROVIDER)},
    )
    adapter.mass.webserver.auth.authenticate_with_token = AsyncMock(return_value=None)
    monkeypatch.setattr("provider.dynamic_api.confirm_or_raise", AsyncMock())

    with pytest.raises(ToolError, match="Authentication is required"):
        await adapter.call(
            "ma_api:config/providers/reload",
            {},
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=MagicMock(),
        )
    adapter.mass.webserver.auth.authenticate_with_token.assert_awaited_once_with("secret")
    assert called is False


async def test_valid_bearer_revalidation_uses_the_fresh_user_after_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Post-confirm execution uses the user returned by MA token validation."""
    _bypass_ma_argument_parser(monkeypatch)
    called = False
    fresh_user = SimpleNamespace(user_id="u1", enabled=True, role="admin")

    async def reload_provider() -> None:
        nonlocal called
        called = True

    adapter = _real_adapter(
        _handler("config/providers/reload", reload_provider, "config.providers.write"),
        policy=DynamicPolicy(write=True),
        allowed_tags={str(Tag.CONFIG_WRITE_PROVIDER)},
    )
    adapter.mass.webserver.auth.authenticate_with_token = AsyncMock(return_value=fresh_user)
    monkeypatch.setattr("provider.dynamic_api.confirm_or_raise", AsyncMock())

    await adapter.call(
        "ma_api:config/providers/reload",
        {},
        response_mode="compact",
        fields=None,
        max_items=None,
        ctx=MagicMock(),
    )
    adapter.mass.webserver.auth.authenticate_with_token.assert_awaited_once_with("secret")
    assert called is True


async def test_post_confirmation_revalidation_rejects_a_different_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bearer token cannot switch the adapter to another MA user identity."""
    _bypass_ma_argument_parser(monkeypatch)
    called = False

    async def reload_provider() -> None:
        nonlocal called
        called = True

    adapter = _real_adapter(
        _handler("config/providers/reload", reload_provider, "config.providers.write"),
        policy=DynamicPolicy(write=True),
        allowed_tags={str(Tag.CONFIG_WRITE_PROVIDER)},
    )
    adapter.mass.webserver.auth.authenticate_with_token = AsyncMock(
        return_value=SimpleNamespace(user_id="other-user", enabled=True, role="admin")
    )
    monkeypatch.setattr("provider.dynamic_api.confirm_or_raise", AsyncMock())

    with pytest.raises(ToolError, match="Authentication is required"):
        await adapter.call(
            "ma_api:config/providers/reload",
            {},
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=MagicMock(),
        )
    assert called is False


async def test_target_filter_revoked_during_confirmation_prevents_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Post-confirm authorization re-applies the current user's target filters."""
    _bypass_ma_argument_parser(monkeypatch)
    called = False
    current_user: Any = SimpleNamespace(
        user_id="u1",
        enabled=True,
        role="user",
        player_filter=["kitchen"],
        provider_filter=[],
    )

    async def clear(queue_id: str) -> None:
        nonlocal called
        del queue_id
        called = True

    adapter = _real_adapter(
        _handler("player_queues/clear", clear, "queues.control"),
        policy=DynamicPolicy(write=True),
        allowed_tags={str(Tag.DELETE_QUEUE)},
        user=current_user,
    )
    adapter.mass.webserver.auth.get_user = AsyncMock(side_effect=lambda _user_id: current_user)
    adapter.mass.webserver.auth.authenticate_with_token = AsyncMock(
        side_effect=lambda _token: current_user
    )

    async def revoke_filter(*_args: Any, **_kwargs: Any) -> None:
        nonlocal current_user
        current_user = SimpleNamespace(
            user_id="u1",
            enabled=True,
            role="user",
            player_filter=["living-room"],
            provider_filter=[],
        )

    monkeypatch.setattr(
        "provider.dynamic_api.confirm_or_raise",
        AsyncMock(side_effect=revoke_filter),
    )

    with pytest.raises(ToolError, match="target is not permitted"):
        await adapter.call(
            "ma_api:player_queues/clear",
            {"queue_id": "kitchen"},
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=MagicMock(),
        )
    assert called is False


async def test_secret_tag_revoked_during_confirmation_prevents_config_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The request-dependent secret guard runs again after the prompt returns."""
    _bypass_ma_argument_parser(monkeypatch)
    called = False
    state = {"secret": True}

    async def save_provider_config(
        provider_domain: str,
        values: dict[str, Any],
        instance_id: str | None = None,
    ) -> None:
        nonlocal called
        del provider_domain, values, instance_id
        called = True

    adapter = _real_adapter(
        _handler("config/providers/save", save_provider_config, "config.providers.write"),
        policy=DynamicPolicy(write=True),
        allowed_tags=set(),
    )
    adapter._allowed_tags_provider = lambda: {
        str(Tag.CONFIG_WRITE_PROVIDER),
        *({str(Tag.CONFIG_WRITE_SECRET)} if state["secret"] else set()),
    }
    adapter.mass.config.get_provider_config_entries = AsyncMock(
        return_value=[ConfigEntry(key="token", type=ConfigEntryType.SECURE_STRING, label="Token")]
    )

    async def revoke_secret(*_args: Any, **_kwargs: Any) -> None:
        state["secret"] = False

    monkeypatch.setattr(
        "provider.dynamic_api.confirm_or_raise",
        AsyncMock(side_effect=revoke_secret),
    )

    with pytest.raises(ToolError, match="config:write:secret"):
        await adapter.call(
            "ma_api:config/providers/save",
            {
                "provider_domain": "demo",
                "instance_id": "demo--1",
                "values": {"token": "secret"},
            },
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=MagicMock(),
        )
    assert called is False


async def test_flow_category_revoked_during_confirmation_prevents_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A flow rechecks its exact provider/player permission after confirmation."""
    _bypass_ma_argument_parser(monkeypatch)
    called = False
    state = {"provider": True}

    async def submit_flow(flow_id: str, values: dict[str, Any]) -> None:
        nonlocal called
        del flow_id, values
        called = True

    adapter = _real_adapter(
        _handler("config/flows/submit", submit_flow),
        policy=DynamicPolicy(write=True),
        allowed_tags=set(),
    )
    adapter._allowed_tags_provider = lambda: {
        str(Tag.CONFIG_WRITE_PLAYER),
        *({str(Tag.CONFIG_WRITE_PROVIDER)} if state["provider"] else set()),
    }
    adapter.mass.config.get_setup_flow_required_scope = lambda _flow_id: "config.providers.write"
    adapter.mass.config.get_setup_flow = AsyncMock(
        return_value=SimpleNamespace(
            entries=[ConfigEntry(key="name", type=ConfigEntryType.STRING, label="Name")]
        )
    )

    async def revoke_provider_category(*_args: Any, **_kwargs: Any) -> None:
        state["provider"] = False

    monkeypatch.setattr(
        "provider.dynamic_api.confirm_or_raise",
        AsyncMock(side_effect=revoke_provider_category),
    )

    with pytest.raises(ToolError, match="config:write:provider"):
        await adapter.call(
            "ma_api:config/flows/submit",
            {"flow_id": "provider-flow", "values": {"name": "Kitchen"}},
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=MagicMock(),
        )
    assert called is False


async def test_player_only_tag_executes_a_player_setup_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catalog any-of visibility still permits the matching live flow category."""
    _bypass_ma_argument_parser(monkeypatch)
    called = False

    async def submit_flow(flow_id: str, values: dict[str, Any]) -> None:
        nonlocal called
        del flow_id, values
        called = True

    adapter = _real_adapter(
        _handler("config/flows/submit", submit_flow),
        policy=DynamicPolicy(write=True),
        allowed_tags={str(Tag.CONFIG_WRITE_PLAYER)},
    )
    adapter.mass.config.get_setup_flow_required_scope = lambda _flow_id: "config.players.write"
    adapter.mass.config.get_setup_flow = AsyncMock(
        return_value=SimpleNamespace(
            entries=[ConfigEntry(key="name", type=ConfigEntryType.STRING, label="Name")]
        )
    )
    monkeypatch.setattr("provider.dynamic_api.confirm_or_raise", AsyncMock())

    await adapter.call(
        "ma_api:config/flows/submit",
        {"flow_id": "player-flow", "values": {"name": "Kitchen"}},
        response_mode="compact",
        fields=None,
        max_items=None,
        ctx=MagicMock(),
    )
    assert called is True


async def test_provider_setup_flow_rejects_player_only_tag_before_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catalog visibility does not let a player tag invoke a provider flow."""
    _bypass_ma_argument_parser(monkeypatch)
    confirmation = AsyncMock()

    async def submit_flow(flow_id: str, values: dict[str, Any]) -> None:
        del flow_id, values

    adapter = _real_adapter(
        _handler("config/flows/submit", submit_flow),
        policy=DynamicPolicy(write=True),
        allowed_tags={str(Tag.CONFIG_WRITE_PLAYER)},
    )
    adapter.mass.config.get_setup_flow_required_scope = lambda _flow_id: "config.providers.write"
    adapter.mass.config.get_setup_flow = AsyncMock(
        return_value=SimpleNamespace(
            entries=[ConfigEntry(key="name", type=ConfigEntryType.STRING, label="Name")]
        )
    )
    monkeypatch.setattr("provider.dynamic_api.confirm_or_raise", confirmation)

    with pytest.raises(ToolError, match="config:write:provider"):
        await adapter.call(
            "ma_api:config/flows/submit",
            {"flow_id": "provider-flow", "values": {"name": "Kitchen"}},
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=MagicMock(),
        )
    confirmation.assert_not_awaited()


async def test_native_config_secret_denial_precedes_confirmation_and_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Native config secret preflight rejects before elicitation or mutation."""
    confirmation = AsyncMock()
    monkeypatch.setattr("provider.dynamic_api.confirm_or_raise", confirmation)
    called = False

    async def save_provider_config(
        provider_domain: str,
        values: dict[str, Any],
        instance_id: str | None = None,
    ) -> None:
        nonlocal called
        del provider_domain, values, instance_id
        called = True

    adapter = _real_adapter(
        _handler(
            "config/providers/save",
            save_provider_config,
            "config.providers.write",
        ),
        policy=DynamicPolicy(write=True),
        allowed_tags={str(Tag.CONFIG_WRITE_PROVIDER)},
    )
    adapter.mass.config.get_provider_config_entries = AsyncMock(
        return_value=[ConfigEntry(key="token", type=ConfigEntryType.SECURE_STRING, label="Token")]
    )
    with pytest.raises(ToolError, match="config:write:secret"):
        await adapter.call(
            "ma_api:config/providers/save",
            {
                "provider_domain": "demo",
                "instance_id": "demo--1",
                "values": {"token": "secret"},
            },
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=MagicMock(),
        )
    confirmation.assert_not_awaited()
    assert called is False


async def test_impersonation_is_authorized_before_confirmation_and_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller without impersonation scope cannot elicit or run as another user."""
    confirmation = AsyncMock()
    monkeypatch.setattr("provider.dynamic_api.confirm_or_raise", confirmation)
    called = False

    async def operation() -> None:
        nonlocal called
        called = True

    caller = SimpleNamespace(
        user_id="u1",
        username="caller",
        enabled=True,
        role="guest",
        player_filter=[],
        provider_filter=[],
    )
    target = SimpleNamespace(
        user_id="u2",
        username="target",
        enabled=True,
        role="guest",
        player_filter=[],
        provider_filter=[],
    )
    handler = _handler("music/read", operation, "library.read")
    handler.allow_impersonation = True
    adapter = _real_adapter(handler, user=caller)
    adapter.mass.webserver.auth.get_user = AsyncMock(
        side_effect=lambda identifier: caller if identifier == "u1" else target
    )
    adapter.mass.webserver.auth.get_user_by_username = AsyncMock(return_value=None)
    with pytest.raises(ToolError, match="impersonate"):
        await adapter.call(
            "ma_api:music/read",
            {"user": "u2"},
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=MagicMock(),
        )
    confirmation.assert_not_awaited()
    assert called is False
