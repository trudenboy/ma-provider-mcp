"""
MCP Server provider — main PluginProvider implementation.

The provider is a thin lifecycle wrapper over :class:`MCPServerRuntime` from
``server.py``. ``handle_async_init`` constructs the runtime and starts it;
``unload`` shuts it down; ``update_config`` either hot-swaps the tag-filter
middleware (for permission-only changes) or restarts the runtime.
"""

from __future__ import annotations

import logging
import re
from contextlib import suppress
from typing import TYPE_CHECKING

from music_assistant_models.config_entries import ConfigEntry
from music_assistant_models.enums import ConfigEntryType

from music_assistant.models.plugin import PluginProvider

from .constants import is_hot_swappable_key

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
        from .config import build_config_entries, current_user_mcp_tokens  # noqa: PLC0415
        from .constants import (  # noqa: PLC0415
            CONF_MANUAL_TOKEN_IDS,
            CONF_MOUNT_PATH,
            DEFAULT_MOUNT_PATH,
        )

        tokens = await current_user_mcp_tokens(self.mass)
        return build_config_entries(
            self.mass,
            str(self.get_config_value(CONF_MOUNT_PATH, DEFAULT_MOUNT_PATH)),
            tokens=tokens,
            manual_token_ids=self.get_config_value(CONF_MANUAL_TOKEN_IDS, []) or (),
            stored_value_provider=self._raw_policy_value,
        )

    async def handle_config_action(self, action: str) -> tuple[ConfigEntry, ...] | None:
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
            raw_policy_value_provider=self._raw_policy_value,
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
        self._persist_policy_suffix_index(config, changed_keys)
        if self._commands is not None:
            self._commands.update_config(config)
        if self._runtime is None:
            if self._commands is not None:
                await self._start_runtime(config)
            return
        normalized_keys = {k.removeprefix("values/") for k in changed_keys}
        if all(is_hot_swappable_key(key) for key in normalized_keys):
            await self._runtime.apply_permission_change(config, normalized_keys)
        else:
            await self._runtime.stop()
            self._runtime = None
            await self._start_runtime(config)

    async def _start_runtime(self, config: ProviderConfig) -> None:
        """Create and start a runtime, leaving no failed instance attached."""
        from .server import MCPServerRuntime  # noqa: PLC0415

        if self._commands is not None:
            self._commands.update_config(config, active_token_ids=frozenset())
        runtime = MCPServerRuntime(
            self.mass,
            config,
            self.logger,
            policy_change_callback=self._apply_policy_token_ids,
        )
        resolve_policy = getattr(
            runtime,
            "resolve_request_policy",
            getattr(runtime, "resolve_policy", None),
        )
        if self._commands is not None and callable(resolve_policy):
            self._commands.set_policy_provider(resolve_policy)
            self._commands.set_audit_client_id_provider(runtime.audit_client_id)
        self._runtime = runtime
        try:
            await runtime.start()
        except BaseException:
            self._runtime = None
            with suppress(BaseException):
                await runtime.stop()
            raise

    def _apply_policy_token_ids(self, token_ids: frozenset[str]) -> None:
        """Refresh event retention when authenticated token identities change."""
        if self._commands is not None:
            self._commands.update_config(self.config, active_token_ids=token_ids)

    def _raw_policy_value(self, key: str) -> object:
        """Read one preserved policy value through MA's sanctioned raw API."""
        instance_id = str(getattr(getattr(self, "config", None), "instance_id", ""))
        config_controller = getattr(self.mass, "config", None)
        getter = getattr(config_controller, "get_raw_provider_config_value", None)
        if not instance_id or not callable(getter):
            return None
        return getter(instance_id, key, None)

    def _persist_policy_suffix_index(
        self,
        config: ProviderConfig,
        changed_keys: set[str],
    ) -> None:
        """Persist non-reversible suffixes for newly rendered token policy rows."""
        from .constants import CONF_POLICY_TOKEN_SUFFIXES  # noqa: PLC0415

        suffixes = {
            match.group(1)
            for key in changed_keys
            if (match := re.search(r"([0-9a-f]{64})$", key.removeprefix("values/")))
        }
        if not suffixes:
            return
        current = config.get_value(CONF_POLICY_TOKEN_SUFFIXES, [])
        if isinstance(current, list | tuple | set | frozenset):
            suffixes.update(
                str(value) for value in current if re.fullmatch(r"[0-9a-f]{64}", str(value))
            )
        ordered = sorted(suffixes)
        entry = getattr(config, "values", {}).get(CONF_POLICY_TOKEN_SUFFIXES)
        if entry is not None:
            entry.value = ordered
        config_controller = getattr(self.mass, "config", None)
        setter = getattr(config_controller, "set_raw_provider_config_value", None)
        instance_id = str(getattr(config, "instance_id", ""))
        if callable(setter) and instance_id:
            setter(
                instance_id,
                CONF_POLICY_TOKEN_SUFFIXES,
                ordered,
                immediate=True,
            )
