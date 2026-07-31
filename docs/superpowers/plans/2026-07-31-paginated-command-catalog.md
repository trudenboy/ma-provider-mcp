# Paginated Music Assistant Command Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic cursor pagination to `search_tools` and expose the same request-visible alphabetical command catalog through a read-only MCP resource template.

**Architecture:** Keep `MetaDiscoveryService` as the single owner of the live visible catalog and BM25 index. Put stateless cursor encoding, revision hashing, response types, and limit validation in a pure `catalog_pagination` module; register the `catalog://commands{?cursor,limit}` transport adapter in a focused `catalog_resource` module that delegates to the same service.

**Tech Stack:** Python 3.14, Music Assistant current `dev` checkout at `/Users/renso/Projects/ma-server`, FastMCP `>=3.2,<4.0` (development venv currently 3.4.5), MCP resources, stdlib dataclasses/TypedDict/base64/hashlib/json, pytest 9, pytest-asyncio, Ruff, mypy, pre-commit, Docker Compose.

## Global Constraints

- MCP `tools/list` must continue to expose exactly `search_tools`, `get_tool_schema`, and `call_tool`.
- `search_tools` intentionally changes from a top-level array to one stable `DiscoveryPage` object; do not add a legacy union return type.
- Non-empty search defaults to 5 results; empty catalog browse defaults to 25; explicit limits are strict integers from 1 through 50.
- Search pages contain `name` and `description`; catalog pages and the catalog resource contain `name` only; neither contains command schemas.
- `catalog://commands{?cursor,limit}` is an untagged, always-visible infrastructure resource whose contents are filtered entry-by-entry by `DynamicAPIAdapter.visible_catalog()`.
- Every page recomputes live caller visibility. Cursors never bypass authentication, scopes, provider/player filters, risk gates, or configured tags.
- Cursor traversal is stateless and detects changes in registry contents, discovery metadata, or effective visibility.
- Keep `fastmcp>=3.2,<4.0`; do not hand-edit auto-generated `pyproject.toml`, `ruff.toml`, `.pre-commit-config.yaml`, or workflow files.
- Use the existing isolated worktree `/Users/renso/Projects/ma-provider-mcp/.worktrees/native-ma-command-catalog` and preserve unrelated user changes.
- Run MA-dependent verification through the real dev slice at `/Users/renso/Projects/ma-server` and never print MCP tokens or provider credentials.

## File Structure

- Create `provider/catalog_pagination.py`: JSON-safe page types, query normalization, strict limits, catalog revision digest, opaque cursor codec, and stable pagination exceptions. This module has no FastMCP dependency.
- Create `provider/catalog_resource.py`: FastMCP resource-template registration and JSON/`next_uri` transport formatting. This module contains no search, visibility, or ordering logic.
- Modify `provider/meta_discovery.py`: produce paginated search/catalog pages from the existing index and adapter, expose the new tool contract, and register the catalog resource against the same service.
- Modify `provider/server.py`: teach server instructions about paginated browsing and the catalog resource.
- Create `tests/test_catalog_pagination.py`: pure codec, revision, normalization, and limit tests.
- Modify `tests/test_dynamic_catalog.py`: service pagination, tool wire contract, stale/invalid cursor, legacy, concurrency, and token-budget tests.
- Modify `tests/test_meta_discovery.py`: exact three-tool surface and untagged catalog-resource middleware behavior.
- Modify `tests/test_e2e_smoke.py`: full runtime resource-template preservation.
- Modify `tests/integration/test_live_catalog.py`: complete traversal and tool/resource parity against real MA.
- Modify `README.md`, `CLAUDE.local.md`, and `specs/done/0026-dynamic-ma-api-catalog.md`: user workflow, architectural invariant, and historical supersession note.

---

### Task 1: Pure Pagination Contract and Cursor Codec

**Files:**
- Create: `provider/catalog_pagination.py`
- Create: `tests/test_catalog_pagination.py`

**Interfaces:**
- Consumes: `CatalogFingerprint` and `DynamicEntry` from `provider.dynamic_api`.
- Produces: `DiscoveryMode`, `DiscoveryItem`, `DiscoveryPage`, `CursorState`, `PaginationError`, `normalize_query()`, `resolve_limit()`, `catalog_revision()`, `encode_cursor()`, and `decode_cursor()`.
- Constants: `SEARCH_DEFAULT_LIMIT = 5`, `CATALOG_DEFAULT_LIMIT = 25`, `MAX_PAGE_LIMIT = 50`, `CURSOR_VERSION = 1`, and `MAX_CURSOR_LENGTH = 2048`.

- [ ] **Step 1: Write failing normalization and strict-limit tests**

Create `tests/test_catalog_pagination.py` with these tests and imports:

```python
from __future__ import annotations

import base64
from dataclasses import replace

import pytest

from provider.catalog_pagination import (
    CATALOG_DEFAULT_LIMIT,
    MAX_PAGE_LIMIT,
    SEARCH_DEFAULT_LIMIT,
    CursorState,
    PaginationError,
    catalog_revision,
    decode_cursor,
    encode_cursor,
    normalize_query,
    resolve_limit,
)
from provider.command_policy import DynamicRisk
from provider.dynamic_api import DynamicEntry


def _entry(
    name: str,
    *,
    description: str = "Description",
    aliases: tuple[str, ...] = (),
) -> DynamicEntry:
    return DynamicEntry(
        name=name,
        command=name.removeprefix("ma_api:"),
        description=description,
        input_schema={"type": "object", "properties": {}},
        risk=DynamicRisk.READ,
        required_scope=None,
        allow_impersonation=False,
        handler=object(),
        search_aliases=aliases,
    )


def test_normalize_query_is_unicode_and_whitespace_stable() -> None:
    assert normalize_query("  ALBUM\u00a0 Tracks  ") == "album tracks"
    assert normalize_query("ＡＬＢＵＭ") == "album"
    assert normalize_query(None) == ""


def test_resolve_limit_uses_mode_defaults_and_bounds() -> None:
    assert resolve_limit("search", None) == SEARCH_DEFAULT_LIMIT
    assert resolve_limit("catalog", None) == CATALOG_DEFAULT_LIMIT
    assert resolve_limit("catalog", 1) == 1
    assert resolve_limit("search", MAX_PAGE_LIMIT) == MAX_PAGE_LIMIT


@pytest.mark.parametrize("value", [0, 51, -1, True, 1.5, "5"])
def test_resolve_limit_rejects_non_strict_or_out_of_range_values(value: object) -> None:
    with pytest.raises(PaginationError) as exc_info:
        resolve_limit("search", value)  # type: ignore[arg-type]
    assert exc_info.value.code == "invalid_limit"
    assert "1 through 50" in str(exc_info.value)
```

- [ ] **Step 2: Run the focused tests and verify the module is missing**

Run:

```bash
uv run pytest tests/test_catalog_pagination.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'provider.catalog_pagination'`.

- [ ] **Step 3: Add failing cursor and catalog-revision tests**

Append these tests:

```python
def test_cursor_round_trips_without_padding() -> None:
    state = CursorState(
        version=1,
        mode="search",
        query="album tracks",
        offset=5,
        revision="abc123",
    )
    encoded = encode_cursor(state)
    assert "=" not in encoded
    assert decode_cursor(encoded) == state


@pytest.mark.parametrize(
    "cursor",
    ["", "not-json", "e30", "x" * 2049],
)
def test_decode_cursor_rejects_malformed_payloads(cursor: str) -> None:
    with pytest.raises(PaginationError) as exc_info:
        decode_cursor(cursor)
    assert exc_info.value.code == "invalid_cursor"


def test_encode_cursor_rejects_unsupported_version() -> None:
    encoded = encode_cursor(
        CursorState(version=1, mode="catalog", query="", offset=25, revision="rev")
    )
    raw = decode_cursor(encoded)
    with pytest.raises(PaginationError, match="version") as exc_info:
        encode_cursor(replace(raw, version=2))
    assert exc_info.value.code == "invalid_cursor"


def test_decode_cursor_rejects_unsupported_version() -> None:
    raw = b'{"v":2,"m":"catalog","q":"","o":25,"r":"rev"}'
    encoded = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    with pytest.raises(PaginationError, match="version") as exc_info:
        decode_cursor(encoded)
    assert exc_info.value.code == "invalid_cursor"


def test_catalog_revision_changes_for_discovery_or_visibility_changes() -> None:
    fingerprint = (1, "fake", (("music/search", 1),))
    first = _entry("ma_api:music/search", aliases=("find music",))
    same = _entry("ma_api:music/search", aliases=("find music",))
    described = _entry("ma_api:music/search", description="Changed")
    hidden = _entry("ma_api:players/all")
    revision = catalog_revision(fingerprint, (first, hidden))
    assert catalog_revision(fingerprint, (same, hidden)) == revision
    assert catalog_revision(fingerprint, (described, hidden)) != revision
    assert catalog_revision(fingerprint, (first,)) != revision
    assert catalog_revision((2, "fake", ()), (first, hidden)) != revision
```

- [ ] **Step 4: Implement the pure pagination module**

Create `provider/catalog_pagination.py` with the following public types and behavior:

```python
"""Pure response, revision, and cursor primitives for command discovery."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, NotRequired, TypedDict, cast

from .dynamic_api import CatalogFingerprint, DynamicEntry

type DiscoveryMode = Literal["search", "catalog"]

SEARCH_DEFAULT_LIMIT = 5
CATALOG_DEFAULT_LIMIT = 25
MAX_PAGE_LIMIT = 50
CURSOR_VERSION = 1
MAX_CURSOR_LENGTH = 2048


class DiscoveryItem(TypedDict):
    """One schema-free discovery result."""

    name: str
    description: NotRequired[str]


class DiscoveryPage(TypedDict):
    """One stable page returned by the discovery tool."""

    mode: DiscoveryMode
    items: list[DiscoveryItem]
    total: int
    next_cursor: str | None
    catalog_revision: str


@dataclass(frozen=True, slots=True)
class CursorState:
    """Stateless continuation data encoded into an opaque cursor."""

    version: int
    mode: DiscoveryMode
    query: str
    offset: int
    revision: str


class PaginationError(ValueError):
    """Stable pagination failure suitable for tool or resource transport."""

    def __init__(self, code: str, message: str) -> None:
        """Store a stable machine-readable code beside the client-facing message."""

        super().__init__(message)
        self.code = code


def normalize_query(value: str | None) -> str:
    """Normalize query text for mode selection and cursor comparison."""

    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join(normalized.split())


def resolve_limit(mode: DiscoveryMode, limit: int | None) -> int:
    """Return the mode default or validate one strict explicit page size."""

    if limit is None:
        return SEARCH_DEFAULT_LIMIT if mode == "search" else CATALOG_DEFAULT_LIMIT
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_PAGE_LIMIT:
        raise PaginationError("invalid_limit", "limit must be an integer from 1 through 50")
    return limit


def catalog_revision(
    fingerprint: CatalogFingerprint,
    entries: Sequence[DynamicEntry],
) -> str:
    """Digest the registry and caller-visible fields that affect discovery."""

    payload = [
        CURSOR_VERSION,
        fingerprint,
        [[entry.name, entry.description, list(entry.search_aliases)] for entry in entries],
    ]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:24]


def encode_cursor(state: CursorState) -> str:
    """Encode validated continuation state as unpadded base64url JSON."""

    _validate_state(state)
    payload = {
        "v": state.version,
        "m": state.mode,
        "q": state.query,
        "o": state.offset,
        "r": state.revision,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> CursorState:
    """Decode and validate an opaque continuation cursor."""

    if not cursor or len(cursor) > MAX_CURSOR_LENGTH:
        raise PaginationError("invalid_cursor", "cursor is malformed")
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
        if not isinstance(payload, dict) or set(payload) != {"v", "m", "q", "o", "r"}:
            raise ValueError
        mode = payload["m"]
        if mode not in ("search", "catalog"):
            raise ValueError
        state = CursorState(
            version=payload["v"],
            mode=cast("DiscoveryMode", mode),
            query=payload["q"],
            offset=payload["o"],
            revision=payload["r"],
        )
        _validate_state(state)
    except PaginationError:
        raise
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise PaginationError("invalid_cursor", "cursor is malformed") from exc
    return state


def _validate_state(state: CursorState) -> None:
    """Reject state that cannot have been emitted for a next page."""

    valid = (
        type(state.version) is int
        and state.version == CURSOR_VERSION
        and state.mode in ("search", "catalog")
        and isinstance(state.query, str)
        and normalize_query(state.query) == state.query
        and type(state.offset) is int
        and state.offset > 0
        and isinstance(state.revision, str)
        and bool(state.revision)
        and ((state.mode == "search" and bool(state.query)) or (state.mode == "catalog" and not state.query))
    )
    if not valid:
        message = (
            "cursor version is unsupported"
            if type(state.version) is int and state.version != CURSOR_VERSION
            else "cursor is malformed"
        )
        raise PaginationError("invalid_cursor", message)
```

