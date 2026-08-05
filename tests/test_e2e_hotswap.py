"""End-to-end permission hot-swap tests for the retained resource surface."""
# mypy: disable-error-code="arg-type, no-untyped-def, type-arg, assignment, operator, misc, attr-defined"

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

from fastmcp import Client, FastMCP

from provider.config import policy_mode_key
from provider.constants import CONF_DEFAULT_POLICY
from provider.middleware import TagFilterMiddleware
from provider.resources import register_resources
from provider.server import MCPServerRuntime, build_tag_lookup
from provider.tags import Tag, enabled_tags


def _build_runtime_with_resources(
    mock_mass: MagicMock, mock_config: MagicMock
) -> tuple[MCPServerRuntime, FastMCP]:
    """Build the production resource/tag shape without mounting an HTTP route."""
    runtime = MCPServerRuntime(mock_mass, mock_config, logging.getLogger("t"))
    mcp = FastMCP(name="hotswap-test")
    register_resources(mcp, mock_mass, mock_config)
    runtime._mcp = mcp
    runtime._allowed_tags = {str(tag) for tag in enabled_tags(mock_config)}
    mcp.add_middleware(TagFilterMiddleware(lambda: runtime._allowed_tags, build_tag_lookup(mcp)))
    return runtime, mcp


def _set_config_values(config: MagicMock, **overrides: Any) -> None:
    """Mutate the test provider config in place, matching MA update semantics."""
    config._values.update(overrides)


async def test_hot_swap_makes_disabled_resource_visible_without_restart(
    mock_mass: MagicMock, mock_config: MagicMock
) -> None:
    """Enabling a permission exposes its already-registered resource templates."""
    _set_config_values(
        mock_config,
        **{
            CONF_DEFAULT_POLICY: "Custom",
            policy_mode_key(Tag.QUERY_LIBRARY): "allow",
        },
    )
    runtime, mcp = _build_runtime_with_resources(mock_mass, mock_config)

    async with Client(mcp) as client:
        before = {template.uriTemplate for template in await client.list_resource_templates()}
    assert "player://{player_id}" not in before

    _set_config_values(mock_config, **{policy_mode_key(Tag.QUERY_PLAYERS): "allow"})
    await runtime.apply_permission_change(
        mock_config,
        changed_keys={policy_mode_key(Tag.QUERY_PLAYERS)},
    )

    async with Client(mcp) as client:
        after = {template.uriTemplate for template in await client.list_resource_templates()}
    assert "player://{player_id}" in after


async def test_hot_swap_hides_previously_visible_resource(
    mock_mass: MagicMock, mock_config: MagicMock
) -> None:
    """Disabling library query permission hides resources on the same FastMCP root."""
    runtime, mcp = _build_runtime_with_resources(mock_mass, mock_config)

    async with Client(mcp) as client:
        before = {template.uriTemplate for template in await client.list_resource_templates()}
    assert "library://track/{track_id}" in before

    _set_config_values(
        mock_config,
        **{
            CONF_DEFAULT_POLICY: "Custom",
            policy_mode_key(Tag.QUERY_LIBRARY): "deny",
        },
    )
    await runtime.apply_permission_change(
        mock_config,
        changed_keys={policy_mode_key(Tag.QUERY_LIBRARY)},
    )

    async with Client(mcp) as client:
        after = {template.uriTemplate for template in await client.list_resource_templates()}
    assert "library://track/{track_id}" not in after
