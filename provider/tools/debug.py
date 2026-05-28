"""FastMCP sub-server for debug / troubleshooting tools.

Spec: ``specs/inprogress/0005-debug-namespace.md``.

All tools in this module are gated by off-by-default ConfigEntries
(see ``provider/config.py``). With no tag enabled the entire namespace
is invisible to MCP clients via ``TagFilterMiddleware``.
"""
# ruff: noqa: TID252  -- relative imports are the canonical MA-provider pattern.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from ..debug.inspect_serializer import dump
from ..models import (
    PlayerInspect,
    ProviderInspect,
    QueueInspect,
)
from ..tags import Tag
from ._common import TIMEOUT_FAST

if TYPE_CHECKING:
    from music_assistant.mass import MusicAssistant


LOGGER = logging.getLogger("music_assistant.providers.fastmcp_server.debug")

_PAYLOAD_CAP_BYTES = 256 * 1024


def _safe_get(obj: Any, name: str, default: Any = None) -> Any:
    """Like getattr(obj, name, default) but also swallows property exceptions.

    The inspect tools claim to work on broken/unavailable entities — a raising
    @property on the inspected object must not crash the tool. The serializer
    itself is defensive at the dataclass-field level; this helper covers the
    one-shot tool-level accesses (state, manifest, current_item).
    """
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _readonly(title: str) -> ToolAnnotations:
    return ToolAnnotations(
        title=title,
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )


def build_debug_server(mass: MusicAssistant, *, require_confirmation: bool = True) -> FastMCP:  # noqa: ARG001
    """Build the ``debug`` sub-server.

    :param mass: MusicAssistant instance.
    :param require_confirmation: When True (default), ``debug_reload_provider``
        elicits explicit confirmation from the MCP client before reloading.
    """
    sub = FastMCP(name="debug")
    _register_inspect_tools(sub, mass)
    return sub


def _register_inspect_tools(sub: FastMCP, mass: MusicAssistant) -> None:
    @sub.tool(
        tags={Tag.DEBUG_INSPECT},
        annotations=_readonly("Inspect raw player state"),
        timeout=TIMEOUT_FAST,
    )  # type: ignore[untyped-decorator, unused-ignore]
    async def inspect_player(player_id: str) -> PlayerInspect:
        """Return the raw runtime state of a player, including state.* fields the brief omits.

        Works for unavailable and disabled players — that is the point.
        See also: debug_recent_events with id_filter=<player_id> for transitions,
        debug_tail_log for the textual context.

        :param player_id: Identifier of the player to inspect.
        """
        player = mass.players.get_player(player_id)
        if player is None:
            raise ToolError(f"player_id={player_id!r} not found")
        state_obj = _safe_get(player, "state", None)
        raw, raw_trunc = dump(
            player,
            max_total_bytes=_PAYLOAD_CAP_BYTES,
            return_truncated=True,
        )
        if state_obj is not None:
            state, state_trunc = dump(
                state_obj,
                max_total_bytes=_PAYLOAD_CAP_BYTES,
                return_truncated=True,
            )
        else:
            state, state_trunc = {}, False
        # raw includes state; surface it again under .state for convenience.
        if isinstance(raw, dict) and "state" in raw:
            raw.pop("state", None)
        return PlayerInspect(
            player_id=player_id,
            raw=raw,
            state=state,
            truncated=bool(raw_trunc or state_trunc),
        )

    @sub.tool(
        tags={Tag.DEBUG_INSPECT},
        annotations=_readonly("Inspect raw queue state"),
        timeout=TIMEOUT_FAST,
    )  # type: ignore[untyped-decorator, unused-ignore]
    async def inspect_queue(queue_id: str) -> QueueInspect:
        """Return the raw runtime state of a PlayerQueue plus the current_item resolved.

        See also: debug_inspect_player for the queue's owning player,
        debug_recent_events with id_filter=<queue_id> for transitions.

        :param queue_id: Identifier of the queue to inspect.
        """
        queue = mass.player_queues.get(queue_id)
        if queue is None:
            raise ToolError(f"queue_id={queue_id!r} not found")
        raw, raw_trunc = dump(queue, max_total_bytes=_PAYLOAD_CAP_BYTES, return_truncated=True)
        current = _safe_get(queue, "current_item", None)
        current_payload, current_trunc = (
            dump(current, max_total_bytes=_PAYLOAD_CAP_BYTES, return_truncated=True)
            if current is not None
            else (None, False)
        )
        return QueueInspect(
            queue_id=queue_id,
            raw=raw,
            current_item=current_payload,
            truncated=bool(raw_trunc or current_trunc),
        )

    @sub.tool(
        tags={Tag.DEBUG_INSPECT},
        annotations=_readonly("Inspect raw provider state"),
        timeout=TIMEOUT_FAST,
    )  # type: ignore[untyped-decorator, unused-ignore]
    async def inspect_provider(instance_id: str) -> ProviderInspect:
        """Return the raw runtime state of a configured provider plus its manifest.

        See also: debug_inspect_provider_config for masked configuration,
        debug_list_webserver_routes for the routes this provider registered,
        debug_reload_provider to restart it.

        :param instance_id: Identifier of the provider instance to inspect.
        """
        prov = mass.get_provider(instance_id)
        if prov is None:
            raise ToolError(f"provider instance_id={instance_id!r} not configured")
        manifest = _safe_get(prov, "manifest", None)
        raw, raw_trunc = dump(prov, max_total_bytes=_PAYLOAD_CAP_BYTES, return_truncated=True)
        manifest_payload, manifest_trunc = (
            dump(manifest, max_total_bytes=_PAYLOAD_CAP_BYTES, return_truncated=True)
            if manifest is not None
            else ({}, False)
        )
        if isinstance(raw, dict):
            raw.pop("manifest", None)
        return ProviderInspect(
            instance_id=instance_id,
            raw=raw,
            manifest=manifest_payload,
            truncated=bool(raw_trunc or manifest_trunc),
        )
