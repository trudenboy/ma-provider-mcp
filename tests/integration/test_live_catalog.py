"""Opt-in authenticated smoke coverage for the mounted live MA MCP catalog."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator, Mapping
from typing import Any, cast

import pytest
from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError

LIBRARY_ITEM_COMMANDS = [
    "music/albums/library_items",
    "music/artists/library_items",
    "music/audiobooks/library_items",
    "music/genres/library_items",
    "music/playlists/library_items",
    "music/podcasts/library_items",
    "music/tracks/library_items",
]

type LiveClient = Client[Any]


async def _accept_elicitation(message: str, response_type: Any, params: Any, context: Any) -> Any:
    """Accept only in the explicit, reversible integration environment."""
    del message, params, context
    return response_type(value=True)


def _live_settings() -> tuple[str, str]:
    url = os.getenv("MA_MCP_URL")
    token = os.getenv("MA_MCP_TOKEN")
    if not url or not token:
        pytest.skip("set MA_MCP_URL and MA_MCP_TOKEN for Docker integration tests")
    return url, token


@pytest.fixture
async def live_client() -> AsyncIterator[LiveClient]:
    """Yield a live authenticated client only when credentials were supplied."""
    url, token = _live_settings()
    transport = StreamableHttpTransport(url, auth=token)
    async with Client(transport, elicitation_handler=_accept_elicitation) as client:
        yield client


async def call_ma(client: LiveClient, command: str, arguments: Mapping[str, Any]) -> Any:
    """Invoke a canonical MA command and return its JSON-compatible payload."""
    result = await client.call_tool(
        "call_tool", {"name": f"ma_api:{command}", "arguments": dict(arguments)}
    )
    assert not result.is_error, result.content
    envelope = result.data
    assert envelope["command"] == f"ma_api:{command}"
    json.dumps(envelope["data"])
    return envelope["data"]


def require_env(name: str) -> str:
    """Require explicit opt-in before any state-changing integration operation."""
    value = os.getenv(name)
    if not value:
        pytest.skip(f"set {name} to run the queue mutation test")
    return value


def item_id(item: Mapping[str, Any]) -> str:
    """Normalize MA queue-item identifiers across current server versions."""
    return str(item.get("queue_item_id") or item["item_id"])


async def queue_items(client: LiveClient, queue_id: str) -> list[dict[str, Any]]:
    """Read enough queue items to compare ordering after reversible cleanup."""
    return cast(
        "list[dict[str, Any]]",
        await call_ma(client, "player_queues/items", {"queue_id": queue_id, "limit": 500}),
    )


async def find_test_track_uri(client: LiveClient, *, purpose: str) -> str:
    """Find one provider-backed item, or explicitly skip unavailable live coverage."""
    search = await call_ma(
        client,
        "music/search",
        {
            "search_query": "Daft Punk Random Access Memories",
            "media_types": ["track"],
            "limit": 5,
            "library_only": False,
        },
    )
    if not (tracks := search.get("tracks", [])):
        pytest.skip(f"configured providers returned no track for {purpose}")
    for track in tracks:
        uri = str(track.get("uri", ""))
        provider = str(track.get("provider", ""))
        if uri.startswith("yandex_music") and provider.startswith("yandex_music"):
            return uri
    pytest.skip(f"configured provider search returned no provider-backed track URI for {purpose}")


async def wait_for_own_added_item(
    client: LiveClient, queue_id: str, before_ids: set[str], track_uri: str
) -> dict[str, Any]:
    """Find only this test's one new URI, never a concurrent caller's row."""
    for _attempt in range(20):
        added = [
            item for item in await queue_items(client, queue_id) if item_id(item) not in before_ids
        ]
        owned = [item for item in added if str(item.get("uri", "")) == track_uri]
        if len(owned) == 1:
            return owned[0]
        if len(owned) > 1:
            raise AssertionError("concurrent queue update made the test-added item ambiguous")
        await asyncio.sleep(0.25)
    raise AssertionError("test-added queue item did not appear within five seconds")


async def remove_added_item(client: LiveClient, queue_id: str, added_id: str) -> None:
    """Remove the exact queue item ID established from this test's unique diff."""
    removed = await call_ma(
        client,
        "fastmcp/queue/remove_items_safe",
        {"queue_id": queue_id, "item_ids": [added_id]},
    )
    assert removed["removed"] == [added_id]


