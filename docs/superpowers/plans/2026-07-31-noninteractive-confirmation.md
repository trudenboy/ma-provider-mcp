# Non-interactive Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make confirmation policy usable by MCP clients without elicitation, separate system confirmation control, classify queue mutations as ordinary edits, and pin FastMCP 3.4.5.

**Architecture:** Keep authorization and confirmation as independent stages in the native MA command dispatcher. Replace `NEVER/CONFIGURED/ALWAYS` with `NEVER/STANDARD/SYSTEM`, feed the dispatcher two live configuration providers, and retain the existing post-confirmation authorization pass. Queue mutations get exact non-destructive write policies using `edit:queue`.

**Tech Stack:** Python 3.14, Music Assistant `dev`, FastMCP 3.4.5, MCP Python SDK, pytest/pytest-asyncio, Ruff, mypy, Docker Linux test environment.

## Global Constraints

- `require_confirmation` and `require_system_confirmation` default to `true`.
- `require_system_confirmation` is an advanced provider setting and also governs impersonation.
- Standard confirmation falls through only for a genuinely unsupported elicitation capability; unexpected MCP and transport errors fail closed.
- Disabling confirmation never bypasses authentication, MA scopes, dynamic risk gates, permission tags, target filters, request preflight, or post-confirmation revalidation.
- Queue clear, remove, move, and reorder operations use `edit_queue` and `destructiveHint=false`.
- Remove `delete_queue` without migration, alias, read-through, or compatibility shim.
- Pin the canonical manifest requirement to `fastmcp==3.4.5`; do not migrate to FastMCP 4 APIs.
- Do not change `VERSION`; release versioning remains maintainer-owned.
- Run MA-dependent verification against the real Music Assistant `dev` source in Linux, not a reduced standalone macOS environment.

---

## File map

- `provider/constants.py`: configuration keys and hot-swap classification.
- `provider/config.py`: provider configuration entries.
- `provider/strings.json`: user-facing confirmation and queue permission copy.
- `provider/server.py`: live configuration closures supplied to the dispatcher.
- `provider/command_policy.py`: confirmation classes, command policy resolution, queue annotations and permission tags.
- `provider/dynamic_api.py`: elicitation fallback, effective confirmation selection, and post-confirmation flow.
- `provider/tags.py`: public permission-tag enum and config mapping.
- `provider/manifest.json`: canonical FastMCP runtime pin.
- `tests/conftest.py`: provider-config defaults used by tests.
- `tests/test_config_entries.py`: configuration surface and defaults.
- `tests/test_constants.py`: hot-swappable key partition.
- `tests/test_apply_permission_change.py`: live setting updates without remount.
- `tests/test_command_policy.py`: static command classification and queue policy.
- `tests/test_dynamic_catalog.py`: runtime confirmation matrix and security revalidation.
- `tests/test_tags.py`: permission mapping after removing `delete_queue`.
- `tests/test_manifest.py`: exact runtime dependency contract.
- `README.md`: operator-facing permission and confirmation documentation.

---

### Task 1: Add independent hot-swappable confirmation settings

**Files:**
- Modify: `provider/constants.py:5-20,65-115`
- Modify: `provider/config.py:10-52,99-126`
- Modify: `provider/strings.json`
- Modify: `provider/server.py:120-152`
- Modify: `tests/conftest.py:197-227`
- Modify: `tests/test_config_entries.py:7-45`
- Modify: `tests/test_constants.py:5-30`
- Modify: `tests/test_apply_permission_change.py:109-131`

**Interfaces:**
- Produces: `CONF_REQUIRE_SYSTEM_CONFIRMATION: str`.
- Produces: `CONFIRMATION_KEYS: frozenset[str]` containing both confirmation settings.
- Preserves: `MCPServerRuntime.apply_permission_change(new_config, changed_keys)` as the hot-swap entry point.

- [ ] **Step 1: Write failing configuration and hot-swap tests**

Add these assertions to `tests/test_config_entries.py`:

```python
from provider.constants import (
    CONF_REQUIRE_CONFIRMATION,
    CONF_REQUIRE_SYSTEM_CONFIRMATION,
)


def test_confirmation_entries_default_on_and_system_is_advanced(mock_mass: MagicMock) -> None:
    entries = {entry.key: entry for entry in build_config_entries(mock_mass, DEFAULT_MOUNT_PATH)}

    assert entries[CONF_REQUIRE_CONFIRMATION].default_value is True
    assert entries[CONF_REQUIRE_SYSTEM_CONFIRMATION].default_value is True
    assert entries[CONF_REQUIRE_SYSTEM_CONFIRMATION].advanced is True


def test_total_entry_count(mock_mass: MagicMock) -> None:
    entries = build_config_entries(mock_mass, DEFAULT_MOUNT_PATH)
    assert len(entries) == 43
```

