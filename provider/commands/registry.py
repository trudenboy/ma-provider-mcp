"""Registration compatibility and lifecycle for native MA API commands."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from music_assistant_models.auth import Scope

from provider.debug.event_buffer import EventBuffer
from provider.tags import Tag, enabled_tags

from . import debug, queue
from .authorization import authorize_extension

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ProviderConfig


@dataclass(frozen=True, slots=True)
class ProviderCommand:
    """One provider command with its MA scope and provider-permission tag."""

    command: str
    handler: Callable[..., Any]
    required_scope: str
    required_tag: str


def _scope(value: str) -> Scope:
    """Build the MA Scope representation while keeping compatibility centralized."""
    return Scope(value)


def _register(mass: Any, definition: ProviderCommand) -> Callable[[], None]:
    """Register on old and new MA releases, retaining an unregister callback."""
    supported = inspect.signature(mass.register_api_command).parameters
    options: dict[str, Any] = {"authenticated": True}
    if "required_scope" in supported:
        options["required_scope"] = _scope(definition.required_scope)
    return mass.register_api_command(definition.command, definition.handler, **options)


class ProviderCommandSet:
    """Own and register the provider's minimal native MA command surface."""

    def __init__(self, mass: Any, config: ProviderConfig) -> None:
        """Bind MA state and its currently active provider configuration."""
        self._mass = mass
        self._config = config
        self._buffer = EventBuffer(mass, capacity=500) if hasattr(mass, "subscribe") else None
        self._unregister: list[Callable[[], None]] = []

    def update_config(self, config: ProviderConfig) -> None:
        """Make existing handler closures observe the new provider configuration."""
        self._config = config
        if self._unregister and self._buffer is not None:
            if Tag.DEBUG_EVENTS in enabled_tags(config):
                self._buffer.start()
            else:
                self._buffer.stop()

    def start(self) -> None:
        """Register each command, restoring the previous state on partial failure."""
        if self._unregister:
            return
        definitions = self._definitions()
        registered: list[Callable[[], None]] = []
        try:
            for definition in definitions:
                registered.append(_register(self._mass, definition))
        except Exception:
            for unregister in reversed(registered):
                unregister()
            raise
        self._unregister = registered
        if self._buffer is not None and Tag.DEBUG_EVENTS in enabled_tags(self._config):
            self._buffer.start()

    def stop(self) -> None:
        """Unregister in reverse order and detach the event subscriber once."""
        if not self._unregister:
            return
        callbacks, self._unregister = self._unregister, []
        try:
            for unregister in reversed(callbacks):
                unregister()
        finally:
            if self._buffer is not None:
                self._buffer.stop()

    def _guard(self, scope: str, tag: Tag) -> None:
        authorize_extension(
            self._config,
            required_scope=scope,
            required_tag=str(tag),
        )

    def _definitions(self) -> tuple[ProviderCommand, ...]:
        async def remove_items_safe(queue_id: str, item_ids: list[str]) -> Any:
            self._guard("queues.control", Tag.DELETE_QUEUE)
            return await queue.remove_items_safe(self._mass, queue_id, item_ids)

        async def tail_log(**kwargs: Any) -> Any:
            self._guard("system.read", Tag.DEBUG_LOGS)
            return await debug.tail_log(self._mass, **kwargs)

        async def log_stats(**kwargs: Any) -> Any:
            self._guard("system.read", Tag.DEBUG_LOGS)
            return await debug.log_stats(self._mass, **kwargs)

        async def recent_events(**kwargs: Any) -> Any:
            self._guard("system.read", Tag.DEBUG_EVENTS)
            return await debug.recent_events(self._buffer, **kwargs)

        async def event_buffer_stats() -> Any:
            self._guard("system.read", Tag.DEBUG_EVENTS)
            return await debug.event_buffer_stats(self._buffer)

        async def health() -> Any:
            self._guard("system.read", Tag.DEBUG_PROVIDERS)
            return await debug.health(
                self._mass,
                buffer=self._buffer,
                logs_enabled=Tag.DEBUG_LOGS in enabled_tags(self._config),
            )

        async def routes() -> Any:
            self._guard("system.read", Tag.DEBUG_PROVIDERS)
            return await debug.routes(self._mass)

        async def packages() -> Any:
            self._guard("system.read", Tag.DEBUG_PROVIDERS)
            return await debug.packages()

        return (
            ProviderCommand(
                "fastmcp/queue/remove_items_safe",
                remove_items_safe,
                "queues.control",
                str(Tag.DELETE_QUEUE),
            ),
            ProviderCommand("fastmcp/debug/tail_log", tail_log, "system.read", str(Tag.DEBUG_LOGS)),
            ProviderCommand(
                "fastmcp/debug/log_stats", log_stats, "system.read", str(Tag.DEBUG_LOGS)
            ),
            ProviderCommand(
                "fastmcp/debug/recent_events", recent_events, "system.read", str(Tag.DEBUG_EVENTS)
            ),
            ProviderCommand(
                "fastmcp/debug/event_buffer_stats",
                event_buffer_stats,
                "system.read",
                str(Tag.DEBUG_EVENTS),
            ),
            ProviderCommand(
                "fastmcp/debug/health", health, "system.read", str(Tag.DEBUG_PROVIDERS)
            ),
            ProviderCommand(
                "fastmcp/debug/routes", routes, "system.read", str(Tag.DEBUG_PROVIDERS)
            ),
            ProviderCommand(
                "fastmcp/debug/packages", packages, "system.read", str(Tag.DEBUG_PROVIDERS)
            ),
        )
