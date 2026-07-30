"""Lifecycle test: config sub-server is mounted with secret-writes wiring."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from provider import server
from provider.commands import ProviderCommandSet
from provider.provider import MCPServerProvider
from provider.server import MCPServerRuntime


class _LifecycleMass:
    """Small MA boundary that records provider-owned registrations and subscriptions."""

    def __init__(self, call_order: list[str] | None = None) -> None:
        self.call_order = call_order if call_order is not None else []
        self.registered: dict[str, Callable[..., Any]] = {}
        self.register_api_command = MagicMock(side_effect=self._register)
        self.subscribe = MagicMock(side_effect=self._subscribe)

    def _register(
        self, command: str, handler: Callable[..., Any], **_kwargs: Any
    ) -> Callable[[], None]:
        if command in self.registered:
            raise RuntimeError(f"duplicate {command}")
        self.registered[command] = handler

        def unregister() -> None:
            self.call_order.append("commands.stop")
            self.registered.pop(command, None)

        return unregister

    def _subscribe(self, _callback: Callable[..., Any]) -> Callable[[], None]:
        def unsubscribe() -> None:
            self.call_order.append("buffer.stop")

        return unsubscribe


def _provider(mass: Any, config: MagicMock) -> MCPServerProvider:
    """Create a provider without invoking its MA framework constructor."""
    provider = MCPServerProvider.__new__(MCPServerProvider)
    provider.mass = mass
    provider.config = config
    provider.logger = logging.getLogger("task-7-lifecycle")
    provider._runtime = None
    return provider


def _config(*, debug_events: bool = False) -> MagicMock:
    """Return only the config surface provider command registration needs."""
    config = MagicMock()
    config.get_value.side_effect = lambda key, default=None: {
        "debug_events": debug_events,
        "debug_event_buffer_capacity": 100,
    }.get(key, default)
    return config


@pytest.mark.asyncio
async def test_mcp_restart_does_not_reregister_provider_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A runtime restart retains the one provider command registry surface."""
    mass = _LifecycleMass()
    provider = _provider(mass, _config())

    class Runtime:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        def dynamic_diagnostics(self) -> dict[str, bool]:
            return {"available": True}

    monkeypatch.setattr(server, "MCPServerRuntime", Runtime)

    await provider.handle_async_init()
    commands = provider._commands
    calls_after_start = mass.register_api_command.call_count

    await provider.update_config(_config(), {"mount_path"})

    assert provider._commands is commands
    assert mass.register_api_command.call_count == calls_after_start
    assert commands is not None
    assert commands._diagnostics_provider is not None
    assert commands._diagnostics_provider() == {"available": True}
    await provider.unload()


@pytest.mark.asyncio
async def test_runtime_start_base_exception_rolls_back_provider_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupt during runtime start tears down every already-owned command."""
    call_order: list[str] = []
    mass = _LifecycleMass(call_order)
    provider = _provider(mass, _config())

    class Runtime:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        async def start(self) -> None:
            raise KeyboardInterrupt("mount interrupted")

        async def stop(self) -> None:
            call_order.append("runtime.stop")
            raise RuntimeError("teardown failed")

    monkeypatch.setattr(server, "MCPServerRuntime", Runtime)

    with pytest.raises(KeyboardInterrupt, match="mount interrupted"):
        await provider.handle_async_init()

    assert provider._runtime is None
    assert provider._commands is None
    assert mass.registered == {}
    assert call_order[0] == "runtime.stop"
    assert "commands.stop" in call_order


@pytest.mark.asyncio
async def test_unload_stops_mcp_before_unregistering_commands() -> None:
    """The endpoint is removed before its supporting MA commands disappear."""
    call_order: list[str] = []
    provider = _provider(MagicMock(), _config())
    provider._runtime = MagicMock(
        stop=AsyncMock(side_effect=lambda: call_order.append("runtime.stop"))
    )
    provider._commands = MagicMock(
        stop=MagicMock(side_effect=lambda: call_order.append("commands.stop"))
    )

    await provider.unload()

    assert call_order == ["runtime.stop", "commands.stop"]


@pytest.mark.asyncio
async def test_restart_does_not_duplicate_event_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP-only restarts preserve the command-owned event subscriber exactly once."""
    mass = _LifecycleMass()
    provider = _provider(mass, _config(debug_events=True))

    class Runtime:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

    monkeypatch.setattr(server, "MCPServerRuntime", Runtime)

    await provider.handle_async_init()
    await provider.update_config(_config(debug_events=True), {"mount_path"})

    assert mass.subscribe.call_count == 1
    await provider.unload()