Update `tests/test_constants.py` so the set invariant is explicit:

```python
from provider.constants import CONFIRMATION_KEYS


def test_hot_swappable_includes_confirmation_keys() -> None:
    assert HOT_SWAPPABLE_KEYS == (
        PERMISSION_KEYS | RESOURCE_KEYS | DYNAMIC_API_KEYS | CONFIRMATION_KEYS
    )
```

Add to `tests/test_apply_permission_change.py`:

```python
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed_key",
    ["require_confirmation", "require_system_confirmation"],
)
async def test_confirmation_change_hot_swaps(
    changed_key: str, mock_mass: MagicMock, mock_config: MagicMock
) -> None:
    from provider.server import MCPServerRuntime

    runtime = MCPServerRuntime(mock_mass, mock_config, logging.getLogger("t"))
    runtime._allowed_tags = {"query:library"}
    runtime.stop = AsyncMock()
    runtime.start = AsyncMock()

    await runtime.apply_permission_change(mock_config, changed_keys={changed_key})

    runtime.stop.assert_not_awaited()
    runtime.start.assert_not_awaited()
    assert runtime._config is mock_config
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run in the canonical Linux MA environment:

```bash
python -m pytest -q \
  tests/test_config_entries.py \
  tests/test_constants.py \
  tests/test_apply_permission_change.py
```

Expected: import/assertion failures because `CONF_REQUIRE_SYSTEM_CONFIRMATION` and `CONFIRMATION_KEYS` do not exist.

- [ ] **Step 3: Add the configuration constants and entry**

In `provider/constants.py`, add:

```python
CONF_REQUIRE_SYSTEM_CONFIRMATION = "require_system_confirmation"

CONFIRMATION_KEYS: frozenset[str] = frozenset(
    {CONF_REQUIRE_CONFIRMATION, CONF_REQUIRE_SYSTEM_CONFIRMATION}
)

HOT_SWAPPABLE_KEYS: frozenset[str] = (
    PERMISSION_KEYS | RESOURCE_KEYS | DYNAMIC_API_KEYS | CONFIRMATION_KEYS
)
```

In `provider/config.py`, add an advanced entry immediately after the existing confirmation entry:

```python
ConfigEntry(
    key=CONF_REQUIRE_SYSTEM_CONFIRMATION,
    type=ConfigEntryType.BOOLEAN,
    default_value=True,
    category="server",
    advanced=True,
    required=False,
),
```

Add the same default to `tests/conftest.py`:

```python
"require_system_confirmation": True,
```

- [ ] **Step 4: Make confirmation-only changes hot-swappable**

Update `MCPServerRuntime.apply_permission_change`:

```python
from .constants import CONFIRMATION_KEYS, DYNAMIC_API_KEYS, PERMISSION_KEYS

permission_only = changed_keys.issubset(
    PERMISSION_KEYS | DYNAMIC_API_KEYS | CONFIRMATION_KEYS
)
```

Keep resource keys out of `permission_only`; they remain routed through this method but still restart registration.

- [ ] **Step 5: Add localized setting text**

Set the two entries in `provider/strings.json` to:

```json
"require_confirmation": {
  "label": "Confirm write operations",
  "description": "Ask for confirmation before write operations when the MCP client supports interactive elicitation. Clients without elicitation continue using the configured permissions."
},
"require_system_confirmation": {
  "label": "Require system confirmations",
  "description": "Require interactive confirmation for system commands and impersonation. Disable only when authenticated clients may run these operations without an additional prompt."
}
```

- [ ] **Step 6: Run focused tests and verify GREEN**

```bash
python -m pytest -q \
  tests/test_config_entries.py \
  tests/test_constants.py \
  tests/test_apply_permission_change.py
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit the settings layer**

```bash
git add provider/constants.py provider/config.py provider/strings.json provider/server.py \
  tests/conftest.py tests/test_config_entries.py tests/test_constants.py \
  tests/test_apply_permission_change.py
git commit -m "feat(config): separate system confirmation control"
```

---

