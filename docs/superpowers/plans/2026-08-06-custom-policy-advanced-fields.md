# Custom Policy Advanced Fields Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show each 26-capability Custom policy matrix only when its profile selector is `Custom` and Music Assistant's Advanced mode is enabled, with the Advanced requirement visible in the Custom option title.

**Architecture:** Keep the existing profile selectors and `depends_on` relationships unchanged. Mark only matrix entries as advanced, and separate each profile option's stored value from its visible title so Custom remains compatible while advertising the Advanced requirement.

**Tech Stack:** Python 3.13, Music Assistant `ConfigEntry`, pytest, JSON localization strings, Ruff, mypy, pre-commit.

## Global Constraints

- Default and per-token profile selectors remain visible outside Advanced mode.
- Every Custom capability entry retains its current selector dependency and defaults to `deny`.
- The Custom option title is `Custom (Advanced mode required)` while its value remains `Custom`.
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

### Task 2: Advertise the Advanced requirement in the Custom option

**Files:**
- Modify: `tests/test_policy_config.py`
- Modify: `provider/config.py`

**Interfaces:**
- Consumes: `_policy_selector(key: str, label: str | None, *, allow_inherit: bool) -> ConfigEntry`
- Produces: profile options whose stored values remain unchanged and whose Custom title is `Custom (Advanced mode required)`

- [x] **Step 1: Add a failing option title/value test**

Extend `test_dynamic_entries_have_conditional_matrices_and_hashed_token_keys` with literal expected pairs for both selectors:

```python
assert [(option.value, option.title) for option in by_key[CONF_DEFAULT_POLICY].options] == [
    ("Read-only", "Read-only"),
    ("Home control", "Home control"),
    ("Interactive admin", "Interactive admin"),
    ("Trusted", "Trusted"),
    ("Custom", "Custom (Advanced mode required)"),
]
assert [(option.value, option.title) for option in by_key[selector_key].options][-1] == (
    "Custom",
    "Custom (Advanced mode required)",
)
```

- [x] **Step 2: Run the focused test and confirm RED**

Run:

```bash
uv run pytest -q \
  tests/test_policy_config.py::test_dynamic_entries_have_conditional_matrices_and_hashed_token_keys
```

Expected: failure because the Custom option title is currently `Custom`.

- [x] **Step 3: Implement the distinct Custom display title**

Build each option with its existing value and a conditional title:

```python
options=[
    ConfigValueOption(
        value=value,
        title=(
            "Custom (Advanced mode required)"
            if value == PolicyProfile.CUSTOM.value
            else value
        ),
    )
    for value in values
],
```

- [x] **Step 4: Run focused policy configuration tests and confirm GREEN**

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
uv run pre-commit run --all-files
```

Expected: every command exits successfully.

- [x] **Step 6: Commit the implementation**

```bash
git add provider/config.py tests/test_policy_config.py \
  docs/superpowers/plans/2026-08-06-custom-policy-advanced-fields.md
git commit -m "fix: label Custom profile as Advanced-only"
```
