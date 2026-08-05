"""Declarative compatibility profiles for the dynamic MA command surface."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

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


@dataclass(frozen=True, slots=True)
class LegacyMigration:
    """One non-executable legacy-name replacement or concrete usage hint."""

    command: str | None = None
    message: str | None = None


def migration(command: str) -> LegacyMigration:
    """Create a migration to a live MA command."""
    return LegacyMigration(command=command)


def retired(message: str) -> LegacyMigration:
    """Create a migration hint for a former aggregate operation."""
    return LegacyMigration(message=message)


LEGACY_COMMAND_MAPPINGS: dict[str, LegacyMigration] = {
    **{legacy: migration(command) for legacy, command in CURATED_PROFILE_MAPPINGS.items()},
    "players_list_players": migration("players/all"),
    "players_get_player": migration("players/get"),
    "queue_get_active_queue": migration("player_queues/get_active_queue"),
    "queue_add_to_queue": migration("player_queues/play_media"),
    "queue_remove_item": migration("fastmcp/queue/remove_items_safe"),
    "queue_clear_queue": migration("player_queues/clear"),
    "queue_move_item": migration("player_queues/move_item"),
    "queue_move_item_to_end": migration("player_queues/move_item_end"),
    "queue_transfer_queue": migration("player_queues/transfer"),
    "playlists_add_tracks": migration("music/playlists/add_playlist_tracks"),
    "debug_reload_provider": migration("config/providers/reload"),
    "debug_inspect_player": migration("players/get"),
    "debug_inspect_queue": migration("player_queues/get"),
    "debug_inspect_provider": migration("providers"),
    "debug_list_providers": migration("providers"),
    "debug_inspect_provider_config": migration("config/providers/get"),
    "debug_tail_log": migration("fastmcp/debug/tail_log"),
    "debug_log_stats": migration("fastmcp/debug/log_stats"),
    "debug_recent_events": migration("fastmcp/debug/recent_events"),
    "debug_event_buffer_stats": migration("fastmcp/debug/event_buffer_stats"),
    "debug_health_summary": migration("fastmcp/debug/health"),
    "debug_list_webserver_routes": migration("fastmcp/debug/routes"),
    "debug_list_package_versions": migration("fastmcp/debug/packages"),
    "config_get_provider": migration("config/providers/get"),
    "config_get_core": migration("config/core/get"),
    "config_get_player": migration("config/players/get"),
    "config_get_dsp": migration("config/players/dsp/get"),
    "config_set_provider_value": migration("config/providers/save"),
    "config_save_provider": migration("config/providers/save"),
    "config_trigger_provider_action": migration("config/providers/invoke_action"),
    "config_set_core_value": migration("config/core/save"),
    "config_save_core": migration("config/core/save"),
    "config_set_player_value": migration("config/players/save"),
    "config_save_player": migration("config/players/save"),
    "config_save_dsp": migration("config/players/dsp/save"),
    "config_list_targets": retired("Use search_tools('config providers core players')"),
    "config_get_entries": retired("Use the target-specific config/*/get_entries command"),
    "playback_play": migration("players/cmd/play"),
    "mcp_api:players/summary": migration("players/all"),
    "mcp_api:queue/snapshot": migration("player_queues/get_active_queue"),
    "mcp_api:queue/add": migration("player_queues/play_media"),
    "mcp_api:queue/remove": retired("Use fastmcp/queue/remove_items_safe or player_queues/clear"),
    "mcp_api:queue/move": retired("Use player_queues/move_item, move_item_end, or transfer"),
    "mcp_api:playlist/add_many": migration("music/playlists/add_playlist_tracks"),
    "mcp_api:config/targets": retired("Use search_tools('config targets')"),
    "mcp_api:config/entries": retired("Use the target-specific config/*/get_entries command"),
    "mcp_api:config/save": retired("Use the target-specific config/*/save command"),
    "mcp_api:config/save_dsp": migration("config/players/dsp/save"),
    "mcp_api:debug/inspect": retired(
        "Use native players, queues, providers, config, or diagnostics commands"
    ),
    "mcp_api:debug/logs": retired("Use fastmcp/debug/tail_log or fastmcp/debug/log_stats"),
    "mcp_api:debug/events": retired(
        "Use fastmcp/debug/recent_events or fastmcp/debug/event_buffer_stats"
    ),
    "mcp_api:debug/health": migration("fastmcp/debug/health"),
    "mcp_api:debug/routes": migration("fastmcp/debug/routes"),
    "mcp_api:debug/packages": migration("fastmcp/debug/packages"),
}


@dataclass(frozen=True, slots=True)
class CommandProfile:
    """
    Provider-owned ergonomics layered over one live MA command handler.

    Profiles never replace MA's signature or authorization. They only add
    backwards-friendly argument spellings, compact response projection and
    conservative metadata that cannot be inferred reliably from annotations.
    """

    command: str
    search_aliases: tuple[str, ...] = ()
    argument_aliases: Mapping[str, str] = field(default_factory=dict)
    list_arguments: frozenset[str] = frozenset()
    compact_fields: tuple[str, ...] = ()
    operation_override: str | None = None
    annotations: Mapping[str, bool] = field(default_factory=dict)
    allow_extra_kwargs: bool = False

    def convert_arguments(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Translate ergonomic aliases without overriding canonical values."""
        converted = dict(arguments)
        for alias, canonical in self.argument_aliases.items():
            if alias not in converted:
                continue
            if canonical in converted:
                raise ValueError(f"Use either {alias!r} or {canonical!r}, not both")
            converted[canonical] = converted.pop(alias)
        for name in self.list_arguments:
            value = converted.get(name)
            if value is not None and not isinstance(value, list | tuple | set):
                converted[name] = [value]
        return converted

    def project_compact(self, value: Any) -> Any:
        """Apply a shallow, command-specific compact projection when declared."""
        if not self.compact_fields:
            return value
        selected = set(self.compact_fields)

        def project(item: Any) -> Any:
            if not isinstance(item, dict):
                return item
            return {key: child for key, child in item.items() if key in selected}

        if isinstance(value, list):
            return [project(item) for item in value]
        if isinstance(value, dict):
            if {"uri", "name", "item_id"}.intersection(value):
                return project(value)
            # SearchResults and similar envelopes contain typed result lists.
            return {
                key: [project(item) for item in child]
                if isinstance(child, list)
                else project(child)
                for key, child in value.items()
            }
        return value