@pytest.mark.integration
async def test_live_meta_surface_and_discovery_latency(live_client: LiveClient) -> None:
    """The mounted endpoint exposes only discovery tools and has bounded lookup latency."""
    assert {tool.name for tool in await live_client.list_tools()} == {
        "search_tools",
        "get_tool_schema",
        "call_tool",
    }
    started = time.monotonic()
    await asyncio.gather(
        *(live_client.call_tool("search_tools", {"query": "album tracks"}) for _ in range(10))
    )
    cold_elapsed = time.monotonic() - started
    started = time.monotonic()
    await live_client.call_tool("search_tools", {"query": "album tracks"})
    warm_elapsed = time.monotonic() - started
    print(f"discovery cold={cold_elapsed:.3f}s warm={warm_elapsed:.3f}s")  # noqa: T201
    assert cold_elapsed < 5.0
    assert warm_elapsed < 1.0


@pytest.mark.integration
async def test_live_track_album_and_player_calls_are_json_serializable(
    live_client: LiveClient,
) -> None:
    """Provider-backed item, album, and player paths serialize through one envelope."""
    providers = await call_ma(live_client, "providers", {})
    assert any(
        provider.get("domain") == "yandex_music" and provider.get("available") is True
        for provider in providers
    )
    track_uri = await find_test_track_uri(live_client, purpose="track/album serialization")
    track = await call_ma(live_client, "music/item_by_uri", {"uri": track_uri})
    assert track["uri"] == track_uri
    album = track.get("album")
    if not isinstance(album, Mapping) or not (album_uri := album.get("uri")):
        pytest.skip("provider-backed track did not include an album URI")
    album_details = await call_ma(live_client, "music/item_by_uri", {"uri": album_uri})
    await call_ma(
        live_client,
        "music/albums/album_tracks",
        {
            "item_id": str(album_details["item_id"]),
            "provider_instance_id_or_domain": str(album_details["provider"]),
        },
    )
    players = await call_ma(live_client, "players/all", {})
    if not players:
        pytest.skip("configured MA instance has no player for players/get regression")
    player_id = str(players[0]["player_id"])
    await call_ma(live_client, "players/get", {"player_id": player_id})
    active_queue = await call_ma(
        live_client, "player_queues/get_active_queue", {"player_id": player_id}
    )
    if not active_queue:
        pytest.skip("configured player has no active queue for queue read regression")
    queue_id = str(active_queue["queue_id"])
    await call_ma(live_client, "player_queues/get", {"queue_id": queue_id})
    await call_ma(live_client, "player_queues/items", {"queue_id": queue_id, "limit": 2})


@pytest.mark.integration
@pytest.mark.parametrize("command", LIBRARY_ITEM_COMMANDS)
async def test_live_library_items_have_truthful_schema_and_execute(
    live_client: LiveClient, command: str
) -> None:
    """Library list schemas have no synthetic kwargs and return JSON data."""
    schema_result = await live_client.call_tool(
        "get_tool_schema", {"tool_name": f"ma_api:{command}"}
    )
    assert not schema_result.is_error, schema_result.content
    schema = schema_result.data
    assert "kwargs" not in schema["inputSchema"].get("properties", {})
    assert "kwargs" not in schema["inputSchema"].get("required", [])
    output = schema.get("outputSchema", {})
    assert not (output.get("type") == "string" and "list[" in output.get("x-python-type", ""))
    await call_ma(live_client, command, {"limit": 2})