Keep `_validate_state()` private. Do not add signing or server-side cursor storage: authorization is reapplied by the service in Task 2.

- [ ] **Step 5: Run and pass the pure tests and static checks**

Run:

```bash
uv run pytest tests/test_catalog_pagination.py -v
uv run ruff check provider/catalog_pagination.py tests/test_catalog_pagination.py
uv run mypy provider/catalog_pagination.py tests/test_catalog_pagination.py
```

Expected: all tests and checks pass.

- [ ] **Step 6: Commit the pure pagination contract**

```bash
git add provider/catalog_pagination.py tests/test_catalog_pagination.py
git commit -m "feat: add command catalog cursor contract"
```

---

### Task 2: Paginated Discovery Service and `search_tools` Wire Contract

**Files:**
- Modify: `provider/meta_discovery.py`
- Modify: `tests/test_dynamic_catalog.py`

**Interfaces:**
- Consumes: all public Task 1 interfaces.
- Produces: `MetaDiscoveryService.discover(query: str | None = None, *, cursor: str | None = None, limit: int | None = None) -> DiscoveryPage`.
- Produces: FastMCP tool `search_tools(query=None, cursor=None, limit=None) -> DiscoveryPage`.
- Preserves: `_rank()`, `_build_search_index()`, singleflight index caching, exact schema lookup, and `call_tool` behavior.

- [ ] **Step 1: Convert existing search assertions to the page envelope**

Update the wire assertions in `tests/test_dynamic_catalog.py`:

```python
async def test_search_uses_alias_but_returns_canonical_ma_name() -> None:
    mcp, _adapter = _server()
    async with Client(mcp) as client:
        result = await client.call_tool("search_tools", {"query": "playback_play"})
    assert result.data["mode"] == "search"
    assert result.data["items"] == [
        {
            "name": "ma_api:players/cmd/play",
            "description": "Start playback on a player.",
        }
    ]
    assert result.data["total"] == 1
    assert result.data["next_cursor"] is None
    assert result.data["catalog_revision"]
```

Update legacy assertions to read `search.data["items"][0]`. Replace direct
`service.search(query)` calls with `service.discover(query)` and compare
`page["items"]`, while retaining all existing index-build-count assertions.

- [ ] **Step 2: Run the converted tests to demonstrate the old contract fails**

Run:

```bash
uv run pytest tests/test_dynamic_catalog.py -k "search or index or registry_change" -v
```

Expected: failures show that `MetaDiscoveryService` has no `discover` method and `search_tools` still returns an array.

- [ ] **Step 3: Add deterministic search and catalog pagination tests**

Add this helper beside `_catalog_entry`:

```python
def _catalog_snapshot(count: int = 7) -> CatalogSnapshot:
    entries = tuple(
        _catalog_entry(f"ma_api:music/command_{index:02d}", f"Music command {index}")
        for index in range(count)
    )
    return CatalogSnapshot(
        (1, "test", tuple((entry.command, index) for index, entry in enumerate(entries))),
        entries,
    )
```

Add exact page traversal tests:

```python
async def test_empty_query_browses_alphabetical_catalog_without_descriptions() -> None:
    service = _meta_service(_SnapshotAdapter(_catalog_snapshot()))
    first = await service.discover("", limit=3)
    second = await service.discover(cursor=first["next_cursor"], limit=3)
    third = await service.discover(cursor=second["next_cursor"], limit=3)
    assert first["mode"] == second["mode"] == third["mode"] == "catalog"
    assert first["total"] == second["total"] == third["total"] == 7
    assert [item["name"] for page in (first, second, third) for item in page["items"]] == [
        f"ma_api:music/command_{index:02d}" for index in range(7)
    ]
    assert all(set(item) == {"name"} for page in (first, second, third) for item in page["items"])
    assert third["next_cursor"] is None


async def test_ranked_search_pages_have_no_duplicates_or_gaps() -> None:
    service = _meta_service(_SnapshotAdapter(_catalog_snapshot()))
    first = await service.discover("music command", limit=2)
    second = await service.discover(cursor=first["next_cursor"], limit=2)
    assert first["mode"] == second["mode"] == "search"
    assert first["total"] == 7
    assert len({item["name"] for item in first["items"] + second["items"]}) == 4
    assert all("description" in item for item in first["items"] + second["items"])


async def test_cursor_accepts_matching_query_and_rejects_conflicting_query() -> None:
    service = _meta_service(_SnapshotAdapter(_catalog_snapshot()))
    first = await service.discover("music", limit=2)
    resumed = await service.discover(" MUSIC ", cursor=first["next_cursor"], limit=2)
    assert resumed["items"]
    with pytest.raises(PaginationError) as exc_info:
        await service.discover("players", cursor=first["next_cursor"])
    assert exc_info.value.code == "invalid_cursor"


async def test_catalog_change_invalidates_cursor() -> None:
    adapter = _SnapshotAdapter(_catalog_snapshot())
    service = _meta_service(adapter)
    first = await service.discover(limit=2)
    adapter.snapshot = _catalog_snapshot(8)
    with pytest.raises(PaginationError) as exc_info:
        await service.discover(cursor=first["next_cursor"])
    assert exc_info.value.code == "catalog_changed"


async def test_impossible_cursor_offset_is_rejected() -> None:
    service = _meta_service(_SnapshotAdapter(_catalog_snapshot(2)))
    first = await service.discover(limit=1)
    state = decode_cursor(cast("str", first["next_cursor"]))
    forged = encode_cursor(replace(state, offset=99))
    with pytest.raises(PaginationError) as exc_info:
        await service.discover(cursor=forged)
    assert exc_info.value.code == "invalid_cursor"
```

Import `replace`, `cast`, and the Task 1 pagination symbols needed by these tests.
Add this visibility-revision test; it changes only the request-visible view while
retaining the same base fingerprint:

```python
async def test_visibility_change_invalidates_cursor_without_leaking_hidden_name() -> None:
    class _VisibilityAdapter(_SnapshotAdapter):
        restricted = False

        async def visible_catalog(self) -> CatalogView:
            entries = self.snapshot.entries[:-1] if self.restricted else self.snapshot.entries
            return CatalogView(self.snapshot.fingerprint, entries)

    adapter = _VisibilityAdapter(_catalog_snapshot())
    service = _meta_service(adapter)
    first = await service.discover(limit=2)
    hidden_name = adapter.snapshot.entries[-1].name
    adapter.restricted = True
    with pytest.raises(PaginationError) as exc_info:
        await service.discover(cursor=first["next_cursor"])
    assert exc_info.value.code == "catalog_changed"
    restricted = await service.discover(limit=50)
    assert hidden_name not in {item["name"] for item in restricted["items"]}
```

- [ ] **Step 4: Implement `MetaDiscoveryService.discover()`**

Import the Task 1 types/functions and replace `search()` with this algorithm:

```python
async def discover(
    self,
    query: str | None = None,
    *,
    cursor: str | None = None,
    limit: int | None = None,
) -> DiscoveryPage:
    explicit_query = normalize_query(query)
    state = decode_cursor(cursor) if cursor is not None else None
    mode: DiscoveryMode
    if state is not None:
        if query is not None and explicit_query != state.query:
            raise PaginationError("invalid_cursor", "cursor query does not match query")
        mode = state.mode
        normalized_query = state.query
        offset = state.offset
    else:
        mode = "search" if explicit_query else "catalog"
        normalized_query = explicit_query
        offset = 0
    page_limit = resolve_limit(mode, limit)

    while True:
        view = await self.adapter.visible_catalog()
        snapshot = await self.adapter.base_snapshot()
        if view.fingerprint == snapshot.fingerprint:
            break
    visible = {entry.name: entry for entry in view.entries}
    revision = catalog_revision(snapshot.fingerprint, view.entries)
    if state is not None and state.revision != revision:
        raise PaginationError(
            "catalog_changed",
            "catalog changed; restart pagination without a cursor",
        )

    index = await self._index_for(snapshot) if mode == "search" else None
    legacy = LEGACY_MIGRATIONS.get(normalized_query) if mode == "search" else None
    ordered_items: list[DiscoveryItem]
    if legacy is not None:
        canonical = f"ma_api:{legacy.command}" if legacy.command is not None else None
        if canonical is not None and canonical in visible:
            ordered_items = [
                {"name": canonical, "description": visible[canonical].description}
            ]
        else:
            hint = canonical or legacy.message
            ordered_items = [
                {
                    "name": normalized_query,
                    "description": f"Retired tool; use {hint}.",
                }
            ]
    elif mode == "search":
        assert index is not None
        names = _rank(index, _tokens(normalized_query), allowed_names=set(visible))
        ordered_items = [
            {"name": name, "description": visible[name].description} for name in names
        ]
    else:
        ordered_items = [{"name": name} for name in sorted(visible)]

    total = len(ordered_items)
    if state is not None and offset >= total:
        raise PaginationError("invalid_cursor", "cursor offset is outside the result set")
    page_items = ordered_items[offset : offset + page_limit]
    next_offset = offset + len(page_items)
    next_cursor = (
        encode_cursor(
            CursorState(
                version=CURSOR_VERSION,
                mode=mode,
                query=normalized_query,
                offset=next_offset,
                revision=revision,
            )
        )
        if next_offset < total
        else None
    )
    return {
        "mode": mode,
        "items": page_items,
        "total": total,
        "next_cursor": next_cursor,
        "catalog_revision": revision,
    }
```

