"""Tests for dynamic Music Assistant response serialization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from uuid import UUID

from provider.dynamic_serialization import json_value


@dataclass(frozen=True)
class Artist:
    """A minimal MA artist-shaped model."""

    item_id: str
    name: str


class UniqueList(list[Artist]):
    """A collection that only accepts artist values."""

    def __init__(self, values: list[Artist]) -> None:
        """Initialise the collection with artist values."""
        if any(not isinstance(value, Artist) for value in values):
            raise TypeError("UniqueList accepts Artist values")
        super().__init__(values)


@dataclass
class Track:
    """A minimal MA track-shaped model."""

    uri: str
    artists: UniqueList


def test_dataclass_unique_list_is_converted_field_by_field() -> None:
    """Serialize dataclass fields without rebuilding custom collections."""
    value = Track("library://track/1", UniqueList([Artist("7", "Artist")]))

    assert json_value(value) == {
        "uri": "library://track/1",
        "artists": [{"item_id": "7", "name": "Artist"}],
    }


def test_to_dict_precedes_dataclass_conversion() -> None:
    """Prefer MA model serializers over dataclass fields."""

    @dataclass
    class Item:
        secret: str

        def to_dict(self) -> dict[str, str]:
            """Return the model's public representation."""
            return {"masked": "***"}

    assert json_value(Item("do-not-return")) == {"masked": "***"}


def test_set_output_is_deterministic() -> None:
    """Sort unordered values by their JSON representation."""
    assert json_value({"beta", "alpha"}) == ["alpha", "beta"]


def test_model_dump_precedes_dataclass_conversion() -> None:
    """Prefer Pydantic-style JSON model dumping over dataclass fields."""

    @dataclass
    class Item:
        secret: str

        def model_dump(self, *, mode: str) -> dict[str, str]:
            """Return the JSON-mode public representation."""
            assert mode == "json"
            return {"masked": "***"}

    assert json_value(Item("do-not-return")) == {"masked": "***"}


def test_common_scalar_and_container_values_are_json_safe() -> None:
    """Serialize scalar MA values inside nested mappings."""

    class State(Enum):
        PLAYING = "playing"

    value = {
        "nested": {
            "state": State.PLAYING,
            "day": date(2026, 7, 30),
            "moment": datetime(2026, 7, 30, 12, 45, 0, tzinfo=UTC),
            "identifier": UUID("12345678-1234-5678-1234-567812345678"),
            "path": Path("music/track.flac"),
            "values": frozenset({"z", "a"}),
        }
    }

    assert json_value(value) == {
        "nested": {
            "state": "playing",
            "day": "2026-07-30",
            "moment": "2026-07-30T12:45:00+00:00",
            "identifier": "12345678-1234-5678-1234-567812345678",
            "path": "music/track.flac",
            "values": ["a", "z"],
        }
    }


def test_repeated_non_cyclic_dataclass_is_serialized_each_time() -> None:
    """Only active recursive references are treated as cycles."""
    artist = Artist("7", "Artist")

    assert json_value([artist, artist]) == [
        {"item_id": "7", "name": "Artist"},
        {"item_id": "7", "name": "Artist"},
    ]


def test_cyclic_dataclass_uses_a_stable_cycle_marker() -> None:
    """Replace recursive object references with an explanatory marker."""

    @dataclass
    class Node:
        child: Node | None = None

    node = Node()
    node.child = node

    assert json_value(node) == {"child": f"<{Node.__module__}.{Node.__qualname__}:cycle>"}
