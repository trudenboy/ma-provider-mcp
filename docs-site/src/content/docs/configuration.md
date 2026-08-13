---
title: Configuration
---

# Configuration

The public endpoint remains `/mcp/v1`. By default the model sees `search_tools`,
`get_tool_schema`, and `call_tool`.

The default **Safe queries** policy exposes library, queue, player, and metadata
queries. It intentionally excludes configuration, diagnostics, control, edit,
delete, and system capabilities even when an individual operation is read-only.

## Connect Wizard

The Connect Wizard represents each target application once. If an application
supports multiple setup paths, its simplest method is selected first and marked
as recommended; alternate CLI, configuration-file, or guided UI methods remain
inside the same card. All methods for that application reuse one revocable
`MCP — <Client>` token, so switching methods does not create another credential.
The Custom card exposes the server name, selected URL, Streamable HTTP transport,
and complete Bearer header for clients that are not listed explicitly.
Roo Code is available with both global and `.roo/mcp.json` project methods.
Products that only accept OAuth for remote connectors, including Claude Desktop
Chat/Cowork and ChatGPT custom connectors, are intentionally not offered by this
static-token wizard.

## Optional MCP App

Turn on **Enable MCP App** to register `app_music_assistant`, two renderer-only backend
tools, and the bundled Prefab UI 0.20.2 renderer. The setting is off by default and a
change triggers a controlled runtime restart. Ordinary MCP clients receive a text
fallback when they invoke the App entry point.

The App shares the normal command execution path. `Deny` hides a control, `Allow`
executes it, and `Confirm` elicits on every invocation. Clicking a button is not policy
confirmation.

## Discovery

Use `include_top_schema: true` only with a non-empty `search_tools` query and without a
cursor. Only the first result receives a `schema` field. Search normalizes Unicode and
uses canonical/curated aliases; it does not translate text or use external search.

## Clients without elicitation

Such clients cannot execute `Confirm` operations. Keep the capability denied or set
only the reviewed capability for that exact token to `Allow`.
