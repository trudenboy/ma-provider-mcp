"""Authorization shared by provider-owned native MA API commands."""
# ruff: noqa: TID252 -- provider source is transplanted under the MA package.

from __future__ import annotations

from typing import TYPE_CHECKING

from music_assistant_models.auth import Scope
from music_assistant_models.errors import AuthenticationRequired, InsufficientPermissions

from music_assistant.controllers.webserver.helpers.auth_middleware import (
    get_current_user,
    has_scope,
)

from ..tags import enabled_tags

if TYPE_CHECKING:
    from music_assistant_models.auth import User
    from music_assistant_models.config_entries import ProviderConfig


def normalize_scope(required_scope: object) -> Scope | None:
    """Return one known MA scope or fail closed for unknown runtime values."""
    if isinstance(required_scope, Scope):
        scope = required_scope
    elif isinstance(required_scope, str):
        try:
            scope = Scope(required_scope)
        except ValueError:
            return None
    else:
        return None
    return None if scope is Scope.UNKNOWN else scope


def scope_allowed(user: User, required_scope: object) -> bool:
    """Delegate enabled-user scope checks to Music Assistant's current helper."""
    if not getattr(user, "enabled", False):
        return False
    scope = normalize_scope(required_scope)
    if scope is None:
        return False
    return bool(has_scope(user, scope))


def authorize_extension(
    config: ProviderConfig,
    *,
    required_scope: str,
    required_tag: str,
) -> User:
    """Require an enabled MA user, a matching scope, and the provider tag."""
    user = get_current_user()
    if user is None or not getattr(user, "enabled", False):
        raise AuthenticationRequired("An enabled Music Assistant user is required")
    if not scope_allowed(user, required_scope):
        raise InsufficientPermissions(f"Scope {required_scope!r} is required")
    if required_tag not in {str(tag) for tag in enabled_tags(config)}:
        raise InsufficientPermissions(f"Provider permission {required_tag!r} is disabled")
    return user  # type: ignore[no-any-return, unused-ignore]
