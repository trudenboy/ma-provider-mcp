# Upstream API Provider Synchronization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adapt the canonical FastMCP provider to current Music Assistant config-action and impersonation APIs, close empty reverse-sync PRs, restore green provider CI, and update radio-contract PR #253.

**Architecture:** Port only confirmed upstream contracts into the current provider architecture. Structured config-action outcomes flow through the provider lifecycle and the native dynamic command serializer; auth adaptation remains inside the existing impersonation boundary.

**Tech Stack:** Python 3.14, Music Assistant `dev`, `music-assistant-models`, FastMCP 3.4.6, pytest/pytest-asyncio, Ruff, mypy, pre-commit, GitHub Actions.

## Global Constraints

- Base implementation work on current `origin/dev` in an isolated worktree.
- Use feature branch `sync/current-ma-apis`.
- Treat `music-assistant/server` and `trudenboy/ma-server` as read-only.
- Do not hand-edit generated `pyproject.toml`, `docker-compose.dev.yml`, `scripts/docker-init.sh`, or workflows.
- Do not preserve the synthetic `connect_wizard_url` config-entry contract.
- `VERSION` is maintainer-owned and remains unchanged unless the maintainer separately requests a release bump.
- Every production behavior change uses RED/GREEN TDD.
- PR #5452 is a no-op because its upstream-only fixtures do not exist locally.
- Do not merge feature branches or mark #253 ready until their required checks are green.

---

### Task 1: Adopt structured config-action outcomes

**Files:**
- Modify: `provider/provider.py:17-84`
- Modify: `provider/strings.json:90-100`
- Modify: `tests/test_config_lifecycle.py:77-130`

**Interfaces:**
- Consumes: upstream `ConfigActionResult` and `ActionUnavailable`.
- Produces: `MCPServerProvider.handle_config_action(action: str) -> tuple[ConfigEntry, ...] | ConfigActionResult | None`.

- [ ] **Step 1: Replace the synthetic URL test with a failing structured-result test**

Import `ConfigActionResult` and add:

```python
@pytest.mark.asyncio
async def test_open_connect_action_returns_a_one_shot_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The frontend receives a one-shot URL without rebuilding the config form."""
    provider = _provider(MagicMock(), _config())
    get_entries = AsyncMock()
    monkeypatch.setattr(MCPServerProvider, "get_config_entries", get_entries)
    monkeypatch.setattr(MCPServerProvider, "get_config_value", MagicMock(return_value="/mcp/v1"))
    wizard_url = "https://ma.example/mcp/v1/connect?bootstrap=one-shot"
    monkeypatch.setattr(_init_helpers, "_dispatch_open_connect", AsyncMock(return_value=wizard_url))

    result = await provider.handle_config_action("open_connect")

    assert isinstance(result, ConfigActionResult)
    assert result.open_url == wizard_url
    assert result.message is None
    get_entries.assert_not_awaited()
```

- [ ] **Step 2: Add failing error and pass-through tests**

```python
@pytest.mark.asyncio
async def test_open_connect_action_without_url_reports_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing wizard URL is a translated action failure, not a silent redraw."""
    provider = _provider(MagicMock(), _config())
    provider.translation_owner = "provider.fastmcp_server"
    monkeypatch.setattr(MCPServerProvider, "get_config_value", MagicMock(return_value="/mcp/v1"))
    monkeypatch.setattr(_init_helpers, "_dispatch_open_connect", AsyncMock(return_value=None))

    with pytest.raises(ActionUnavailable) as error:
        await provider.handle_config_action("open_connect")

    assert error.value.translation_key == "connect_wizard_unavailable"
    assert error.value.translation_owner == "provider.fastmcp_server"


@pytest.mark.asyncio
@pytest.mark.parametrize("base_result", [None, ConfigActionResult(open_url="https://ma.example/result")])
async def test_unknown_config_action_preserves_native_result(
    monkeypatch: pytest.MonkeyPatch,
    base_result: ConfigActionResult | None,
) -> None:
    """Future MA action outcome types pass through without tuple coercion."""
    provider = _provider(MagicMock(), _config())
    base_handler = AsyncMock(return_value=base_result)
    monkeypatch.setattr(PluginProvider, "handle_config_action", base_handler)

    result = await provider.handle_config_action("future_ma_action")

    assert result is base_result
```

