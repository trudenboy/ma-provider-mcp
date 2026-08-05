"""Tests for stable capabilities and v2 global-policy visibility."""

from __future__ import annotations

from unittest.mock import MagicMock

from provider.config import policy_mode_key
from provider.constants import CONF_DEFAULT_POLICY
from provider.tags import Tag, enabled_tags


def _config(values: dict[str, object]) -> MagicMock:
    config = MagicMock()
    config.get_value.side_effect = lambda key, default=None: values.get(key, default)
    return config


def test_capability_enum_remains_namespaced_and_complete() -> None:
    """All 26 stable capabilities use a recognized namespaced verb."""
    assert len(Tag) == 26
    for tag in Tag:
        verb, _, _ = tag.value.partition(":")
        assert verb in {"query", "control", "edit", "delete", "debug", "config", "system"}


def test_enabled_tags_uses_v2_default_snapshot_and_ignores_v1_values() -> None:
    """Visibility derives from v2 modes, never legacy booleans."""
    tags = enabled_tags(_config({"query_library": False, "debug_events": True}))

    assert tags == {
        Tag.QUERY_LIBRARY,
        Tag.QUERY_QUEUE,
        Tag.QUERY_PLAYERS,
        Tag.QUERY_METADATA,
    }


def test_custom_visibility_includes_allow_and_confirm_only() -> None:
    """Deny hides capabilities while Allow and Confirm remain discoverable."""
    tags = enabled_tags(
        _config(
            {
                CONF_DEFAULT_POLICY: "Custom",
                policy_mode_key(Tag.DEBUG_EVENTS): "confirm",
                policy_mode_key(Tag.CONTROL_PLAYBACK): "allow",
            }
        )
    )

    assert tags == {Tag.DEBUG_EVENTS, Tag.CONTROL_PLAYBACK}
