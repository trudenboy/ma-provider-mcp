---
id: "0001"
title: "Expose player availability so callers can ignore offline devices"
size: S
status: done
priority: P1
effort_minutes: 10
feature_id:
---

## Problem Statement

`players_list_players` returns every player Music Assistant knows about,
including ones that are currently offline or have been disabled in MA's
settings. For LLM clients there is no way to tell those apart from
genuinely-playable devices: all of them report `state="idle"` (because
MA never receives push updates from them) and `powered=true` (cached).
A model asked to "play something on a speaker" ends up choosing a
device that the user can no longer reach.

## Solution Summary

Expose MA's `Player.available` and `Player.enabled` on `PlayerBrief`,
synthesize `state="unavailable"` when a player is not available
(regardless of cached `playback_state`), and give `list_players` an
opt-in `include_unavailable` flag so unavailable devices are hidden
from the default response.

## Acceptance Criteria

1. `PlayerBrief` carries two new boolean fields, `available` and
   `enabled`, both defaulting to `True` for back-compat with existing
   test stubs.
2. `to_brief_player` reads `Player.available` / `Player.enabled` from
   the upstream object when present and falls back to `True` when
   absent, so `SimpleNamespace`-based fixtures keep working.
3. When `Player.available` is `False`, the brief's `state` is the
   literal string `"unavailable"`, overriding any cached
   `playback_state` value (typically `"idle"`).
4. `players_list_players` accepts a new
   `include_unavailable: bool = False` parameter. With the default,
   unavailable players are filtered out of the returned list; with
   `True`, every player is returned.
5. `players_get_player` is unchanged: a direct id lookup still returns
   the player regardless of availability (so a caller that already
   holds an id can still introspect a temporarily-offline device).

## Test Plan

- Unit (`tests/test_models.py`):
  - `to_brief_player` exposes `available` / `enabled` from the
    upstream player object.
  - When `available=False`, `brief.state == "unavailable"` even if
    `playback_state.value == "idle"`.
  - Missing `available` / `enabled` attrs default to `True`
    (back-compat with existing stubs).
- Tool (`tests/test_players_tool.py`, new):
  - `list_players` default response excludes a player whose
    `available=False`.
  - `list_players(include_unavailable=True)` returns both available
    and unavailable players.
  - `get_player` returns the brief regardless of `available`.
