"""JSON-safe serialization for dynamic Music Assistant command results."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

type JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]


def json_value(value: Any) -> JSONValue:
    """Convert one MA result without reconstructing custom collection types."""
    return _json_value(value, active_ids=set())


def _json_value(value: Any, active_ids: set[int]) -> JSONValue:
    """Convert one value while tracking active recursive references."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Enum):
        return _json_value(value.value, active_ids)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID | Path):
        return str(value)

    object_id = id(value)
    if object_id in active_ids:
        return f"<{type(value).__module__}.{type(value).__qualname__}:cycle>"
    active_ids.add(object_id)
    try:
        if callable(to_dict := getattr(value, "to_dict", None)):
            return _json_value(to_dict(), active_ids)
        if callable(model_dump := getattr(value, "model_dump", None)):
            return _json_value(model_dump(mode="json"), active_ids)
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return {
                field.name: _json_value(getattr(value, field.name), active_ids)
                for field in dataclasses.fields(value)
            }
        if isinstance(value, Mapping):
            return {str(key): _json_value(child, active_ids) for key, child in value.items()}
        if isinstance(value, set | frozenset):
            children = [_json_value(child, active_ids) for child in value]
            return sorted(children, key=lambda child: json.dumps(child, sort_keys=True))
        if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
            return [_json_value(child, active_ids) for child in value]
        return f"<{type(value).__module__}.{type(value).__qualname__}>"
    finally:
        active_ids.remove(object_id)
