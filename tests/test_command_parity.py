"""Parity contracts for retired curated tools and their MA command successors."""

from __future__ import annotations

from pathlib import Path

import pytest

from music_assistant import MusicAssistant
from music_assistant.controllers.config import ConfigController
from music_assistant.controllers.discovery import DiscoveryController
from provider.command_policy import resolve_command_policy
from provider.command_profiles import (
    COMMAND_PROFILES,
    CURATED_PROFILE_MAPPINGS,
    LEGACY_COMMAND_MAPPINGS,
    LegacyMigration,
)

_PROFILE_BASELINE = {
    "library_get_track_by_uri": "music/item_by_uri",
    "library_get_album_by_uri": "music/item_by_uri",
    "library_get_artist_by_uri": "music/item_by_uri",
    "library_get_artist_albums": "music/artists/artist_albums",
    "library_get_playlist_by_uri": "music/item_by_uri",
    "library_get_radio_by_uri": "music/item_by_uri",
    "library_get_album_tracks": "music/albums/album_tracks",
    "library_search_tracks": "music/search",
    "library_search_albums": "music/search",
    "library_search_artists": "music/search",
    "library_list_library_tracks": "music/tracks/library_items",
    "library_list_library_albums": "music/albums/library_items",
    "library_list_library_artists": "music/artists/library_items",
    "library_list_library_playlists": "music/playlists/library_items",
    "library_list_library_radio": "music/radios/library_items",
    "library_recently_added_tracks": "music/recently_added_tracks",
    "media_add_to_favorites": "music/favorites/add_item",
    "media_remove_from_favorites": "music/favorites/remove_item",
    "media_add_to_library": "music/library/add_item",
    "media_remove_from_library": "music/library/remove_item",
    "media_mark_played": "music/mark_played",
    "media_play_announcement": "players/cmd/play_announcement",
    "metadata_recommendations": "music/recommendations",
    "metadata_recommendation_items": "music/recommendations/items",
    "metadata_recently_played": "music/recently_played_items",
    "metadata_get_lyrics": "metadata/get_track_lyrics",
    "playback_pause": "players/cmd/pause",
    "playback_resume": "players/cmd/resume",
    "playback_play_pause": "players/cmd/play_pause",
    "playback_stop": "players/cmd/stop",
    "playback_next_track": "players/cmd/next",
    "playback_previous_track": "players/cmd/previous",
    "playback_skip": "player_queues/skip",
    "playback_seek": "players/cmd/seek",
    "playback_play_media": "player_queues/play_media",
    "playback_play_index": "player_queues/play_index",
    "players_set_power": "players/cmd/power",
    "players_group_player": "players/cmd/group",
    "players_ungroup_player": "players/cmd/ungroup",
    "playlists_create_playlist": "music/playlists/create_playlist",
    "playlists_add_track": "music/playlists/add_playlist_tracks",
    "playlists_remove_tracks": "music/playlists/remove_playlist_tracks",
    "queue_set_shuffle": "player_queues/shuffle",
    "queue_set_repeat": "player_queues/repeat",
    "volume_volume_set": "players/cmd/volume_set",
    "volume_volume_up": "players/cmd/volume_up",
    "volume_volume_down": "players/cmd/volume_down",
    "volume_volume_mute": "players/cmd/volume_mute",
    "volume_group_volume_set": "players/cmd/group_volume",
}
_RECIPE_SOURCE_BASELINE = {
    "players_list_players": "players/all",
    "players_get_player": "players/get",
    "queue_get_active_queue": "player_queues/get_active_queue",
    "queue_add_to_queue": "player_queues/play_media",
    "queue_remove_item": "fastmcp/queue/remove_items_safe",
    "queue_clear_queue": "player_queues/clear",
    "queue_move_item": "player_queues/move_item",
    "queue_move_item_to_end": "player_queues/move_item_end",
    "queue_transfer_queue": "player_queues/transfer",
    "playlists_add_tracks": "music/playlists/add_playlist_tracks",
    "config_get_provider": "config/providers/get",
    "config_get_core": "config/core/get",
    "config_get_player": "config/players/get",
    "config_get_dsp": "config/players/dsp/get",
    "config_set_provider_value": "config/providers/save",
    "config_save_provider": "config/providers/save",
    "config_trigger_provider_action": "config/providers/invoke_action",
    "config_set_core_value": "config/core/save",
    "config_save_core": "config/core/save",
    "config_set_player_value": "config/players/save",
    "config_save_player": "config/players/save",
    "config_save_dsp": "config/players/dsp/save",
    "debug_reload_provider": "config/providers/reload",
    "debug_inspect_player": "players/get",
    "debug_inspect_queue": "player_queues/get",
    "debug_inspect_provider": "providers",
    "debug_list_providers": "providers",
    "debug_inspect_provider_config": "config/providers/get",
    "debug_tail_log": "fastmcp/debug/tail_log",
    "debug_log_stats": "fastmcp/debug/log_stats",
    "debug_recent_events": "fastmcp/debug/recent_events",
    "debug_event_buffer_stats": "fastmcp/debug/event_buffer_stats",
    "debug_health_summary": "fastmcp/debug/health",
    "debug_list_webserver_routes": "fastmcp/debug/routes",
    "debug_list_package_versions": "fastmcp/debug/packages",
}
_RETIRED_BASELINE = {"config_list_targets", "config_get_entries"}
_RECIPE_NAME_BASELINE = {
    "mcp_api:players/summary": ("players/all", None),
    "mcp_api:queue/snapshot": ("player_queues/get_active_queue", None),
    "mcp_api:queue/add": ("player_queues/play_media", None),
    "mcp_api:queue/remove": (None, "Use fastmcp/queue/remove_items_safe or player_queues/clear"),
    "mcp_api:queue/move": (None, "Use player_queues/move_item, move_item_end, or transfer"),
    "mcp_api:playlist/add_many": ("music/playlists/add_playlist_tracks", None),
    "mcp_api:config/targets": (None, "Use search_tools('config targets')"),
    "mcp_api:config/entries": (None, "Use the target-specific config/*/get_entries command"),
    "mcp_api:config/save": (None, "Use the target-specific config/*/save command"),
    "mcp_api:config/save_dsp": ("config/players/dsp/save", None),
    "mcp_api:debug/inspect": (
        None,
        "Use native players, queues, providers, config, or diagnostics commands",
    ),
    "mcp_api:debug/logs": (None, "Use fastmcp/debug/tail_log or fastmcp/debug/log_stats"),
    "mcp_api:debug/events": (
        None,
        "Use fastmcp/debug/recent_events or fastmcp/debug/event_buffer_stats",
    ),
    "mcp_api:debug/health": ("fastmcp/debug/health", None),
    "mcp_api:debug/routes": ("fastmcp/debug/routes", None),
    "mcp_api:debug/packages": ("fastmcp/debug/packages", None),
}


