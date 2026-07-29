"""Compatibility-level tests for the permanent meta-discovery surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastmcp import Client, FastMCP

from provider.config import build_config_entries
from provider.constants import (
    CONF_DYNAMIC_API_CONTROL,
    CONF_DYNAMIC_API_READ,
    CONF_DYNAMIC_API_SYSTEM,
    CONF_DYNAMIC_API_WRITE,
    HOT_SWAPPABLE_KEYS,
)
from provider.dynamic_api import DynamicEntry, DynamicRisk
from provider.meta_discovery import register_meta_discovery
from provider.server import build_tag_lookup


@dataclass
class _Adapter:
    """Minimal catalog adapter for transform integration tests."""

    async def visible_entries(self) -> list[DynamicEntry]:
        """Return an empty dynamic catalog."""
        return []

    async def get_visible_entry(self, name: str) -> DynamicEntry | None:
        """Resolve no names."""
        del name
        return None

    async def call(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        response_mode: str,
        fields: list[str] | None,
        max_items: int | None,
        ctx: Any,
    ) -> dict[str, Any]:
        """Reject calls because the adapter is intentionally empty."""
        del name, arguments, response_mode, fields, max_items, ctx
        raise AssertionError("unreachable")


async def test_listing_is_permanently_collapsed() -> None:
    """There is no longer a toggle that restores the curated public catalog."""
    mcp: FastMCP = FastMCP(name="test")

    @mcp.tool
    async def old_tool() -> None:
        """Former public tool."""

    register_meta_discovery(
        mcp,
        allowed_tags_provider=set,
        lookup_component_tags=build_tag_lookup(mcp),
        dynamic_adapter=_Adapter(),
    )
    async with Client(mcp) as client:
        names = {tool.name for tool in await client.list_tools()}
    assert names == {"search_tools", "call_tool", "get_tool_schema"}


def test_dynamic_config_entries_replace_meta_toggle(mock_mass: Any) -> None:
    """Four risk gates replace the former discovery-mode switch."""
    entries = {entry.key: entry for entry in build_config_entries(mock_mass, {})}
    keys = {
        CONF_DYNAMIC_API_READ,
        CONF_DYNAMIC_API_CONTROL,
        CONF_DYNAMIC_API_WRITE,
        CONF_DYNAMIC_API_SYSTEM,
    }
    assert keys <= entries.keys()
    assert entries[CONF_DYNAMIC_API_READ].default_value is True
    assert all(entries[key].category == "dynamic_api" for key in keys)
    assert all(entries[key].default_value is False for key in keys - {CONF_DYNAMIC_API_READ})
    assert keys <= HOT_SWAPPABLE_KEYS


def test_dynamic_entry_type_still_carries_risk() -> None:
    """Keep the imported risk model visible to static consumers."""
    assert DynamicRisk.READ.value == "read"
