# Radio Playback MCP Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the ambiguous dynamic-radio flags from the MCP-facing `player_queues/play_media` contract while preserving direct radio-station URI playback.

**Architecture:** Extend the existing declarative `CommandProfile` with canonical arguments that are unavailable through MCP. Apply that declaration both when publishing dynamic input schemas and before binding submitted arguments, leaving the shared execution pipeline command-agnostic.

**Tech Stack:** Python 3.14, pytest, FastMCP, Pydantic-generated JSON Schema, Ruff, mypy, pre-commit.

## Global Constraints

- Follow red/green/refactor TDD; observe the regression tests fail before changing production code.
- Do not preserve compatibility for `radio` or `radio_mode`.
- Preserve `uri` as an alias for canonical `media`.
- Do not change the native Music Assistant handler or any upstream repository.
- Use Sphinx-style docstrings and keep private methods at the bottom of classes.
- Add a `Fixed` changelog entry, but do not modify maintainer-owned `VERSION`.
- Run `pre-commit run --all-files` after code changes.

---

## File Structure

- `provider/command_profiles.py`: declare arguments excluded from the MCP contract and reject them during profile conversion.
- `provider/execution.py`: remove profile-excluded arguments from published command schemas.
- `tests/test_dynamic_catalog.py`: cover the published schema, rejected manual arguments, and unchanged direct Radio URI execution.
- `CHANGELOG.md`: record the user-visible playback fix under version 2.1.1.

### Task 1: Reproduce the ambiguous radio contract

**Files:**
- Modify: `tests/test_dynamic_catalog.py`

**Interfaces:**
- Consumes: `_handler(command: str, target: Any, scope: str = "library.read") -> Any` and `_real_adapter(handler: Any, ...) -> DynamicAPIAdapter`.
- Produces: regression coverage for `ma_api:player_queues/play_media` schema and execution.

- [ ] **Step 1: Add the schema regression test**

```python
async def test_play_media_schema_excludes_dynamic_radio_arguments() -> None:
    """Radio stations play directly without ambiguous dynamic-radio flags."""

    async def play_media(
        queue_id: str,
        media: str,
        radio_mode: bool = False,
    ) -> None:
        del queue_id, media, radio_mode

    adapter = _real_adapter(_handler("player_queues/play_media", play_media))
    entry = (await adapter.visible_entries())[0]
    properties = entry.input_schema["properties"]

    assert "media" in properties
    assert "uri" in properties
    assert "radio" not in properties
    assert "radio_mode" not in properties
```

- [ ] **Step 2: Add the execution rejection test**

```python
@pytest.mark.parametrize("argument", ["radio", "radio_mode"])
async def test_play_media_rejects_dynamic_radio_arguments(argument: str) -> None:
    """Hidden dynamic-radio arguments cannot bypass the published contract."""
    calls: list[tuple[str, str, bool]] = []

    async def play_media(
        queue_id: str,
        media: str,
        radio_mode: bool = False,
    ) -> None:
        calls.append((queue_id, media, radio_mode))

    adapter = _real_adapter(_handler("player_queues/play_media", play_media))

    with pytest.raises(ToolError, match=r"\[invalid_arguments\]"):
        await adapter.call(
            "ma_api:player_queues/play_media",
            {
                "queue_id": "living-room",
                "media": "siriusxm://radio/real-jazz",
                argument: True,
            },
            response_mode="compact",
            fields=None,
            max_items=None,
            ctx=MagicMock(),
        )

    assert calls == []
```

- [ ] **Step 3: Add the direct-play characterization test**

```python
async def test_play_media_passes_radio_uri_without_dynamic_mode() -> None:
    """A Radio URI reaches the native handler with its default direct-play mode."""
    calls: list[tuple[str, str, bool]] = []

    async def play_media(
        queue_id: str,
        media: str,
        radio_mode: bool = False,
    ) -> None:
        calls.append((queue_id, media, radio_mode))

    adapter = _real_adapter(_handler("player_queues/play_media", play_media))

    await adapter.call(
        "ma_api:player_queues/play_media",
        {"queue_id": "living-room", "media": "siriusxm://radio/real-jazz"},
        response_mode="compact",
        fields=None,
        max_items=None,
        ctx=MagicMock(),
    )

    assert calls == [("living-room", "siriusxm://radio/real-jazz", False)]
```

- [ ] **Step 4: Run the focused tests and verify RED**

Run:

```bash
UV_CACHE_DIR=/tmp/ma-provider-mcp-uv-cache uv run pytest \
  tests/test_dynamic_catalog.py::test_play_media_schema_excludes_dynamic_radio_arguments \
  tests/test_dynamic_catalog.py::test_play_media_rejects_dynamic_radio_arguments \
  tests/test_dynamic_catalog.py::test_play_media_passes_radio_uri_without_dynamic_mode -q
```

Expected: the schema test fails because `radio` and `radio_mode` are present; both rejection cases fail because the handler is called. The direct-play characterization case passes.

