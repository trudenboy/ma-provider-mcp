"""Native dynamic configuration and fail-closed v2 policy parsing."""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from music_assistant_models.config_entries import ConfigEntry, ConfigValueOption
from music_assistant_models.enums import ConfigEntryType

from .constants import (
    CONF_CONNECT_EXTERNAL_URL,
    CONF_DEBUG_EVENT_BUFFER_CAPACITY,
    CONF_DEFAULT_POLICY,
    CONF_ENFORCE_AUDIENCE,
    CONF_EXTRA_ALLOWED_ORIGINS,
    CONF_MANUAL_TOKEN_IDS,
    CONF_MOUNT_PATH,
    CONF_REQUIRE_AUTH,
    CONF_RES_LIBRARY,
    CONF_RES_PLAYER,
    CONF_RES_PROMPTS,
    CONF_TRUST_FORWARDED_PROTO,
    DEFAULT_MOUNT_PATH,
    POLICY_MODE_KEY_PREFIX,
    TOKEN_POLICY_KEY_PREFIX,
)
from .policy import PolicyMode, PolicyProfile, PolicyResolver, PolicySelection
from .tags import Tag

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ProviderConfig

    from music_assistant.mass import MusicAssistant

LOGGER = logging.getLogger(__name__)

INHERIT_POLICY = "Inherit"
MCP_TOKEN_NAME_PREFIX = "MCP — "


@dataclass(frozen=True, slots=True)
class PolicyToken:
    """Non-secret token metadata used to render one override group."""

    token_id: str
    name: str


def policy_token_suffix(token_id: str) -> str:
    """Return a deterministic non-reversible suffix for one MA token ID."""
    return hashlib.sha256(token_id.encode()).hexdigest()


def token_policy_key(token_id: str) -> str:
    """Return the selector key for one token ID without embedding that ID."""
    return f"{TOKEN_POLICY_KEY_PREFIX}{policy_token_suffix(token_id)}"


def policy_mode_key(capability: str | Tag, token_id: str | None = None) -> str:
    """Return one default or token-specific Custom capability key."""
    capability_fragment = str(capability).replace(":", "_")
    if token_id is None:
        return f"{POLICY_MODE_KEY_PREFIX}{capability_fragment}"
    return f"{TOKEN_POLICY_KEY_PREFIX}{capability_fragment}_{policy_token_suffix(token_id)}"


async def current_user_mcp_tokens(mass: MusicAssistant) -> tuple[PolicyToken, ...]:
    """Discover exact-prefix MCP tokens belonging to MA's current settings user."""
    try:
        current_user = await mass.webserver.auth.get_current_user_info()
        tokens = await mass.webserver.auth.get_user_tokens()
    except Exception:
        LOGGER.warning("Unable to discover current-user MCP tokens")
        return ()
    user_id = str(getattr(current_user, "user_id", ""))
    discovered = {
        str(token.token_id): PolicyToken(str(token.token_id), str(token.name))
        for token in tokens
        if str(getattr(token, "user_id", "")) == user_id
        and str(getattr(token, "name", "")).startswith(MCP_TOKEN_NAME_PREFIX)
        and str(getattr(token, "token_id", ""))
    }
    return tuple(sorted(discovered.values(), key=lambda token: (token.name, token.token_id)))


def build_policy_resolver(
    config: ProviderConfig,
    *,
    active_token_ids: Iterable[str] = (),
) -> PolicyResolver:
    """Compile raw provider values into an immutable fail-closed policy resolver."""
    default = _parse_selection(config, token_id=None, allow_inherit=False)
    token_ids = set(_manual_token_ids(config.get_value(CONF_MANUAL_TOKEN_IDS)))
    token_ids.update(str(token_id) for token_id in active_token_ids if str(token_id))
    overrides = {
        token_id: _parse_selection(config, token_id=token_id, allow_inherit=True)
        for token_id in sorted(token_ids)
    }
    return PolicyResolver(default=default, overrides=overrides)


