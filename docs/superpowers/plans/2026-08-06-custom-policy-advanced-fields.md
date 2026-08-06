# Custom Policy Advanced Fields Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show each 26-capability Custom policy matrix only when its profile selector is `Custom` and Music Assistant's Advanced mode is enabled.

**Architecture:** Keep the existing profile selectors and `depends_on` relationships unchanged. Mark only matrix entries as advanced, and add concise selector guidance so users know where the Custom controls appear.

**Tech Stack:** Python 3.13, Music Assistant `ConfigEntry`, pytest, JSON localization strings, Ruff, mypy, pre-commit.

## Global Constraints

- Default and per-token profile selectors remain visible outside Advanced mode.
- Every Custom capability entry retains its current selector dependency and defaults to `deny`.
- No policy parsing or enforcement behavior changes.

---

### Task 1: Make Custom capability matrices advanced-only

**Files:**
- Modify: `tests/test_policy_config.py`
- Modify: `tests/test_strings_json.py`
- Modify: `provider/config.py`
- Modify: `provider/provider.py` (only if the full type gate exposes the known MA override drift)
- Modify: `provider/strings.json`

- [x] **Step 1: Add failing configuration-schema tests**

Extend `test_dynamic_entries_have_conditional_matrices_and_hashed_token_keys` to require ordinary selectors, advanced matrix entries, and guidance on the dynamic per-token selector:

```python
assert by_key[CONF_DEFAULT_POLICY].advanced is False
assert by_key[selector_key].advanced is False
assert by_key[selector_key].description == (
    "Select Custom and enable Advanced mode to edit individual capability modes."
)
assert all(entry.advanced is True for entry in default_matrix)
assert all(entry.advanced is True for entry in token_matrix)
```

Extend the strings contract test to require the same guidance on the static default selector:

```python
assert "Advanced mode" in entries["policy_default"]["description"]
```

- [x] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
uv run pytest -q \
  tests/test_policy_config.py::test_dynamic_entries_have_conditional_matrices_and_hashed_token_keys \
  tests/test_strings_json.py::test_strings_expose_only_v2_policy_configuration_contract
```

Expected: failure because Custom matrix entries are not advanced and the selector guidance is absent.

- [x] **Step 3: Implement the minimal schema change**

In `_custom_matrix`, set the capability entries to advanced while preserving their existing dependency:

```python
advanced=True,
depends_on=selector_key,
depends_on_value=PolicyProfile.CUSTOM.value,
```

In `_policy_selector`, add the runtime description only for dynamically named per-token selectors:

```python
description=(
    "Select Custom and enable Advanced mode to edit individual capability modes."
    if label is not None
    else None
),
```

Append the equivalent sentence to `config_entries.policy_default.description` in `provider/strings.json`.

- [x] **Step 4: Run focused tests and confirm GREEN**

Run:

```bash
uv run pytest -q tests/test_policy_config.py tests/test_strings_json.py
```

Expected: all policy configuration and string contract tests pass.

- [x] **Step 5: Run the complete quality gate**

Run:

```bash
uv run pytest -q
uv run ruff check provider tests
uv run ruff format --check provider tests
uv run mypy provider tests
pre-commit run --all-files
```

Expected: every command exits successfully.

The full gate exposed a stale `handle_config_action` return annotation introduced by
an earlier merge. Align it with the current MA base class and the method's actual
always-tuple behavior, then rerun the complete gate.

- [x] **Step 6: Commit the implementation**

```bash
git add provider/config.py provider/strings.json \
  tests/test_policy_config.py tests/test_strings_json.py \
  docs/superpowers/plans/2026-08-06-custom-policy-advanced-fields.md
git commit -m "fix: hide custom policy fields outside advanced mode"
```