- [ ] **Step 3: Run focused tests and verify RED**

```bash
.venv/bin/python -m pytest tests/test_config_lifecycle.py -k "config_action or open_connect_action" -q
```

Expected: structured result/error/pass-through assertions fail against the tuple contract.

- [ ] **Step 4: Implement the upstream contract**

In `provider/provider.py`:

- remove the runtime `ConfigEntryType` import;
- add `ConfigActionResult` to the `TYPE_CHECKING` import group;
- annotate the override with the exact union;
- inside `open_connect`, runtime-import `ConfigActionResult` and
  `ActionUnavailable`;
- raise `ActionUnavailable` with the upstream message and translation metadata
  when `url is None`;
- otherwise return `ConfigActionResult(open_url=url)`;
- return `await super().handle_config_action(action)` unchanged for other actions.

In `provider/strings.json`, remove `config_entries.connect_wizard_url` and add:

```json
"errors": {
  "connect_wizard_unavailable": "The Connect Wizard could not be opened; check the provider logs."
}
```

- [ ] **Step 5: Verify GREEN**

```bash
.venv/bin/python -m pytest tests/test_config_lifecycle.py tests/test_strings_json.py -q
```

Expected: both modules pass.

- [ ] **Step 6: Commit the config-action adaptation**

```bash
git add provider/provider.py provider/strings.json tests/test_config_lifecycle.py
git commit -m "fix: adopt structured config action results"
```

---

### Task 2: Adapt impersonation to auth-provider identities

**Files:**
- Modify: `provider/execution.py:1421-1439`
- Modify: `tests/test_dynamic_catalog.py`

**Interfaces:**
- Consumes: `music_assistant_models.auth.AuthProviderType.BUILTIN` and upstream `resolve_impersonated_user(mass, provider_type, provider_user_id)`.
- Produces: unchanged MCP `user: str` behavior backed by the new upstream call signature.

- [ ] **Step 1: Add a failing boundary test**

Add the current upstream enum import and test the provider wrapper rather than a mock-only helper:

```python
async def test_impersonation_resolves_a_builtin_ma_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A legacy string user identifier is scoped to MA's built-in auth provider."""
    adapter = _real_adapter(_handler("music/search", lambda: None))
    expected_user = MagicMock(user_id="listener")
    resolve = AsyncMock(return_value=expected_user)
    monkeypatch.setattr(
        "music_assistant.controllers.webserver.helpers.auth_middleware.resolve_impersonated_user",
        resolve,
    )

    result = await adapter._resolve_impersonated_user(None, "listener")

    assert result is expected_user
    resolve.assert_awaited_once_with(adapter.mass, AuthProviderType.BUILTIN, "listener")
```

- [ ] **Step 2: Run the test and verify RED**

```bash
.venv/bin/python -m pytest tests/test_dynamic_catalog.py::test_impersonation_resolves_a_builtin_ma_user -q
```

Expected: FAIL because only `(mass, "listener")` is passed.

- [ ] **Step 3: Implement the new signature**

Import `AuthProviderType` from `music_assistant_models.auth` and change the
upstream call to:

```python
return await auth_middleware.resolve_impersonated_user(
    self.mass,
    AuthProviderType.BUILTIN,
    requested_user,
)
```

- [ ] **Step 4: Verify GREEN and authorization regressions**

