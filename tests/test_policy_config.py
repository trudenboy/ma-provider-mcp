"""V2 policy configuration parsing and dynamic-entry tests."""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from provider.config import (
    build_config_entries,
    build_policy_resolver,
    current_user_mcp_tokens,
    policy_mode_key,
    token_policy_key,
)
from provider.constants import (
    CONF_DEFAULT_POLICY,
    CONF_MANUAL_TOKEN_IDS,
    DEFAULT_MOUNT_PATH,
)
from provider.policy import PolicyMode, PolicyProfile
from provider.tags import Tag


def _config(values: Mapping[str, object]) -> MagicMock:
    config = MagicMock()
    config.get_value.side_effect = lambda key, default=None: values.get(key, default)
    return config


def test_missing_and_malformed_v2_defaults_fail_closed() -> None:
    """Absent or malformed profile values resolve Read-only, never admin."""
    missing = build_policy_resolver(_config({}))
    malformed = build_policy_resolver(_config({CONF_DEFAULT_POLICY: "typo-admin"}))

    assert missing.resolve(None).profile is PolicyProfile.READ_ONLY
    assert malformed.resolve(None).profile is PolicyProfile.READ_ONLY
    assert malformed.resolve(None).mode(Tag.CONFIG_WRITE_CORE) is PolicyMode.DENY


def test_default_named_and_custom_policy_parsing() -> None:
    """Named profiles and explicit Custom modes compile into complete snapshots."""
    named = build_policy_resolver(_config({CONF_DEFAULT_POLICY: "Home control"}))
    custom = build_policy_resolver(
        _config(
            {
                CONF_DEFAULT_POLICY: "Custom",
                policy_mode_key(Tag.QUERY_LIBRARY): "allow",
                policy_mode_key(Tag.DEBUG_EVENTS): "confirm",
                policy_mode_key(Tag.CONFIG_WRITE_CORE): "not-a-mode",
            }
        )
    )

    assert named.resolve(None).profile is PolicyProfile.HOME_CONTROL
    assert custom.resolve(None).mode(Tag.QUERY_LIBRARY) is PolicyMode.ALLOW
    assert custom.resolve(None).mode(Tag.DEBUG_EVENTS) is PolicyMode.CONFIRM
    assert custom.resolve(None).mode(Tag.CONFIG_WRITE_CORE) is PolicyMode.DENY
    assert custom.resolve(None).mode(Tag.CONTROL_PLAYBACK) is PolicyMode.DENY


def test_override_manual_unknown_and_replacement_resolution() -> None:
    """Only active/manual exact token IDs receive their own selection."""
    revoked_id = "revoked-id"
    replacement_id = "replacement-id"
    manual_id = "foreign-manual-id"
    values = {
        CONF_DEFAULT_POLICY: "Read-only",
        CONF_MANUAL_TOKEN_IDS: [manual_id],
        token_policy_key(revoked_id): "Trusted",
        token_policy_key(replacement_id): "Inherit",
        token_policy_key(manual_id): "Custom",
        policy_mode_key(Tag.CONTROL_PLAYBACK, manual_id): "allow",
    }
    resolver = build_policy_resolver(_config(values), active_token_ids={replacement_id})

    assert resolver.resolve(revoked_id).profile is PolicyProfile.READ_ONLY
    assert resolver.resolve(replacement_id).profile is PolicyProfile.READ_ONLY
    assert resolver.resolve("unknown-id").profile is PolicyProfile.READ_ONLY
    assert resolver.resolve(manual_id).profile is PolicyProfile.CUSTOM
    assert resolver.resolve(manual_id).mode(Tag.CONTROL_PLAYBACK) is PolicyMode.ALLOW


