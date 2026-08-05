"""Registration, authorization, and lifecycle tests for provider MA commands."""
# ruff: noqa: D102, D107, PT012

from __future__ import annotations

import inspect
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, get_type_hints
from unittest.mock import AsyncMock, MagicMock

import pytest
from music_assistant_models.auth import Scope, User, UserRole
from music_assistant_models.errors import AuthenticationRequired, InsufficientPermissions

from music_assistant.helpers.api import APICommandHandler, parse_arguments
from provider.commands import ProviderCommandSet, authorization
from provider.commands import debug as debug_commands
from provider.commands import registry as command_registry
from provider.commands.authorization import authorize_extension, scope_allowed
from provider.dynamic_signatures import compile_signature
from provider.models import (
    EventBufferStats,
    EventSnapshot,
    HealthSummary,
    LogStatsResult,
    LogTailResult,
    PackageVersions,
    RemoveFromQueueResult,
    RouteList,
)
from provider.tags import Tag

COMMAND_ORDER = (
    "fastmcp/queue/remove_items_safe",
    "fastmcp/debug/tail_log",
    "fastmcp/debug/log_stats",
    "fastmcp/debug/recent_events",
    "fastmcp/debug/event_buffer_stats",
    "fastmcp/debug/health",
    "fastmcp/debug/routes",
    "fastmcp/debug/packages",
)
COMMANDS = set(COMMAND_ORDER)


class CommandRegistry:
    """Small real registry surface mirroring current MA registration semantics."""

    def __init__(
        self,
        *,
        fail_at: int | None = None,
        subscribe_error: Exception | None = None,
    ) -> None:
        self.handlers: dict[str, Callable[..., Any]] = {}
        self.options: dict[str, dict[str, Any]] = {}
        self.removed: list[str] = []
        self.fail_at = fail_at
        self.subscribe_error = subscribe_error
        self.subscribed = 0
        self.unsubscribed = 0
        self.subscribers: list[Callable[..., Any]] = []

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

    def subscribe(self, callback: Callable[..., Any]) -> Callable[[], None]:
        """Mirror MA subscriptions, including one-shot unsubscription."""
        self.subscribed += 1
        if self.subscribe_error is not None:
            raise self.subscribe_error
        self.subscribers.append(callback)

        def unsubscribe() -> None:
            if callback in self.subscribers:
                self.subscribers.remove(callback)
                self.unsubscribed += 1

        return unsubscribe


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
    monkeypatch.setattr(authorization, "has_scope", lambda _user, _scope: False, raising=False)
    monkeypatch.setattr(authorization, "get_current_user", lambda: _user(UserRole.USER))
    with pytest.raises(InsufficientPermissions, match=r"system\.read"):
        authorize_extension(
            _config(Tag.DEBUG_LOGS),
            required_scope="system.read",
            required_tag=str(Tag.DEBUG_LOGS),
        )

    monkeypatch.setattr(authorization, "get_current_user", lambda: _user())
    monkeypatch.setattr(authorization, "has_scope", lambda _user, _scope: True, raising=False)
    with pytest.raises(InsufficientPermissions, match="debug:logs"):
        authorize_extension(
            _config(),
            required_scope="system.read",
            required_tag=str(Tag.DEBUG_LOGS),
        )


def test_scope_allowed_delegates_to_current_ma_scope_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scope decisions use MA's live helper and short-circuit disabled users."""
    checked: list[tuple[User, Scope]] = []

    def check(user: User, scope: Scope) -> bool:
        checked.append((user, scope))
        return scope is Scope.QUEUES_CONTROL

    monkeypatch.setattr(authorization, "has_scope", check, raising=False)
    user = _user(UserRole.USER)

    assert scope_allowed(user, "queues.control") is True
    assert scope_allowed(user, "system.read") is False
    assert scope_allowed(_user(UserRole.ADMIN, enabled=False), "queues.control") is False
    assert checked == [(user, Scope.QUEUES_CONTROL), (user, Scope.SYSTEM_READ)]


def test_start_registers_exact_command_set_with_native_scopes() -> None:
    """No legacy or duplicate command leaks into MA's registry."""
    mass = CommandRegistry()
    command_set = ProviderCommandSet(mass, _config(*Tag))

    command_set.start()

    assert set(mass.handlers) == COMMANDS
    assert all(options["authenticated"] is True for options in mass.options.values())
    assert all(isinstance(options["required_scope"], Scope) for options in mass.options.values())


