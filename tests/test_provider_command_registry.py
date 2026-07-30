"""Registration, authorization, and lifecycle tests for provider MA commands."""
# ruff: noqa: D102, D107, PT012

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest
from music_assistant_models.auth import Scope, User, UserRole
from music_assistant_models.errors import AuthenticationRequired, InsufficientPermissions

from provider.commands import ProviderCommandSet, authorization
from provider.commands.authorization import authorize_extension, scope_allowed
from provider.tags import Tag

COMMANDS = {
    "fastmcp/queue/remove_items_safe",
    "fastmcp/debug/tail_log",
    "fastmcp/debug/log_stats",
    "fastmcp/debug/recent_events",
    "fastmcp/debug/event_buffer_stats",
    "fastmcp/debug/health",
    "fastmcp/debug/routes",
    "fastmcp/debug/packages",
}


class CommandRegistry:
    """Small real registry surface mirroring current MA registration semantics."""

    def __init__(self, *, fail_at: int | None = None) -> None:
        self.handlers: dict[str, Callable[..., Any]] = {}
        self.options: dict[str, dict[str, Any]] = {}
        self.removed: list[str] = []
        self.fail_at = fail_at

    def register_api_command(
        self,
        command: str,
        handler: Callable[..., Any],
        authenticated: bool = True,
        required_scope: Scope | None = None,
    ) -> Callable[[], None]:
        if self.fail_at is not None and len(self.handlers) == self.fail_at:
            raise RuntimeError("registration failed")
        if command in self.handlers:
            raise RuntimeError(f"duplicate {command}")
        self.handlers[command] = handler
        self.options[command] = {
            "authenticated": authenticated,
            "required_scope": required_scope,
        }

        def unregister() -> None:
            self.handlers.pop(command, None)
            self.removed.append(command)

        return unregister


class LegacyCommandRegistry(CommandRegistry):
    """Older MA surface without the required_scope keyword."""

    def register_api_command(  # type: ignore[override]
        self,
        command: str,
        handler: Callable[..., Any],
        authenticated: bool = True,
    ) -> Callable[[], None]:
        return super().register_api_command(command, handler, authenticated)


def _config(*enabled: Tag) -> MagicMock:
    config = MagicMock()
    allowed = {str(tag) for tag in enabled}
    config.get_value.side_effect = lambda key, _default=None: any(
        str(tag) in allowed and tag.value.replace(":", "_") == key for tag in Tag
    )
    return config


def _user(role: UserRole = UserRole.ADMIN, *, enabled: bool = True) -> User:
    return User(user_id="u1", username="tester", role=role, enabled=enabled)


def test_authorization_rejects_missing_and_disabled_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every native handler requires a present, enabled MA user."""
    config = _config(Tag.DEBUG_LOGS)
    monkeypatch.setattr(authorization, "get_current_user", lambda: None)
    with pytest.raises(AuthenticationRequired, match="enabled Music Assistant user"):
        authorize_extension(config, required_scope="system.read", required_tag=str(Tag.DEBUG_LOGS))

    monkeypatch.setattr(authorization, "get_current_user", lambda: _user(enabled=False))
    with pytest.raises(AuthenticationRequired, match="enabled Music Assistant user"):
        authorize_extension(config, required_scope="system.read", required_tag=str(Tag.DEBUG_LOGS))


def test_authorization_rejects_wrong_scope_and_disabled_provider_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MA scope and provider config permissions are independent gates."""
    monkeypatch.setattr(authorization, "_ma_has_scope", None)
    monkeypatch.setattr(authorization, "get_current_user", lambda: _user(UserRole.USER))
    with pytest.raises(InsufficientPermissions, match=r"system\.read"):
        authorize_extension(
            _config(Tag.DEBUG_LOGS),
            required_scope="system.read",
            required_tag=str(Tag.DEBUG_LOGS),
        )

    monkeypatch.setattr(authorization, "get_current_user", lambda: _user())
    with pytest.raises(InsufficientPermissions, match="debug:logs"):
        authorize_extension(
            _config(),
            required_scope="system.read",
            required_tag=str(Tag.DEBUG_LOGS),
        )


def test_scope_fallback_is_role_based_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Older role-only MA builds grant only the documented minimum roles."""
    monkeypatch.setattr(authorization, "_ma_has_scope", None)
    assert scope_allowed(_user(UserRole.ADMIN), "system.read") is True
    assert scope_allowed(_user(UserRole.USER), "system.read") is False
    assert scope_allowed(_user(UserRole.USER), "queues.control") is True
    assert scope_allowed(_user(UserRole.GUEST), "queues.control") is False
    assert scope_allowed(_user(UserRole.ADMIN, enabled=False), "queues.control") is False
    assert scope_allowed(_user(UserRole.SERVICE), "future.scope") is False


def test_start_registers_exact_command_set_with_native_scopes() -> None:
    """No legacy or duplicate command leaks into MA's registry."""
    mass = CommandRegistry()
    command_set = ProviderCommandSet(mass, _config(*Tag))

    command_set.start()

    assert set(mass.handlers) == COMMANDS
    assert all(options["authenticated"] is True for options in mass.options.values())
    assert all(isinstance(options["required_scope"], Scope) for options in mass.options.values())


async def test_legacy_registration_stays_protected_inside_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing required_scope support cannot bypass current-user authorization."""
    mass = LegacyCommandRegistry()
    command_set = ProviderCommandSet(mass, _config(*Tag))
    command_set.start()
    monkeypatch.setattr(authorization, "get_current_user", lambda: None)

    with pytest.raises(AuthenticationRequired):
        awaitable = mass.handlers["fastmcp/debug/packages"]()
        await awaitable


def test_partial_start_rolls_back_in_reverse_and_can_retry() -> None:
    """A failed start leaves no duplicates and unregisters in LIFO order."""
    mass = CommandRegistry(fail_at=3)
    command_set = ProviderCommandSet(mass, _config(*Tag))

    with pytest.raises(RuntimeError, match="registration failed"):
        command_set.start()

    assert mass.handlers == {}
    assert mass.removed == [
        "fastmcp/debug/log_stats",
        "fastmcp/debug/tail_log",
        "fastmcp/queue/remove_items_safe",
    ]
    mass.fail_at = None
    command_set.start()
    assert set(mass.handlers) == COMMANDS


async def test_stop_is_idempotent_and_update_config_is_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Handlers see updated config and repeated stop never double-unregisters."""
    mass = LegacyCommandRegistry()
    command_set = ProviderCommandSet(mass, _config())
    command_set.start()
    monkeypatch.setattr(authorization, "get_current_user", lambda: _user())
    packages_handler = mass.handlers["fastmcp/debug/packages"]

    with pytest.raises(InsufficientPermissions, match="debug:providers"):
        awaitable = packages_handler()
        await awaitable

    command_set.update_config(_config(Tag.DEBUG_PROVIDERS))
    awaitable = packages_handler()
    result = await awaitable
    assert "fastmcp" in result.packages

    command_set.stop()
    command_set.stop()
    assert mass.handlers == {}
    assert len(mass.removed) == 8
