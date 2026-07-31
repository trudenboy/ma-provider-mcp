"""Permanent three-tool discovery surface for the dynamic MA API catalog."""

from __future__ import annotations

import asyncio
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Annotated, Any, Protocol

from fastmcp import Context  # noqa: TC002  -- FastMCP resolves injected annotations at runtime.
from fastmcp.exceptions import NotFoundError, ToolError
from mcp.types import ToolAnnotations
from pydantic import WithJsonSchema

from .catalog_pagination import (
    CURSOR_VERSION,
    CursorState,
    DiscoveryItem,
    DiscoveryMode,
    DiscoveryPage,
    PaginationError,
    catalog_revision,
    decode_cursor,
    encode_cursor,
    normalize_query,
    resolve_limit,
)
from .catalog_resource import register_catalog_resource
from .dynamic_api import (
    LEGACY_MIGRATIONS,
    CatalogFingerprint,
    CatalogSnapshot,
    CatalogView,
    DynamicEntry,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastmcp import FastMCP

    from .middleware import TagsLookup

GET_TOOL_SCHEMA_NAME = "get_tool_schema"
CALL_TOOL_NAME = "call_tool"
SEARCH_TOOL_NAME = "search_tools"
_META_NAMES = {CALL_TOOL_NAME, SEARCH_TOOL_NAME, GET_TOOL_SCHEMA_NAME}
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


class DynamicAdapter(Protocol):
    """Direct discovery contract implemented by the MA dispatcher."""

    async def base_snapshot(self) -> CatalogSnapshot:
        """Return the immutable compiled catalog for the live registry."""

    async def visible_catalog(self) -> CatalogView:
        """Return entries visible for the current request."""

    async def call(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        response_mode: str,
        fields: list[str] | None,
        max_items: int | None,
        ctx: Context,
    ) -> dict[str, Any]:
        """Execute an entry and return its bounded envelope."""


@dataclass(frozen=True, slots=True)
class SearchIndex:
    """Immutable token statistics for one base catalog fingerprint."""

    fingerprint: CatalogFingerprint
    documents: Mapping[str, tuple[str, ...]]
    frequencies: Mapping[str, Mapping[str, int]]
    document_frequencies: Mapping[str, int]
    average_length: float


def _tokens(value: str) -> list[str]:
    """Tokenize names and descriptions with Unicode-aware normalization."""
    normalized = unicodedata.normalize("NFKC", value).casefold().replace("/", " ")
    return _TOKEN_RE.findall(normalized.replace("_", " "))


def _build_search_index(snapshot: CatalogSnapshot) -> SearchIndex:
    """Compile immutable BM25 documents once for a base catalog snapshot."""
    documents: dict[str, tuple[str, ...]] = {}
    frequencies: dict[str, Mapping[str, int]] = {}
    document_frequencies: Counter[str] = Counter()
    for entry in snapshot.entries:
        document = tuple(_tokens(" ".join((entry.name, entry.description, *entry.search_aliases))))
        documents[entry.name] = document
        frequency = Counter(document)
        frequencies[entry.name] = MappingProxyType(dict(frequency))
        document_frequencies.update(frequency.keys())
    average_length = sum(map(len, documents.values())) / len(documents) if documents else 1.0
    return SearchIndex(
        fingerprint=snapshot.fingerprint,
        documents=MappingProxyType(documents),
        frequencies=MappingProxyType(frequencies),
        document_frequencies=MappingProxyType(dict(document_frequencies)),
        average_length=average_length or 1.0,
    )


def _rank(index: SearchIndex, query_tokens: list[str], *, allowed_names: set[str]) -> list[str]:
    """Rank only the current request's visible catalog intersection."""
    if not query_tokens:
        return []
    document_count = len(index.documents)
    if not document_count:
        return []
    normalized_query = " ".join(query_tokens)
    scored: list[tuple[float, str]] = []
    for name in allowed_names:
        document = index.documents.get(name)
        frequencies = index.frequencies.get(name)
        if document is None or frequencies is None:
            continue
        score = 0.0
        for token in query_tokens:
            frequency = frequencies.get(token, 0)
            if not frequency:
                continue
            document_frequency = index.document_frequencies.get(token, 0)
            inverse = math.log(
                1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            denominator = frequency + 1.5 * (1 - 0.75 + 0.75 * len(document) / index.average_length)
            score += inverse * frequency * 2.5 / denominator
        normalized_name = " ".join(_tokens(name))
        if normalized_query == normalized_name:
            score += 100.0
        elif normalized_name.startswith(normalized_query):
            score += 25.0
        if score > 0:
            scored.append((score, name))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [name for _score, name in scored]


class MetaDiscoveryService:
    """Search and schema lookup over the adapter's cached catalog snapshots."""

    def __init__(self, adapter: DynamicAdapter) -> None:
        """Initialise a request-safe cache for immutable catalog indexes."""
        self.adapter = adapter
        self._index: SearchIndex | None = None
        self._index_lock = asyncio.Lock()
        self.index_build_count = 0

    async def discover(
        self,
        query: str | None = None,
        *,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> DiscoveryPage:
        """Return one visible ranked-search or alphabetical-catalog page."""
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
                ordered_items = [{"name": canonical, "description": visible[canonical].description}]
            else:
                hint = canonical or legacy.message
                ordered_items = [
                    {"name": normalized_query, "description": f"Retired tool; use {hint}."}
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

    async def get_schema(self, tool_name: str) -> dict[str, Any]:
        """Return one current request-visible entry's complete schema descriptor."""
        entry = next(
            (
                entry
                for entry in (await self.adapter.visible_catalog()).entries
                if entry.name == tool_name
            ),
            None,
        )
        if entry is None:
            raise NotFoundError(f"Tool {tool_name!r} not found")
        return _schema_result(entry)

    async def _index_for(self, snapshot: CatalogSnapshot) -> SearchIndex:
        """Return the snapshot's index, building it once across concurrent callers."""
        if self._index is not None and self._index.fingerprint == snapshot.fingerprint:
            return self._index
        async with self._index_lock:
            if self._index is None or self._index.fingerprint != snapshot.fingerprint:
                self._index = await self._build_index(snapshot)
                self.index_build_count += 1
            return self._index

    async def _build_index(self, snapshot: CatalogSnapshot) -> SearchIndex:
        """Build index data synchronously behind the async singleflight lock."""
        return _build_search_index(snapshot)


def _schema_result(entry: DynamicEntry) -> dict[str, Any]:
    """Serialize the dynamic schema only after an exact visible-name lookup."""
    result: dict[str, Any] = {
        "name": entry.name,
        "kind": entry.name.split(":", 1)[0],
        "command": entry.command,
        "description": entry.description,
        "inputSchema": entry.input_schema,
        "risk": entry.risk.value,
        "requiredScope": entry.required_scope,
        "allowImpersonation": entry.allow_impersonation,
        "annotations": entry.annotations,
    }
    if entry.output_schema is not None:
        result["outputSchema"] = entry.output_schema
    return result


def register_meta_discovery(
    mcp: FastMCP,
    *,
    allowed_tags_provider: Callable[[], set[str]],
    lookup_component_tags: TagsLookup,
    dynamic_adapter: DynamicAdapter,
    enabled: Callable[[], bool] | None = None,
) -> None:
    """Register the permanent direct three-tool discovery surface."""
    # The adapter applies the same live tag closure as the request middleware.
    # These parameters remain for compatibility with existing runtime wiring.
    del allowed_tags_provider, lookup_component_tags, enabled
    service = MetaDiscoveryService(dynamic_adapter)
    register_catalog_resource(mcp, service)

    @mcp.tool(
        name=SEARCH_TOOL_NAME,
        annotations=ToolAnnotations(
            title="Search tools",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )  # type: ignore[untyped-decorator, unused-ignore]
    async def search_tools(
        query: str | None = None,
        cursor: str | None = None,
        limit: Annotated[Any, WithJsonSchema({"type": "integer"})] = None,
    ) -> DiscoveryPage:
        """
        Search visible commands or browse the catalog.

        Follow ``next_cursor`` for another page; fetch a schema only before invocation.

        :param query: Search text, or empty to browse.
        :param cursor: Previous page cursor.
        :param limit: Page size, 1-50.
        """
        try:
            return await service.discover(query, cursor=cursor, limit=limit)
        except PaginationError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc

    @mcp.tool(
        name=GET_TOOL_SCHEMA_NAME,
        annotations=ToolAnnotations(
            title="Get tool schema",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )  # type: ignore[untyped-decorator, unused-ignore]
    async def get_tool_schema(tool_name: str) -> dict[str, Any]:
        """
        Return the full schema for one catalogued tool.

        Use ``search_tools`` first to find candidate tool names, then fetch
        the schema of the one you intend to invoke via ``call_tool``.

        :param tool_name: Exact canonical ``ma_api:*`` name from ``search_tools``.
        """
        return await service.get_schema(tool_name)

    @mcp.tool(name=CALL_TOOL_NAME)  # type: ignore[untyped-decorator, unused-ignore]
    async def call_tool(
        name: str,
        arguments: dict[str, Any] | None = None,
        response_mode: str = "compact",
        fields: list[str] | None = None,
        max_items: int | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """
        Execute a canonical ``ma_api:*`` command found with ``search_tools``.

        :param name: Canonical ``ma_api:*`` name.
        :param arguments: Command arguments from get_tool_schema.
        :param response_mode: ``compact`` (default) or explicit ``full``.
        :param fields: Optional top-level fields to retain.
        :param max_items: Optional smaller item limit.
        """
        if replacement := LEGACY_MIGRATIONS.get(name):
            hint = (
                f"ma_api:{replacement.command}"
                if replacement.command is not None
                else replacement.message
            )
            raise ToolError(f"Tool {name!r} was retired; use {hint!r}")
        if not name.startswith("ma_api:"):
            raise ToolError(f"Tool {name!r} is not a canonical ma_api command")
        if ctx is None:  # pragma: no cover - FastMCP always injects Context
            raise ToolError("MCP request context is unavailable")
        return await dynamic_adapter.call(
            name,
            dict(arguments or {}),
            response_mode=response_mode,
            fields=fields,
            max_items=max_items,
            ctx=ctx,
        )

    # Only the permanent discovery surface is exposed to model clients.
    mcp.disable(components={"tool"})
    mcp.enable(names=_META_NAMES, components={"tool"})
