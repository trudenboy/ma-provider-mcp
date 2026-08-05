"""Request-scoped Permissions & Confirmations v2 enforcement tests."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import Client, Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken
from mcp.shared.exceptions import McpError
from music_assistant_models.config_entries import ConfigEntry
from music_assistant_models.enums import ConfigEntryType

from provider.auth import LOOKUP_FAILURE_CLIENT_ID
from provider.dynamic_api import DynamicAPIAdapter
from provider.meta_discovery import MetaDiscoveryService
from provider.middleware import TagFilterMiddleware
from provider.policy import PolicyMode, PolicyProfile, PolicySnapshot, policy_snapshot
from provider.server import build_tag_lookup
from provider.tags import Tag
from provider.token_identity import TokenIdentity


def _handler(
    command: str,
    target: Any,
    scope: str = "library.read",
    *,
    allow_impersonation: bool = False,
) -> Any:
    """Build the stable subset of MA's API handler contract."""
    return SimpleNamespace(
        command=command,
        signature=inspect.signature(target),
        type_hints=target.__annotations__,
        target=target,
        authenticated=True,
        required_scope=scope,
        allow_impersonation=allow_impersonation,
        alias=False,
    )


def _custom(**modes: PolicyMode) -> PolicySnapshot:
    """Build a literal Custom snapshot from capability fragments."""
    return policy_snapshot(
        PolicyProfile.CUSTOM,
        {capability.replace("__", ":"): mode for capability, mode in modes.items()},
    )


def _adapter(
    handlers: list[Any],
    *,
    current_token: list[AccessToken],
    policies: dict[str, PolicySnapshot],
    user: Any | None = None,
) -> DynamicAPIAdapter:
    """Build an adapter whose token and policy can change during one request."""
    mass = MagicMock()
    mass.command_handlers = {handler.command: handler for handler in handlers}
    user = user or SimpleNamespace(
        user_id="same-user",
        enabled=True,
        role="admin",
        player_filter=[],
        provider_filter=[],
    )
    mass.webserver.auth.authenticate_with_token = AsyncMock(return_value=user)
    mass.webserver.auth.get_token_id_from_token = AsyncMock(
        side_effect=lambda bearer: f"id-{bearer}"
    )
    return DynamicAPIAdapter(
        mass,
        auth_required_provider=lambda: True,
        token_provider=lambda: current_token[0],
        scope_checker=lambda _user, _scope: True,
        policy_provider=lambda bearer: policies[bearer],
        identity_provider=lambda bearer: TokenIdentity("same-user", f"id-{bearer}"),
    )


async def test_two_tokens_for_one_user_get_distinct_discovery_modes() -> None:
    """A user-level cache cannot collapse exact-token allow and confirm policy."""

    async def search() -> list[str]:
        return []

    tokens = [AccessToken(token="allow", client_id="id-allow", scopes=[])]
    policies = {
        "allow": _custom(query__library=PolicyMode.ALLOW),
        "confirm": _custom(query__library=PolicyMode.CONFIRM),
    }
    adapter = _adapter([_handler("music/search", search)], current_token=tokens, policies=policies)

    allow_entry = (await adapter.visible_entries())[0]
    tokens[0] = AccessToken(token="confirm", client_id="id-confirm", scopes=[])
    confirm_entry = (await adapter.visible_entries())[0]

    assert allow_entry.policy_mode is PolicyMode.ALLOW
    assert confirm_entry.policy_mode is PolicyMode.CONFIRM


async def test_deny_hides_and_confirm_elicits_on_every_call() -> None:
    """Deny is undiscoverable while accepted confirmations are never remembered."""
    calls = 0

    async def search() -> str:
        nonlocal calls
        calls += 1
        return "ok"

    tokens = [AccessToken(token="deny", client_id="id-deny", scopes=[])]
    policies = {
        "deny": _custom(),
        "confirm": _custom(query__library=PolicyMode.CONFIRM),
    }
    adapter = _adapter([_handler("music/search", search)], current_token=tokens, policies=policies)
    assert await adapter.visible_entries() == []

    tokens[0] = AccessToken(token="confirm", client_id="id-confirm", scopes=[])
    ctx = SimpleNamespace(
        elicit=AsyncMock(return_value=SimpleNamespace(action="accept", data=True))
    )
    for _ in range(2):
        await adapter.call(
            "ma_api:music/search",
            {},
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=cast("Context", ctx),
        )

    assert ctx.elicit.await_count == 2
    assert calls == 2


