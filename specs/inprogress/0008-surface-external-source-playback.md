---
id: "0008"
title: "Surface external/Connect-source playback in player & queue briefs"
size: M          # S | M | L
status: inprogress     # todo | inprogress | done
priority: P1     # P0 | P1 | P2
effort_minutes: 15
feature_id:
---

## Problem Statement

When a player streams from an external "Connect"-style source — e.g. Yandex
Music Connect (Ynison), Spotify Connect, AirPlay — Music Assistant streams the
audio out-of-band, so the player's own playback state stays `idle` even while
audio is clearly playing. As a result the MCP briefs mislead clients:

- `players_list_players` / `players_get_player` report `state: "idle"` for a
  player that is actually playing.
- `current_item` shows the wrapper name of the source (e.g. `"Yandex Music
  Connect (Ynison)"`) instead of the real track (`"Behind Your Walls"`).
- There is no way to tell **which provider** is driving that playback.

An LLM client reading `state` therefore concludes the player is free and may
make wrong routing decisions; and it can never name the now-playing track.

## Solution Summary

Treat the **active queue** as the source of truth for playback state, exactly
as Music Assistant's own UI does. When a player has an active queue, the
brief's `state` reflects `PlayerQueue.state` (`playing` / `paused`) instead of
the player's lagging `playback_state`. The existing blocking-state ladder keeps
priority. Separately, when the active queue's current item is a plugin audio
source (`media_type == AUDIO_SOURCE`), the brief adds a new `external_source`
field holding the controlling provider's `instance_id`, and replaces the
wrapper name with the real track title taken from the source's
`stream_metadata`. The same title substitution is applied to queue items in
`queue_get_active_queue`.

## Acceptance Criteria

1. For a player whose active queue is `playing` an external `AUDIO_SOURCE`
   item, `players_get_player` returns `state == "playing"` (not `"idle"`).
2. The same player's `PlayerBrief.external_source` equals the controlling
   provider instance id (e.g. `yandex_ynison--PL8BnL7a`); for normal,
   self-driven playback `external_source` is `None`.
3. The same player's `current_item` equals the real track title from
   `stream_metadata` (e.g. `"Behind Your Walls"`), not the source wrapper name.
4. `queue_get_active_queue` returns the current item's `name` as the real
   track title for an external `AUDIO_SOURCE` item, leaving non-source items
   unchanged.
5. The blocking-state ladder still wins: an `unavailable` / `disabled` /
   `needs_setup` / `synced` player keeps that `state` regardless of any active
   queue.
6. A player with no active queue, or a normal self-driven track, is unchanged
   from current behaviour (`state` from `player.playback_state`,
   `external_source` is `None`, `current_item` from `current_media`).
7. `to_brief_player` remains callable without an `active_queue` argument
   (defaults to `None`) — existing callers and tests keep working.

## Test Plan

- `test_to_brief_player_external_source`: build a Player stub (idle
  `playback_state`) plus a PlayerQueue stub whose `state` is `playing` and
  whose `current_item.streamdetails` is an `AUDIO_SOURCE` with
  `provider == "yandex_ynison--PL8BnL7a"` and `stream_metadata.title ==
  "Behind Your Walls"`. Assert `state == "playing"`, `external_source ==
  "yandex_ynison--PL8BnL7a"`, `current_item == "Behind Your Walls"`.
- `test_to_brief_player_normal_playback_unchanged`: active queue with a normal
  `track` current item ⇒ `external_source is None`, `state`/`current_item`
  unchanged.
- `test_to_brief_player_blocking_ladder_wins`: unavailable / synced player with
  an active playing queue ⇒ `state` stays `unavailable` / `synced`.
- `test_to_brief_player_no_active_queue`: `active_queue=None` ⇒ legacy
  behaviour (regression guard for AC 7).
- `test_to_brief_queue_external_item_name`: queue items include an
  `AUDIO_SOURCE` item ⇒ its `QueueItemBrief.name` is the `stream_metadata`
  title; a sibling normal item keeps its own name.
- Integration (in-memory FastMCP `Client`): `players_get_player` and
  `queue_get_active_queue` over a fixture queue assert the end-to-end shape.
- Fixture `tests/fixtures/queue_external_audio_source.json` derived from the
  captured Ynison `debug_inspect_queue` payload.

## Sequence Diagram

```mermaid
sequenceDiagram
    participant LLM as MCP Client
    participant P as players.list/get
    participant Q as mass.players.get_active_queue
    participant B as to_brief_player
    LLM->>P: players_get_player(player_id)
    P->>Q: get_active_queue(player)
    Q-->>P: PlayerQueue (state=playing, current_item=AUDIO_SOURCE)
    P->>B: to_brief_player(player, active_queue)
    Note over B: ladder: unavailable/disabled/needs_setup/synced win;<br/>else state = active_queue.state
    Note over B: if current_item.streamdetails.media_type == AUDIO_SOURCE:<br/>external_source = streamdetails.provider;<br/>current_item = stream_metadata.title
    B-->>P: PlayerBrief(state=playing, external_source=…, current_item=title)
    P-->>LLM: PlayerBrief
```