def policy_event_buffer_enabled(
    config: ProviderConfig,
    *,
    active_token_ids: Iterable[str] = (),
) -> bool:
    """
    Return whether any configured policy can expose debug events.

    Event retention is a conservative boolean decision, not request
    authorization. Scan hashed token selectors already present in raw provider
    config so activation never depends on which settings user happens to be
    current during startup.
    """
    resolver = build_policy_resolver(config, active_token_ids=active_token_ids)
    snapshots = [resolver.resolve(None)]
    snapshots.extend(resolver.resolve(token_id) for token_id in resolver.overrides)
    if any(snapshot.mode(Tag.DEBUG_EVENTS) is not PolicyMode.DENY for snapshot in snapshots):
        return True

    raw = _raw_config_values(config)
    selector = re.compile(rf"^{re.escape(TOKEN_POLICY_KEY_PREFIX)}([0-9a-f]{{64}})$")
    for key, value in raw.items():
        match = selector.fullmatch(key)
        if match is None:
            continue
        if value == INHERIT_POLICY:
            continue
        try:
            profile = PolicyProfile(str(value))
        except ValueError:
            continue
        if profile is PolicyProfile.CUSTOM:
            mode_key = f"{TOKEN_POLICY_KEY_PREFIX}debug_events_{match.group(1)}"
            try:
                mode = PolicyMode(str(raw.get(mode_key, PolicyMode.DENY)))
            except ValueError:
                mode = PolicyMode.DENY
        else:
            from .policy import policy_snapshot  # noqa: PLC0415

            mode = policy_snapshot(profile).mode(Tag.DEBUG_EVENTS)
        if mode is not PolicyMode.DENY:
            return True
    return False


def _raw_config_values(config: ProviderConfig) -> dict[str, Any]:
    """Return context-free provider values without decrypting or user discovery."""
    entries = getattr(config, "values", None)
    if isinstance(entries, Mapping):
        return {str(key): getattr(entry, "value", entry) for key, entry in entries.items()}
    test_values = getattr(config, "_values", None)
    if isinstance(test_values, Mapping):
        return {str(key): value for key, value in test_values.items()}
    return {}


def build_config_entries(
    mass: MusicAssistant,
    mount_path: str,
    *,
    tokens: Iterable[Any] = (),
    manual_token_ids: Iterable[str] = (),
) -> tuple[ConfigEntry, ...]:
    """Return endpoint, resource, prompt, and dynamic v2 policy entries."""
    base_url = mass.webserver.base_url.rstrip("/")
    mount_path = "/" + mount_path.strip("/")
    info_label = (
        f"MCP endpoint: {base_url}{mount_path}\n"
        "Create tokens in Profile → Long-lived access tokens."
    )
    entries: list[ConfigEntry] = [
        ConfigEntry(
            key="info_label",
            type=ConfigEntryType.LABEL,
            label=info_label,
            category="server",
            required=False,
        ),
        ConfigEntry(
            key="open_connect",
            type=ConfigEntryType.ACTION,
            action="open_connect",
            required=False,
        ),
        ConfigEntry(
            key=CONF_REQUIRE_AUTH,
            type=ConfigEntryType.BOOLEAN,
            default_value=True,
            category="server",
            required=False,
        ),
        ConfigEntry(
            key=CONF_MOUNT_PATH,
            type=ConfigEntryType.STRING,
            default_value=DEFAULT_MOUNT_PATH,
            category="server",
            advanced=True,
            required=False,
        ),
        ConfigEntry(
            key=CONF_ENFORCE_AUDIENCE,
            type=ConfigEntryType.BOOLEAN,
            default_value=False,
            category="server",
            advanced=True,
            required=False,
        ),
        ConfigEntry(
            key=CONF_EXTRA_ALLOWED_ORIGINS,
            type=ConfigEntryType.STRING,
            default_value="",
            category="server",
            advanced=True,
            required=False,
        ),
        ConfigEntry(
            key=CONF_CONNECT_EXTERNAL_URL,
            type=ConfigEntryType.STRING,
            default_value="",
            category="server",
            advanced=True,
            required=False,
        ),
        ConfigEntry(
            key=CONF_TRUST_FORWARDED_PROTO,
            type=ConfigEntryType.BOOLEAN,
            default_value=False,
            category="server",
            advanced=True,
            required=False,
        ),
        _policy_selector(CONF_DEFAULT_POLICY, None, allow_inherit=False),
    ]
    entries.extend(_custom_matrix(CONF_DEFAULT_POLICY))
    entries.append(
        ConfigEntry(
            key=CONF_MANUAL_TOKEN_IDS,
            type=ConfigEntryType.STRING,
            default_value=[],
            multi_value=True,
            category="policy",
            required=False,
            advanced=True,
        )
    )

    rendered: dict[str, PolicyToken] = {}
    for token in tokens:
        token_id = str(getattr(token, "token_id", "")).strip()
        if token_id:
            rendered[token_id] = PolicyToken(token_id, str(getattr(token, "name", token_id)))
    for token_id in _manual_token_ids(manual_token_ids):
        rendered.setdefault(token_id, PolicyToken(token_id, f"Manual MCP token ·{token_id[-8:]}"))
    for token in sorted(rendered.values(), key=lambda value: (value.name, value.token_id)):
        selector = token_policy_key(token.token_id)
        entries.append(_policy_selector(selector, token.name, allow_inherit=True))
        entries.extend(_custom_matrix(selector, token.token_id))

    entries.extend(
        (
            _bool(CONF_RES_LIBRARY, True, "mcp_resources"),
            _bool(CONF_RES_PLAYER, True, "mcp_resources"),
            _bool(CONF_RES_PROMPTS, True, "mcp_resources"),
            ConfigEntry(
                key=CONF_DEBUG_EVENT_BUFFER_CAPACITY,
                type=ConfigEntryType.INTEGER,
                default_value=500,
                range=(50, 5000),
                category="debug",
                required=False,
            ),
        )
    )
    return tuple(entries)