### Task 2: Implement STANDARD and SYSTEM runtime confirmation policy

**Files:**
- Modify: `provider/command_policy.py:43-60,178-218,235-269`
- Modify: `provider/dynamic_api.py:66-85,145-175,490-514`
- Modify: `provider/server.py:9-21,251-276`
- Modify: `tests/test_command_policy.py:25-113`
- Modify: `tests/test_dynamic_catalog.py:610-673,1328-1360`

**Interfaces:**
- Consumes: `CONF_REQUIRE_SYSTEM_CONFIRMATION` from Task 1.
- Produces: `Confirmation.NEVER`, `Confirmation.STANDARD`, and `Confirmation.SYSTEM`.
- Produces: `DynamicAPIAdapter(..., confirmation_provider: Callable[[], bool], system_confirmation_provider: Callable[[], bool], ...)`.
- Preserves: `confirm_or_raise(ctx, prompt, required=...)` capability fallback contract.

- [ ] **Step 1: Replace policy expectations with failing STANDARD/SYSTEM tests**

Update static policy tests to assert:

```python
def test_provider_reload_is_a_standard_confirmed_write() -> None:
    decision = resolve_command_policy("config/providers/reload", "config.providers.write", None)

    assert decision.risk is DynamicRisk.WRITE
    assert decision.confirmation is Confirmation.STANDARD


def test_system_health_uses_system_confirmation() -> None:
    decision = resolve_command_policy("fastmcp/debug/health", "system.read", None)

    assert decision.risk is DynamicRisk.SYSTEM
    assert decision.confirmation is Confirmation.SYSTEM
```

Add a runtime matrix to `tests/test_dynamic_catalog.py` using the existing `_real_adapter` helper:

```python
@pytest.mark.parametrize(
    ("confirmation", "standard_enabled", "system_enabled", "expected_required"),
    [
        (Confirmation.NEVER, True, True, None),
        (Confirmation.STANDARD, False, True, None),
        (Confirmation.STANDARD, True, True, False),
        (Confirmation.SYSTEM, True, False, None),
        (Confirmation.SYSTEM, True, True, True),
    ],
)
async def test_confirmation_setting_matrix(
    confirmation: Confirmation,
    standard_enabled: bool,
    system_enabled: bool,
    expected_required: bool | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt = AsyncMock()
    monkeypatch.setattr("provider.dynamic_api.confirm_or_raise", prompt)
    adapter = _real_adapter(_handler("music/write", lambda: None))
    adapter._confirmation_provider = lambda: standard_enabled
    adapter._system_confirmation_provider = lambda: system_enabled
    entry = DynamicEntry(
        "ma_api:music/write",
        "music/write",
        "write",
        {},
        DynamicRisk.WRITE,
        None,
        False,
        object(),
    )

    await adapter._confirm(entry, MagicMock(), confirmation=confirmation)

    if expected_required is None:
        prompt.assert_not_awaited()
    else:
        assert prompt.await_args.kwargs["required"] is expected_required
```

Add an impersonation override test:

```python
async def test_impersonation_uses_system_confirmation_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt = AsyncMock()
    monkeypatch.setattr("provider.dynamic_api.confirm_or_raise", prompt)
    adapter = _real_adapter(_handler("music/search", lambda: None))
    adapter._system_confirmation_provider = lambda: False
    entry = DynamicEntry(
        "ma_api:music/search",
        "music/search",
        "search",
        {},
        DynamicRisk.READ,
        None,
        True,
        object(),
    )

    await adapter._confirm(entry, MagicMock(), impersonating=True)

    prompt.assert_not_awaited()
```

Keep the existing unsupported-capability cases, add `INTERNAL_ERROR` to the
`mcp.types` imports, and add explicit result/error coverage for
`confirm_or_raise`:

