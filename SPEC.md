# Music Assistant MCP Server

## Value Proposition

Let an MCP client discover and invoke Music Assistant's live command registry
without a parallel tool API. Conversation stays on intent; `search_tools`,
`get_tool_schema`, and `call_tool` load one schema at a time and keep payloads
bounded.

**Core actions:** search or browse the command catalog, inspect one schema, and
execute a permitted `ma_api:*` command.

## Product Context

- Existing product/API: Music Assistant and its live command-handler registry.
- Authentication: MA bearer token, scopes, user state, player/provider filters,
  impersonation, and the 26-capability policy pipeline.
- Entry points: `search_tools`, `get_tool_schema`, and `call_tool`.
- Resources: `library://`, `player://`, `queue://`, and `catalog://commands`.
- Runtime: FastMCP 3.4.7 mounted on Music Assistant's webserver at `/mcp/v1`.
- Constraint: the provider never exposes `auth/*` or dashboard registration
  commands, and it never returns unmasked secure configuration.