async def test_confirmation_decline_and_unsupported_errors_are_exact_and_actionable() -> None:
    """Confirm failures neither execute nor conceal the capability/operator remedy."""
    called = False

    async def search() -> None:
        nonlocal called
        called = True

    token = AccessToken(token="confirm", client_id="id-confirm", scopes=[])
    adapter = _adapter(
        [_handler("music/search", search)],
        current_token=[token],
        policies={"confirm": _custom(query__library=PolicyMode.CONFIRM)},
    )
    declined = SimpleNamespace(
        elicit=AsyncMock(return_value=SimpleNamespace(action="decline", data=False))
    )
    with pytest.raises(ToolError, match=r"^Operation cancelled by user$"):
        await adapter.call(
            "ma_api:music/search",
            {},
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=cast("Context", declined),
        )
    unsupported = SimpleNamespace(elicit=AsyncMock(side_effect=NotImplementedError))
    with pytest.raises(ToolError) as exc_info:
        await adapter.call(
            "ma_api:music/search",
            {},
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=cast("Context", unsupported),
        )
    message = str(exc_info.value)
    assert "query:library" in message
    assert "Allow" in message
    assert "elicitation-capable client" in message
    assert called is False


@pytest.mark.parametrize("revoked", ["policy", "scope", "target"])
async def test_revocation_during_confirmation_blocks_execution(revoked: str) -> None:
    """Accepted elicitation cannot outrun policy, scope, or target-filter changes."""
    called = False

    async def get_player(player_id: str) -> None:
        nonlocal called
        del player_id
        called = True

    user = SimpleNamespace(
        user_id="same-user",
        enabled=True,
        role="user",
        player_filter=["kitchen"],
        provider_filter=[],
    )
    token = AccessToken(token="confirm", client_id="id-confirm", scopes=[])
    policies = {"confirm": _custom(query__players=PolicyMode.CONFIRM)}
    adapter = _adapter(
        [_handler("players/get", get_player, "players.read")],
        current_token=[token],
        policies=policies,
        user=user,
    )
    scope_allowed = True
    adapter._scope_checker = lambda _user, _scope: scope_allowed

    async def accept_and_revoke(_prompt: str, *, response_type: type[bool]) -> Any:
        nonlocal scope_allowed
        del response_type
        if revoked == "policy":
            policies["confirm"] = _custom()
        elif revoked == "scope":
            scope_allowed = False
        else:
            user.player_filter = ["bedroom"]
        return SimpleNamespace(action="accept", data=True)

    with pytest.raises(ToolError, match="not permitted"):
        await adapter.call(
            "ma_api:players/get",
            {"player_id": "kitchen"},
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=cast("Context", SimpleNamespace(elicit=accept_and_revoke)),
        )
    assert called is False


async def test_search_schema_and_cursor_revision_include_effective_mode() -> None:
    """Cached discovery state becomes stale when allow changes to confirm."""

    async def search() -> None:
        return None

    async def browse() -> None:
        return None

    token = AccessToken(token="policy", client_id="id-policy", scopes=[])
    policies = {"policy": _custom(query__library=PolicyMode.ALLOW)}
    adapter = _adapter(
        [_handler("music/search", search), _handler("music/browse", browse)],
        current_token=[token],
        policies=policies,
    )
    service = MetaDiscoveryService(adapter)
    first = await service.discover("", limit=1)
    schema = await service.get_schema(first["items"][0]["name"])
    assert first["items"][0]["policy_mode"] == "allow"
    assert schema["policy_mode"] == "allow"
    assert first["next_cursor"] is not None

    policies["policy"] = _custom(query__library=PolicyMode.CONFIRM)
    changed = await service.discover("", limit=1)
    assert changed["items"][0]["policy_mode"] == "confirm"
    assert changed["catalog_revision"] != first["catalog_revision"]
    with pytest.raises(Exception, match="catalog changed"):
        await service.discover("", cursor=first["next_cursor"], limit=1)