```python
@pytest.mark.parametrize(
    ("result", "error"),
    [
        (SimpleNamespace(action="decline", data=None), "Operation cancelled by user"),
        (SimpleNamespace(action="cancel", data=None), "Operation cancelled by user"),
        (SimpleNamespace(action="accept", data=None), "Operation cancelled by user"),
        (SimpleNamespace(action="unknown", data=True), "Operation cancelled by user"),
    ],
)
async def test_confirmation_non_accept_results_fail_closed(result: Any, error: str) -> None:
    ctx = MagicMock()
    ctx.elicit = AsyncMock(return_value=result)

    with pytest.raises(ToolError, match=error):
        await confirm_or_raise(ctx, "Confirm", required=False)


async def test_confirmation_accepts_only_true_data() -> None:
    ctx = MagicMock()
    ctx.elicit = AsyncMock(return_value=SimpleNamespace(action="accept", data=True))

    await confirm_or_raise(ctx, "Confirm", required=True)


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("elicitation timed out"),
        McpError(ErrorData(code=INTERNAL_ERROR, message="handler failed")),
    ],
)
async def test_unexpected_confirmation_errors_fail_closed(error: Exception) -> None:
    ctx = MagicMock()
    ctx.elicit = AsyncMock(side_effect=error)

    with pytest.raises(type(error)):
        await confirm_or_raise(ctx, "Confirm", required=False)
```

- [ ] **Step 2: Run policy and runtime tests and verify RED**

```bash
python -m pytest -q tests/test_command_policy.py tests/test_dynamic_catalog.py
```

Expected: failures because the enum still exposes `CONFIGURED/ALWAYS` and the adapter has no system provider.

- [ ] **Step 3: Replace the confirmation enum and default resolution**

In `provider/command_policy.py`:

```python
class Confirmation(StrEnum):
    """Provider setting that governs confirmation before execution."""

    NEVER = "never"
    STANDARD = "standard"
    SYSTEM = "system"
```

Use `Confirmation.SYSTEM` for `_readonly_system`, `Confirmation.STANDARD` for write/delete helpers and exact write policies, and resolve defaults with:

```python
confirmation = (
    Confirmation.SYSTEM
    if risk is DynamicRisk.SYSTEM
    else Confirmation.STANDARD
    if risk is DynamicRisk.WRITE
    else Confirmation.NEVER
)
```

- [ ] **Step 4: Add the live system-setting provider to the adapter**

Extend `DynamicAPIAdapter.__init__`:

```python
system_confirmation_provider: Callable[[], bool],
```

Store it as:

```python
self._system_confirmation_provider = system_confirmation_provider
```

Update every adapter construction in production and tests. In `provider/server.py` pass:

```python
system_confirmation_provider=lambda: config_bool(
    CONF_REQUIRE_SYSTEM_CONFIRMATION,
    default=True,
),
```

- [ ] **Step 5: Implement the effective confirmation selection**

Replace `_confirm` with the equivalent of:

```python
confirmation = confirmation or (
    entry.decision.confirmation
    if entry.decision is not None
    else Confirmation.SYSTEM
    if entry.risk is DynamicRisk.SYSTEM
    else Confirmation.STANDARD
    if entry.risk is DynamicRisk.WRITE
    else Confirmation.NEVER
)
if impersonating:
    confirmation = Confirmation.SYSTEM
if confirmation is Confirmation.NEVER:
    return
if confirmation is Confirmation.STANDARD:
    if not self._confirmation_provider():
        return
    await confirm_or_raise(ctx, f"Run {entry.name} ({entry.risk.value})?", required=False)
    return
if not self._system_confirmation_provider():
    return
await confirm_or_raise(ctx, f"Run {entry.name} ({entry.risk.value})?", required=True)
```

For unsupported required elicitation, return this actionable `ToolError` message from `confirm_or_raise`:

```text
This client does not support the required system confirmation; use an elicitation-capable client or disable "Require system confirmations" in the provider's advanced settings
```

Keep unsupported `STANDARD` elicitation as a return, and re-raise every other `McpError` unchanged.

- [ ] **Step 6: Add a real no-handler client regression**

Add these focused protocol regressions to `tests/test_dynamic_catalog.py`. They use
FastMCP's in-process `Client` without an elicitation handler, so the SDK negotiates
the same missing capability that non-interactive clients expose. Extend the FastMCP
test import to `from fastmcp import Client, Context, FastMCP`, then add:

```python
async def test_client_without_elicitation_runs_standard_fallback() -> None:
    called = False
    mcp = FastMCP(name="confirmation-test")

    @mcp.tool(name="authorized_write")
    async def authorized_write(ctx: Context) -> str:
        nonlocal called
        await confirm_or_raise(ctx, "Confirm write?", required=False)
        called = True
        return "ok"

    async with Client(mcp) as client:
        result = await client.call_tool("authorized_write")

    assert result.data == "ok"
    assert called is True


async def test_client_without_elicitation_rejects_required_system_prompt() -> None:
    called = False
    mcp = FastMCP(name="confirmation-test")

    @mcp.tool(name="authorized_system")
    async def authorized_system(ctx: Context) -> str:
        nonlocal called
        await confirm_or_raise(ctx, "Confirm system command?", required=True)
        called = True
        return "ok"

    async with Client(mcp) as client:
        with pytest.raises(
            ToolError,
            match="disable .*Require system confirmations.*advanced settings",
        ):
            await client.call_tool("authorized_system")

    assert called is False
```

