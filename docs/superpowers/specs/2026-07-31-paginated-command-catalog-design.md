# Paginated Music Assistant Command Catalog Design

Date: 2026-07-31

## Status

Approved in conversation on 2026-07-31. This specification extends the discovery
contract in `2026-07-30-native-ma-command-catalog-design.md`; all authorization,
policy, invocation, and provider-extension decisions from that design remain in
force.

## Problem

The unified Music Assistant catalog exposes roughly three hundred commands while
keeping only three permanent MCP tools. The existing `search_tools(query)` contract
returns at most five ranked results and returns an empty list for an empty query.
Consequently, a client can discover a command by intent but cannot enumerate the
complete request-visible catalog.

Returning every command in one response would solve enumeration at the cost of a
large and unpredictable context payload. Adding a fourth `list_commands` tool would
also increase the permanent tool surface and duplicate discovery behavior.

## Goals

- Let clients enumerate every command visible to the current caller.
- Paginate both semantic search results and alphabetical catalog browsing.
- Preserve exactly three entries in MCP `tools/list`.
- Provide a protocol-native, read-only catalog resource for clients that support
  MCP resources.
- Keep the default response small and require `get_tool_schema` for full schemas.
- Apply the same live authorization and visibility filtering to every page.
- Make page traversal deterministic and detect catalog or permission changes.

## Non-goals

- Returning command input or output schemas in search or catalog pages.
- Persisting per-client pagination sessions on the server.
- Making a cursor an authentication or authorization capability.
- Adding a fourth public tool or exposing each command as a FastMCP tool.
- Providing arbitrary sorting, filtering expressions, or bulk invocation.

## Decision

`search_tools` becomes a paginated discovery tool with two modes:

1. A non-empty `query` performs deterministic BM25-ranked search and includes a
   short description with each result.
2. An absent, empty, or whitespace-only `query` browses all visible canonical
   command names in ascending lexical order and omits descriptions to minimize
   tokens.

The same alphabetical browse operation is exposed as the read-only FastMCP
resource template:

```text
catalog://commands{?cursor,limit}
```

The tool and resource call one shared pagination implementation. The resource is a
supplementary protocol surface, not an executable command and not a fourth tool.
FastMCP 3.2 supports URI templates with RFC 6570 query expansions, so this contract
works at the project's declared minimum FastMCP version.

## Tool Contract

The public signature is conceptually:

```python
search_tools(
    query: str | None = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> DiscoveryPage
```

The first request supplies `query` or leaves it empty for catalog mode. A subsequent
request may supply only `cursor`; the cursor carries the original normalized query
and mode. If a client supplies both, the explicit query must normalize to the query
stored in the cursor or the request fails as an invalid cursor request.

`limit` rules:

- search mode defaults to 5;
- catalog mode defaults to 25;
- all explicit values must be integers from 1 through 50;
- a later page may use a different valid limit.

Every successful call returns one object rather than the former top-level array:

```json
{
  "mode": "search",
  "items": [
    {
      "name": "ma_api:music/albums",
      "description": "Return albums matching the request"
    }
  ],
  "total": 17,
  "next_cursor": "opaque-value-or-null",
  "catalog_revision": "stable-visible-revision"
}
```

In catalog mode `mode` is `"catalog"` and each item contains only `name`.
`total` is the number of request-visible results before pagination. An empty result
is a normal page with `items: []`, `total: 0`, and `next_cursor: null`.

Changing the return shape from an array to `DiscoveryPage` is intentional. Returning
an array for old calls and an object for paginated calls would create a union schema,
make client handling ambiguous, and prevent a single reliable pagination contract.
Prompts, documentation, tests, and live MCP expectations are updated together.

Legacy migration queries retain their current behavior but use the page envelope.
They produce at most one canonical or retirement-hint item, `total` of zero or one,
and no next cursor.

## Catalog Resource Contract

`catalog://commands{?cursor,limit}` is advertised through
`resources/listResourceTemplates`. Reading `catalog://commands` returns the first
alphabetical page. Reading the URI with `cursor` resumes traversal. `limit` follows
the catalog-mode tool rules: default 25 and range 1 through 50.

The resource has MIME type `application/json` and returns:

```json
{
  "items": [{"name": "ma_api:config/providers"}],
  "total": 282,
  "next_cursor": "opaque-value-or-null",
  "next_uri": "catalog://commands?cursor=...&limit=25",
  "catalog_revision": "stable-visible-revision"
}
```

`next_uri` is null on the last page. It is included because resource clients often
read concrete URIs rather than invoke a typed function and should not have to
implement URI-template expansion or cursor escaping. The resource never includes
schemas or descriptions; semantic discovery remains the responsibility of
`search_tools`, and exact details remain the responsibility of `get_tool_schema`.

## Ordering and Cursor Model

Pagination is stateless. Before slicing, each request obtains the current
request-visible catalog using the existing adapter and waits for a view whose base
fingerprint matches the compiled snapshot.

Ordering is stable within a revision:

- catalog mode sorts by canonical command name;
- search mode uses the existing `(-BM25 score, canonical name)` ordering.

The opaque base64url cursor encodes only pagination state:

- cursor format version;
- mode;
- normalized query for search mode;
- next offset;
- catalog revision.

The catalog revision is a digest of the base catalog fingerprint, the ordered
discovery fields of entries visible to the current caller (name, description, and
search aliases), and the pagination format version. It therefore changes when
registry contents, catalog metadata relevant to discovery, or the caller's
effective visibility changes.

The cursor is not trusted for authorization. Every page recomputes the visible
catalog before applying its offset. Editing a cursor cannot reveal a hidden entry.
Malformed cursors, mode/query conflicts, impossible offsets, and unsupported cursor
versions fail with a concise `invalid_cursor` error. A revision mismatch fails with
`catalog_changed` and instructs the client to restart without a cursor. Silently
continuing after a revision change is prohibited because it could skip or duplicate
commands.

## Architecture

`MetaDiscoveryService` remains the owner of the immutable BM25 index. It gains a
shared page builder that:

1. obtains a fingerprint-consistent visible view and base snapshot;
2. selects ranked search or alphabetical catalog mode;
3. validates or creates the cursor state;
4. slices the ordered entries;
5. emits a typed page plus optional next cursor.

The FastMCP `search_tools` handler serializes that page directly. A catalog resource
handler registered alongside meta discovery serializes the same catalog page to
JSON text and adds `next_uri`. This placement gives the resource access to the same
adapter and cache without creating a second catalog, index, or dispatcher.

The existing resource registration for `library://`, `player://`, and `queue://`
remains unchanged. The catalog resource has no single domain permission tag because
its entries span all domains; per-entry visibility is enforced by
`visible_catalog()` on every read.

## Token-Budget Behavior

- `tools/list` still advertises exactly three tools.
- A normal semantic search still defaults to five schema-free summaries.
- Alphabetical browsing defaults to 25 names without descriptions.
- No page may exceed 50 items.
- Full schemas remain on-demand through one exact `get_tool_schema` call.
- The resource consumes no model context until a client explicitly reads it.

## Error Behavior

- Invalid `limit`: reject before catalog work and state the accepted range.
- Invalid or conflicting cursor: `invalid_cursor`; do not fall back to page one.
- Stale cursor: `catalog_changed`; do not return a partial page.
- Missing authentication or dynamic catalog availability: preserve the existing
  adapter's fail-closed behavior.
- Empty visible catalog or unmatched search: return a successful empty page.
- Resource errors use the equivalent FastMCP resource error while preserving the
  same stable error code and restart guidance in the message.

## Testing

### Unit tests

- Empty query selects alphabetical catalog mode.
- Search ranking remains deterministic and paginates without duplicates or gaps.
- Defaults, limits 1 and 50, and invalid limits are covered.
- A cursor can resume without repeating the query.
- Repeating a matching query with a cursor succeeds; a conflicting query fails.
- Malformed, unsupported-version, impossible-offset, and stale cursors fail.
- A visibility change invalidates the prior cursor and never leaks hidden names.
- Legacy aliases return a one-item page envelope.
- Concurrent searches continue to build the BM25 index once per base fingerprint.

### In-memory MCP tests

- `tools/list` remains exactly `search_tools`, `get_tool_schema`, and `call_tool`.
- `search_tools` advertises and returns the structured page contract.
- `resources/listResourceTemplates` includes
  `catalog://commands{?cursor,limit}`.
- Reading the first and subsequent catalog resource pages produces valid JSON,
  correct `next_uri` values, and the same ordered names as tool catalog mode.
- Existing resource-tag middleware does not suppress the catalog template, while
  per-command visibility still applies.

### Real Music Assistant development slice

- Run the canonical suite in the venv backed by
  `/Users/renso/Projects/ma-server` dev.
- Traverse every `search_tools` catalog page against the test instance and assert
  that the collected unique count equals `total`.
- Traverse the resource catalog independently and assert exact name parity.
- Resolve representative track, album, provider, player, queue, config, and debug
  entries with `get_tool_schema`.
- Repeat with a restricted caller or permission configuration and verify that
  hidden commands are absent and a cursor from the broader view is rejected.
- Retain the existing Ruff, mypy, pre-commit, full pytest, Docker, and live MCP
  integration gates.

## Acceptance Criteria

1. `tools/list` exposes exactly the existing three meta-tools.
2. `search_tools` supports deterministic cursor pagination for both semantic
   results and complete alphabetical browsing.
3. The catalog resource template is discoverable and all of its pages can be read
   without a custom client-side pagination convention.
4. Tool catalog mode and resource traversal return the same ordered visible names.
5. No page exceeds 50 items and no page contains command schemas.
6. Catalog or permission changes invalidate existing cursors rather than causing
   duplicates, gaps, or visibility leaks.
7. The implementation uses one live MA registry-backed catalog, one visibility
   path, and one pagination implementation.
8. Tests pass against the current real Music Assistant dev checkout and the live
   `ma-test` MCP instance.
