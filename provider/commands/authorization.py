"""Authorization shared by provider-owned native MA API commands."""
# ruff: noqa: TID252 -- provider source is transplanted under the MA package.

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from music_assistant_models.auth import Scope, UserRole
from music_assistant_models.errors import AuthenticationRequired, InsufficientPermissions

from ..tags import enabled_tags

if TYPE_CHECKING:
    from music_assistant_models.auth import User
    from music_assistant_models.config_entries import ProviderConfig

try:
    from music_assistant.controllers.webserver.helpers.auth_middleware import (
        get_current_user,
    )
except ImportError:

    def get_current_user() -> User | None:
        """Minimal-development fallback; real MA supplies the context-local user."""
        return None


def _load_ma_has_scope() -> Callable[[User, Scope], bool] | None:
    """Load MA's scope helper while retaining compatibility with older releases."""
    try:
        from music_assistant.controllers.webserver.helpers.auth_middleware import (  # noqa: PLC0415
            has_scope,
        )
    except ImportError:
        return None
    return has_scope  # type: ignore[no-any-return, unused-ignore]


_ma_has_scope = _load_ma_has_scope()


def scope_allowed(user: User, required_scope: str) -> bool:
    """Use MA scope checks when available; otherwise apply a narrow role fallback."""
    if not getattr(user, "enabled", False):
        return False
    raw_role = getattr(user, "role", None)
    if isinstance(raw_role, UserRole):
        role = raw_role
    else:
        role_value = getattr(raw_role, "value", raw_role)
        if not isinstance(role_value, str):
            return False
        try:
            role = UserRole(role_value)
        except TypeError, ValueError:
            return False
    if _ma_has_scope is not None:
        try:
            return bool(_ma_has_scope(user, Scope(required_scope)))
        except AttributeError, TypeError, ValueError:
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
    return user  # type: ignore[no-any-return, unused-ignore]