Keep the fingerprint-consistency loop and singleflight `_index_for()` behavior unchanged. Do not cache request-visible pages.

- [ ] **Step 5: Change the FastMCP `search_tools` handler to the stable page object**

Replace its signature and docstring with:

```python
async def search_tools(
    query: str | None = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> DiscoveryPage:
    """
    Search visible commands or browse the complete visible catalog.

    Non-empty queries return ranked names and descriptions. An empty query
    returns alphabetical names only. Follow ``next_cursor`` to read another
    page, and use ``get_tool_schema`` only for the command you will invoke.

    :param query: Search text; omit or leave empty to browse all commands.
    :param cursor: Opaque cursor returned by the preceding page.
    :param limit: Page size from 1 through 50.
    """
    try:
        return await service.discover(query, cursor=cursor, limit=limit)
    except PaginationError as exc:
        raise ToolError(f"{exc.code}: {exc}") from exc
```

Do not change `get_tool_schema`, `call_tool`, `_META_NAMES`, or tool annotations.

- [ ] **Step 6: Add tool-level validation, legacy, schema, and budget assertions**

Add or update tests so they assert:

```python
async def test_search_tool_rejects_invalid_limit_with_stable_code() -> None:
    mcp, _adapter = _server()
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="invalid_limit"):
            await client.call_tool("search_tools", {"query": "music", "limit": 0})


async def test_search_tool_rejects_malformed_cursor_with_stable_code() -> None:
    mcp, _adapter = _server()
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="invalid_cursor"):
            await client.call_tool("search_tools", {"cursor": "not-json"})


async def test_search_tools_schema_advertises_pagination() -> None:
    mcp, _adapter = _server()
    async with Client(mcp) as client:
        tool = next(item for item in await client.list_tools() if item.name == "search_tools")
    assert set(tool.inputSchema["properties"]) == {"query", "cursor", "limit"}
    assert tool.outputSchema is not None
    assert {"mode", "items", "total", "next_cursor", "catalog_revision"} <= set(
        tool.outputSchema["properties"]
    )
```

Retain `test_meta_catalog_stays_under_three_kib`. If the expanded structured schema
exceeds 3072 bytes, shorten only discovery docstrings/descriptions; do not remove
fields, annotations, or weaken the budget assertion.

- [ ] **Step 7: Run the discovery tests and static checks**

Run:

```bash
uv run pytest tests/test_catalog_pagination.py tests/test_dynamic_catalog.py tests/test_meta_discovery.py -v
uv run ruff check provider/meta_discovery.py tests/test_dynamic_catalog.py
uv run mypy provider/meta_discovery.py tests/test_dynamic_catalog.py
```

Expected: all tests pass; the existing concurrency tests still report one index build per fingerprint.

- [ ] **Step 8: Commit the paginated tool contract**

```bash
git add provider/meta_discovery.py tests/test_dynamic_catalog.py
git commit -m "feat: paginate command discovery"
```

---

### Task 3: Read-Only Catalog Resource Template

**Files:**
- Create: `provider/catalog_resource.py`
- Modify: `provider/meta_discovery.py`
- Modify: `tests/test_meta_discovery.py`
- Modify: `tests/test_e2e_smoke.py`

**Interfaces:**
- Consumes: `MetaDiscoveryService.discover()` from Task 2 and `resolve_limit()`/`PaginationError` from Task 1.
- Produces: `register_catalog_resource(mcp: FastMCP, pager: CatalogPager) -> None`.
- Produces: MCP resource template `catalog://commands{?cursor,limit}` with MIME type `application/json`.

- [ ] **Step 1: Write failing template discovery and first-page tests**

Extend `tests/test_meta_discovery.py` with a multi-entry adapter or reuse an adapter
backed by `CatalogSnapshot`, then add:

```python
async def test_catalog_resource_template_is_discoverable_and_matches_tool_browse() -> None:
    mcp = FastMCP(name="test")
    register_meta_discovery(
        mcp,
        allowed_tags_provider=set,
        lookup_component_tags=build_tag_lookup(mcp),
        dynamic_adapter=_Adapter(),
    )
    async with Client(mcp) as client:
        templates = {str(item.uriTemplate) for item in await client.list_resource_templates()}
        tool_page = await client.call_tool("search_tools", {"query": "", "limit": 25})
        contents = await client.read_resource("catalog://commands?limit=25")
    assert "catalog://commands{?cursor,limit}" in templates
    payload = json.loads(next(item.text for item in contents if hasattr(item, "text")))
    assert payload["items"] == tool_page.data["items"]
    assert payload["total"] == tool_page.data["total"]
    assert payload["catalog_revision"] == tool_page.data["catalog_revision"]
    assert payload["next_uri"] is None
    assert set(payload) == {
        "items",
        "total",
        "next_cursor",
        "next_uri",
        "catalog_revision",
    }
```

Import `json`. Update `tests/test_e2e_smoke.py` so its template set also requires
`"catalog://commands{?cursor,limit}"`.

- [ ] **Step 2: Run the tests to prove the resource is absent**

Run:

```bash
uv run pytest tests/test_meta_discovery.py::test_catalog_resource_template_is_discoverable_and_matches_tool_browse tests/test_e2e_smoke.py -v
```

Expected: the catalog template assertion fails.

- [ ] **Step 3: Implement the focused resource transport module**

Create `provider/catalog_resource.py`:

