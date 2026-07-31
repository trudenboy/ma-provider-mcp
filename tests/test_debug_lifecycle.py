"""Lifecycle tests for the provider-owned debug event subscription."""

from __future__ import annotations

from unittest.mock import MagicMock

from provider.commands import ProviderCommandSet


def test_command_set_subscribes_when_debug_events_enabled(
    mock_mass: MagicMock, mock_config: MagicMock
) -> None:
    """When DEBUG_EVENTS=True, the provider command set starts the buffer."""
    mock_config.get_value.side_effect = lambda key, default=None: {
        "debug_events": True,
        "debug_event_buffer_capacity": 100,
    }.get(key, default if default is not None else False)

    commands = ProviderCommandSet(mock_mass, mock_config)
    commands.start()
    assert mock_mass.subscribe.called
    commands.stop()


def test_command_set_does_not_subscribe_when_events_disabled(
    mock_mass: MagicMock, mock_config: MagicMock
) -> None:
    """With DEBUG_EVENTS=False, no subscription is created and stop() doesn't raise."""
    mock_config.get_value.return_value = False
    commands = ProviderCommandSet(mock_mass, mock_config)
    commands.start()
    commands.stop()  # must not raise
    assert mock_mass.subscribe.called is False


def test_event_buffer_stop_is_idempotent_during_command_unload(
    mock_mass: MagicMock, mock_config: MagicMock
) -> None:
    """Double-stop must not raise."""
    mock_config.get_value.side_effect = lambda key, default=None: {
        "debug_events": True,
        "debug_event_buffer_capacity": 100,
    }.get(key, default if default is not None else False)

    commands = ProviderCommandSet(mock_mass, mock_config)
    commands.start()
    commands.stop()
    commands.stop()  # must not raise — second call is a no-op