@pytest.mark.integration
async def test_live_reversible_queue_cycle(live_client: LiveClient) -> None:
    """Only an explicitly selected non-current queue item is added and removed."""
    player_id = require_env("MA_TEST_PLAYER_ID")
    queue = await call_ma(live_client, "player_queues/get_active_queue", {"player_id": player_id})
    queue_id = str(queue["queue_id"])
    before = await queue_items(live_client, queue_id)
    if not before or queue.get("current_index") is None:
        pytest.skip("queue test requires a dedicated player with an active non-empty queue")
    before_ids = {item_id(item) for item in before}
    track_uri = await find_test_track_uri(live_client, purpose="queue mutation")
    if any(str(item.get("uri", "")) == track_uri for item in before):
        pytest.skip("dedicated queue already contains the selected test track URI")
    added_id: str | None = None
    add_attempted = False
    cleaned_up = False
    try:
        # The transport might fail after MA accepted this request, so recovery starts
        # before the request is made and never relies on its response arriving.
        add_attempted = True
        await call_ma(
            live_client,
            "player_queues/play_media",
            {
                "queue_id": queue_id,
                "media": track_uri,
                "option": "add",
            },
        )
        added = await wait_for_own_added_item(live_client, queue_id, before_ids, track_uri)
        added_id = item_id(added)
        assert added.get("played", False) is False
        refreshed = await call_ma(live_client, "player_queues/get", {"queue_id": queue_id})
        current_index = refreshed.get("current_index")
        buffer_index = refreshed.get("index_in_buffer")
        protected = max(
            int(current_index) if current_index is not None else -1,
            int(buffer_index) if buffer_index is not None else -1,
        )
        assert int(added["index"]) > protected
        await call_ma(
            live_client,
            "player_queues/move_item_end",
            {"queue_id": queue_id, "queue_item_id": added_id},
        )
        await remove_added_item(live_client, queue_id, added_id)
        added_id = None
        cleaned_up = True
    finally:
        if add_attempted and not cleaned_up:
            if added_id is None:
                # Recover the exact test-owned row if the first visibility poll
                # timed out or its response was interrupted. Ambiguous concurrent
                # rows are rejected by wait_for_own_added_item rather than removed.
                added = await wait_for_own_added_item(live_client, queue_id, before_ids, track_uri)
                added_id = item_id(added)
            await remove_added_item(live_client, queue_id, added_id)
    assert [item_id(item) for item in await queue_items(live_client, queue_id)] == [
        item_id(item) for item in before
    ]


@pytest.mark.integration
async def test_live_annotations_and_declined_queue_confirmation(
    live_client: LiveClient,
) -> None:
    """Destructive queue schemas and read-only health annotations remain truthful."""
    for command in (
        "player_queues/delete_item",
        "player_queues/clear",
        "fastmcp/queue/remove_items_safe",
    ):
        result = await live_client.call_tool("get_tool_schema", {"tool_name": f"ma_api:{command}"})
        assert result.data["annotations"]["destructiveHint"] is True
        assert result.data["risk"] == "write"
    health = await live_client.call_tool(
        "get_tool_schema", {"tool_name": "ma_api:fastmcp/debug/health"}
    )
    assert health.data["annotations"]["readOnlyHint"] is True
    assert health.data["risk"] == "system"
    declines = 0

    async def decline_elicitation(
        message: str, response_type: Any, params: Any, context: Any
    ) -> ElicitResult[Any]:
        nonlocal declines
        del message, response_type, params, context
        declines += 1
        return ElicitResult(action="decline")

    url, token = _live_settings()
    transport = StreamableHttpTransport(url, auth=token)
    async with Client(transport, elicitation_handler=decline_elicitation) as client:
        with pytest.raises(ToolError, match="Operation cancelled by user"):
            await client.call_tool(
                "call_tool",
                {
                    "name": "ma_api:fastmcp/queue/remove_items_safe",
                    "arguments": {"queue_id": "stale", "item_ids": ["stale"]},
                },
            )
    assert declines == 1