```python
"""Read-only MCP resource transport for the visible command catalog."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlencode

from fastmcp.exceptions import ResourceError

from .catalog_pagination import (
    DiscoveryPage,
    PaginationError,
    resolve_limit,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP


class CatalogPager(Protocol):
    """Minimal discovery-service interface consumed by the resource transport."""

    async def discover(
        self,
        query: str | None = None,
        *,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> DiscoveryPage:
        """Return one request-visible discovery page."""
        ...


def register_catalog_resource(mcp: FastMCP, pager: CatalogPager) -> None:
    """Register the always-on, request-filtered catalog resource template."""

    @mcp.resource(
        "catalog://commands{?cursor,limit}",
        name="command_catalog",
        description="Browse visible Music Assistant command names by page.",
        mime_type="application/json",
    )  # type: ignore[untyped-decorator, unused-ignore]
    async def command_catalog(
        cursor: str | None = None,
        limit: int | None = None,
    ) -> str:
        """Return one alphabetical page of visible command names."""
        try:
            page_limit = resolve_limit("catalog", limit)
            page = await pager.discover("", cursor=cursor, limit=page_limit)
        except PaginationError as exc:
            raise ResourceError(f"{exc.code}: {exc}") from exc
        next_cursor = page["next_cursor"]
        next_uri = (
            f"catalog://commands?{urlencode({'cursor': next_cursor, 'limit': page_limit})}"
            if next_cursor is not None
            else None
        )
        payload: dict[str, Any] = {
            "items": page["items"],
            "total": page["total"],
            "next_cursor": page["next_cursor"],
            "next_uri": next_uri,
            "catalog_revision": page["catalog_revision"],
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
```

The explicit empty query passed to `discover()` ensures a search-mode cursor is
rejected instead of being accepted by the resource.

- [ ] **Step 4: Register the resource against the existing service**

In `register_meta_discovery()` immediately after constructing the service:

```python
from .catalog_resource import register_catalog_resource

service = MetaDiscoveryService(dynamic_adapter)
register_catalog_resource(mcp, service)
```

Keep it untagged. This is the deliberate infrastructure exception to domain
resource tags; `TagFilterMiddleware` already treats an empty tag set as always-on,
while `visible_catalog()` filters every returned entry.

- [ ] **Step 5: Add multi-page URI, invalid cursor, and middleware tests**

Use this focused adapter/server fixture for resource tests:

```python
class _CatalogAdapter(_Adapter):
    def __init__(self, entry_count: int) -> None:
        entries = tuple(
            DynamicEntry(
                name=f"ma_api:music/command_{index:02d}",
                command=f"music/command_{index:02d}",
                description=f"Music command {index}",
                input_schema={"type": "object", "properties": {}},
                risk=DynamicRisk.READ,
                required_scope=None,
                allow_impersonation=False,
                handler=object(),
            )
            for index in range(entry_count)
        )
        self._snapshot = CatalogSnapshot(
            (
                1,
                "catalog",
                tuple((entry.command, index + 1) for index, entry in enumerate(entries)),
            ),
            entries,
        )


def _catalog_server(entry_count: int, *, middleware: bool = False) -> FastMCP:
    mcp: FastMCP = FastMCP(name="catalog-test")
    register_meta_discovery(
        mcp,
        allowed_tags_provider=set,
        lookup_component_tags=build_tag_lookup(mcp),
        dynamic_adapter=_CatalogAdapter(entry_count),
    )
    if middleware:
        mcp.add_middleware(TagFilterMiddleware(lambda: set(), build_tag_lookup(mcp)))
    return mcp
```

Add tests that use 3 entries and `limit=2`:

```python
async def test_catalog_resource_next_uri_reads_the_next_page() -> None:
    mcp = _catalog_server(entry_count=3)
    async with Client(mcp) as client:
        first_contents = await client.read_resource("catalog://commands?limit=2")
        first = json.loads(next(item.text for item in first_contents if hasattr(item, "text")))
        second_contents = await client.read_resource(first["next_uri"])
    second = json.loads(next(item.text for item in second_contents if hasattr(item, "text")))
    assert len(first["items"]) == 2
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None
    assert second["next_uri"] is None
    assert [item["name"] for item in first["items"] + second["items"]] == sorted(
        item["name"] for item in first["items"] + second["items"]
    )


async def test_catalog_resource_rejects_search_cursor() -> None:
    mcp = _catalog_server(entry_count=3)
    async with Client(mcp) as client:
        search = await client.call_tool("search_tools", {"query": "music", "limit": 1})
        with pytest.raises(McpError, match="invalid_cursor"):
            await client.read_resource(
                f"catalog://commands?{urlencode({'cursor': search.data['next_cursor']})}"
            )


async def test_untagged_catalog_resource_survives_empty_tag_middleware() -> None:
    mcp = _catalog_server(entry_count=0, middleware=True)
    async with Client(mcp) as client:
        templates = {str(item.uriTemplate) for item in await client.list_resource_templates()}
        contents = await client.read_resource("catalog://commands")
    assert "catalog://commands{?cursor,limit}" in templates
    page = json.loads(next(item.text for item in contents if hasattr(item, "text")))
    assert page["items"] == []
    assert page["total"] == 0
```

Import `McpError`, `urlencode`, and `TagFilterMiddleware` for these assertions.

- [ ] **Step 6: Run the focused resource and runtime smoke tests**

Run:

```bash
uv run pytest tests/test_catalog_pagination.py tests/test_dynamic_catalog.py tests/test_meta_discovery.py tests/test_middleware.py tests/test_e2e_smoke.py -v
uv run ruff check provider/catalog_resource.py provider/meta_discovery.py tests/test_meta_discovery.py tests/test_e2e_smoke.py
uv run mypy provider/catalog_resource.py provider/meta_discovery.py tests/test_meta_discovery.py tests/test_e2e_smoke.py
```

Expected: all tests and static checks pass; resource reads return JSON text and the public tool count remains three.

