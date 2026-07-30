"""Authorization shared by provider-owned native MA API commands."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from music_assistant_models.auth import UserRole
from music_assistant_models.errors import AuthenticationRequired, InsufficientPermissions

from ..tags import enabled_tags

if TYPE_CHECKING:
    from music_assistant_models.auth import User
    from music_assistant_models.config_entries import ProviderConfig

try:
    from music_assistant.controllers.webserver.helpers.auth_middleware import (
        get_current_user,
        has_scope as _ma_has_scope,
    )
except ImportError:
    def get_current_user() -> User | None:
        """Minimal-development fallback; real MA supplies the context-local user."""
        return None

    _ma_has_scope: Any = None


def scope_allowed(user: User, required_scope: str) -> bool:
    """Use MA scope checks when available; otherwise apply a narrow role fallback."""
    if not getattr(user, "enabled", False):
        return False
    role = getattr(user, "role", None)
    if not isinstance(role, UserRole):
        try:
            role = UserRole(getattr(role, "value", role))
        except (TypeError, ValueError):
            return False
    if _ma_has_scope is not None:
        try:
            from music_assistant_models.auth import Scope

            return bool(_ma_has_scope(user, Scope(required_scope)))
        except (AttributeError, TypeError, ValueError):
            return False
    if required_scope.startswith(("system.", "config.")):
        return role is UserRole.ADMIN
    if required_scope.startswith("queues."):
        return role in {UserRole.ADMIN, UserRole.USER}
    return False


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
    return user
