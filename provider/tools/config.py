"""FastMCP sub-server for configuration view/edit tools.

Spec: ``specs/inprogress/0006-config-read-write.md``.

Read tools proxy ``mass.config.get_*`` (secrets masked by MA's
``__post_serialize__``). Write tools (later registration functions)
delegate to MA's atomic ``save_*_config``. All tools are gated by
off-by-default ConfigEntries; with no tag enabled the namespace is
invisible via ``TagFilterMiddleware``.
"""
# ruff: noqa: TID252  -- relative imports are the canonical MA-provider pattern.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from ..models import (
    ConfigEntryDump,
    ConfigEntryList,
    ConfigTarget,
    ConfigTargetList,
    ConfigValueDump,
    CoreConfigDump,
    DSPConfigDump,
    PlayerConfigDump,
    ProviderConfigDump,
)
from ..tags import Tag
from ._common import TIMEOUT_FAST

if TYPE_CHECKING:
    from music_assistant_models.config_entries import (
        ConfigEntry,
        CoreConfig,
        PlayerConfig,
        ProviderConfig,
    )

    from music_assistant.mass import MusicAssistant


LOGGER = logging.getLogger("music_assistant.providers.fastmcp_server.config")

_PAYLOAD_CAP_BYTES = 256 * 1024
_SAVE_PAYLOAD_CAP_BYTES = 64 * 1024


def _readonly(title: str) -> ToolAnnotations:
    return ToolAnnotations(
        title=title,
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )


def _values_from_raw(raw: dict[str, Any]) -> tuple[list[ConfigValueDump], bool]:
    """Build ConfigValueDump list from a Config.to_dict() raw dict (secrets pre-masked)."""
    out: list[ConfigValueDump] = []
    truncated = False
    running = 0
    for key, entry in raw.get("values", {}).items():
        value = entry.get("value")
        etype = entry.get("type", "unknown")
        size = len(str(value)) + len(str(key)) + len(str(etype)) + 16
        if running + size > _PAYLOAD_CAP_BYTES:
            truncated = True
            break
        running += size
        out.append(ConfigValueDump(key=str(key), type=str(etype), value=value))
    return out, truncated


def _entry_dump(entry: ConfigEntry, current: Any) -> ConfigEntryDump:
    """Map a ConfigEntry + current value to ConfigEntryDump."""
    opts = [o.value for o in entry.options] if entry.options else None
    return ConfigEntryDump(
        key=entry.key,
        type=entry.type.value,
        label=entry.label,
        default_value=entry.default_value,
        required=entry.required,
        description=entry.description,
        options=opts,
        range=entry.range,
        advanced=getattr(entry, "advanced", False),
        hidden=entry.hidden,
        requires_reload=entry.requires_reload,
        depends_on=entry.depends_on,
        action=entry.action,
        current_value=current,
    )


async def _resolve_entries(
    mass: MusicAssistant, target_type: str, target_id: str, action: str | None
) -> tuple[list[ConfigEntry], dict[str, Any]]:
    """Fetch ConfigEntry list + current values dict for a target.

    :param mass: MusicAssistant instance.
    :param target_type: "provider" | "core" | "player".
    :param target_id: The target identifier.
    :param action: Optional action key (provider only).
    """
    cfg: ProviderConfig | CoreConfig | PlayerConfig
    if target_type == "provider":
        cfg = await mass.config.get_provider_config(target_id)
        entries = await mass.config.get_provider_config_entries(
            getattr(cfg, "domain", target_id), instance_id=target_id, action=action
        )
    elif target_type == "core":
        cfg = await mass.config.get_core_config(target_id)
        entries = await mass.config.get_core_config_entries(target_id)
    elif target_type == "player":
        cfg = await mass.config.get_player_config(target_id)
        entries = await mass.config.get_player_config_entries(target_id)
    else:
        raise ToolError(f"unknown target_type {target_type!r}")
    current = {k: getattr(v, "value", None) for k, v in getattr(cfg, "values", {}).items()}
    return list(entries), current


def build_config_server(
    mass: MusicAssistant,
    *,
    require_confirmation: bool = True,  # noqa: ARG001
    secret_writes_enabled: bool = True,  # noqa: ARG001
) -> FastMCP:
    """Build the ``config`` sub-server.

    :param mass: MusicAssistant instance.
    :param require_confirmation: When True (default), every write elicits
        confirmation before mutating.
    :param secret_writes_enabled: When True, SECURE_STRING values may be
        written; when False, such writes are rejected (the orthogonal
        config:write:secret value-gate). Read tools ignore this.
    """
    sub = FastMCP(name="config")
    _register_read_tools(sub, mass)
    # write registrations land in later tasks
    return sub


