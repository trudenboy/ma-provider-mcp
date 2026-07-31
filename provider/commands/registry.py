"""Registration compatibility and lifecycle for native MA API commands."""
# ruff: noqa: TID252 -- provider source is transplanted under the MA package.

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from music_assistant_models.auth import Scope

from ..constants import CONF_DEBUG_EVENT_BUFFER_CAPACITY
from ..debug.event_buffer import EventBuffer
from ..models import (
    EventBufferStats,
    EventSnapshot,
    HealthSummary,
    LogStatsResult,
    LogTailResult,
    PackageVersions,
    RemoveFromQueueResult,
    RouteList,
)
from ..tags import Tag, enabled_tags
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
    return cast(
        "Callable[[], None]",
        mass.register_api_command(definition.command, definition.handler, **options),
    )


class ProviderCommandSet:
    """Own and register the provider's minimal native MA command surface."""

    def __init__(
        self,
        mass: Any,
        config_provider: Callable[[], ProviderConfig] | ProviderConfig,
        diagnostics_provider: Callable[[], Mapping[str, Any]] | None = None,
    ) -> None:
        """Bind MA state and lazy providers for configuration and diagnostics."""
        self._mass = mass
        self._config_provider: Callable[[], ProviderConfig]
        if hasattr(config_provider, "get_value"):
            fixed_config = cast("ProviderConfig", config_provider)
            self._config_provider = lambda: fixed_config
        else:
            self._config_provider = config_provider
        self._current_config: ProviderConfig | None = None
        self._diagnostics_provider = diagnostics_provider
        self._buffer: EventBuffer | None = EventBuffer(
            self._mass, capacity=self._event_buffer_capacity(self._config())
        )
        self._unregister: list[Callable[[], None]] = []

    @property
    def event_buffer(self) -> EventBuffer | None:
        """Return the command-owned event buffer for the MCP debug server."""
        return self._buffer

    def update_config(self, config: ProviderConfig) -> None:
        """Make existing handler closures observe the new provider configuration."""
        self._current_config = config
        if self._unregister:
            self._configure_event_buffer(config)

    def start(self) -> None:
        """Register each command, restoring the previous state on partial failure."""
        if self._unregister:
            return
        definitions = self._definitions()
        registered: list[Callable[[], None]] = []
        try:
            for definition in definitions:
                registered.append(_register(self._mass, definition))
            self._configure_event_buffer(self._config())
        except BaseException:
            for unregister in reversed(registered):
                with suppress(BaseException):
                    unregister()
            raise
        self._unregister = registered

    def stop(self) -> None:
        """Unregister in reverse order and detach the event subscriber once."""
        if not self._unregister:
            return
        callbacks, self._unregister = self._unregister, []
        first_error: Exception | None = None
        try:
            for unregister in reversed(callbacks):
                try:
                    unregister()
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
        finally:
            if self._buffer is not None:
                try:
                    self._buffer.stop()
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
        if first_error is not None:
            raise first_error

    def _configure_event_buffer(self, config: ProviderConfig) -> None:
        """Start, stop, or resize the subscription held across MCP restarts."""
        enabled = Tag.DEBUG_EVENTS in enabled_tags(config)
        capacity = self._event_buffer_capacity(config)
        if self._buffer is None or self._buffer.stats().capacity != capacity:
            if self._buffer is not None:
                self._buffer.stop()
            self._buffer = EventBuffer(self._mass, capacity=capacity)
        if not enabled:
            self._buffer.stop()
            return
        self._buffer.start()

    @staticmethod
    def _event_buffer_capacity(config: ProviderConfig) -> int:
        """Read and clamp the configured event buffer capacity."""
        value = config.get_value(CONF_DEBUG_EVENT_BUFFER_CAPACITY)
        capacity = int(value) if isinstance(value, int | float | str) else 500
        return max(50, min(capacity, 5000))

    def _config(self) -> ProviderConfig:
        """Return the most recently applied config, or lazily read the provider state."""
        return self._current_config or self._config_provider()

    def _guard(self, scope: str, tag: Tag) -> None:
        authorize_extension(
            self._config(),
            required_scope=scope,
            required_tag=str(tag),
        )

    def _definitions(self) -> tuple[ProviderCommand, ...]:
        async def remove_items_safe(queue_id: str, item_ids: list[str]) -> RemoveFromQueueResult:
            self._guard("queues.control", Tag.DELETE_QUEUE)
            return await queue.remove_items_safe(self._mass, queue_id, item_ids)

        async def tail_log(
            lines: int = 200,
            level: str | None = None,
            component_regex: str | None = None,
            search: str | None = None,
            since_seconds: int | None = None,
            before: str | None = None,
            name: str = "musicassistant.log",
        ) -> LogTailResult:
            self._guard("system.read", Tag.DEBUG_LOGS)
            return await debug.tail_log(
                self._mass,
                lines=lines,
                level=level,
                component_regex=component_regex,
                search=search,
                since_seconds=since_seconds,
                before=before,
                name=name,
            )

        async def log_stats(
            since_seconds: int | None = None,
            name: str = "musicassistant.log",
        ) -> LogStatsResult:
            self._guard("system.read", Tag.DEBUG_LOGS)
            return await debug.log_stats(self._mass, since_seconds=since_seconds, name=name)

        async def recent_events(
            limit: int = 100,
            event_types: list[str] | None = None,
            id_filter: str | None = None,
            since_seconds: int | None = None,
        ) -> EventSnapshot:
            self._guard("system.read", Tag.DEBUG_EVENTS)
            return await debug.recent_events(
                self._buffer,
                limit=limit,
                event_types=event_types,
                id_filter=id_filter,
                since_seconds=since_seconds,
            )

        async def event_buffer_stats() -> EventBufferStats:
            self._guard("system.read", Tag.DEBUG_EVENTS)
            return await debug.event_buffer_stats(self._buffer)

        async def health() -> HealthSummary:
            self._guard("system.read", Tag.DEBUG_PROVIDERS)
            return await debug.health(
                self._mass,
                buffer=self._buffer,
                logs_enabled=Tag.DEBUG_LOGS in enabled_tags(self._config()),
                dynamic_diagnostics_provider=self._diagnostics_provider,
            )

        async def routes() -> RouteList:
            self._guard("system.read", Tag.DEBUG_PROVIDERS)
            return await debug.routes(self._mass)

        async def packages() -> PackageVersions:
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
