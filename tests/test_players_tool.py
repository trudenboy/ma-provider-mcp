"""Tests for the ``players`` sub-server tools.

End-to-end through a FastMCP ``Client`` so the parameter signature and
filtering behaviour exposed to MCP clients are pinned, not just the
in-process helpers.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastmcp import Client, FastMCP

from provider.tools import build_players_server


def _player(
    *,
    player_id: str,
    name: str,
    available: bool = True,
    enabled: bool = True,
    state: str = "idle",
) -> SimpleNamespace:
    """Build a minimal player stub that satisfies ``to_brief_player``."""
    return SimpleNamespace(
        player_id=player_id,
        name=name,
        playback_state=SimpleNamespace(value=state),
        volume_level=None,
        powered=True,
        current_media=None,
        available=available,
        enabled=enabled,
    )


@pytest.fixture
def mounted_players(mock_mass: Any) -> FastMCP:
    """A root FastMCP with only the players sub-server mounted."""
    mcp: FastMCP = FastMCP(name="test")
    mcp.mount(build_players_server(mock_mass), namespace="players")
    return mcp


async def test_list_players_hides_unavailable_by_default(
    mock_mass: Any, mounted_players: FastMCP
) -> None:
    """Default ``list_players`` call drops players whose ``available`` is False.

    Matches the spec: a model asked to pick a speaker should not see
    devices MA can no longer reach.
    """
    mock_mass.players.all_players.return_value = [
        _player(player_id="ok", name="Kitchen", available=True),
        _player(player_id="gone", name="Bedroom", available=False),
    ]
    async with Client(mounted_players) as client:
        result = await client.call_tool("players_list_players", {})
    ids = {p.player_id for p in result.data}
    assert ids == {"ok"}, "unavailable players must be filtered out by default"


async def test_list_players_include_unavailable_returns_all(
    mock_mass: Any, mounted_players: FastMCP
) -> None:
    """With ``include_unavailable=True`` every player comes through.

    The unavailable one is still tagged ``state="unavailable"`` so the
    caller can act on it.
    """
    mock_mass.players.all_players.return_value = [
        _player(player_id="ok", name="Kitchen", available=True),
        _player(player_id="gone", name="Bedroom", available=False),
    ]
    async with Client(mounted_players) as client:
        result = await client.call_tool(
            "players_list_players", {"include_unavailable": True}
        )
    by_id = {p.player_id: p for p in result.data}
    assert set(by_id) == {"ok", "gone"}
    assert by_id["gone"].state == "unavailable"
    assert by_id["ok"].state == "idle"


async def test_get_player_returns_unavailable_player(
    mock_mass: Any, mounted_players: FastMCP
) -> None:
    """Direct id lookup ignores availability — the caller already has the id."""
    mock_mass.players.get_player.return_value = _player(
        player_id="gone", name="Bedroom", available=False
    )
    async with Client(mounted_players) as client:
        result = await client.call_tool("players_get_player", {"player_id": "gone"})
    assert result.data.player_id == "gone"
    assert result.data.available is False
    assert result.data.state == "unavailable"
