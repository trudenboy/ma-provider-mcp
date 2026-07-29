"""Declarative migration matrix for the former curated MCP tool surface."""

from __future__ import annotations

CURATED_PROFILE_MAPPINGS: dict[str, str] = {
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

CURATED_RECIPE_SOURCES: dict[str, tuple[str, ...]] = {
    "mcp_api:players/summary": ("players_list_players", "players_get_player"),
    "mcp_api:queue/snapshot": ("queue_get_active_queue",),
    "mcp_api:queue/add": ("queue_add_to_queue",),
    "mcp_api:queue/remove": ("queue_remove_item", "queue_clear_queue"),
    "mcp_api:queue/move": (
        "queue_move_item",
        "queue_move_item_to_end",
        "queue_transfer_queue",
    ),
    "mcp_api:playlist/add_many": ("playlists_add_tracks",),
    "mcp_api:config/targets": (
        "config_list_targets",
        "config_get_provider",
        "config_get_core",
        "config_get_player",
    ),
    "mcp_api:config/entries": ("config_get_entries", "config_get_dsp"),
    "mcp_api:config/save": (
        "config_set_provider_value",
        "config_save_provider",
        "config_trigger_provider_action",
        "config_set_core_value",
        "config_save_core",
        "config_set_player_value",
        "config_save_player",
    ),
    "mcp_api:config/save_dsp": ("config_save_dsp",),
    "mcp_api:debug/inspect": (
        "debug_reload_provider",
        "debug_inspect_player",
        "debug_inspect_queue",
        "debug_inspect_provider",
        "debug_list_providers",
        "debug_inspect_provider_config",
    ),
    "mcp_api:debug/logs": ("debug_tail_log", "debug_log_stats"),
    "mcp_api:debug/events": ("debug_recent_events", "debug_event_buffer_stats"),
    "mcp_api:debug/health": ("debug_health_summary",),
    "mcp_api:debug/routes": ("debug_list_webserver_routes",),
    "mcp_api:debug/packages": ("debug_list_package_versions",),
}


def aliases_by_command() -> dict[str, tuple[str, ...]]:
    """Invert the profile matrix into runtime command search aliases."""
    aliases: dict[str, list[str]] = {}
    for legacy_name, command in CURATED_PROFILE_MAPPINGS.items():
        aliases.setdefault(command, []).append(legacy_name)
    return {command: tuple(sorted(names)) for command, names in aliases.items()}


def legacy_migrations() -> dict[str, str]:
    """Return concise replacements for every former curated public name."""
    migrations = {
        legacy: f"ma_api:{command}" for legacy, command in CURATED_PROFILE_MAPPINGS.items()
    }
    for recipe, sources in CURATED_RECIPE_SOURCES.items():
        migrations.update(dict.fromkeys(sources, recipe))
    return migrations