- [ ] **Step 7: Commit the catalog resource**

```bash
git add provider/catalog_resource.py provider/meta_discovery.py tests/test_meta_discovery.py tests/test_e2e_smoke.py
git commit -m "feat: expose paginated command catalog resource"
```

---

### Task 4: User Documentation and Live MA Catalog Coverage

**Files:**
- Modify: `provider/server.py`
- Modify: `README.md`
- Modify: `CLAUDE.local.md`
- Modify: `specs/done/0026-dynamic-ma-api-catalog.md`
- Modify: `tests/integration/test_live_catalog.py`

**Interfaces:**
- Consumes: final paginated tool and resource contracts from Tasks 2 and 3.
- Produces: documented client workflow and real-server proof that both traversal paths enumerate the same live visible catalog.

- [ ] **Step 1: Add live traversal helpers and a failing parity test**

Add these helpers to `tests/integration/test_live_catalog.py`:

```python
async def collect_tool_catalog(client: LiveClient) -> tuple[list[str], str]:
    names: list[str] = []
    cursor: str | None = None
    revision: str | None = None
    total: int | None = None
    while True:
        arguments: dict[str, Any] = {"limit": 50}
        if cursor is None:
            arguments["query"] = ""
        else:
            arguments["cursor"] = cursor
        result = await client.call_tool("search_tools", arguments)
        assert not result.is_error, result.content
        page = result.data
        assert page["mode"] == "catalog"
        revision = revision or str(page["catalog_revision"])
        total = int(page["total"]) if total is None else total
        assert page["catalog_revision"] == revision
        assert page["total"] == total
        names.extend(str(item["name"]) for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            assert len(names) == total
            return names, revision


async def collect_resource_catalog(client: LiveClient) -> tuple[list[str], str]:
    names: list[str] = []
    uri: str | None = "catalog://commands?limit=50"
    revision: str | None = None
    total: int | None = None
    while uri is not None:
        contents = await client.read_resource(uri)
        page = json.loads(next(item.text for item in contents if hasattr(item, "text")))
        revision = revision or str(page["catalog_revision"])
        total = int(page["total"]) if total is None else total
        assert page["catalog_revision"] == revision
        assert page["total"] == total
        names.extend(str(item["name"]) for item in page["items"])
        uri = page["next_uri"]
    assert len(names) == total
    return names, cast("str", revision)
```

Add the live test:

```python
@pytest.mark.integration
async def test_live_paginated_catalog_tool_resource_parity(live_client: LiveClient) -> None:
    templates = {str(item.uriTemplate) for item in await live_client.list_resource_templates()}
    assert "catalog://commands{?cursor,limit}" in templates
    tool_names, tool_revision = await collect_tool_catalog(live_client)
    resource_names, resource_revision = await collect_resource_catalog(live_client)
    assert tool_names == sorted(tool_names)
    assert len(tool_names) == len(set(tool_names))
    assert resource_names == tool_names
    assert resource_revision == tool_revision
    representatives = (
        "ma_api:music/search",
        "ma_api:music/albums/library_items",
        "ma_api:providers",
        "ma_api:players/all",
        "ma_api:player_queues/items",
        "ma_api:config/providers",
        "ma_api:fastmcp/debug/health",
    )
    for name in representatives:
        assert name in tool_names
        schema = await live_client.call_tool("get_tool_schema", {"tool_name": name})
        assert schema.data["name"] == name
```

- [ ] **Step 2: Add opt-in restricted-token cursor isolation coverage**

Add a `restricted_live_client` fixture using `MA_MCP_RESTRICTED_TOKEN`; skip when it
is absent. Add:

```python
@pytest.mark.integration
async def test_live_restricted_catalog_isolated_from_broader_cursor(
    live_client: LiveClient,
    restricted_live_client: LiveClient,
) -> None:
    broad_first = await live_client.call_tool("search_tools", {"query": "", "limit": 1})
    restricted_names, _revision = await collect_tool_catalog(restricted_live_client)
    broad_names, _revision = await collect_tool_catalog(live_client)
    assert set(restricted_names) < set(broad_names)
    with pytest.raises(ToolError, match="catalog_changed"):
        await restricted_live_client.call_tool(
            "search_tools",
            {"cursor": broad_first.data["next_cursor"]},
        )
```

The token must belong to a deliberately restricted MA user. Never log either token.

- [ ] **Step 3: Run the live test file before implementation deployment**

Run against the currently mounted server:

```bash
docker compose -f docker-compose.dev.yml exec -T \
  -e MA_MCP_URL=http://127.0.0.1:8095/mcp/v1 \
  -e MA_MCP_TOKEN="$MA_MCP_TOKEN" \
  -e MA_MCP_RESTRICTED_TOKEN="$MA_MCP_RESTRICTED_TOKEN" \
  ma /app/venv/bin/python -m pytest -o addopts= -p no:cacheprovider \
  --confcutdir=/tmp/provider-tests/integration \
  /tmp/provider-tests/integration/test_live_catalog.py \
  -m integration -k paginated_catalog -v -s
```

Expected before rebuilding/restarting: failure because the running server lacks the page object and catalog resource.

- [ ] **Step 4: Update server instructions and user documentation**

Change the FastMCP instructions in `provider/server.py` to say:

```text
Music Assistant MCP server with on-demand discovery. Use search_tools with a short
query, then get_tool_schema for one canonical ma_api:* command, then execute it
through call_tool. Use an empty search_tools query or catalog://commands for
paginated alphabetical browsing. Follow next_cursor/next_uri; responses default to
compact mode. Resources also expose library://, player:// and queue:// views.
```

In `README.md` under “Unified command catalog,” document:

