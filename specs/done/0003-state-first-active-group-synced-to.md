---
id: "0003"
title: "Read active_group / synced_to from Player.state so SyncGroupPlayer membership resolves correctly"
size: S
status: done
priority: P0
effort_minutes: 10
feature_id:
---

## Problem Statement

v0.3.32 exposed `active_group` and `synced_to` on `PlayerBrief` and
added `state="synced"` to the state ladder for any player with either
field non-None. Live verification on a SyncGroupPlayer (`Sendspin BT`)
playing through Kitchen + Lenco showed that BOTH followers still
report `state="idle"` and `active_group=null`, even though their
`current_item` matched the group's playback ("Лёгкий Джаз" on all
three).

Root cause: `to_brief_player` reads `getattr(player, "active_group",
None)` and `getattr(player, "synced_to", None)` — these are the RAW
`_attr_*` dataclass fields, which lag and stay None for sync
followers. The canonical view lives on `Player.state` and is
populated by Music Assistant's `__final_active_group` /
`__final_synced_to` cached properties, which walk all GROUP-type
players and resolve membership / protocol-id translation. The same
state-first pattern is already in use for `powered` and
`current_media` in this very function.

## Solution Summary

Apply the existing state-first / raw-fallback pattern (already used
for `powered` / `current_media` in `to_brief_player`) to
`active_group` and `synced_to`. The `needs_setup` field stays on the
raw attribute — it is a static config flag, not a computed lagging
property.

## Acceptance Criteria

1. `to_brief_player` reads `player.state.active_group` and
   `player.state.synced_to` when `Player.state` is present (the real
   MA Player object).
2. When `Player.state` is absent (legacy `SimpleNamespace` stubs), the
   function falls back to `getattr(player, "active_group", None)` and
   `getattr(player, "synced_to", None)` — back-compat with every
   existing test stub is preserved.
3. The state-synthesis ladder fires `state="synced"` based on the
   canonical values, so a sync follower captured by an active
   SyncGroupPlayer surfaces as `state="synced"` with the resolved
   group player id in `active_group`.
4. The `needs_setup` field continues to read from the raw attribute
   — no functional change there.
5. The two stubs in `tests/test_resources.py` that drive
   `test_player_resource_reports_synced_state` keep working without
   adding a `state` sub-object, demonstrating the back-compat branch.

## Test Plan

- Unit (`tests/test_models.py`):
  - `to_brief_player` prefers `player.state.active_group` over the
    raw attr when both are set and disagree.
  - Same for `player.state.synced_to`.
  - When `player.state` is absent, raw attr is read (regression
    guard against the back-compat branch dropping out).
- Tool (`tests/test_players_tool.py`): a stub with `state.active_group`
  set surfaces as `state="synced"` end-to-end through the FastMCP
  Client.
- Manual MCP verification: with Sendspin BT playing, Kitchen and
  Lenco should now report `state="synced"` and `active_group="syncgroup_namklkxy"`.
