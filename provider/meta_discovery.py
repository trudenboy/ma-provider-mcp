"""Permanent three-tool discovery surface for the dynamic MA API catalog."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import TYPE_CHECKING, Any, Protocol

from fastmcp import Context  # noqa: TC002  -- FastMCP resolves injected annotations at runtime.
from fastmcp.exceptions import NotFoundError, ToolError
from fastmcp.server.transforms.search import BM25SearchTransform
from fastmcp.tools import Tool
from mcp.types import ToolAnnotations

from .dynamic_api import LEGACY_MIGRATIONS, DynamicEntry

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from fastmcp import FastMCP
    from fastmcp.server.transforms import GetToolNext
    from fastmcp.utilities.versions import VersionSpec

    from .middleware import TagsLookup

GET_TOOL_SCHEMA_NAME = "get_tool_schema"
SEARCH_MAX_RESULTS = 5
CALL_TOOL_NAME = "call_tool"
SEARCH_TOOL_NAME = "search_tools"
_META_NAMES = {CALL_TOOL_NAME, SEARCH_TOOL_NAME, GET_TOOL_SCHEMA_NAME}
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


class DynamicAdapter(Protocol):
    """Transform-facing contract implemented by the MA dispatcher."""

    async def visible_entries(self) -> list[DynamicEntry]:
        """Return entries visible for the current request."""

    async def get_visible_entry(self, name: str) -> DynamicEntry | None:
        """Resolve a visible entry by canonical name."""

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


def _light_results(tools: Sequence[Tool]) -> list[dict[str, str]]:
    """Serialize search hits as name + description only — schemas stay on demand."""
    return [{"name": t.name, "description": (t.description or "").strip()} for t in tools]


def _tokens(value: str) -> list[str]:
    """Tokenize names and descriptions with Unicode-aware normalization."""
    normalized = unicodedata.normalize("NFKC", value).casefold().replace("/", " ")
    return _TOKEN_RE.findall(normalized.replace("_", " "))


class MetaDiscoveryTransform(BM25SearchTransform):  # type: ignore[misc, unused-ignore]
    """Expose only meta-tools and search dynamic catalog entries."""

    def __init__(self, adapter: DynamicAdapter) -> None:
        """Initialise the permanent discovery transform."""
        super().__init__(
            max_results=SEARCH_MAX_RESULTS,
            always_visible=[GET_TOOL_SCHEMA_NAME],
            search_result_serializer=_light_results,
        )
        self.adapter = adapter
        self._entries: dict[str, DynamicEntry] = {}

    async def transform_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        """Collapse every listing to the permanent three-tool surface."""
        ingest = getattr(self.adapter, "ingest_curated", None)
        if ingest is not None:
            ingest(tools)
        return await super().transform_tools(tools)

    async def get_tool(
        self, name: str, call_next: GetToolNext, *, version: VersionSpec | None = None
    ) -> Tool | None:
        """Resolve only the public meta-tools; old curated names are retired."""
        if name not in _META_NAMES:
            return None
        return await super().get_tool(name, call_next, version=version)

    async def _get_visible_tools(self, ctx: Context) -> Sequence[Tool]:
        """Render current dynamic entries as lightweight virtual tools."""
        del ctx
        entries = await self.adapter.visible_entries()
        self._entries = {entry.name: entry for entry in entries}
        return [self._entry_tool(entry) for entry in entries]

    async def _search(self, tools: Sequence[Tool], query: str) -> Sequence[Tool]:
        """Rank entries with a small Unicode-aware BM25 implementation."""
        if not tools:
            return []
        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        documents: list[list[str]] = []
        for tool in tools:
            entry = self._entries[tool.name]
            documents.append(
                _tokens(" ".join((entry.name, entry.description, *entry.search_aliases)))
            )
        avg_len = sum(map(len, documents)) / len(documents) or 1.0
        doc_freq = Counter(
            token for token in set(query_tokens) for doc in documents if token in doc
        )
        scored: list[tuple[float, str, Tool]] = []
        for tool, document in zip(tools, documents, strict=True):
            frequencies = Counter(document)
            score = 0.0
            for token in query_tokens:
                frequency = frequencies[token]
                if not frequency:
                    continue
                inverse = math.log(
                    1 + (len(documents) - doc_freq[token] + 0.5) / (doc_freq[token] + 0.5)
                )
                denominator = frequency + 1.5 * (1 - 0.75 + 0.75 * len(document) / avg_len)
                score += inverse * frequency * 2.5 / denominator
            normalized_query = " ".join(query_tokens)
            if normalized_query == " ".join(_tokens(tool.name)):
                score += 100.0
            elif " ".join(_tokens(tool.name)).startswith(normalized_query):
                score += 25.0
            if score > 0:
                scored.append((score, tool.name, tool))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [tool for _score, _name, tool in scored[:SEARCH_MAX_RESULTS]]

    def _make_call_tool(self) -> Tool:
        """Create the proxy that routes canonical dynamic names."""
        transform = self

        async def call_tool(
            name: str,
            arguments: dict[str, Any] | None = None,
            response_mode: str = "compact",
            fields: list[str] | None = None,
            max_items: int | None = None,
            ctx: Context | None = None,
        ) -> dict[str, Any]:
            """
            Execute a command found with search_tools.

            :param name: Canonical ``ma_api:*`` or ``mcp_api:*`` name.
            :param arguments: Command arguments from get_tool_schema.
            :param response_mode: ``compact`` (default) or explicit ``full``.
            :param fields: Optional top-level fields to retain.
            :param max_items: Optional smaller item limit.
            """
            if replacement := LEGACY_MIGRATIONS.get(name):
                raise ToolError(f"Tool {name!r} was retired; use {replacement!r}")
            if name in _META_NAMES:
                raise ToolError(f"Meta-tool {name!r} cannot call itself")
            if ctx is None:  # pragma: no cover - FastMCP always injects Context
                raise ToolError("MCP request context is unavailable")
            entry = await transform.adapter.get_visible_entry(name)
            if entry is None:
                raise ToolError(f"Tool {name!r} not found or not permitted")
            return await transform.adapter.call(
                name,
                dict(arguments or {}),
                response_mode=response_mode,
                fields=fields,
                max_items=max_items,
                ctx=ctx,
            )

        return Tool.from_function(fn=call_tool, name=CALL_TOOL_NAME)

    @staticmethod
    def _entry_tool(entry: DynamicEntry) -> Tool:
        """Create a virtual tool descriptor without registering an executor."""

        async def unavailable() -> None:
            """Virtual catalog entry; invoke it through call_tool."""

        tool = Tool.from_function(
            fn=unavailable,
            name=entry.name,
            description=entry.description,
        )
        return tool.model_copy(update={"parameters": entry.input_schema})


def register_meta_discovery(
    mcp: FastMCP,
    *,
    allowed_tags_provider: Callable[[], set[str]],
    lookup_component_tags: TagsLookup,
    dynamic_adapter: DynamicAdapter,
    enabled: Callable[[], bool] | None = None,
) -> None:
    """
    Register schema lookup and install the permanent discovery transform.

    :param mcp: Root FastMCP server (after all sub-servers are mounted).
    :param dynamic_adapter: Runtime command catalog and dispatcher.
    :param enabled: Deprecated compatibility parameter; ignored.
    :param allowed_tags_provider: Zero-arg callable returning the currently
        allowed permission tags (same closure the tag-filter middleware uses).
    :param lookup_component_tags: Async ``(kind, key) -> tags | None`` resolver
        (see :func:`provider.server.build_tag_lookup`).
    """
    # Recipe visibility is enforced by the adapter from the same live tag
    # closure. The lookup remains part of the compatibility signature because
    # direct curated calls are still guarded by TagFilterMiddleware internally.
    del allowed_tags_provider, lookup_component_tags, enabled
    transform = MetaDiscoveryTransform(dynamic_adapter)

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
        Returns ``name``, ``description`` and ``inputSchema``, plus
        ``outputSchema`` and ``annotations`` when the tool declares them.

        :param tool_name: Exact tool name as returned by ``search_tools``.
        """
        entry = await transform.adapter.get_visible_entry(tool_name)
        if entry is None:
            raise NotFoundError(f"Tool {tool_name!r} not found")
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

    mcp.add_transform(transform)
