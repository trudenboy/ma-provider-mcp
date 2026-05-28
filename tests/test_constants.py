"""Sanity tests for invariants in ``provider.constants``."""

from __future__ import annotations

from provider.constants import (
    HOT_SWAPPABLE_KEYS,
    PERMISSION_KEYS,
    RESOURCE_KEYS,
)


def test_permission_keys_count() -> None:
    """21 permission keys: 4 verbs x 4 categories + 5 debug tags."""
    assert len(PERMISSION_KEYS) == 21


def test_resource_keys_count() -> None:
    """3 resource toggles."""
    assert len(RESOURCE_KEYS) == 3


def test_hot_swappable_includes_perm_and_resource_keys() -> None:
    """Hot-swappable set is exactly the union — anything else triggers a runtime restart."""
    assert HOT_SWAPPABLE_KEYS == PERMISSION_KEYS | RESOURCE_KEYS


def test_no_overlap_perm_resource() -> None:
    """Permission and resource key sets don't overlap (cleanly partitioned)."""
    assert PERMISSION_KEYS.isdisjoint(RESOURCE_KEYS)
