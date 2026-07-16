---
id: "0021"
title: "Agent ergonomics: queue_id alias for queue lookup + hardened find_and_play prompt"
size: S
status: done
priority: P1
effort_minutes: 10
feature_id:
---

## Problem Statement

LLM agents frequently pass the wrong identifier to `queue_get_active_queue`:
the tool requires `player_id`, but agents that just read a `QueueBrief` hold a
`queue_id` and pass that under the wrong parameter name — the call fails even
though both values coincide for a normal player-backed queue. Separately, the
`find_and_play` prompt gives no guidance for the "nothing found" case, so
agents spiral into repeated retries or unrelated tool calls, and it never
tells the agent how to resolve a human player name ("kitchen speaker") into a
`player_id` before playing.

Ported from upstream PR music-assistant/server#4390-wave PR **#4392**
(steamEngineer), which could not merge upstream due to recurring conflicts
with this repo's forward-sync.

## Solution Summary

`queue_get_active_queue` accepts `queue_id` as a convenience alias for
`player_id` (either may be supplied; a clear `ToolError` is raised when both
are empty). The `find_and_play` prompt is hardened: agents are told to stop
gracefully and report "not found" when every search returns no results, and
to resolve the target player via `players_list_players` before calling
`playback_play_media`.

## Acceptance Criteria

1. `queue_get_active_queue(queue_id="X")` returns the same result as
   `queue_get_active_queue(player_id="X")` for a player-backed queue.
2. `queue_get_active_queue()` with neither identifier raises a `ToolError`
   whose message names both `player_id` and `queue_id`.
3. Passing `player_id` keeps working unchanged (no schema break: the
   parameter keeps its name and position).
4. The `find_and_play` prompt instructs the agent to stop and report
   "not found" when all searches return no results, without retrying the
   same searches or calling unrelated tools.
5. The `find_and_play` prompt instructs the agent to resolve the target
   player via `players_list_players` and to use the resolved `player_id`
   as the `queue_id` for playback.
6. Existing prompt guidance (positional inserts via
   `next_insertable_index`) is preserved.

## Test Plan

- `test_queue_get_active_queue_by_player_or_queue_id` (parametrized over
  `player_id` / `queue_id`) — pins the alias on the AUDIO_SOURCE fixture and
  asserts `player_queues.get_active_queue` / `items` receive the resolved id.
- `test_queue_get_active_queue_requires_an_identifier` — pins the
  missing-identifier `ToolError`.
- `test_find_and_play_references_expected_tools` — extended to require
  `players_list_players` in the prompt text.
- Manual: none required (in-memory FastMCP client covers the wire contract).