The test must use the real `confirm_or_raise` path; do not monkeypatch it.

- [ ] **Step 7: Run focused runtime tests and verify GREEN**

```bash
python -m pytest -q tests/test_command_policy.py tests/test_dynamic_catalog.py
```

Expected: all selected tests pass, including the client without an elicitation handler.

- [ ] **Step 8: Run security revalidation regressions**

```bash
python -m pytest -q tests/test_dynamic_catalog.py \
  -k 'revoked or revalidation or confirmation or impersonation or secret or target'
```

Expected: all selected tests pass; authorization is checked before and after skipped or accepted confirmation.

- [ ] **Step 9: Commit the runtime policy**

```bash
git add provider/command_policy.py provider/dynamic_api.py provider/server.py \
  tests/test_command_policy.py tests/test_dynamic_catalog.py
git commit -m "feat(policy): support non-interactive confirmation modes"
```

---

### Task 3: Unify queue mutation permission and remove destructive annotations

**Files:**
- Modify: `provider/constants.py:28-45,65-93`
- Modify: `provider/config.py:10-52,169-179`
- Modify: `provider/strings.json`
- Modify: `provider/tags.py:8-34,40-96`
- Modify: `provider/command_policy.py:73-97,126-218`
- Modify: `tests/conftest.py:201-227`
- Modify: `tests/test_command_policy.py:25-80,131-151`
- Modify: `tests/test_config_entries.py:31-78`
- Modify: `tests/test_constants.py:13-30`
- Modify: `tests/test_tags.py:7-43`
- Modify: `README.md:20-105,118-128`

**Interfaces:**
- Removes: `CONF_DELETE_QUEUE` and `Tag.DELETE_QUEUE` without compatibility aliases.
- Produces: exact queue mutation decisions requiring `Tag.EDIT_QUEUE`, `DynamicRisk.WRITE`, `Confirmation.STANDARD`, and `destructiveHint=False`.

- [ ] **Step 1: Rewrite queue policy tests for the approved behavior**

Replace the destructive queue tests with:

```python
@pytest.mark.parametrize(
    "command",
    [
        "player_queues/delete_item",
        "player_queues/clear",
        "fastmcp/queue/remove_items_safe",
    ],
)
def test_queue_mutations_are_standard_non_destructive_edits(command: str) -> None:
    decision = resolve_command_policy(command, "queues.control", profile=None)

    assert decision.risk is DynamicRisk.WRITE
    assert decision.required_tags == frozenset({str(Tag.EDIT_QUEUE)})
    assert decision.confirmation is Confirmation.STANDARD
    assert decision.annotations == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
```

Also preserve the MA-native move/reorder commands as non-destructive queue edits:

```python
@pytest.mark.parametrize("command", ["player_queues/move_item", "player_queues/move_item_end"])
def test_queue_reordering_uses_edit_permission(command: str) -> None:
    decision = resolve_command_policy(command, "queues.control", profile=None)

    assert decision.required_tags == frozenset({str(Tag.EDIT_QUEUE)})
    assert decision.annotations["destructiveHint"] is False
```

Update config/tag invariant tests:

```python
def test_queue_delete_permission_is_not_exposed(mock_mass: MagicMock) -> None:
    keys = {entry.key for entry in build_config_entries(mock_mass, DEFAULT_MOUNT_PATH)}
    assert "delete_queue" not in keys


def test_queue_uses_only_edit_tag() -> None:
    assert "delete:queue" not in {tag.value for tag in Tag}
    assert CONFIG_TO_TAG["edit_queue"] is Tag.EDIT_QUEUE
```

Reduce the `PERMISSION_KEYS` and unique-tag expected counts by one.
Because Task 1 added one setting and this task removes one permission, restore
`test_total_entry_count` to `42`.

- [ ] **Step 2: Run queue/config/tag tests and verify RED**

```bash
python -m pytest -q \
  tests/test_command_policy.py \
  tests/test_config_entries.py \
  tests/test_constants.py \
  tests/test_tags.py
```

