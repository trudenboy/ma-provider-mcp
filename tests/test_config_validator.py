"""Unit tests for the config value validator."""

# ruff: noqa: D103 -- test functions don't need docstrings

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError
from music_assistant_models.config_entries import ConfigEntry, ConfigValueOption
from music_assistant_models.enums import ConfigEntryType

from provider.config_io.validator import coerce


def _entry(**kw):
    base = {"key": "k", "type": ConfigEntryType.STRING, "label": "K"}
    base.update(kw)
    return ConfigEntry(**base)


def test_coerce_type_coercion_str_to_int() -> None:
    entry = _entry(type=ConfigEntryType.INTEGER)
    assert coerce(entry, "8099") == 8099


def test_coerce_type_coercion_str_to_bool() -> None:
    entry = _entry(type=ConfigEntryType.BOOLEAN)
    assert coerce(entry, "1") is True


def test_coerce_type_coercion_int_to_float() -> None:
    entry = _entry(type=ConfigEntryType.FLOAT)
    assert coerce(entry, 42) == 42.0


def test_coerce_passes_through_validation_callback() -> None:
    def check_positive(val: int) -> bool:
        return val > 0

    entry = _entry(type=ConfigEntryType.INTEGER, validate=check_positive)
    with pytest.raises(ToolError, match="failed validation"):
        coerce(entry, -5)


def test_coerce_int_out_of_range_rejected() -> None:
    entry = _entry(type=ConfigEntryType.INTEGER, range=(1, 15))
    with pytest.raises(ToolError, match="failed validation"):
        coerce(entry, 999)


def test_coerce_string_not_in_options_rejected() -> None:
    entry = _entry(
        type=ConfigEntryType.STRING,
        options=[ConfigValueOption(title="A", value="a"), ConfigValueOption(title="B", value="b")],
    )
    with pytest.raises(ToolError, match="failed validation"):
        coerce(entry, "z")


def test_coerce_int_in_range_ok() -> None:
    entry = _entry(type=ConfigEntryType.INTEGER, range=(1, 15))
    assert coerce(entry, 8) == 8


def test_coerce_string_in_options_ok() -> None:
    entry = _entry(
        type=ConfigEntryType.STRING,
        options=[ConfigValueOption(title="A", value="a"), ConfigValueOption(title="B", value="b")],
    )
    assert coerce(entry, "a") == "a"