async def test_resource_confirm_is_hidden_and_direct_reads_follow_policy_changes() -> None:
    """A cached concrete resource URI works only while its capability is Allow."""
    policy = [_custom(query__library=PolicyMode.ALLOW)]
    mcp: FastMCP = FastMCP(name="resource-policy")

    @mcp.resource("library://track/{track_id}", tags={Tag.QUERY_LIBRARY})  # type: ignore[untyped-decorator, unused-ignore]
    async def track(track_id: str) -> str:
        return track_id

    mcp.add_middleware(
        TagFilterMiddleware(
            lambda: {str(Tag.QUERY_LIBRARY)},
            build_tag_lookup(mcp),
            policy_provider=lambda: policy[0],
        )
    )
    async with Client(mcp) as client:
        await client.read_resource("library://track/17")
        policy[0] = _custom(query__library=PolicyMode.CONFIRM)
        templates = {str(item.uriTemplate) for item in await client.list_resource_templates()}
        assert "library://track/{track_id}" not in templates
        with pytest.raises(McpError):
            await client.read_resource("library://track/17")


async def test_secret_capability_escalates_and_is_rechecked_after_confirmation() -> None:
    """A secure field adds its own capability and prompt-time denial wins."""
    called = False

    async def save(
        provider_domain: str,
        values: dict[str, Any],
        instance_id: str | None = None,
    ) -> None:
        nonlocal called
        del provider_domain, values, instance_id
        called = True

    token = AccessToken(token="config", client_id="id-config", scopes=[])
    policies = {
        "config": _custom(
            config__write__provider=PolicyMode.ALLOW,
            config__write__secret=PolicyMode.CONFIRM,
        )
    }
    adapter = _adapter(
        [_handler("config/providers/save", save, "config.providers.write")],
        current_token=[token],
        policies=policies,
    )
    adapter.mass.config.get_provider_config_entries = AsyncMock(
        return_value=[ConfigEntry(key="token", type=ConfigEntryType.SECURE_STRING, label="Token")]
    )

    async def accept_then_revoke(_prompt: str, *, response_type: type[bool]) -> Any:
        del response_type
        policies["config"] = _custom(config__write__provider=PolicyMode.ALLOW)
        return SimpleNamespace(action="accept", data=True)

    with pytest.raises(ToolError, match="not permitted"):
        await adapter.call(
            "ma_api:config/providers/save",
            {
                "provider_domain": "demo",
                "instance_id": "demo--1",
                "values": {"token": "new-secret"},
            },
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=cast("Context", SimpleNamespace(elicit=accept_then_revoke)),
        )
    assert called is False


async def test_policy_revoked_during_preflight_is_rechecked_before_confirmation() -> None:
    """An awaited secret inspection cannot leave a stale allow snapshot executable."""
    called = False

    async def save(
        provider_domain: str,
        values: dict[str, Any],
        instance_id: str | None = None,
    ) -> None:
        nonlocal called
        del provider_domain, values, instance_id
        called = True

    token = AccessToken(token="config", client_id="id-config", scopes=[])
    policies = {
        "config": _custom(
            config__write__provider=PolicyMode.ALLOW,
            config__write__secret=PolicyMode.ALLOW,
        )
    }
    adapter = _adapter(
        [_handler("config/providers/save", save, "config.providers.write")],
        current_token=[token],
        policies=policies,
    )

    inspections = 0

    async def inspect_then_revoke(_target: str) -> list[ConfigEntry]:
        nonlocal inspections
        inspections += 1
        if inspections == 2:
            policies["config"] = _custom()
        return [ConfigEntry(key="token", type=ConfigEntryType.SECURE_STRING, label="Token")]

    adapter.mass.config.get_provider_config_entries = inspect_then_revoke
    with pytest.raises(ToolError, match="not permitted"):
        await adapter.call(
            "ma_api:config/providers/save",
            {
                "provider_domain": "demo",
                "instance_id": "demo--1",
                "values": {"token": "new-secret"},
            },
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=MagicMock(),
        )
    assert called is False