_READ_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
_CONTROL_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": False,
}
_WRITE_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": False,
    "openWorldHint": False,
}
_MEDIA_FIELDS = (
    "uri",
    "name",
    "media_type",
    "artists",
    "artist",
    "album",
    "duration",
    "provider",
    "item_id",
    "available",
)


def _profile_annotations(command: str) -> Mapping[str, bool]:
    """Derive safe MCP hints for the migrated command families."""
    if any(part in command for part in ("remove", "delete", "clear")):
        return _WRITE_ANNOTATIONS
    if command.startswith(("players/cmd/", "player_queues/")):
        return _CONTROL_ANNOTATIONS
    if any(part in command for part in ("/add_", "/create_", "/mark_")):
        return _WRITE_ANNOTATIONS
    return _READ_ANNOTATIONS


def _profile_operation(command: str) -> str:
    """Keep known curated commands stable if upstream scope metadata drifts."""
    if any(part in command for part in ("remove", "delete", "clear")):
        return "write"
    if command.startswith(("players/cmd/", "player_queues/")):
        return "control"
    if any(part in command for part in ("/add_", "/create_", "/mark_")):
        return "write"
    return "read"


def _build_profiles() -> dict[str, CommandProfile]:
    aliases = aliases_by_command()
    profiles: dict[str, CommandProfile] = {}
    for command in sorted(set(CURATED_PROFILE_MAPPINGS.values())):
        profiles[command] = CommandProfile(
            command=command,
            search_aliases=aliases.get(command, ()),
            compact_fields=_MEDIA_FIELDS if command.startswith("music/") else (),
            operation_override=_profile_operation(command),
            annotations=_profile_annotations(command),
        )
    profiles["providers"] = CommandProfile(
        command="providers",
        compact_fields=(
            "instance_id",
            "domain",
            "type",
            "name",
            "available",
            "enabled",
            "last_error",
        ),
        operation_override="read",
        annotations=_READ_ANNOTATIONS,
    )

    overrides: dict[str, dict[str, Any]] = {
        "music/search": {
            "argument_aliases": {"query": "search_query"},
            "list_arguments": frozenset({"media_types", "providers"}),
        },
        "player_queues/play_media": {
            "argument_aliases": {"uri": "media", "radio": "radio_mode"},
        },
        "music/playlists/add_playlist_tracks": {
            "argument_aliases": {"track_uri": "uris"},
            "list_arguments": frozenset({"uris"}),
        },
        "music/playlists/remove_playlist_tracks": {
            "argument_aliases": {"positions": "positions_to_remove"},
            "list_arguments": frozenset({"positions_to_remove"}),
        },
        "music/playlists/create_playlist": {
            "argument_aliases": {"provider_instance_id": "provider_instance_or_domain"},
        },
    }
    for command, changes in overrides.items():
        base = profiles[command]
        profiles[command] = CommandProfile(
            command=base.command,
            search_aliases=base.search_aliases,
            compact_fields=base.compact_fields,
            operation_override=base.operation_override,
            annotations=base.annotations,
            **changes,
        )
    return profiles


def aliases_by_command() -> dict[str, tuple[str, ...]]:
    """Invert the profile matrix into runtime command search aliases."""
    aliases: dict[str, list[str]] = {}
    for legacy_name, command in CURATED_PROFILE_MAPPINGS.items():
        aliases.setdefault(command, []).append(legacy_name)
    for legacy_name, target in LEGACY_COMMAND_MAPPINGS.items():
        if target.command is not None:
            aliases.setdefault(target.command, []).append(legacy_name)
    return {command: tuple(sorted(set(names))) for command, names in aliases.items()}


COMMAND_PROFILES: dict[str, CommandProfile] = _build_profiles()
