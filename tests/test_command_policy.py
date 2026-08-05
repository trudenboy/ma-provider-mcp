"""Command policy and config preflight contract tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastmcp.exceptions import ToolError
from music_assistant_models.config_entries import ConfigEntry
from music_assistant_models.constants import SECURE_STRING_SUBSTITUTE
from music_assistant_models.enums import ConfigEntryType

from provider.command_policy import (
    CommandDecision,
    Confirmation,
    DynamicRisk,
    command_tags_visible,
    preflight_command,
    resolve_command_policy,
)
from provider.command_profiles import CommandProfile
from provider.tags import Tag


@pytest.mark.parametrize("command", ["player_queues/delete_item", "player_queues/clear"])
def test_direct_queue_deletes_are_confirmed_destructive_writes(command: str) -> None:
    """Direct queue deletion cannot inherit the queue-control policy."""
    decision = resolve_command_policy(command, "queues.control", profile=None)
    assert decision.risk is DynamicRisk.WRITE
    assert decision.confirmation is Confirmation.ALWAYS
    assert decision.annotations == {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    }


def test_system_health_is_still_read_only() -> None:
    """System sensitivity does not make diagnostic behavior destructive."""
    decision = resolve_command_policy("fastmcp/debug/health", "system.read", profile=None)
    assert decision.risk is DynamicRisk.SYSTEM
    assert decision.annotations["readOnlyHint"] is True
    assert decision.annotations["destructiveHint"] is False
    assert decision.annotations["idempotentHint"] is True


def test_unknown_command_fails_into_system_gate() -> None:
    """Unknown unscoped commands fail closed behind the system gate."""
    decision = resolve_command_policy("future/new_command", None, None)
    assert decision.risk is DynamicRisk.SYSTEM


def test_exact_policy_precedes_profile_and_family_policy() -> None:
    """An ergonomic profile cannot weaken an exact destructive override."""
    profile = CommandProfile(
        command="player_queues/clear",
        risk_override="control",
        annotations={"destructiveHint": False},
    )
    decision = resolve_command_policy("player_queues/clear", "queues.control", profile)
    assert decision.risk is DynamicRisk.WRITE
    assert decision.required_tags == frozenset({str(Tag.DELETE_QUEUE)})
    assert decision.confirmation is Confirmation.ALWAYS


def test_safe_queue_extension_keeps_always_destructive_policy() -> None:
    """The deferred safe-removal extension already has its mandatory policy."""
    decision = resolve_command_policy("fastmcp/queue/remove_items_safe", "queues.control", None)
    assert decision.risk is DynamicRisk.WRITE
    assert decision.confirmation is Confirmation.ALWAYS
    assert decision.required_tags == frozenset({str(Tag.DELETE_QUEUE)})
    assert decision.annotations["destructiveHint"] is True


def test_player_queue_write_operations_require_edit_queue_permission() -> None:
    """Saving a queue is an edit, not an untagged write-scope escape hatch."""
    decision = resolve_command_policy("player_queues/save_as_playlist", "library.write", None)

    assert decision.required_tags == frozenset({str(Tag.EDIT_QUEUE)})


def test_fixed_tags_and_alternative_tags_use_distinct_permission_semantics() -> None:
    """Fixed requirements are conjunctive while setup-flow categories are any-of."""
    decision = CommandDecision(
        DynamicRisk.WRITE,
        {},
        frozenset({"fixed:first", "fixed:second"}),
        alternative_tags=frozenset({"category:provider", "category:player"}),
    )

    assert command_tags_visible(
        decision,
        {"fixed:first", "fixed:second", "category:player"},
    )
    assert not command_tags_visible(decision, {"fixed:first", "category:player"})
    assert not command_tags_visible(decision, {"fixed:first", "fixed:second"})


def test_provider_reload_is_confirmed_destructive_config_write() -> None:
    """Native provider reload cannot bypass the provider-write permission or confirmation."""
    decision = resolve_command_policy("config/providers/reload", "config.providers.write", None)

    assert decision.risk is DynamicRisk.WRITE
    assert decision.required_tags == frozenset({str(Tag.CONFIG_WRITE_PROVIDER)})
    assert decision.confirmation is Confirmation.ALWAYS
    assert decision.annotations == {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    }


@pytest.mark.parametrize(
    ("command", "scope", "risk"),
    [
        ("future/read", "library.read", DynamicRisk.READ),
        ("future/control", "players.control", DynamicRisk.CONTROL),
        ("future/write", "library.write", DynamicRisk.WRITE),
        ("future/system", "system.read", DynamicRisk.SYSTEM),
    ],
)
def test_ma_scope_is_used_when_no_command_policy_matches(
    command: str, scope: str, risk: DynamicRisk
) -> None:
    """Current MA scope metadata remains the fallback classifier."""
    assert resolve_command_policy(command, scope, None).risk is risk


@pytest.mark.parametrize(
    ("command", "scope", "tag"),
    [
        ("music/search", "library.read", Tag.QUERY_LIBRARY),
        ("music/playlists/create_playlist", "library.write", Tag.EDIT_PLAYLISTS),
        (
            "music/playlists/remove_playlist_tracks",
            "library.write",
            Tag.DELETE_PLAYLISTS,
        ),
        ("players/cmd/volume_set", "players.control", Tag.CONTROL_VOLUME),
        ("player_queues/items", "queues.read", Tag.QUERY_QUEUE),
        ("config/core/save", "config.core.write", Tag.CONFIG_WRITE_CORE),
    ],
)
def test_longest_family_policy_assigns_required_permission_tag(
    command: str, scope: str, tag: Tag
) -> None:
    """Family policy selects the narrow permission toggle for each operation."""
    decision = resolve_command_policy(command, scope, None)
    assert decision.required_tags == frozenset({str(tag)})


def _config_mass() -> SimpleNamespace:
    entries = [
        ConfigEntry(key="name", type=ConfigEntryType.STRING, label="Name"),
        ConfigEntry(key="token", type=ConfigEntryType.SECURE_STRING, label="Token"),
    ]
    config = SimpleNamespace(
        get_provider_config_entries=AsyncMock(return_value=entries),
        get_core_config_entries=AsyncMock(return_value=entries),
        get_player_config_entries=AsyncMock(return_value=entries),
    )
    return SimpleNamespace(config=config)


def _flow_mass(
    scope: str | None,
    entries: list[ConfigEntry],
) -> SimpleNamespace:
    """Build the current MA setup-flow API surface needed by request preflight."""
    config = SimpleNamespace(
        get_setup_flow_required_scope=lambda _flow_id: scope,
        get_setup_flow=AsyncMock(return_value=SimpleNamespace(entries=entries)),
    )
    return SimpleNamespace(config=config)


async def test_secure_config_preflight_requires_independent_secret_tag() -> None:
    """Generic provider config-write permission cannot authorize a secret value."""
    mass = _config_mass()
    decision = resolve_command_policy("config/providers/save", "config.providers.write", None)
    arguments = {
        "provider_domain": "demo",
        "instance_id": "demo--1",
        "values": {"token": "secret"},
    }
    with pytest.raises(ToolError, match="config:write:secret"):
        await preflight_command(
            mass,
            decision,
            arguments,
            {str(Tag.CONFIG_WRITE_PROVIDER)},
        )


async def test_nonsecret_config_preflight_needs_no_secret_tag() -> None:
    """Ordinary config writes remain authorized by their existing family toggle."""
    mass = _config_mass()
    decision = resolve_command_policy("config/providers/save", "config.providers.write", None)
    await preflight_command(
        mass,
        decision,
        {
            "provider_domain": "demo",
            "instance_id": "demo--1",
            "values": {"name": "Kitchen"},
        },
        {str(Tag.CONFIG_WRITE_PROVIDER)},
    )


@pytest.mark.parametrize(
    ("command", "arguments", "getter_name", "getter_arguments"),
    [
        (
            "config/providers/get_value",
            {"instance_id": "demo--1", "key": "token"},
            "get_provider_config_entries",
            ("demo",),
        ),
        (
            "config/core/get_value",
            {"domain": "webserver", "key": "token"},
            "get_core_config_entries",
            ("webserver",),
        ),
        (
            "config/players/get_value",
            {"player_id": "kitchen", "key": "token"},
            "get_player_config_entries",
            ("kitchen",),
        ),
    ],
)
async def test_secure_config_value_reads_return_masking_projector(
    command: str,
    arguments: dict[str, str],
    getter_name: str,
    getter_arguments: tuple[str, ...],
) -> None:
    """Every config value family masks keys declared as SECURE_STRING."""
    entries = [ConfigEntry(key="token", type=ConfigEntryType.SECURE_STRING, label="Token")]
    config = SimpleNamespace(
        get_provider_config=AsyncMock(return_value=SimpleNamespace(domain="demo")),
        get_provider_config_entries=AsyncMock(return_value=entries),
        get_core_config_entries=AsyncMock(return_value=entries),
        get_player_config_entries=AsyncMock(return_value=entries),
    )
    decision = resolve_command_policy(command, "config.read", None)

    projector = await preflight_command(
        SimpleNamespace(config=config),
        decision,
        arguments,
        {str(Tag.CONFIG_READ)},
    )

    assert callable(projector)
    assert projector("raw-encrypted-token") == SECURE_STRING_SUBSTITUTE
    assert projector(None) is None
    getter = getattr(config, getter_name)
    if command == "config/providers/get_value":
        getter.assert_awaited_once_with(*getter_arguments, instance_id="demo--1")
    else:
        getter.assert_awaited_once_with(*getter_arguments)


async def test_nonsecure_config_value_read_needs_no_projector() -> None:
    """Ordinary config values pass through unchanged."""
    config = SimpleNamespace(
        get_core_config_entries=AsyncMock(
            return_value=[ConfigEntry(key="name", type=ConfigEntryType.STRING, label="Name")]
        )
    )
    decision = resolve_command_policy("config/core/get_value", "config.core.read", None)

    projector = await preflight_command(
        SimpleNamespace(config=config),
        decision,
        {"domain": "webserver", "key": "name"},
        {str(Tag.CONFIG_READ)},
    )

    assert projector is None


async def test_unknown_config_value_key_fails_closed() -> None:
    """An unrecognized key cannot bypass secure-value classification."""
    config = SimpleNamespace(get_core_config_entries=AsyncMock(return_value=[]))
    decision = resolve_command_policy("config/core/get_value", "config.core.read", None)

    with pytest.raises(ToolError, match="Unable to classify config value"):
        await preflight_command(
            SimpleNamespace(config=config),
            decision,
            {"domain": "webserver", "key": "future-secret"},
            {str(Tag.CONFIG_READ)},
        )


async def test_config_value_schema_failure_fails_closed() -> None:
    """Schema lookup failures cannot expose an unclassified value."""
    config = SimpleNamespace(
        get_player_config_entries=AsyncMock(side_effect=RuntimeError("player disappeared"))
    )
    decision = resolve_command_policy("config/players/get_value", "config.players.read", None)

    with pytest.raises(ToolError, match="Unable to classify config value"):
        await preflight_command(
            SimpleNamespace(config=config),
            decision,
            {"player_id": "missing", "key": "token"},
            {str(Tag.CONFIG_READ)},
        )


async def test_secret_config_preflight_accepts_explicit_secret_tag() -> None:
    """The dedicated secret toggle authorizes secure config values."""
    mass = _config_mass()
    decision = resolve_command_policy("config/providers/save", "config.providers.write", None)
    await preflight_command(
        mass,
        decision,
        {
            "provider_domain": "demo",
            "instance_id": "demo--1",
            "values": {"token": "secret"},
        },
        {str(Tag.CONFIG_WRITE_PROVIDER), str(Tag.CONFIG_WRITE_SECRET)},
    )


async def test_provider_setup_flow_secret_requires_secret_tag() -> None:
    """A provider flow cannot submit a secure value without the orthogonal tag."""
    mass = _flow_mass(
        "config.providers.write",
        [ConfigEntry(key="token", type=ConfigEntryType.SECURE_STRING, label="Token")],
    )
    decision = resolve_command_policy("config/flows/submit", None, None)

    with pytest.raises(ToolError, match="config:write:secret"):
        await preflight_command(
            mass,
            decision,
            {"flow_id": "provider-flow", "values": {"token": "secret"}},
            {str(Tag.CONFIG_WRITE_PROVIDER)},
        )


async def test_provider_setup_flow_secret_accepts_provider_and_secret_tags() -> None:
    """A provider flow accepts secure values with both required permissions."""
    mass = _flow_mass(
        "config.providers.write",
        [ConfigEntry(key="token", type=ConfigEntryType.SECURE_STRING, label="Token")],
    )
    decision = resolve_command_policy("config/flows/submit", None, None)

    await preflight_command(
        mass,
        decision,
        {"flow_id": "provider-flow", "values": {"token": "secret"}},
        {str(Tag.CONFIG_WRITE_PROVIDER), str(Tag.CONFIG_WRITE_SECRET)},
    )


async def test_player_setup_flow_allows_player_only_nonsecret_write() -> None:
    """A player flow needs its own category tag, not the provider category."""
    mass = _flow_mass(
        "config.players.write",
        [ConfigEntry(key="name", type=ConfigEntryType.STRING, label="Name")],
    )
    decision = resolve_command_policy("config/flows/submit", None, None)

    await preflight_command(
        mass,
        decision,
        {"flow_id": "player-flow", "values": {"name": "Kitchen"}},
        {str(Tag.CONFIG_WRITE_PLAYER)},
    )


async def test_setup_flow_rejects_the_wrong_config_category() -> None:
    """Provider flow submission cannot use the player-write permission."""
    mass = _flow_mass(
        "config.providers.write",
        [ConfigEntry(key="name", type=ConfigEntryType.STRING, label="Name")],
    )
    decision = resolve_command_policy("config/flows/submit", None, None)

    with pytest.raises(ToolError, match="config:write:provider"):
        await preflight_command(
            mass,
            decision,
            {"flow_id": "provider-flow", "values": {"name": "Kitchen"}},
            {str(Tag.CONFIG_WRITE_PLAYER)},
        )


async def test_unknown_setup_flow_fails_closed() -> None:
    """A missing flow scope cannot become an unguarded config write."""
    mass = _flow_mass(None, [])
    decision = resolve_command_policy("config/flows/submit", None, None)

    with pytest.raises(ToolError, match="setup flow"):
        await preflight_command(
            mass,
            decision,
            {"flow_id": "missing-flow", "values": {}},
            {str(Tag.CONFIG_WRITE_PROVIDER), str(Tag.CONFIG_WRITE_PLAYER)},
        )