def test_malformed_token_profile_fails_closed() -> None:
    """A corrupt override cannot silently broaden into Interactive admin."""
    token_id = "configured-id"
    resolver = build_policy_resolver(
        _config(
            {
                CONF_DEFAULT_POLICY: "Trusted",
                token_policy_key(token_id): "Interactive administrator",
            }
        ),
        active_token_ids={token_id},
    )

    assert resolver.resolve(token_id).profile is PolicyProfile.READ_ONLY
    assert resolver.resolve(token_id).mode(Tag.SYSTEM_ADMIN) is PolicyMode.DENY


@pytest.mark.asyncio
async def test_current_user_discovery_uses_ma_apis_and_exact_prefix(mock_mass: MagicMock) -> None:
    """Discovery includes only current-user tokens with the exact MCP em-dash prefix."""
    current = SimpleNamespace(user_id="current-user")
    mock_mass.webserver.auth.get_current_user_info = AsyncMock(return_value=current)
    mock_mass.webserver.auth.get_user_tokens = AsyncMock(
        return_value=[
            SimpleNamespace(token_id="a", user_id="current-user", name="MCP — Claude"),
            SimpleNamespace(token_id="b", user_id="current-user", name="MCP - wrong dash"),
            SimpleNamespace(token_id="c", user_id="foreign-user", name="MCP — Foreign"),
            SimpleNamespace(token_id="d", user_id="current-user", name="Other client"),
        ]
    )

    tokens = await current_user_mcp_tokens(mock_mass)

    assert [(token.token_id, token.name) for token in tokens] == [("a", "MCP — Claude")]
    mock_mass.webserver.auth.get_user_tokens.assert_awaited_once_with()


def test_dynamic_entries_have_conditional_matrices_and_hashed_token_keys(
    mock_mass: MagicMock,
) -> None:
    """Each selector controls exactly one 26-capability Custom matrix."""
    raw_id = "token-id-must-not-appear"
    entries = build_config_entries(
        mock_mass,
        DEFAULT_MOUNT_PATH,
        tokens=(SimpleNamespace(token_id=raw_id, name="MCP — Claude"),),
        manual_token_ids=("manual-foreign-id",),
    )
    by_key = {entry.key: entry for entry in entries}
    selector_key = token_policy_key(raw_id)

    assert CONF_DEFAULT_POLICY in by_key
    assert CONF_MANUAL_TOKEN_IDS in by_key
    assert by_key[CONF_MANUAL_TOKEN_IDS].multi_value is True
    assert selector_key in by_key
    assert [option.value for option in by_key[CONF_DEFAULT_POLICY].options] == [
        "Read-only",
        "Home control",
        "Interactive admin",
        "Trusted",
        "Custom",
    ]
    assert [option.value for option in by_key[selector_key].options] == [
        "Inherit",
        "Read-only",
        "Home control",
        "Interactive admin",
        "Trusted",
        "Custom",
    ]
    assert raw_id not in selector_key
    assert token_policy_key(raw_id) == token_policy_key(raw_id)
    assert token_policy_key(raw_id) != token_policy_key("replacement-id")
    assert all(raw_id not in entry.key for entry in entries)

    default_matrix = [
        entry
        for entry in entries
        if entry.depends_on == CONF_DEFAULT_POLICY and entry.depends_on_value == "Custom"
    ]
    token_matrix = [
        entry
        for entry in entries
        if entry.depends_on == selector_key and entry.depends_on_value == "Custom"
    ]
    assert len(default_matrix) == len(Tag) == 26
    assert len(token_matrix) == len(Tag) == 26


def test_v1_entries_are_removed_even_if_stored_values_exist(mock_mass: MagicMock) -> None:
    """The breaking v2 UI ignores all legacy permission/risk/confirmation keys."""
    entries = build_config_entries(mock_mass, DEFAULT_MOUNT_PATH)
    keys = {entry.key for entry in entries}

    assert {
        "query_library",
        "debug_events",
        "config_write_core",
        "dynamic_api_read",
        "require_confirmation",
    }.isdisjoint(keys)
