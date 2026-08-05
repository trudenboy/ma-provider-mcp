"""Independent risk, permission, annotation and confirmation policy."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastmcp.exceptions import ToolError
from music_assistant_models.constants import SECURE_STRING_SUBSTITUTE
from music_assistant_models.enums import ConfigEntryType

from .config_io.secret_handler import gate_secret_writes
from .tags import Tag

if TYPE_CHECKING:
    from .command_profiles import CommandProfile

type ResultProjector = Callable[[Any], Any]


class DynamicRisk(StrEnum):
    """Provider-side risk classes for dynamically discovered commands."""

    READ = "read"
    CONTROL = "control"
    WRITE = "write"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class DynamicPolicy:
    """Independent exposure switches for the four dynamic risk classes."""

    read: bool = True
    control: bool = False
    write: bool = False
    system: bool = False

    def allows(self, risk: DynamicRisk) -> bool:
        """Return whether a risk class is enabled."""
        return bool(getattr(self, risk.value))


class Confirmation(StrEnum):
    """Confirmation behavior applied immediately before command execution."""

    NEVER = "never"
    CONFIGURED = "configured"
    ALWAYS = "always"


@dataclass(frozen=True, slots=True)
class CommandDecision:
    """Resolved policy for one canonical command."""

    risk: DynamicRisk
    annotations: Mapping[str, bool]
    required_tags: frozenset[str] = frozenset()
    confirmation: Confirmation = Confirmation.NEVER
    preflight: str | None = None
    alternative_tags: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class FamilyPolicy:
    """Permission tags and optional risk behavior for a command prefix."""

    prefix: str
    tags: Mapping[str, Tag]
    risk: DynamicRisk | None = None
    readonly: bool = False


_READ_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
_CONTROL_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": False,
}
_DESTRUCTIVE_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": False,
    "openWorldHint": False,
}
_SYSTEM_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": False,
    "openWorldHint": False,
}
_DESTRUCTIVE_VERBS = frozenset({"clear", "delete", "remove", "reset", "revoke"})
_SAFE_UNSCOPED_COMMANDS = frozenset({"info", "translations/locales"})
_SYSTEM_PREFIXES = frozenset({"audio_analysis", "auth", "dashboard", "logging", "tasks"})


def _family(
    prefix: str,
    *,
    read: Tag | None = None,
    control: Tag | None = None,
    write: Tag | None = None,
    delete: Tag | None = None,
    risk: DynamicRisk | None = None,
    readonly: bool = False,
) -> FamilyPolicy:
    """Build one compact family-policy declaration."""
    tags = {
        operation: tag
        for operation, tag in (
            ("read", read),
            ("control", control),
            ("write", write),
            ("delete", delete),
        )
        if tag is not None
    }
    return FamilyPolicy(prefix, tags, risk=risk, readonly=readonly)


FAMILY_TAGS = (
    _family(
        "music/playlists/",
        read=Tag.QUERY_LIBRARY,
        write=Tag.EDIT_PLAYLISTS,
        delete=Tag.DELETE_PLAYLISTS,
    ),
    _family(
        "music/favorites/",
        read=Tag.QUERY_LIBRARY,
        write=Tag.EDIT_FAVORITES,
        delete=Tag.DELETE_FAVORITES,
    ),
    _family(
        "music/",
        read=Tag.QUERY_LIBRARY,
        control=Tag.CONTROL_MEDIA,
        write=Tag.EDIT_LIBRARY,
        delete=Tag.DELETE_LIBRARY,
    ),
    _family("players/cmd/volume", control=Tag.CONTROL_VOLUME),
    _family("players/cmd/", control=Tag.CONTROL_PLAYERS),
    _family("players/", read=Tag.QUERY_PLAYERS),
    _family(
        "player_queues/",
        read=Tag.QUERY_QUEUE,
        control=Tag.EDIT_QUEUE,
        write=Tag.EDIT_QUEUE,
        delete=Tag.DELETE_QUEUE,
    ),
    _family("metadata/", read=Tag.QUERY_METADATA),
    _family(
        "config/providers/",
        read=Tag.CONFIG_READ,
        write=Tag.CONFIG_WRITE_PROVIDER,
    ),
    _family("config/core/", read=Tag.CONFIG_READ, write=Tag.CONFIG_WRITE_CORE),
    _family(
        "config/players/",
        read=Tag.CONFIG_READ,
        write=Tag.CONFIG_WRITE_PLAYER,
    ),
    _family(
        "diagnostics/",
        read=Tag.DEBUG_INSPECT,
        risk=DynamicRisk.SYSTEM,
        readonly=True,
    ),
    _family("providers", read=Tag.DEBUG_PROVIDERS),
)


def _readonly_system(tag: Tag) -> CommandDecision:
    """Return a read-only command guarded by the system risk gate."""
    return CommandDecision(
        DynamicRisk.SYSTEM,
        _READ_ANNOTATIONS,
        frozenset({str(tag)}),
        Confirmation.ALWAYS,
    )


def _destructive_write(tag: Tag) -> CommandDecision:
    """Return an always-confirmed destructive write decision."""
    return CommandDecision(
        DynamicRisk.WRITE,
        _DESTRUCTIVE_ANNOTATIONS,
        frozenset({str(tag)}),
        Confirmation.ALWAYS,
    )


EXACT_POLICIES: dict[str, CommandDecision] = {
    "player_queues/delete_item": _destructive_write(Tag.DELETE_QUEUE),
    "player_queues/clear": _destructive_write(Tag.DELETE_QUEUE),
    "fastmcp/queue/remove_items_safe": _destructive_write(Tag.DELETE_QUEUE),
    "config/providers/reload": _destructive_write(Tag.CONFIG_WRITE_PROVIDER),
    "config/flows/submit": CommandDecision(
        DynamicRisk.WRITE,
        _CONTROL_ANNOTATIONS,
        frozenset(),
        Confirmation.CONFIGURED,
        "config_flow_submit",
        frozenset({str(Tag.CONFIG_WRITE_PROVIDER), str(Tag.CONFIG_WRITE_PLAYER)}),
    ),
    "fastmcp/debug/tail_log": _readonly_system(Tag.DEBUG_LOGS),
    "fastmcp/debug/log_stats": _readonly_system(Tag.DEBUG_LOGS),
    "fastmcp/debug/recent_events": _readonly_system(Tag.DEBUG_EVENTS),
    "fastmcp/debug/event_buffer_stats": _readonly_system(Tag.DEBUG_EVENTS),
    "fastmcp/debug/health": _readonly_system(Tag.DEBUG_PROVIDERS),
    "fastmcp/debug/routes": _readonly_system(Tag.DEBUG_PROVIDERS),
    "fastmcp/debug/packages": _readonly_system(Tag.DEBUG_PROVIDERS),
}


def resolve_command_policy(
    command: str, scope: Any, profile: CommandProfile | None
) -> CommandDecision:
    """
    Resolve risk, behavior hints and permission gates for a command.

    :param command: Canonical Music Assistant command.
    :param scope: Live MA required-scope value or enum member.
    :param profile: Optional ergonomic command profile.
    """
    if exact := EXACT_POLICIES.get(command):
        return exact

    family = _matching_family(command)
    operation = _operation(command, scope, profile, family)
    risk = family.risk if family is not None and family.risk is not None else _risk(operation)
    destructive = operation == "delete"
    annotations = dict(
        _READ_ANNOTATIONS
        if family is not None and family.readonly
        else _annotations(risk, destructive=destructive)
    )
    if profile is not None:
        annotations.update(profile.annotations)
    required_tags = _required_tags(family, operation)
    confirmation = (
        Confirmation.ALWAYS
        if risk is DynamicRisk.SYSTEM
        else Confirmation.CONFIGURED
        if risk is DynamicRisk.WRITE
        else Confirmation.NEVER
    )
    preflight = (
        "config_secret_read"
        if command
        in {
            "config/providers/get_value",
            "config/core/get_value",
            "config/players/get_value",
        }
        else "config_secret_write"
        if command
        in {
            "config/providers/save",
            "config/core/save",
            "config/players/save",
        }
        else None
    )
    return CommandDecision(
        risk,
        annotations,
        required_tags,
        confirmation,
        preflight,
    )


async def preflight_command(
    mass: Any,
    decision: CommandDecision,
    arguments: Mapping[str, Any],
    allowed_tags: set[str],
) -> ResultProjector | None:
    """
    Enforce request-dependent guards before confirmation and execution.

    :param mass: Running Music Assistant instance.
    :param decision: Resolved command policy.
    :param arguments: Strictly parsed command arguments.
    :param allowed_tags: Current provider permission tags.
    """
    if decision.preflight == "config_secret_read":
        return await _config_value_projector(mass, arguments)
    if decision.preflight == "config_secret_write":
        values = arguments.get("values")
        if not isinstance(values, Mapping):
            return None
        getter_name, target = _config_entries_target(arguments)
        entries = getattr(mass.config, getter_name)(target)
        if inspect.isawaitable(entries):
            entries = await entries
        gate_secret_writes(
            entries,
            values,
            secret_tag_enabled=str(Tag.CONFIG_WRITE_SECRET) in allowed_tags,
        )
    elif decision.preflight == "config_flow_submit":
        await _preflight_setup_flow_submit(mass, arguments, allowed_tags)
    return None


def command_tags_visible(decision: CommandDecision, allowed_tags: set[str]) -> bool:
    """Return whether a command's fixed and any-of tag requirements are visible."""
    required = decision.required_tags
    alternatives = decision.alternative_tags
    return required.issubset(allowed_tags) and (
        not alternatives or bool(alternatives & allowed_tags)
    )


