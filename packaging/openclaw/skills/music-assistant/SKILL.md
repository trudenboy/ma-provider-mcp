---
name: music-assistant
description: >-
  Use when the user wants to play, pause, queue, search, or browse music, or
  control speakers/players through Music Assistant. Wraps the Music Assistant
  MCP server (the `ma` server declared in this bundle's .mcp.json).
---

# Music Assistant

This skill drives a self-hosted [Music Assistant](https://www.music-assistant.io/)
instance through its MCP server. The tools are exposed by the `ma` server in
this bundle's `.mcp.json` and are namespaced by category.

## When to use

Reach for the `ma` tools when the user asks to:

- Play / pause / skip / seek, or play a specific track, album, artist, or
  playlist (`playback_*`, `media_*`).
- Search or browse the library (`library_*`, `metadata_*`).
- Inspect or change what is queued (`queue_*`, `playlists_*`).
- List players, change volume, power, or group speakers (`players_*`,
  `volume_*`).

## How to use

1. Find the target with a `library_search_*` tool before acting on it — most
   playback tools take a media URI or an item id, not a free-text name.
2. Pick the player with `players_list_players` when the user names a room or
   speaker; pass its id to playback/volume tools.
3. Prefer the smallest tool for the job — e.g. `playback_play_media` to start
   something, `queue_get_active_queue` to report what is playing.

## Notes

- The server enforces per-capability permissions; some tools may be absent if
  the operator disabled that category. Do not assume a tool exists — rely on
  the live tool list.
- Destructive actions (clearing a queue, removing from library) may require
  user confirmation; surface what will change before calling them.
