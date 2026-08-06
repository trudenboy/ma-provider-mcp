"""Tests for the stable capability vocabulary."""

from __future__ import annotations

from provider.capabilities import Capability


def test_capability_enum_remains_namespaced_and_complete() -> None:
    """All 26 stable capabilities use a recognized namespaced verb."""
    assert len(Capability) == 26
    for capability in Capability:
        verb, _, _ = capability.value.partition(":")
        assert verb in {"query", "control", "edit", "delete", "debug", "config", "system"}