Expected: failures showing the old queue-delete constant, config entry, tag and destructive exact policies.

- [ ] **Step 3: Remove the queue-delete configuration surface**

Delete `CONF_DELETE_QUEUE` from `provider/constants.py`, imports, `PERMISSION_KEYS`, `provider/config.py`, `provider/tags.py`, and `tests/conftest.py`. Delete `Tag.DELETE_QUEUE` and the `delete_queue` strings entry.

Do not add a deprecated alias or inspect old config values.

- [ ] **Step 4: Add exact non-destructive queue write decisions**

Add a focused helper to `provider/command_policy.py`:

```python
def _queue_edit() -> CommandDecision:
    """Return the standard non-destructive queue mutation policy."""
    return CommandDecision(
        DynamicRisk.WRITE,
        _CONTROL_ANNOTATIONS,
        frozenset({str(Tag.EDIT_QUEUE)}),
        Confirmation.STANDARD,
    )
```

Use it for all three exact commands:

```python
"player_queues/delete_item": _queue_edit(),
"player_queues/clear": _queue_edit(),
"fastmcp/queue/remove_items_safe": _queue_edit(),
```

Set the queue family's `delete` mapping to `Tag.EDIT_QUEUE` as defense for future remove/delete command names:

```python
_family(
    "player_queues/",
    read=Tag.QUERY_QUEUE,
    control=Tag.EDIT_QUEUE,
    write=Tag.EDIT_QUEUE,
    delete=Tag.EDIT_QUEUE,
),
```

- [ ] **Step 5: Update user-facing queue and system copy**

Change `edit_queue` text to cover enqueue, move, remove and clear. Remove claims that every system command always requires confirmation from `dynamic_api_system`. Update README permission counts and explain the independent standard/system confirmation settings.

- [ ] **Step 6: Run queue/config/tag tests and verify GREEN**

```bash
python -m pytest -q \
  tests/test_command_policy.py \
  tests/test_config_entries.py \
  tests/test_constants.py \
  tests/test_tags.py \
  tests/test_provider_commands_queue.py
```

Expected: all selected tests pass and no `delete:queue` permission remains.

- [ ] **Step 7: Scan for forbidden legacy references**

```bash
git grep -n -E 'CONF_DELETE_QUEUE|Tag\.DELETE_QUEUE|delete:queue|"delete_queue"' -- \
  provider tests README.md
```

Expected: no output.

- [ ] **Step 8: Commit queue permission unification**

```bash
git add provider/constants.py provider/config.py provider/strings.json provider/tags.py \
  provider/command_policy.py tests/conftest.py tests/test_command_policy.py \
  tests/test_config_entries.py tests/test_constants.py tests/test_tags.py \
  tests/test_provider_commands_queue.py README.md
git commit -m "refactor(queue): treat queue mutations as ordinary edits"
```

---

### Task 4: Pin and verify FastMCP 3.4.5

**Files:**
- Modify: `provider/manifest.json:12`
- Create: `tests/test_manifest.py`

**Interfaces:**
- Produces: canonical manifest requirement `fastmcp==3.4.5`.
- Preserves: FastMCP 3.x `Context.elicit`, `ToolError`, transformed tools, and schema APIs.

- [ ] **Step 1: Write the failing manifest contract test**

Create `tests/test_manifest.py`:

```python
"""Provider manifest dependency contract tests."""

from __future__ import annotations

import json
from pathlib import Path


def test_fastmcp_runtime_is_pinned_to_3_4_5() -> None:
    manifest = json.loads((Path(__file__).parents[1] / "provider" / "manifest.json").read_text())

    assert manifest["requirements"] == ["fastmcp==3.4.5"]
```

- [ ] **Step 2: Run the manifest test and verify RED**

```bash
python -m pytest -q tests/test_manifest.py
```

Expected: assertion diff from `fastmcp==3.4.4` to `fastmcp==3.4.5`.

- [ ] **Step 3: Update the canonical manifest pin**

Set:

```json
"requirements": ["fastmcp==3.4.5"]
```

Do not manually edit the auto-generated `pyproject.toml` range.

- [ ] **Step 4: Verify the dependency and schema regressions**

In the Linux MA dev environment, install the manifest requirement and run:

```bash
python -c 'import fastmcp; assert fastmcp.__version__ == "3.4.5"'
python -m pytest -q \
  tests/test_manifest.py \
  tests/test_dynamic_signatures.py \
  tests/test_dynamic_catalog.py -k 'schema or confirmation'
```