def _bool(key: str, default: bool, category: str) -> ConfigEntry:
    """Build one optional boolean provider entry."""
    return ConfigEntry(
        key=key,
        type=ConfigEntryType.BOOLEAN,
        default_value=default,
        category=category,
        required=False,
    )


def _policy_selector(key: str, label: str | None, *, allow_inherit: bool) -> ConfigEntry:
    """Build one profile selector."""
    values = ([INHERIT_POLICY] if allow_inherit else []) + [
        profile.value for profile in PolicyProfile
    ]
    return ConfigEntry(
        key=key,
        type=ConfigEntryType.STRING,
        default_value=INHERIT_POLICY if allow_inherit else PolicyProfile.READ_ONLY.value,
        options=[ConfigValueOption(value=value, title=value) for value in values],
        label=label,
        category="policy",
        required=False,
    )


def _custom_matrix(selector_key: str, token_id: str | None = None) -> list[ConfigEntry]:
    """Build the conditional 26-capability Custom matrix for one selector."""
    options = [ConfigValueOption(value=mode.value, title=mode.value.title()) for mode in PolicyMode]
    return [
        ConfigEntry(
            key=policy_mode_key(capability, token_id),
            type=ConfigEntryType.STRING,
            default_value=PolicyMode.DENY.value,
            options=options,
            depends_on=selector_key,
            depends_on_value=PolicyProfile.CUSTOM.value,
            label=str(capability),
            category="policy",
            required=False,
        )
        for capability in Tag
    ]


def _parse_selection(
    config: ProviderConfig,
    *,
    token_id: str | None,
    allow_inherit: bool,
) -> PolicySelection:
    """Parse one selector and fail closed on every malformed raw value."""
    key = CONF_DEFAULT_POLICY if token_id is None else token_policy_key(token_id)
    raw = config.get_value(key)
    if raw is None:
        return (
            PolicySelection.inherit()
            if allow_inherit
            else PolicySelection.profile(PolicyProfile.READ_ONLY)
        )
    if allow_inherit and raw == INHERIT_POLICY:
        return PolicySelection.inherit()
    if not isinstance(raw, str):
        return PolicySelection.profile(PolicyProfile.READ_ONLY)
    try:
        profile = PolicyProfile(raw)
    except TypeError, ValueError:
        return PolicySelection.profile(PolicyProfile.READ_ONLY)
    if profile is not PolicyProfile.CUSTOM:
        return PolicySelection.profile(profile)
    modes = {
        str(capability): _parse_mode(config.get_value(policy_mode_key(capability, token_id)))
        for capability in Tag
    }
    return PolicySelection.custom(modes)


def _parse_mode(raw: object) -> PolicyMode:
    """Parse one raw mode, defaulting invalid and missing values to deny."""
    if not isinstance(raw, str):
        return PolicyMode.DENY
    try:
        return PolicyMode(raw)
    except TypeError, ValueError:
        return PolicyMode.DENY


def _manual_token_ids(raw: object) -> tuple[str, ...]:
    """Normalize a multi-value config input into ordered unique token IDs."""
    if isinstance(raw, str):
        values: Iterable[object] = (raw,)
    elif isinstance(raw, Iterable):
        values = raw
    else:
        values = ()
    return tuple(dict.fromkeys(value for item in values if (value := str(item).strip())))
