---
id: "0004"
title: "Expose group_volume, volume_muted, group_volume_muted on PlayerBrief"
size: S
status: done
priority: P1
effort_minutes: 10
feature_id:
---

## Problem Statement

`PlayerBrief` exposes `volume_level` only. Live verification of the
`Sendspin group` SyncGroupPlayer on the test container shows
`volume_level=null` — group players hold their volume on a separate
`group_volume` property, which the brief drops entirely. The mute
state is also invisible: `volume_muted` and `group_volume_muted` are
both on MA's `Player.state`, neither flows through. A caller asking
"is anything actually audible?" can't answer it from the brief.

## Solution Summary

Expose `volume_muted`, `group_volume`, and `group_volume_muted` on
`PlayerBrief`, reading the canonical values from `Player.state` with
a raw-attribute fallback — the same state-first pattern that v0.3.34
applied to `active_group` and `synced_to`.

## Acceptance Criteria

1. `PlayerBrief` gains `volume_muted: bool | None = None`,
   `group_volume: int | None = None`, and `group_volume_muted: bool |
   None = None` — all default-safe so legacy stubs keep working.
2. `to_brief_player` reads each of the three from
   `player.state.<field>` when `state` carries them, and falls back
   to `getattr(player, "<field>", None)` otherwise.
3. The existing test stubs (those whose `state` has only `powered`
   and `current_media`) keep producing identical briefs — back-compat
   for every test that predates this change.
4. Live verification on the test container: the `Sendspin group`
   SyncGroupPlayer's brief carries a numeric `group_volume` once a
   sync session is active and its `group_volume_muted` reflects the
   mute state of the group volume.
5. Individual players (non-group) leave `group_volume` /
   `group_volume_muted` as `None` and surface their own mute via
   `volume_muted`.

## Test Plan

- Unit (`tests/test_models.py`):
  - `to_brief_player` reads `state.volume_muted` /
    `state.group_volume` / `state.group_volume_muted` over the raw
    attributes.
  - Legacy stubs without those fields still produce briefs with the
    new fields defaulting to `None`/`False`-safe values.
- Tool (`tests/test_players_tool.py`): a stub representing a sync
  group exposes `group_volume` round-tripped through the FastMCP
  Client.
- Manual MCP verification: live container's `Sendspin group` brief
  reports `group_volume` instead of bare `volume_level=null`.
