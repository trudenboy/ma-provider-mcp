"""Tests for dynamic Music Assistant handler signature compilation."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any, get_type_hints
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp.server.auth import AccessToken
from music_assistant_models.media_items import Track

from provider.dynamic_api import DynamicAPIAdapter, DynamicPolicy


async def library_items(
    favorite: bool | None = None,
    limit: int = 500,
    **kwargs: Any,
) -> list[Track]:
    """Return library items for a representative MA controller."""
    del favorite, limit, kwargs
    return []


def _compile(signature: inspect.Signature, type_hints: Mapping[str, Any]) -> Any:
    """Compile a handler signature through the public signature compiler."""
    from provider.dynamic_signatures import compile_signature

    return compile_signature(signature, type_hints)


def _handler(command: str, target: Any) -> Any:
    """Build the MA command-handler metadata relevant to compilation."""
    return SimpleNamespace(
        command=command,
        signature=inspect.signature(target),
        type_hints=get_type_hints(target),
        target=target,
        authenticated=True,
        required_scope="library.read",
        allow_impersonation=False,
        alias=False,
    )


def _adapter(handler: Any) -> DynamicAPIAdapter:
    """Build an authenticated adapter around one command handler."""
    mass = MagicMock()
    mass.command_handlers = {handler.command: handler}
    mass.webserver.auth.get_user = AsyncMock(return_value=MagicMock(enabled=True))
    return DynamicAPIAdapter(
        mass,
        policy_provider=DynamicPolicy,
        auth_required_provider=lambda: True,
        confirmation_provider=lambda: True,
        token_provider=lambda: AccessToken(token="secret", client_id="u1", scopes=[]),
        scope_checker=lambda _user, _scope: True,
    )


async def test_adapter_does_not_publish_kwargs_as_a_required_property() -> None:
    """The live adapter schema excludes MA's internal keyword catch-all."""
    entry = (
        await _adapter(
            _handler("music/tracks/library_items", library_items)
        ).visible_entries()
    )[0]

    assert "kwargs" not in entry.input_schema["properties"]
    assert "kwargs" not in entry.input_schema.get("required", [])
    assert entry.input_schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "command",
    [
        "music/albums/library_items",
        "music/artists/library_items",
        "music/audiobooks/library_items",
        "music/genres/library_items",
        "music/playlists/library_items",
        "music/podcasts/library_items",
        "music/tracks/library_items",
    ],
)
def test_library_item_commands_exclude_kwargs_from_their_schema(command: str) -> None:
    """All library-item command families expose only named handler arguments."""
    del command
    compiled = _compile(inspect.signature(library_items), get_type_hints(library_items))

    assert "kwargs" not in compiled.input_schema["properties"]
    assert "kwargs" not in compiled.input_schema.get("required", [])
    assert compiled.input_schema["additionalProperties"] is False


def test_named_arguments_execute_without_kwargs_container() -> None:
    """Named MA arguments bind without an artificial keyword container."""
    compiled = _compile(inspect.signature(library_items), get_type_hints(library_items))

    assert compiled.parse({"favorite": True, "limit": 10}) == {
        "favorite": True,
        "limit": 10,
    }


def test_var_positional_handler_is_incompatible() -> None:
    """Handlers with positional variadic values are rejected at discovery time."""
    from provider.dynamic_signatures import UnsupportedSignatureError

    def invalid(first: str, *values: str) -> None:
        pass

    with pytest.raises(UnsupportedSignatureError, match=r"\*values"):
        _compile(inspect.signature(invalid), get_type_hints(invalid))


def test_list_track_output_schema_is_not_a_string() -> None:
    """Track collection outputs never masquerade as scalar strings."""
    compiled = _compile(inspect.signature(library_items), get_type_hints(library_items))

    assert compiled.output_schema() != {"type": "string"}


def test_resolvable_output_type_uses_pydantic_json_schema() -> None:
    """Resolvable collection outputs retain Pydantic's array schema."""
    compiled = _compile(inspect.signature(lambda: None), {"return": list[str]})

    assert compiled.output_schema() == {"items": {"type": "string"}, "type": "array"}


def test_unresolved_output_type_has_unconstrained_python_type_metadata() -> None:
    """Unresolvable annotations do not masquerade as strings."""
    compiled = _compile(inspect.signature(lambda: None), {"return": "MissingModel"})

    assert compiled.output_schema() == {"x-python-type": "MissingModel"}