async def test_auth_revoked_during_final_preflight_blocks_handler_execution() -> None:
    """The last awaited secure inspection cannot leave bearer auth stale."""
    called = False
    inspections = 0

    async def save(
        provider_domain: str,
        values: dict[str, Any],
        instance_id: str | None = None,
    ) -> None:
        nonlocal called
        del provider_domain, values, instance_id
        called = True

    token = AccessToken(token="config", client_id="id-config", scopes=[])
    policies = {
        "config": _custom(
            config__write__provider=PolicyMode.ALLOW,
            config__write__secret=PolicyMode.ALLOW,
        )
    }
    adapter = _adapter(
        [_handler("config/providers/save", save, "config.providers.write")],
        current_token=[token],
        policies=policies,
    )

    async def inspect_then_revoke_auth(_target: str) -> list[ConfigEntry]:
        nonlocal inspections
        inspections += 1
        if inspections == 2:
            adapter.mass.webserver.auth.authenticate_with_token = AsyncMock(return_value=None)
        return [ConfigEntry(key="token", type=ConfigEntryType.SECURE_STRING, label="Token")]

    adapter.mass.config.get_provider_config_entries = inspect_then_revoke_auth
    with pytest.raises(ToolError, match="Authentication is required"):
        await adapter.call(
            "ma_api:config/providers/save",
            {
                "provider_domain": "demo",
                "instance_id": "demo--1",
                "values": {"token": "new-secret"},
            },
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=MagicMock(),
        )
    assert called is False


@pytest.mark.parametrize("revoked", ["token_identity", "user"])
async def test_exact_identity_revoked_during_final_preflight_blocks_execution(
    revoked: str,
) -> None:
    """Final preflight cannot leave an exact token binding or enabled user stale."""
    called = False
    inspections = 0
    user = SimpleNamespace(
        user_id="same-user",
        enabled=True,
        role="admin",
        player_filter=[],
        provider_filter=[],
    )

    async def save(
        provider_domain: str,
        values: dict[str, Any],
        instance_id: str | None = None,
    ) -> None:
        nonlocal called
        del provider_domain, values, instance_id
        called = True

    token = AccessToken(token="config", client_id="id-config", scopes=[])
    adapter = _adapter(
        [_handler("config/providers/save", save, "config.providers.write")],
        current_token=[token],
        policies={
            "config": _custom(
                config__write__provider=PolicyMode.ALLOW,
                config__write__secret=PolicyMode.ALLOW,
            )
        },
        user=user,
    )

    async def inspect_then_revoke_identity(_target: str) -> list[ConfigEntry]:
        nonlocal inspections
        inspections += 1
        if inspections == 2:
            if revoked == "token_identity":
                adapter.mass.webserver.auth.get_token_id_from_token = AsyncMock(
                    return_value="replacement"
                )
            else:
                user.enabled = False
        return [ConfigEntry(key="token", type=ConfigEntryType.SECURE_STRING, label="Token")]

    adapter.mass.config.get_provider_config_entries = inspect_then_revoke_identity
    with pytest.raises(ToolError, match="Authentication is required"):
        await adapter.call(
            "ma_api:config/providers/save",
            {
                "provider_domain": "demo",
                "instance_id": "demo--1",
                "values": {"token": "new-secret"},
            },
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=MagicMock(),
        )
    assert called is False


async def test_impersonation_revoked_during_final_preflight_blocks_execution() -> None:
    """The impersonated identity is resolved again after the final inspection."""
    called = False

    async def save(
        provider_domain: str,
        values: dict[str, Any],
        instance_id: str | None = None,
    ) -> None:
        nonlocal called
        del provider_domain, values, instance_id
        called = True

    token = AccessToken(token="config", client_id="id-config", scopes=[])
    adapter = _adapter(
        [
            _handler(
                "config/providers/save",
                save,
                "config.providers.write",
                allow_impersonation=True,
            )
        ],
        current_token=[token],
        policies={
            "config": _custom(
                config__write__provider=PolicyMode.ALLOW,
                config__write__secret=PolicyMode.ALLOW,
            )
        },
    )
    adapter.mass.config.get_provider_config_entries = AsyncMock(
        return_value=[ConfigEntry(key="token", type=ConfigEntryType.SECURE_STRING, label="Token")]
    )
    impersonated_user = SimpleNamespace(
        user_id="target",
        enabled=True,
        role="admin",
        player_filter=[],
        provider_filter=[],
    )
    resolutions = 0

    async def resolve_then_revoke(_auth: Any, _requested: str) -> Any:
        nonlocal resolutions
        resolutions += 1
        if resolutions == 3:
            raise ToolError("Unable to impersonate requested user")
        return impersonated_user

    cast("Any", adapter)._resolve_impersonated_user = resolve_then_revoke
    ctx = SimpleNamespace(
        elicit=AsyncMock(return_value=SimpleNamespace(action="accept", data=True))
    )
    with pytest.raises(ToolError, match="Unable to impersonate requested user"):
        await adapter.call(
            "ma_api:config/providers/save",
            {
                "provider_domain": "demo",
                "instance_id": "demo--1",
                "values": {"token": "new-secret"},
                "user": "target",
            },
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=cast("Context", ctx),
        )
    assert resolutions == 3
    assert called is False