```bash
.venv/bin/python -m pytest tests/test_dynamic_catalog.py::test_impersonation_resolves_a_builtin_ma_user tests/test_request_policy_enforcement.py tests/test_target_filters.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the auth adaptation**

```bash
git add provider/execution.py tests/test_dynamic_catalog.py
git commit -m "fix: scope impersonation to builtin identities"
```

---

### Task 3: Localize structured native command results

**Files:**
- Modify: `provider/execution.py:400-425`
- Modify: `tests/test_dynamic_catalog.py`

**Interfaces:**
- Consumes: `music_assistant_models.translations.TRANSLATION_RESOLVER` and `mass.translations.get_translation`.
- Produces: bounded MCP envelopes whose MA model `to_dict()` hooks localize and strip internal translation metadata.

- [ ] **Step 1: Add failing end-to-end adapter tests**

```python
async def test_config_action_result_localizes_in_dynamic_response() -> None:
    """Native config action messages use MA's translation resolver in MCP output."""
    async def invoke() -> ConfigActionResult:
        return ConfigActionResult(
            translation_key="cleanup.result",
            translation_owner="core.cache",
            translation_args=[3],
        )

    adapter = _real_adapter(_handler("config/core/invoke_action", invoke, "config.core.write"))
    adapter.mass.translations.get_translation.side_effect = (
        lambda key, owner=None, params=None: f"{key}|{owner}|{','.join(params or ())}"
    )

    response = await adapter.call(
        "ma_api:config/core/invoke_action",
        {},
        response_mode="full",
        fields=None,
        max_items=None,
        ctx=MagicMock(),
    )

    assert response["data"] == {
        "message": "config_actions.cleanup.result|core.cache|3",
        "open_url": None,
    }


async def test_config_action_open_url_survives_dynamic_response() -> None:
    """A one-shot action URL reaches MCP clients without translation metadata."""
    async def invoke() -> ConfigActionResult:
        return ConfigActionResult(open_url="https://ma.example/result")

    adapter = _real_adapter(_handler("config/providers/invoke_action", invoke, "config.providers.write"))
    response = await adapter.call(
        "ma_api:config/providers/invoke_action",
        {},
        response_mode="full",
        fields=None,
        max_items=None,
        ctx=MagicMock(),
    )

    assert response["data"] == {
        "message": None,
        "open_url": "https://ma.example/result",
    }
```

- [ ] **Step 2: Run the tests and verify RED**

```bash
.venv/bin/python -m pytest tests/test_dynamic_catalog.py -k "config_action_result_localizes or config_action_open_url" -q
```

Expected: the localized test exposes `translation_key`, `translation_args`, and
`translation_owner` instead of the translated message.

- [ ] **Step 3: Bind MA translation resolution during envelope serialization**

Import `TRANSLATION_RESOLVER` from `music_assistant_models.translations`. In
`DynamicAPIAdapter._call`, wrap only the final `_bounded_envelope` call:

```python
translation_token = TRANSLATION_RESOLVER.set(self.mass.translations.get_translation)
try:
    return self._bounded_envelope(
        name,
        result,
        response_mode=response_mode,
        fields=fields,
        max_items=max_items,
        profile=invocation.entry.profile,
    )
finally:
    TRANSLATION_RESOLVER.reset(translation_token)
```

This uses MA models' own `__post_serialize__` contract for every native model and
does not special-case `ConfigActionResult`.

- [ ] **Step 4: Verify GREEN and serializer regressions**

```bash
.venv/bin/python -m pytest tests/test_dynamic_catalog.py tests/test_dynamic_serialization.py -q
```

Expected: both modules pass.

- [ ] **Step 5: Commit the dynamic translation context**

```bash
git add provider/execution.py tests/test_dynamic_catalog.py
git commit -m "fix: localize native action outcomes"
```

---

### Task 4: Document, verify, and publish the provider adaptation

**Files:**
- Modify: `CHANGELOG.md`
- Include: `docs/superpowers/specs/2026-08-11-upstream-provider-sync-design.md`
- Include: both implementation plan documents.

**Interfaces:**
- Consumes: Tasks 1-3 and the approved design.
- Produces: one focused draft provider PR against `dev`, plus accurate closure of empty reverse-sync PRs.

- [ ] **Step 1: Add a changelog entry without changing VERSION**

Add this block above `2.1.0`. Do not add #5452 as a code change and do not
modify `VERSION`:

```markdown
## [2.1.1] - 2026-08-11

### Fixed
- Settings actions now return one-shot messages and URLs through Music
  Assistant's structured result contract without redrawing the form.
- User impersonation works with Music Assistant's auth-provider identities,
  and native action outcomes are localized before reaching MCP clients.