- `search_tools(query="album tracks")` for ranked pages;
- `search_tools(query="", limit=25)` and then `search_tools(cursor="...")` for full browsing;
- `catalog://commands{?cursor,limit}` for resource-aware clients;
- search pages have descriptions, catalog pages have names only, and schemas remain on-demand.

In `CLAUDE.local.md`, add `provider/catalog_pagination.py` and
`provider/catalog_resource.py` to the architecture bullets. Narrow “Tool decorators
always include tags” to domain components and record that the catalog resource is
intentionally untagged infrastructure with per-entry visibility.

In the supersession notice at the top of `specs/done/0026-dynamic-ma-api-catalog.md`,
add a link to
`docs/superpowers/specs/2026-07-31-paginated-command-catalog-design.md` and state
that the historical five-result array contract is replaced by the page contract.

- [ ] **Step 5: Run focused documentation and integration static checks**

Run:

```bash
uv run pytest tests/integration/test_live_catalog.py --collect-only -q
uv run codespell README.md CLAUDE.local.md specs/done/0026-dynamic-ma-api-catalog.md provider/server.py tests/integration/test_live_catalog.py
uv run ruff check provider/server.py tests/integration/test_live_catalog.py
uv run mypy provider/server.py tests/integration/test_live_catalog.py
```

Expected: test collection and all checks pass without requiring live credentials.

- [ ] **Step 6: Commit documentation and live coverage**

```bash
git add provider/server.py README.md CLAUDE.local.md specs/done/0026-dynamic-ma-api-catalog.md tests/integration/test_live_catalog.py
git commit -m "test: cover paginated live command catalog"
```

---

### Task 5: Full Real-MA, Docker, and MCP Verification

**Files:**
- Modify only files implicated by a failing gate; do not weaken tests or alter unrelated user work.

**Interfaces:**
- Verifies all preceding task deliverables as one release candidate.
- Produces terminal evidence for unit, canonical MA dev, static, Docker, live HTTP MCP, and connected-session behavior.

- [ ] **Step 1: Run the focused pagination suite**

```bash
uv run pytest \
  tests/test_catalog_pagination.py \
  tests/test_dynamic_catalog.py \
  tests/test_meta_discovery.py \
  tests/test_middleware.py \
  tests/test_e2e_smoke.py -v
```

Expected: all tests pass and `test_meta_catalog_stays_under_three_kib` remains green.

- [ ] **Step 2: Run the full canonical Music Assistant dev suite**

```bash
bash .superpowers/sdd/2026-07-30-native-ma-command-catalog/run-ma-tests.sh -q
```

Expected: the entire provider suite passes in the Linux venv built from
`/Users/renso/Projects/ma-server`; integration-only tests skip unless credentials
are explicitly supplied.

- [ ] **Step 3: Run all static and repository gates**

```bash
uv run ruff check provider tests
uv run ruff format --check provider tests
uv run mypy provider tests
uv run pre-commit run --all-files
git diff --check
```

Expected: every command exits zero. If a formatter changes files, inspect the diff,
rerun the focused tests, and commit the formatting with the task it belongs to.

- [ ] **Step 4: Rebuild and validate the Docker test slice**

```bash
MA_SERVER_ROOT=/Users/renso/Projects/ma-server \
docker compose -f docker-compose.dev.yml up -d --build --wait --wait-timeout 120
docker compose -f docker-compose.dev.yml exec -T ma \
  /app/venv/bin/python -c \
  'import fastmcp, music_assistant, music_assistant.providers.fastmcp_server as p; print(fastmcp.__version__); print(music_assistant.__file__); print(p.__file__)'
```

Expected: Compose reports the service healthy, FastMCP is in the supported 3.x
range, and both MA/provider import paths begin with `/ma-server/`.

- [ ] **Step 5: Run live HTTP pagination and resource parity**

```bash
docker compose -f docker-compose.dev.yml exec -T \
  -e MA_MCP_URL=http://127.0.0.1:8095/mcp/v1 \
  -e MA_MCP_TOKEN="$MA_MCP_TOKEN" \
  -e MA_MCP_RESTRICTED_TOKEN="$MA_MCP_RESTRICTED_TOKEN" \
  -e MA_TEST_PLAYER_ID="$MA_TEST_PLAYER_ID" \
  ma /app/venv/bin/python -m pytest -o addopts= -p no:cacheprovider \
  --confcutdir=/tmp/provider-tests/integration \
  /tmp/provider-tests/integration/test_live_catalog.py -m integration -v -s
```

Expected: full traversal collects one duplicate-free sorted catalog; tool and
resource names match; representative track, album, provider, player, queue, config,
and debug schemas resolve. The restricted-token test may skip only when the explicit
restricted token is unavailable; record that skip in the handoff.

- [ ] **Step 6: Verify the connected `ma-test` session contract**

Through the connected MCP client:

1. Confirm `tools/list` returns exactly the three meta-tools.
2. Call `search_tools` with `query=""` and `limit=25`; verify a catalog page and `next_cursor`.
3. Follow the cursor to the next page and verify no repeated names.
4. List resource templates and confirm `catalog://commands{?cursor,limit}`.
5. Read `catalog://commands?limit=25`, follow `next_uri`, and compare names with the tool pages.
6. Fetch one track, album, queue, player, provider, config, and debug schema by exact catalog name.

Expected: all reads succeed with the configured `ma-test` identity and no additional
public tool appears.

- [ ] **Step 7: Inspect the final branch and commit any verified gate fix**

```bash
git status --short
git log --oneline -8
```

Expected: only intentional changes are present. If a gate required a code change,
rerun its red/green test and commit that focused fix with a Conventional Commit
message. Do not create an empty verification commit.