@pytest.mark.parametrize(("legacy", "target"), sorted(LEGACY_COMMAND_MAPPINGS.items()))
def test_legacy_mapping_targets_registry_or_explicit_retirement(
    legacy: str, target: LegacyMigration
) -> None:
    """Every old public name has a concrete non-executable migration path."""
    assert legacy
    assert not legacy.startswith("ma_api:")
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
                "metadata/",
            )
        )
    else:
        assert target.message


def test_frozen_baseline_maps_every_former_source_exactly_once() -> None:
    """The b297b17 profile and recipe source matrix has no migration gaps."""
    expected = _PROFILE_BASELINE | _RECIPE_SOURCE_BASELINE
    assert CURATED_PROFILE_MAPPINGS == _PROFILE_BASELINE
    assert set(LEGACY_COMMAND_MAPPINGS) == (
        set(expected) | _RETIRED_BASELINE | set(_RECIPE_NAME_BASELINE) | {"playback_play"}
    )
    assert {legacy: LEGACY_COMMAND_MAPPINGS[legacy].command for legacy in expected} == expected
    assert {
        name: (LEGACY_COMMAND_MAPPINGS[name].command, LEGACY_COMMAND_MAPPINGS[name].message)
        for name in _RECIPE_NAME_BASELINE
    } == _RECIPE_NAME_BASELINE
    assert all(
        migration.command is None or not migration.command.startswith("mcp_api:")
        for migration in LEGACY_COMMAND_MAPPINGS.values()
    )


async def test_current_ma_registry_is_capability_classified_or_explicitly_denied(
    tmp_path: Path,
) -> None:
    """Every authenticated handler in MA's real core registry has a v2 classification."""
    mass = MusicAssistant(str(tmp_path), str(tmp_path))
    mass.config = ConfigController(mass)
    mass.config.initialized = True
    mass.discovery = DiscoveryController(mass)
    await mass._load_core_controllers()
    mass._register_api_commands()

    unclassified: list[str] = []
    unexpectedly_denied: list[str] = []
    for command, handler in mass.command_handlers.items():
        if not handler.authenticated:
            continue
        decision = resolve_command_policy(
            command,
            handler.required_scope,
            COMMAND_PROFILES.get(command),
        )
        if not (
            decision.hard_denied
            or decision.required_capabilities
            or decision.alternative_capabilities
        ):
            unclassified.append(command)
        if decision.hard_denied and not (
            command.startswith("auth/") or command in {"dashboard/register", "dashboard/unregister"}
        ):
            unexpectedly_denied.append(command)

    assert unclassified == []
    assert unexpectedly_denied == []