@pytest.mark.asyncio
async def test_config_reaches_commands_before_runtime_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live MA commands observe the new config before the MCP runtime changes."""
    call_order: list[str] = []
    provider = _provider(MagicMock(), _config())
    provider._commands = MagicMock(
        spec=ProviderCommandSet,
        update_config=MagicMock(side_effect=lambda _config: call_order.append("commands.update")),
    )
    provider._runtime = MagicMock(
        stop=AsyncMock(side_effect=lambda: call_order.append("runtime.stop")),
    )

    class Runtime:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        async def start(self) -> None:
            call_order.append("runtime.start")

    monkeypatch.setattr("provider.server.MCPServerRuntime", Runtime)

    await provider.update_config(_config(), {"mount_path"})

    assert call_order[:2] == ["commands.update", "runtime.stop"]


def test_runtime_exposes_dynamic_diagnostics_without_adapter_leak(
    mock_mass: MagicMock, mock_config: MagicMock
) -> None:
    """Provider closures can read a plain health snapshot without reaching into runtime internals."""
    runtime = MCPServerRuntime(mock_mass, mock_config, logger=MagicMock())
    runtime._dynamic_adapter = MagicMock(diagnostics=MagicMock(return_value={"available": True}))

    assert runtime.dynamic_diagnostics() == {"available": True}


async def test_config_server_mounted_and_visible(
    mock_mass: MagicMock, mock_config: MagicMock
) -> None:
    """Config sub-server stays internal behind the permanent meta surface."""
    mock_config.get_value.side_effect = lambda key, default=None: {
        "config_read": True,
        "config_write_provider": True,
        "config_write_secret": True,
    }.get(key, default if default is not None else False)

    from provider.server import MCPServerRuntime  # noqa: PLC0415

    runtime = MCPServerRuntime(mock_mass, mock_config, logger=MagicMock())
    await runtime.start()
    try:
        from fastmcp import Client  # noqa: PLC0415

        async with Client(runtime._mcp) as client:
            names = {t.name for t in await client.list_tools()}
        assert names == {"search_tools", "get_tool_schema", "call_tool"}
    finally:
        await runtime.stop()


async def test_config_secret_flag_threaded(mock_mass: MagicMock, mock_config: MagicMock) -> None:
    """secret_writes_enabled is threaded from CONF_CONFIG_WRITE_SECRET config value."""
    # config_write_secret OFF → provider/read/write visible, but the
    # secret value-gate is closed. We assert the runtime starts cleanly
    # with the flag off (the gate behavior itself is unit-tested elsewhere).
    mock_config.get_value.side_effect = lambda key, default=None: {
        "config_read": True,
        "config_write_provider": True,
        "config_write_secret": False,
    }.get(key, default if default is not None else False)

    from provider.server import MCPServerRuntime  # noqa: PLC0415

    runtime = MCPServerRuntime(mock_mass, mock_config, logger=MagicMock())
    await runtime.start()
    try:
        from fastmcp import Client  # noqa: PLC0415

        async with Client(runtime._mcp) as client:
            names = {t.name for t in await client.list_tools()}
        assert names == {"search_tools", "get_tool_schema", "call_tool"}
    finally:
        await runtime.stop()
