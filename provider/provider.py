"""
MCP Server provider — main PluginProvider implementation.

The provider is a thin lifecycle wrapper over :class:`MCPServerRuntime` from
``server.py``. ``handle_async_init`` constructs the runtime and starts it;
``unload`` shuts it down; ``update_config`` either hot-swaps the tag-filter
middleware (for permission-only changes) or restarts the runtime.
"""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import TYPE_CHECKING

from music_assistant_models.config_entries import ConfigEntry
from music_assistant_models.enums import ConfigEntryType

from music_assistant.models.plugin import PluginProvider

from .constants import HOT_SWAPPABLE_KEYS

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ProviderConfig

    from .commands import ProviderCommandSet
    from .server import MCPServerRuntime


LOGGER = logging.getLogger(__name__)


class MCPServerProvider(PluginProvider):  # type: ignore[misc, unused-ignore]
    """Music Assistant plugin provider wrapping an MCP server runtime."""

    _runtime: MCPServerRuntime | None = None
    _commands: ProviderCommandSet | None = None

    async def get_config_entries(self) -> tuple[ConfigEntry, ...]:
        """Return Config entries to configure this provider."""
        from .config import build_config_entries  # noqa: PLC0415
        from .constants import CONF_MOUNT_PATH, DEFAULT_MOUNT_PATH  # noqa: PLC0415

        return build_config_entries(
            self.mass, str(self.get_config_value(CONF_MOUNT_PATH, DEFAULT_MOUNT_PATH))
        )

    async def handle_config_action(self, action: str) -> tuple[ConfigEntry, ...]:
        """Handle a one-shot config action button press and re-render the entries."""
        if action == "open_connect":
            from ._init_helpers import _dispatch_open_connect  # noqa: PLC0415
            from .constants import CONF_CONNECT_EXTERNAL_URL, CONF_MOUNT_PATH  # noqa: PLC0415

            url = await _dispatch_open_connect(
                self.mass,
                {
                    CONF_MOUNT_PATH: self.get_config_value(CONF_MOUNT_PATH),
                    CONF_CONNECT_EXTERNAL_URL: self.get_config_value(CONF_CONNECT_EXTERNAL_URL),
                },
            )
            entries = await self.get_config_entries()
            if url is None:
                return entries
            # a URL entry in an invoke_action response is opened one-shot by the frontend
            return (
                *entries,
                ConfigEntry(
                    key="connect_wizard_url",
                    type=ConfigEntryType.URL,
                    value=url,
                ),
            )
        return await super().handle_config_action(action)

    async def handle_async_init(self) -> None:
        """Register MA commands, then build and start the FastMCP runtime."""
        from .commands import ProviderCommandSet  # noqa: PLC0415

        self._commands = ProviderCommandSet(
            self.mass,
            config_provider=lambda: self.config,
            diagnostics_provider=lambda: (
                self._runtime.dynamic_diagnostics()
                if self._runtime is not None
                else {"available": False, "last_error": "MCP runtime not started"}
            ),
        )
        try:
            self._commands.start()
            await self._start_runtime(self.config)
        except BaseException:
            try:
                if self._runtime is not None:
                    with suppress(BaseException):
                        await self._runtime.stop()
            finally:
                try:
                    if self._commands is not None:
                        with suppress(BaseException):
                            self._commands.stop()
                finally:
                    self._runtime = None
                    self._commands = None
            raise

    async def loaded_in_mass(self) -> None:
        """Log the public URL once everything is wired up."""
        if self._runtime is not None:
            self.logger.info("MCP server mounted at %s", self._runtime.public_url)

    async def unload(self, is_removed: bool = False) -> None:
        """Stop the MCP endpoint before withdrawing its MA commands."""
        try:
            if self._runtime is not None:
                await self._runtime.stop()
        finally:
            self._runtime = None
            try:
                if self._commands is not None:
                    self._commands.stop()
            finally:
                self._commands = None

    async def update_config(self, config: ProviderConfig, changed_keys: set[str]) -> None:
        """Apply config changes — hot-swap when possible, restart otherwise."""
        self.config = config
        if self._commands is not None:
            self._commands.update_config(config)
        if self._runtime is None:
            if self._commands is not None:
                await self._start_runtime(config)
            return
        normalized_keys = {k.removeprefix("values/") for k in changed_keys}
        if normalized_keys.issubset(HOT_SWAPPABLE_KEYS):
            await self._runtime.apply_permission_change(config, normalized_keys)
        else:
            await self._runtime.stop()
            self._runtime = None
            await self._start_runtime(config)

    async def _start_runtime(self, config: ProviderConfig) -> None:
        """Create and start a runtime, leaving no failed instance attached."""
        from .server import MCPServerRuntime  # noqa: PLC0415

        runtime = MCPServerRuntime(self.mass, config, self.logger)
        self._runtime = runtime
        try:
            await runtime.start()
        except BaseException:
            self._runtime = None
            with suppress(BaseException):
                await runtime.stop()
            raise