async def test_final_revalidation_cannot_reuse_confirmation_for_a_new_capability() -> None:
    """A prompt for one capability cannot bless a different final Confirm requirement."""
    called = False

    async def save(
        provider_domain: str,
        values: dict[str, Any],
        instance_id: str | None = None,
    ) -> None:
        nonlocal called
        del provider_domain, values, instance_id
        called = True

    token = AccessToken(token="config", client_id="id-config", scopes=[])
    policies = {
        "config": _custom(
            config__write__provider=PolicyMode.ALLOW,
            config__write__secret=PolicyMode.CONFIRM,
        )
    }
    adapter = _adapter(
        [_handler("config/providers/save", save, "config.providers.write")],
        current_token=[token],
        policies=policies,
    )
    adapter.mass.config.get_provider_config_entries = AsyncMock(
        return_value=[ConfigEntry(key="token", type=ConfigEntryType.SECURE_STRING, label="Token")]
    )
    user = await adapter.mass.webserver.auth.authenticate_with_token("config")
    authentications = 0

    async def authenticate_and_swap_requirement(_bearer: str) -> Any:
        nonlocal authentications
        authentications += 1
        if authentications == 4:
            policies["config"] = _custom(
                config__write__provider=PolicyMode.CONFIRM,
                config__write__secret=PolicyMode.ALLOW,
            )
        return user

    adapter.mass.webserver.auth.authenticate_with_token = authenticate_and_swap_requirement
    ctx = SimpleNamespace(
        elicit=AsyncMock(return_value=SimpleNamespace(action="accept", data=True))
    )

    with pytest.raises(ToolError, match="retry the operation"):
        await adapter.call(
            "ma_api:config/providers/save",
            {
                "provider_domain": "demo",
                "instance_id": "demo--1",
                "values": {"token": "new-secret"},
            },
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=cast("Context", ctx),
        )
    assert ctx.elicit.await_count == 1
    assert called is False


@pytest.mark.parametrize(
    ("flow_scope", "allowed_capability", "denied_capability"),
    [
        (
            "config.providers.write",
            Tag.CONFIG_WRITE_PLAYER,
            Tag.CONFIG_WRITE_PROVIDER,
        ),
        (
            "config.players.write",
            Tag.CONFIG_WRITE_PROVIDER,
            Tag.CONFIG_WRITE_PLAYER,
        ),
    ],
)
async def test_flow_abort_requires_its_exact_category(
    flow_scope: str,
    allowed_capability: Tag,
    denied_capability: Tag,
) -> None:
    """One allowed config category cannot abort a flow owned by the other."""
    called = False

    async def abort(flow_id: str) -> None:
        nonlocal called
        del flow_id
        called = True

    token = AccessToken(token="abort", client_id="id-abort", scopes=[])
    adapter = _adapter(
        [_handler("config/flows/abort", abort, "config.providers.write")],
        current_token=[token],
        policies={
            "abort": policy_snapshot(
                PolicyProfile.CUSTOM,
                {allowed_capability: PolicyMode.ALLOW},
            )
        },
    )
    adapter.mass.config.get_setup_flow_required_scope = lambda _flow_id: flow_scope

    with pytest.raises(ToolError, match=str(denied_capability)):
        await adapter.call(
            "ma_api:config/flows/abort",
            {"flow_id": "flow-1"},
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=MagicMock(),
        )
    assert called is False


