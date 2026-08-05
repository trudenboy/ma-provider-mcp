"""Stable capability names and temporary global-policy visibility helpers."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ProviderConfig


class Tag(StrEnum):
    """The 26 stable Permissions & Confirmations v2 capabilities."""

    QUERY_LIBRARY = "query:library"
    QUERY_QUEUE = "query:queue"
    QUERY_PLAYERS = "query:players"
    QUERY_METADATA = "query:metadata"
    CONTROL_PLAYBACK = "control:playback"
    CONTROL_VOLUME = "control:volume"
    CONTROL_PLAYERS = "control:players"
    CONTROL_MEDIA = "control:media"
    EDIT_LIBRARY = "edit:library"
    EDIT_QUEUE = "edit:queue"
    EDIT_PLAYLISTS = "edit:playlists"
    EDIT_FAVORITES = "edit:favorites"
    DELETE_LIBRARY = "delete:library"
    DELETE_QUEUE = "delete:queue"
    DELETE_PLAYLISTS = "delete:playlists"
    DELETE_FAVORITES = "delete:favorites"
    DEBUG_INSPECT = "debug:inspect"
    DEBUG_LOGS = "debug:logs"
    DEBUG_EVENTS = "debug:events"
    DEBUG_PROVIDERS = "debug:providers"
    CONFIG_READ = "config:read"
    CONFIG_WRITE_PROVIDER = "config:write:provider"
    CONFIG_WRITE_CORE = "config:write:core"
    CONFIG_WRITE_PLAYER = "config:write:player"
    CONFIG_WRITE_SECRET = "config:write:secret"
    SYSTEM_ADMIN = "system:admin"


def enabled_tags(config: ProviderConfig) -> set[Tag]:
    """Return capabilities visible under the current global v2 policy."""
    from .config import build_policy_resolver  # noqa: PLC0415
    from .policy import PolicyMode  # noqa: PLC0415

    snapshot = build_policy_resolver(config).resolve(None)
    return {capability for capability in Tag if snapshot.mode(capability) is not PolicyMode.DENY}
