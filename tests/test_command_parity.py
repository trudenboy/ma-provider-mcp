"""Parity contracts for retired curated tools and their MA command successors."""

from __future__ import annotations

import pytest

from provider.command_profiles import (
    CURATED_PROFILE_MAPPINGS,
    LEGACY_COMMAND_MAPPINGS,
    LegacyMigration,
)


@pytest.mark.parametrize(("legacy", "target"), sorted(LEGACY_COMMAND_MAPPINGS.items()))
def test_legacy_mapping_targets_registry_or_explicit_retirement(
    legacy: str, target: LegacyMigration
) -> None:
    """Every old public name has a concrete non-executable migration path."""
    assert legacy and not legacy.startswith("ma_api:")
    if target.command is not None:
        assert target.command.startswith(
            (
                "music/",
                "players/",
                "player_queues/",
                "config/",
                "providers",
                "diagnostics/",
                "fastmcp/",
            )
        )
    else:
        assert target.message


def test_retired_sources_are_mapped_once_without_recipe_targets() -> None:
    """Profiles and migrations fully replace the old executable recipe surface."""
    expected = {
        "players_list_players": "players/all",
        "players_get_player": "players/get",
        "queue_get_active_queue": "player_queues/get_active_queue",
        "queue_add_to_queue": "player_queues/play_media",
        "queue_remove_item": "fastmcp/queue/remove_items_safe",
        "queue_clear_queue": "player_queues/clear",
        "debug_tail_log": "fastmcp/debug/tail_log",
        "config_save_dsp": "config/players/dsp/save",
    }
    assert {legacy: LEGACY_COMMAND_MAPPINGS[legacy].command for legacy in expected} == expected
    assert set(CURATED_PROFILE_MAPPINGS).isdisjoint(expected)
    assert all(
        migration.command is None or not migration.command.startswith("mcp_api:")
        for migration in LEGACY_COMMAND_MAPPINGS.values()
    )

