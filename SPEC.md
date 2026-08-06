# Music Assistant MCP App

## Value Proposition

Control the currently selected Music Assistant player from an MCP client without
leaving the conversation. The app is for Music Assistant users who need a compact,
safe view of players, now-playing state, transport, volume, power, and queue edits.

**Core actions:** select a player and inspect playback state; control transport,
volume, mute, and power; move or remove queue items.

## Why an MCP App

Conversation finds music and expresses intent efficiently, while the embedded view
provides precise state and controls for actions that benefit from direct manipulation.
The model does not have Music Assistant's live player/queue data and cannot execute
MA commands without the provider's authenticated authorization pipeline.

## UI Overview

The first view lists permitted players, selects one, and shows Now Playing plus the
current queue. Controls update through closed, server-defined actions. Destructive or
confirmation-mode actions use MCP elicitation; clicking a UI control is never treated
as policy confirmation. After an action, the app refreshes state and presents a text
fallback to clients without MCP Apps support.

## Product Context

- Existing product/API: Music Assistant and its live command registry.
- Authentication: the existing MA bearer-token, scope, user, filter, impersonation,
  and token-specific capability policy pipeline.
- Entry point: one model-visible `app_music_assistant` tool.
- Private tools: `ma_app_state` and `ma_app_action`, visible only to the app renderer.
- Runtime: FastMCP 3.4.6 and Prefab UI 0.20.2.
- Configuration: `enable_mcp_app`, false by default and restart-required.
- CSP: no external scripts, frames, or network domains.
- Constraint: the app never calls MA directly or accepts arbitrary command names.