def _matching_family(command: str) -> FamilyPolicy | None:
    """Return the longest matching family policy."""
    matches = (family for family in FAMILY_TAGS if command.startswith(family.prefix))
    return max(matches, key=lambda family: len(family.prefix), default=None)


def _operation(
    command: str,
    scope: Any,
    profile: CommandProfile | None,
    family: FamilyPolicy | None,
) -> str:
    """Resolve the operation column independently from MCP annotations."""
    parts = command.casefold().replace("-", "_").split("/")
    words = {word for part in parts for word in part.split("_")}
    if words & _DESTRUCTIVE_VERBS:
        return "delete"
    if parts[0] in _SYSTEM_PREFIXES:
        return "system"
    if profile is not None and profile.risk_override is not None:
        return profile.risk_override
    scope_operation = _scope_operation(scope)
    if scope_operation is not None:
        return scope_operation
    if family is not None and len(family.tags) == 1:
        return next(iter(family.tags))
    if command in _SAFE_UNSCOPED_COMMANDS:
        return "read"
    return "system"


def _scope_operation(scope: Any) -> str | None:
    """Map current MA scope metadata to an operation column."""
    value = str(getattr(scope, "value", scope) or "").casefold()
    if not value:
        return None
    if value.startswith("system."):
        return "system"
    if value.endswith(".control"):
        return "control"
    if value.endswith((".write", ".manage")):
        return "write"
    if value.endswith(".read"):
        return "read"
    return None


