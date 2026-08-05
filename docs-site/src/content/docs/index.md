---
title: FastMCP Server Provider
description: Documentation for the FastMCP Server provider for Music Assistant
---

<img src="https://raw.githubusercontent.com/trudenboy/ma-provider-mcp/dev/provider/icon.svg" alt="FastMCP Server" style="width: 72px; float: right; margin: 0 0 1rem 1.5rem;" />


> FastMCP server for Music Assistant — control MA from Claude Code, Codex, Cursor, and other AI agents


[![CI](https://github.com/trudenboy/ma-provider-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/trudenboy/ma-provider-mcp/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/trudenboy/ma-provider-mcp?display_name=tag)](https://github.com/trudenboy/ma-provider-mcp/releases/latest)
[![License](https://img.shields.io/github/license/trudenboy/ma-provider-mcp)](https://github.com/trudenboy/ma-provider-mcp/blob/dev/LICENSE)
[![Music Assistant](https://img.shields.io/badge/Music%20Assistant-provider-9070B8?logo=python&logoColor=white)](https://www.music-assistant.io/)
[![Stars](https://img.shields.io/github/stars/trudenboy/ma-provider-mcp?style=flat&logo=github)](https://github.com/trudenboy/ma-provider-mcp/stargazers)


<div class="topic-pills"> <code>music-assistant</code> <code>home-assistant</code> <code>python</code> <code>plugin-provider</code> <code>mcp</code> <code>ai</code> <code>fastmcp</code> <code>mcp-server</code> <code>claude-code</code> <code>codex</code> <code>cursor</code> <code>chatgpt</code> <code>gemini</code> <code>vscode</code> <code>cline</code> <code>zed</code> <code>ai-agents</code> <code>llm-tools</code>
</div>



The FastMCP Server provider exposes Music Assistant's live command registry through
three permanent MCP tools: `search_tools`, `get_tool_schema`, and `call_tool`. It is
mounted at `/mcp/v1` and reuses Music Assistant authentication, TLS, Origin checks,
resources, and prompts.

## Setup

Enable the provider in Music Assistant, then use **Open Connect Wizard** to create a
revocable `MCP — <Client>` token and copy the generated client configuration. Manual
clients connect to `http://<music-assistant-host>:8095/mcp/v1` with that token as an
`Authorization: Bearer …` header.

## Permissions & Confirmations v2

Version 2 uses one default profile plus optional overrides keyed by exact Music
Assistant token ID:

- `Read-only` allows queries and denies everything else.
- `Home control` allows query, control, and edit operations; deletes require confirmation.
- `Interactive admin` allows queries and controls; mutation, debug, configuration,
  and system operations require confirmation.
- `Trusted` allows every capability without prompting.
- `Custom` assigns `Deny`, `Allow`, or `Confirm` to all 26 capabilities.

The secure default is `Read-only`. Stored v1 permission keys are ignored, so review
the default and token overrides after upgrading. Confirmations are per call and never
remembered.

Clients without MCP elicitation cannot execute `Confirm` operations. Keep the
capability denied, use an elicitation-capable client, or deliberately set only the
required capability for that token to `Allow`. Resource reads require `Allow` and do
not provide a confirmation bypass.

See the repository [README](https://github.com/trudenboy/ma-provider-mcp#permissions--confirmations)
for the complete profile and security model.