```

- [ ] **Step 2: Run focused and full verification**

```bash
.venv/bin/python -m pytest tests/test_config_lifecycle.py tests/test_dynamic_catalog.py tests/test_dynamic_serialization.py tests/test_request_policy_enforcement.py -q
.venv/bin/python -m pytest -q
UV_CACHE_DIR=/tmp/ma-provider-mcp-sync-uv-cache .venv/bin/pre-commit run --all-files
git diff --check origin/dev...HEAD
```

Expected: full pytest and every pre-commit hook pass against current MA `dev`.

- [ ] **Step 3: Commit documentation**

```bash
git add CHANGELOG.md docs/superpowers/specs/2026-08-11-upstream-provider-sync-design.md docs/superpowers/plans/2026-08-11-fastmcp-wrapper-sync.md docs/superpowers/plans/2026-08-11-upstream-api-provider-sync.md
git commit -m "docs: record upstream provider synchronization"
```

- [ ] **Step 4: Push and create the replacement draft PR**

Use `github:yeet` against `trudenboy/ma-provider-mcp:dev`. Title:

```text
Sync FastMCP with current Music Assistant APIs
```

The PR body links upstream #5402, #5417, and #5452; identifies #5452 as a no-op;
and reports RED/GREEN and complete verification evidence.

- [ ] **Step 5: Close the empty reverse-sync PRs with precise reasons**

After the replacement PR URL exists, close #241 as superseded by that PR and
close #243 as a no-op because its upstream test modules do not exist locally:

```bash
sync_pr_url=$(gh pr list --repo trudenboy/ma-provider-mcp --head sync/current-ma-apis --state open --json url --jq '.[0].url')
gh pr close 241 --repo trudenboy/ma-provider-mcp --comment "Closing this empty reverse-sync scaffold. The applicable ConfigActionResult contract from upstream #5402 is implemented and tested in ${sync_pr_url}."
gh pr close 243 --repo trudenboy/ma-provider-mcp --comment "Closing as a reverse-sync no-op. Upstream #5452 only deduplicates provider test fixtures for modules that no longer exist in this repository's current flattened test architecture."
```

---

### Task 5: Integrate generated wrappers and refresh radio PR #253

**Files:**
- Generated through `ma-provider-tools`: `pyproject.toml`, `docker-compose.dev.yml`, `scripts/docker-init.sh`.
- Existing branch: `fix/radio-playback-contract` / PR #253.

**Interfaces:**
- Consumes: green tools PR, its normal distribution PR, and the green provider API PR.
- Produces: green `dev` plus an updated, ready-for-review PR #253.

- [ ] **Step 1: Stop at the integration checkpoint**

Use `superpowers:finishing-a-development-branch` for both implementation
branches. Merge only after the user selects integration and required checks are
green. The tools PR lands before its generated provider distribution PR.

- [ ] **Step 2: Verify generated wrapper output on provider dev**

After distribution lands, update local `dev` with `git pull --ff-only` and run:

```bash
docker compose -f docker-compose.dev.yml config --format json
.venv/bin/python -m pytest tests/test_docs.py -q
.venv/bin/python -m pytest -q
UV_CACHE_DIR=/tmp/ma-provider-mcp-sync-uv-cache .venv/bin/pre-commit run --all-files
```

Expected: Compose reports `/ma-server`, all tests pass, and mypy has no upstream-signature errors.

- [ ] **Step 3: Update PR #253 without rewriting published history**

In the preserved radio worktree:

```bash
git fetch origin dev
git merge --no-edit origin/dev
.venv/bin/python -m pytest -q
UV_CACHE_DIR=/tmp/ma-provider-mcp-radio-uv-cache .venv/bin/pre-commit run --all-files
git push origin fix/radio-playback-contract
```

Expected: merge succeeds without radio-contract conflicts and all checks pass.

- [ ] **Step 4: Confirm GitHub checks and mark #253 ready**

```bash
gh pr checks 253 --repo trudenboy/ma-provider-mcp --watch
gh pr ready 253 --repo trudenboy/ma-provider-mcp
```

Only run `gh pr ready` after every required check is successful. Keep the radio
worktree for review follow-up.