def _risk(operation: str) -> DynamicRisk:
    """Map an operation column to its independent runtime gate."""
    if operation == "read":
        return DynamicRisk.READ
    if operation == "control":
        return DynamicRisk.CONTROL
    if operation in {"write", "delete"}:
        return DynamicRisk.WRITE
    return DynamicRisk.SYSTEM


def _annotations(risk: DynamicRisk, *, destructive: bool) -> Mapping[str, bool]:
    """Return default behavior annotations without changing risk."""
    if destructive:
        return _DESTRUCTIVE_ANNOTATIONS
    if risk is DynamicRisk.READ:
        return _READ_ANNOTATIONS
    if risk in {DynamicRisk.CONTROL, DynamicRisk.WRITE}:
        return _CONTROL_ANNOTATIONS
    return _SYSTEM_ANNOTATIONS


def _required_tags(family: FamilyPolicy | None, operation: str) -> frozenset[str]:
    """Select the family permission for the resolved operation."""
    if family is None:
        return frozenset()
    tag = family.tags.get(operation)
    if tag is None and operation == "delete":
        tag = family.tags.get("write")
    return frozenset({str(tag)}) if tag is not None else frozenset()


def _config_entries_target(arguments: Mapping[str, Any]) -> tuple[str, str]:
    """Resolve the live config-entry getter and target identifier."""
    if "provider_domain" in arguments:
        target = arguments.get("instance_id") or arguments["provider_domain"]
        return "get_provider_config_entries", str(target)
    if "domain" in arguments:
        return "get_core_config_entries", str(arguments["domain"])
    if "player_id" in arguments:
        return "get_player_config_entries", str(arguments["player_id"])
    raise ValueError("Config save arguments do not identify a target")