def test_registration_uses_current_ma_contract_without_signature_reflection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Native scopes are passed directly without feature-detecting MA internals."""
    reflection = SimpleNamespace(
        signature=MagicMock(side_effect=AssertionError("signature reflection is forbidden"))
    )
    monkeypatch.setattr(command_registry, "inspect", reflection, raising=False)
    mass = CommandRegistry()

    ProviderCommandSet(mass, _config(*Tag)).start()

    assert all(options["required_scope"] is not None for options in mass.options.values())


async def test_registered_handlers_keep_native_parseable_signatures_and_result_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MA's command parser and catalog compiler retain all native command contracts."""
    mass = CommandRegistry()
    command_set = ProviderCommandSet(mass, _config(*Tag))
    command_set.start()

    expected_returns = {
        "fastmcp/queue/remove_items_safe": RemoveFromQueueResult,
        "fastmcp/debug/tail_log": LogTailResult,
        "fastmcp/debug/log_stats": LogStatsResult,
        "fastmcp/debug/recent_events": EventSnapshot,
        "fastmcp/debug/event_buffer_stats": EventBufferStats,
        "fastmcp/debug/health": HealthSummary,
        "fastmcp/debug/routes": RouteList,
        "fastmcp/debug/packages": PackageVersions,
    }
    for command, expected_return in expected_returns.items():
        handler = mass.handlers[command]
        ma_handler = APICommandHandler.parse(command, handler)
        signature = ma_handler.signature
        hints = ma_handler.type_hints
        compiled = compile_signature(signature, hints)
        assert ma_handler.target is handler
        assert hints["return"] is expected_return
        assert compiled.output_schema() is not None
        assert all(
            param.kind is not inspect.Parameter.VAR_KEYWORD
            for param in signature.parameters.values()
        )

    tail = mass.handlers["fastmcp/debug/tail_log"]
    tail_signature = inspect.signature(tail)
    tail_hints = get_type_hints(tail)
    parsed = parse_arguments(
        tail_signature,
        tail_hints,
        {"lines": 3, "level": "error", "name": "musicassistant.log"},
        strict=True,
    )
    assert parsed["lines"] == 3
    assert parsed["level"] == "error"
    assert parsed["name"] == "musicassistant.log"
    assert set(compile_signature(tail_signature, tail_hints).input_schema["properties"]) >= {
        "lines",
        "level",
        "component_regex",
        "search",
        "since_seconds",
        "before",
        "name",
    }

    log_stats_handler = APICommandHandler.parse(
        "fastmcp/debug/log_stats", mass.handlers["fastmcp/debug/log_stats"]
    )
    assert (
        parse_arguments(
            log_stats_handler.signature,
            log_stats_handler.type_hints,
            {"since_seconds": 60, "name": "musicassistant.log.1"},
            strict=True,
        )["since_seconds"]
        == 60
    )
    assert set(
        compile_signature(log_stats_handler.signature, log_stats_handler.type_hints).input_schema[
            "properties"
        ]
    ) == {"since_seconds", "name"}

    recent = mass.handlers["fastmcp/debug/recent_events"]
    recent_signature = inspect.signature(recent)
    recent_hints = get_type_hints(recent)
    parsed_recent = parse_arguments(
        recent_signature,
        recent_hints,
        {"limit": 2, "event_types": ["player_updated"], "id_filter": "kitchen"},
        strict=True,
    )
    assert parsed_recent["limit"] == 2
    assert parsed_recent["event_types"] == ["player_updated"]
    assert parsed_recent["id_filter"] == "kitchen"

    monkeypatch.setattr(authorization, "has_scope", lambda _user, _scope: True, raising=False)
    monkeypatch.setattr(authorization, "get_current_user", lambda: _user())
    plain_tail = AsyncMock(
        return_value=LogTailResult(log_path="x", lines=[], bytes_scanned=0, truncated=False)
    )
    monkeypatch.setattr(debug_commands, "tail_log", plain_tail)
    result = await tail(**parsed)
    assert result.log_path == "x"
    plain_tail.assert_awaited_once_with(mass, **parsed)


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


def test_subscription_failure_rolls_back_commands_and_allows_retry() -> None:
    """Event capture is part of the same all-or-nothing startup transaction."""
    mass = CommandRegistry(subscribe_error=RuntimeError("event bus offline"))
    command_set = ProviderCommandSet(mass, _config(*Tag))

    with pytest.raises(RuntimeError, match="event bus offline"):
        command_set.start()

    assert mass.handlers == {}
    assert mass.removed == list(reversed(COMMAND_ORDER))
    mass.subscribe_error = None
    command_set.start()
    assert set(mass.handlers) == COMMANDS
    assert mass.subscribed == 2


async def test_stop_is_idempotent_and_update_config_is_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Handlers see updated config and repeated stop never double-unregisters."""
    mass = CommandRegistry()
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


def test_event_buffer_survives_event_hot_toggles_and_resizes_before_restart() -> None:
    """The command owner retains one buffer until a non-hot capacity change replaces it."""
    mass = CommandRegistry()
    disabled = _config()
    command_set = ProviderCommandSet(mass, disabled)

    command_set.start()
    buffer = command_set.event_buffer
    assert buffer is not None
    assert mass.subscribed == 0

    command_set.update_config(_config(Tag.DEBUG_EVENTS))
    assert command_set.event_buffer is buffer
    assert mass.subscribed == 1

    command_set.update_config(_config())
    assert command_set.event_buffer is buffer
    assert mass.unsubscribed == 1

    command_set.update_config(_config(Tag.DEBUG_EVENTS))
    assert command_set.event_buffer is buffer
    assert mass.subscribed == 2

    resized = _config(Tag.DEBUG_EVENTS)
    resized.get_value.side_effect = lambda key, default=None: {
        "debug_events": True,
        "debug_event_buffer_capacity": 250,
    }.get(key, default)
    command_set.update_config(resized)

    assert command_set.event_buffer is not buffer
    assert command_set.event_buffer is not None
    assert command_set.event_buffer.stats().capacity == 250
    assert mass.unsubscribed == 2
    assert mass.subscribed == 3

    command_set.stop()
    assert mass.unsubscribed == 3


def test_stop_attempts_all_unregistrations_then_raises_first_error() -> None:
    """A bad unregister callback cannot leave later commands registered forever."""
    mass = CommandRegistry()
    command_set = ProviderCommandSet(mass, _config(*Tag))
    command_set.start()
    original = command_set._unregister[-2]

    def broken_unregister() -> None:
        original()
        raise RuntimeError("unregister failed")

    command_set._unregister[-2] = broken_unregister
    with pytest.raises(RuntimeError, match="unregister failed"):
        command_set.stop()

    assert mass.handlers == {}
    assert mass.unsubscribed == 1
    command_set.stop()