async def test_auth_off_uses_global_default_for_discovery_schema_and_execution() -> None:
    """Without request auth, all command surfaces share the global default policy."""
    called = False

    async def search() -> str:
        nonlocal called
        called = True
        return "ok"

    default = [_custom(query__library=PolicyMode.ALLOW)]
    mass = MagicMock()
    handler = _handler("music/search", search)
    mass.command_handlers = {handler.command: handler}
    adapter = DynamicAPIAdapter(
        mass,
        auth_required_provider=lambda: False,
        token_provider=lambda: None,
        scope_checker=lambda _user, _scope: True,
        default_policy_provider=lambda: default[0],
    )
    service = MetaDiscoveryService(adapter)

    page = await service.discover("search")
    assert page["items"][0]["policy_mode"] == "allow"
    schema = await service.get_schema("ma_api:music/search")
    assert schema["policy_mode"] == "allow"
    await adapter.call(
        "ma_api:music/search",
        {},
        response_mode="compact",
        fields=None,
        max_items=None,
        ctx=MagicMock(),
    )
    assert called is True

    default[0] = _custom()
    assert await adapter.visible_entries() == []


async def test_token_identity_revocation_during_confirmation_blocks_execution() -> None:
    """A revoked/replaced exact token cannot execute after an accepted prompt."""
    called = False

    async def search() -> None:
        nonlocal called
        called = True

    token = AccessToken(token="confirm", client_id="id-confirm", scopes=[])
    adapter = _adapter(
        [_handler("music/search", search)],
        current_token=[token],
        policies={"confirm": _custom(query__library=PolicyMode.CONFIRM)},
    )

    async def accept_then_replace(_prompt: str, *, response_type: type[bool]) -> Any:
        del response_type
        adapter.mass.webserver.auth.get_token_id_from_token = AsyncMock(return_value="replacement")
        return SimpleNamespace(action="accept", data=True)

    with pytest.raises(ToolError, match="Authentication is required"):
        await adapter.call(
            "ma_api:music/search",
            {},
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=cast("Context", SimpleNamespace(elicit=accept_then_replace)),
        )
    assert called is False


async def test_lookup_failure_identity_recovery_during_confirmation_fails_closed() -> None:
    """A lookup-failure request cannot adopt a newly resolved token identity mid-call."""
    called = False

    async def search() -> None:
        nonlocal called
        called = True

    token = AccessToken(
        token="lookup-failure",
        client_id=LOOKUP_FAILURE_CLIENT_ID,
        scopes=[],
    )
    adapter = _adapter(
        [_handler("music/search", search)],
        current_token=[token],
        policies={"lookup-failure": _custom(query__library=PolicyMode.CONFIRM)},
    )
    adapter._identity_provider = lambda _bearer: None
    adapter.mass.webserver.auth.get_token_id_from_token = AsyncMock(
        side_effect=RuntimeError("lookup unavailable")
    )

    async def accept_then_recover(_prompt: str, *, response_type: type[bool]) -> Any:
        del response_type
        adapter.mass.webserver.auth.get_token_id_from_token = AsyncMock(return_value="now-known")
        return SimpleNamespace(action="accept", data=True)

    with pytest.raises(ToolError, match="Authentication is required"):
        await adapter.call(
            "ma_api:music/search",
            {},
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=cast("Context", SimpleNamespace(elicit=accept_then_recover)),
        )
    assert called is False


async def test_alternative_capability_catalog_mode_is_conservative() -> None:
    """Any prompt-capable setup-flow branch makes the shared schema confirm."""

    async def submit(flow_id: str, values: dict[str, Any]) -> None:
        del flow_id, values

    token = AccessToken(token="flows", client_id="id-flows", scopes=[])
    adapter = _adapter(
        [_handler("config/flows/submit", submit, "config.providers.write")],
        current_token=[token],
        policies={
            "flows": _custom(
                config__write__provider=PolicyMode.CONFIRM,
                config__write__player=PolicyMode.ALLOW,
            )
        },
    )
    entry = (await adapter.visible_entries())[0]
    assert entry.policy_mode is PolicyMode.CONFIRM