async def _config_value_projector(
    mass: Any,
    arguments: Mapping[str, Any],
) -> ResultProjector | None:
    """Classify one live config value and mask it when its schema is secure."""
    key = arguments.get("key")
    if not isinstance(key, str) or not key:
        raise ToolError("Unable to classify config value")
    try:
        if isinstance(instance_id := arguments.get("instance_id"), str) and instance_id:
            entries = mass.config.get_provider_config_entries(instance_id)
        elif isinstance(domain := arguments.get("domain"), str) and domain:
            entries = mass.config.get_core_config_entries(domain)
        elif isinstance(player_id := arguments.get("player_id"), str) and player_id:
            entries = mass.config.get_player_config_entries(player_id)
        else:
            raise ValueError("Config value arguments do not identify a target")
        if inspect.isawaitable(entries):
            entries = await entries
        entry = next((entry for entry in entries if entry.key == key), None)
    except Exception as exc:
        raise ToolError("Unable to classify config value") from exc
    if entry is None:
        raise ToolError("Unable to classify config value")
    if entry.type is not ConfigEntryType.SECURE_STRING:
        return None
    return lambda result: None if result is None else SECURE_STRING_SUBSTITUTE


async def _preflight_setup_flow_submit(
    mass: Any,
    arguments: Mapping[str, Any],
    allowed_tags: set[str],
) -> None:
    """Authorize one live setup-flow submission and gate its secure fields."""
    flow_id = arguments.get("flow_id")
    values = arguments.get("values")
    if not isinstance(flow_id, str) or not flow_id or not isinstance(values, Mapping):
        raise ToolError("Invalid setup flow submission")
    get_scope = getattr(mass.config, "get_setup_flow_required_scope", None)
    get_flow = getattr(mass.config, "get_setup_flow", None)
    if not callable(get_scope) or not callable(get_flow):
        raise ToolError("Unable to authorize setup flow submission")
    scope = get_scope(flow_id)
    if inspect.isawaitable(scope):
        scope = await scope
    required_tag = _setup_flow_write_tag(scope)
    if required_tag is None:
        raise ToolError("Unknown setup flow or unsupported setup flow scope")
    if str(required_tag) not in allowed_tags:
        raise ToolError(f"Setup flow requires {required_tag} tag")
    try:
        step = get_flow(flow_id)
        if inspect.isawaitable(step):
            step = await step
    except Exception as exc:
        raise ToolError("Unable to inspect setup flow") from exc
    entries = getattr(step, "entries", None)
    if not isinstance(entries, list | tuple):
        raise ToolError("Malformed setup flow step")
    gate_secret_writes(
        entries,
        values,
        secret_tag_enabled=str(Tag.CONFIG_WRITE_SECRET) in allowed_tags,
    )


def _setup_flow_write_tag(scope: Any) -> Tag | None:
    """Map a current MA setup-flow scope to its one config write tag."""
    value = str(getattr(scope, "value", scope) or "").casefold()
    if value == "config.providers.write":
        return Tag.CONFIG_WRITE_PROVIDER
    if value == "config.players.write":
        return Tag.CONFIG_WRITE_PLAYER
    return None
