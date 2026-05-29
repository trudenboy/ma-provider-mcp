"""Static validation of the OpenClaw distribution bundle.

The bundle under ``packaging/openclaw/`` is an installable Claude-format
plugin that pre-declares the Music Assistant MCP server. These tests guard
the artifact against silent drift — a malformed ``.mcp.json`` or a transport
typo would only surface as a failed install on a user's machine otherwise.
"""
# `assert` is the pytest convention.
# mypy: disable-error-code="type-arg, no-any-return"
#   The fixtures return decoded JSON; precise typing adds no safety to a
#   static-artifact validator.

from __future__ import annotations

import json
from pathlib import Path

import pytest

BUNDLE_DIR = Path(__file__).resolve().parents[1] / "packaging" / "openclaw"


@pytest.fixture
def mcp_json() -> dict:
    """Return the bundle's ``.mcp.json`` parsed as a dict."""
    return json.loads((BUNDLE_DIR / ".mcp.json").read_text(encoding="utf-8"))


@pytest.fixture
def plugin_json() -> dict:
    """Return the bundle's ``.claude-plugin/plugin.json`` parsed as a dict."""
    return json.loads((BUNDLE_DIR / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))


def test_bundle_layout_present() -> None:
    """The bundle ships the manifest, the MCP declaration, and a skill guide."""
    assert (BUNDLE_DIR / ".claude-plugin" / "plugin.json").is_file()
    assert (BUNDLE_DIR / ".mcp.json").is_file()
    assert (BUNDLE_DIR / "skills" / "music-assistant" / "SKILL.md").is_file()
    assert (BUNDLE_DIR / "README.md").is_file()


def test_mcp_json_declares_streamable_http_server(mcp_json: dict) -> None:
    """``.mcp.json`` declares the ``ma`` server over streamable-HTTP."""
    server = mcp_json["mcpServers"]["ma"]
    assert server["transport"] == "streamable-http"
    assert server["url"].endswith("/mcp/v1")


def test_mcp_json_uses_env_token_header(mcp_json: dict) -> None:
    """The bearer token is supplied via the ``${MA_TOKEN}`` env var, never inlined.

    OpenClaw interpolates ``${VAR}`` in ``headers`` values (but not in ``url``),
    so the token stays out of the committed artifact and out of bundle config.
    """
    auth = mcp_json["mcpServers"]["ma"]["headers"]["Authorization"]
    assert auth == "Bearer ${MA_TOKEN}"


def test_plugin_manifest_has_name(plugin_json: dict) -> None:
    """The Claude-format manifest carries a non-empty ``name``."""
    assert plugin_json.get("name")