Expected: version assertion and selected tests pass; repeated schema generation remains deterministic.

- [ ] **Step 5: Commit the dependency update**

```bash
git add provider/manifest.json tests/test_manifest.py
git commit -m "build(deps): bump FastMCP to 3.4.5"
```

---

### Task 5: Canonical integration and release-readiness verification

**Files:**
- Verify only: all modified provider and test files.
- Do not modify: `VERSION`.

**Interfaces:**
- Consumes: completed Tasks 1-4.
- Produces: evidence that the approved spec works in the real MA dev slice and survives upstream rewriting.

- [ ] **Step 1: Run the complete provider suite in Linux MA dev**

From this worktree, run the complete suite in the nightly Linux image while
bind-mounting the real `/Users/renso/Projects/ma-server` dev checkout. Override the
service entry point so this verification does not start or modify the persisted MA
instance:

```bash
MA_SERVER_ROOT=/Users/renso/Projects/ma-server \
docker compose -f docker-compose.dev.yml run --rm --no-deps \
  --entrypoint /bin/sh ma -ec '
    export PYTHONPATH=/ma-server:/tmp
    ln -sfn /ma-server/music_assistant/providers/fastmcp_server /tmp/provider
    /app/venv/bin/uv pip install --quiet --python /app/venv/bin/python \
      fastmcp==3.4.5 pytest==9.0.3 pytest-asyncio==1.3.0 \
      pytest-aiohttp==1.1.0 syrupy==5.0.0 ruff==0.15.7 mypy==1.19.1
    cd /tmp
    /app/venv/bin/python -m pytest -o addopts= -p no:cacheprovider \
      --confcutdir=/tmp/provider-tests /tmp/provider-tests -q
  '
```

Expected: zero failures. Record passed/skipped counts for the PR description.

- [ ] **Step 2: Re-run the no-elicitation and hot-swap scenarios in Linux**

Use the same `docker compose run` command from Step 1, replacing its final pytest
selection with:

```bash
/app/venv/bin/python -m pytest -o addopts= -p no:cacheprovider \
  --confcutdir=/tmp/provider-tests /tmp/provider-tests \
  -q -k 'client_without_elicitation or confirmation_change_hot_swaps or confirmation_setting_matrix'
```

Expected: the standard write reaches its handler, the enabled system prompt returns
the actionable advanced-setting error, and toggling either confirmation key does not
restart or remount the runtime.

- [ ] **Step 3: Run formatting, lint, typing and repository gates**

```bash
ruff format --check provider tests
ruff check provider tests
mypy provider tests
pre-commit run --all-files
```

Expected: every command exits 0.

- [ ] **Step 4: Run upstream rewrite checks**

```bash
python -m pytest -q \
  tests/test_command_parity.py \
  tests/test_provider_command_registry.py \
  tests/test_dynamic_catalog.py
```

After pushing the implementation branch, run the two exact reusable-workflow
facades against it:

```bash
gh workflow run test.yml --ref "$(git branch --show-current)"
gh run list --workflow test.yml --branch "$(git branch --show-current)" --limit 1
```

The `Check rewrite-safe tests` workflow has no manual-dispatch trigger, so open the
PR against `dev` and verify it there together with `Test`:

```bash
gh pr checks --watch
```

Expected: `Test` and `Check rewrite-safe tests` pass. The reusable workflows test
the rewritten upstream import paths, Ruff, manifest pin, generated schemas, and the
current `music-assistant/server@dev` slice.

- [ ] **Step 5: Review the final diff against the specification**

```bash
git diff --check origin/dev...HEAD
git diff --stat origin/dev...HEAD
git grep -n -E 'Confirmation\.(CONFIGURED|ALWAYS)|CONF_DELETE_QUEUE|Tag\.DELETE_QUEUE|delete:queue' -- provider tests README.md
```

Expected: `git diff --check` succeeds; the forbidden-symbol scan has no output; the diff contains only the agreed confirmation, queue, dependency, test and documentation changes.

- [ ] **Step 6: Request code review before changelog/version work**

Invoke `superpowers:requesting-code-review` and review `origin/dev...HEAD`. Address
justified findings with focused regression tests and commits. After human approval,
update `CHANGELOG.md` under a maintainer-selected release version; do not change the
already released `1.0.0` section or `VERSION` without that explicit release decision.