### Task 2: Exclude deprecated arguments declaratively

**Files:**
- Modify: `provider/command_profiles.py`
- Modify: `provider/execution.py`
- Test: `tests/test_dynamic_catalog.py`

**Interfaces:**
- Consumes: `CommandProfile.argument_aliases`, `CommandProfile.convert_arguments()`, and `DynamicAPIAdapter._entry_input_schema()`.
- Produces: `CommandProfile.excluded_arguments: frozenset[str]`, used consistently by schema publication and execution.

- [ ] **Step 1: Add exclusion metadata and execution validation**

Add the field and the first validation block to `CommandProfile`:

```python
excluded_arguments: frozenset[str] = frozenset()

def convert_arguments(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Translate ergonomic aliases without overriding canonical values."""
    if self.excluded_arguments.intersection(arguments):
        raise ValueError("One or more arguments are unavailable through MCP")
    converted = dict(arguments)
    for alias, canonical in self.argument_aliases.items():
        if alias not in converted:
            continue
        if canonical in converted:
            raise ValueError(f"Use either {alias!r} or {canonical!r}, not both")
        converted[canonical] = converted.pop(alias)
    for name in self.list_arguments:
        value = converted.get(name)
        if value is not None and not isinstance(value, list | tuple | set):
            converted[name] = [value]
    return converted
```

Change the play-media override to:

```python
"player_queues/play_media": {
    "argument_aliases": {"uri": "media"},
    "excluded_arguments": frozenset({"radio_mode"}),
},
```

- [ ] **Step 2: Remove excluded arguments during schema publication**

Replace `DynamicAPIAdapter._entry_input_schema()` with:

```python
@staticmethod
def _entry_input_schema(
    input_schema: Mapping[str, Any],
    profile: CommandProfile | None,
    *,
    allow_impersonation: bool,
) -> dict[str, Any]:
    """Apply provider-owned argument metadata to a compiled input schema."""
    schema = dict(input_schema)
    properties = dict(schema["properties"])
    schema["properties"] = properties
    required = list(schema.get("required", []))
    alias_requirements: list[dict[str, Any]] = []
    if profile is not None:
        for name in profile.excluded_arguments:
            properties.pop(name, None)
        required = [name for name in required if name not in profile.excluded_arguments]
        for alias, canonical in profile.argument_aliases.items():
            canonical_schema = properties.get(canonical)
            if canonical_schema is None:
                continue
            properties[alias] = {
                **canonical_schema,
                "description": f"Compatibility alias for {canonical!r}.",
            }
            if canonical in required:
                required.remove(canonical)
                alias_requirements.append(
                    {"anyOf": [{"required": [canonical]}, {"required": [alias]}]}
                )
    if allow_impersonation:
        properties["user"] = {
            "type": "string",
            "description": "Optional MA user id or username to impersonate.",
        }
    if required:
        schema["required"] = required
    else:
        schema.pop("required", None)
    if alias_requirements:
        schema["allOf"] = alias_requirements
    return schema
```

- [ ] **Step 3: Run the focused tests and verify GREEN**

Run the Task 1 command again.

Expected: all four collected cases pass; neither rejected invocation reaches the handler.

- [ ] **Step 4: Run the complete dynamic-catalog test module**

Run:

```bash
UV_CACHE_DIR=/tmp/ma-provider-mcp-uv-cache uv run pytest tests/test_dynamic_catalog.py -q
```

Expected: all tests pass with no warnings introduced by the change.

### Task 3: Record and verify the fix

**Files:**
- Modify: `CHANGELOG.md`
- Verify: repository-wide source and tests

**Interfaces:**
- Consumes: the completed schema and execution behavior from Task 2.
- Produces: release-note entry and complete verification evidence.

- [ ] **Step 1: Add the next changelog entry**

Insert above 2.1.0:

```markdown
## [2.1.1] - 2026-08-11

### Fixed
- Radio stations invoked through MCP now play directly instead of exposing
  dynamic-radio flags that could route them into unsupported track generation.
```

Do not modify `VERSION`.

- [ ] **Step 2: Run the full test suite**

```bash
UV_CACHE_DIR=/tmp/ma-provider-mcp-uv-cache uv run pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Run the mandatory repository gate**

```bash
UV_CACHE_DIR=/tmp/ma-provider-mcp-uv-cache .venv/bin/pre-commit run --all-files
```

Expected: every hook passes; if formatting modifies a file, inspect it and rerun the gate until clean.

- [ ] **Step 4: Review the final diff**

```bash
git diff --check
git diff --stat HEAD
git diff HEAD -- provider/command_profiles.py provider/execution.py tests/test_dynamic_catalog.py CHANGELOG.md
```

Expected: only the approved contract, tests, and release note are present; `VERSION` is unchanged.

- [ ] **Step 5: Commit the implementation**

```bash
git add provider/command_profiles.py provider/execution.py tests/test_dynamic_catalog.py CHANGELOG.md
git commit -m "fix: remove ambiguous radio playback flags"
```
