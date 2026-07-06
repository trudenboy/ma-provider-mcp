---
id: "0016"
title: "Radio-seeded playback via radio playlists in playback_play_media"
size: S
status: inprogress
priority: P1
effort_minutes: 10
feature_id:
---

## Problem Statement

The `playback_play_media` tool exposed a `radio_mode` flag that delegated to
Music Assistant's deprecated queue-level radio mode. Upstream replaced that
mechanism with dynamic radio playlists (`radio_playlist://` URIs seeded from a
media item), and upstream PR music-assistant/server#4501 moved the MCP tool to
the new engine. Without the port, the MCP tool keeps driving the deprecated
path and diverges from upstream behaviour: no artist/genre seeding, no
continuously refilled dynamic playlist.

## Solution Summary

Reverse-sync of upstream PR #4501 (author: @marcelveldt). The tool parameter is
renamed `radio_mode` → `radio`. With `radio=True`, the tool resolves the given
URI to a media item, rejects browse folders with a clear error, and enqueues
the item's dynamic radio playlist (`radio_playlist://playlist/<seed-uri>`)
instead of passing the deprecated queue flag. Failed seed lookups surface as a
clean tool error. The provider always runs inside the matching MA version, so
no compatibility fallback for older MA releases is added (maintainer decision).

## Acceptance Criteria

1. `playback_play_media` accepts a boolean `radio` parameter; `radio_mode` is
   no longer part of the tool schema.
2. With `radio` omitted or `False`, the given URI is enqueued as-is and no
   media-item lookup is performed.
3. With `radio=True` and a resolvable URI, the queue receives
   `radio_playlist://playlist/<seed-uri>` for the resolved seed.
4. With `radio=True` and a URI that resolves to a browse folder, the call
   fails with a tool error mentioning the browse folder, and nothing is
   enqueued.
5. With `radio=True` and a URI that fails to resolve, the call fails with a
   "Could not resolve URI for radio" tool error, and nothing is enqueued.
6. The tool docstring documents the radio behaviour (endless dynamic playlist
   seeded from artist/album/track/playlist/genre).

## Test Plan

- `test_play_media_enqueues_uri_directly` — pins criterion 2 (no lookup, URI
  passed through).
- `test_play_media_radio_enqueues_radio_playlist_uri` — pins criterion 3
  (seed resolved once, `radio_playlist://playlist/<seed-uri>` enqueued).
- `test_play_media_radio_rejects_browse_folder` — pins criterion 4.
- `test_play_media_radio_resolution_failure_raises_tool_error` — pins
  criterion 5.
- Manual: against a live MA dev server, call `playback_play_media` with
  `radio=True` on an artist URI and confirm the queue fills with similar
  tracks and keeps refilling.