def _register_read_tools(sub: FastMCP, mass: MusicAssistant) -> None:
    @sub.tool(
        tags={Tag.CONFIG_READ},
        annotations=_readonly("List configurable targets"),
        timeout=TIMEOUT_FAST,
    )
    async def list_targets() -> ConfigTargetList:
        """List every configurable provider, core controller, and player.

        See also: config_get_provider / config_get_core / config_get_player
        for a single target's values, config_get_entries for the editable
        schema.
        """
        providers = [
            ConfigTarget(
                target_type="provider",
                target_id=getattr(c, "instance_id", ""),
                domain=getattr(c, "domain", ""),
                name=getattr(c, "name", "") or getattr(c, "domain", ""),
                enabled=bool(getattr(c, "enabled", True)),
            )
            for c in await mass.config.get_provider_configs()
        ]
        core = [
            ConfigTarget(
                target_type="core",
                target_id=getattr(c, "domain", ""),
                domain=getattr(c, "domain", ""),
                name=getattr(c, "domain", ""),
                enabled=True,
            )
            for c in await mass.config.get_core_configs()
        ]
        players = [
            ConfigTarget(
                target_type="player",
                target_id=getattr(c, "player_id", ""),
                domain=getattr(c, "provider", ""),
                name=getattr(c, "name", "") or getattr(c, "player_id", ""),
                enabled=bool(getattr(c, "enabled", True)),
            )
            for c in await mass.config.get_player_configs()
        ]
        return ConfigTargetList(providers=providers, core=core, players=players)

    @sub.tool(
        tags={Tag.CONFIG_READ},
        annotations=_readonly("Get provider config"),
        timeout=TIMEOUT_FAST,
    )
    async def get_provider(instance_id: str) -> ProviderConfigDump:
        """Return a provider's stored config values (SECURE_STRING masked).

        See also: config_get_entries for editable schema, config_set_provider_value
        to change one value, config_save_provider for bulk.

        :param instance_id: The provider instance identifier.
        """
        try:
            cfg = await mass.config.get_provider_config(instance_id)
        except Exception as exc:
            raise ToolError(f"provider instance_id={instance_id!r} not found") from exc
        values, truncated = _values_from_raw(cfg.to_dict())
        return ProviderConfigDump(
            instance_id=instance_id,
            domain=getattr(cfg, "domain", ""),
            values=values,
            truncated=truncated,
        )

    @sub.tool(
        tags={Tag.CONFIG_READ},
        annotations=_readonly("Get core config"),
        timeout=TIMEOUT_FAST,
    )
    async def get_core(domain: str) -> CoreConfigDump:
        """Return a core controller's stored config values (SECURE_STRING masked).

        See also: config_set_core_value / config_save_core to change them.

        :param domain: Core controller domain (e.g. "webserver", "streams").
        """
        try:
            cfg = await mass.config.get_core_config(domain)
        except Exception as exc:
            raise ToolError(f"core domain={domain!r} not found") from exc
        values, truncated = _values_from_raw(cfg.to_dict())
        return CoreConfigDump(domain=domain, values=values, truncated=truncated)

    @sub.tool(
        tags={Tag.CONFIG_READ},
        annotations=_readonly("Get player config"),
        timeout=TIMEOUT_FAST,
    )
    async def get_player(player_id: str) -> PlayerConfigDump:
        """Return a player's stored config values (SECURE_STRING masked).

        See also: config_set_player_value to change one, config_get_dsp for EQ/DSP.

        :param player_id: The player identifier.
        """
        try:
            cfg = await mass.config.get_player_config(player_id)
        except Exception as exc:
            raise ToolError(f"player_id={player_id!r} not found") from exc
        values, truncated = _values_from_raw(cfg.to_dict())
        return PlayerConfigDump(
            player_id=player_id,
            provider=getattr(cfg, "provider", ""),
            values=values,
            truncated=truncated,
        )

    @sub.tool(
        tags={Tag.CONFIG_READ},
        annotations=_readonly("Get editable config entries"),
        timeout=TIMEOUT_FAST,
    )
    async def get_entries(
        target_type: str, target_id: str, action: str | None = None
    ) -> ConfigEntryList:
        """Return the editable ConfigEntry schema for a target.

        See also: config_set_*_value to write a key. ``action`` activates an
        action-driven entry set (e.g. a provider's QR-login flow).

        :param target_type: "provider" | "core" | "player".
        :param target_id: The target identifier (instance_id / domain / player_id).
        :param action: Optional action key to activate dynamic entries.
        """
        entries, current = await _resolve_entries(mass, target_type, target_id, action)
        dumps = [_entry_dump(e, current.get(e.key)) for e in entries]
        return ConfigEntryList(
            target_type=target_type, target_id=target_id, entries=dumps, truncated=False
        )

    @sub.tool(
        tags={Tag.CONFIG_READ},
        annotations=_readonly("Get player DSP config"),
        timeout=TIMEOUT_FAST,
    )
    async def get_dsp(player_id: str) -> DSPConfigDump:
        """Return a player's DSP configuration (enabled, gains, filter chain).

        See also: config_save_dsp to change it.

        :param player_id: The player identifier.
        """
        try:
            await mass.config.get_player_config(player_id)
        except Exception as exc:
            raise ToolError(f"player_id={player_id!r} not found") from exc
        dsp = mass.config.get_player_dsp_config(player_id)
        raw = dsp.to_dict()
        return DSPConfigDump(
            player_id=player_id,
            enabled=bool(raw.get("enabled", False)),
            input_gain=float(raw.get("input_gain", 0.0)),
            output_gain=float(raw.get("output_gain", 0.0)),
            filters=list(raw.get("filters", [])),
        )
