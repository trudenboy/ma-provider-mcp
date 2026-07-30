# Native Music Assistant Command Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the custom FastMCP domain-tool and `mcp_api:*` recipe surfaces with one registry-backed `ma_api:*` catalog, while fixing every confirmed schema, serialization, policy, error, and discovery defect.

**Architecture:** FastMCP registers only `search_tools`, `get_tool_schema`, and `call_tool`, plus the existing resources and prompts. Catalog entries are compiled from `mass.command_handlers`; declarative profiles add ergonomics and policy, while eight provider-owned commands (`fastmcp/queue/remove_items_safe` and seven read-only `fastmcp/debug/*` commands) register into that same Music Assistant registry because they provide semantics absent from native MA.

**Tech Stack:** Python 3.14, Music Assistant Server runtime API, FastMCP 3.2–3.x, Pydantic TypeAdapter, pytest/pytest-asyncio, Ruff, mypy, pre-commit, Docker Compose.

## Global Constraints

- `tools/list` exposes exactly `search_tools`, `get_tool_schema`, and `call_tool`.
- Every executable catalog entry comes from the live `mass.command_handlers` registry and uses the `ma_api:*` namespace.
- Do not retain FastMCP domain subservers, `RecipeBinding`, `ingest_curated()`, `CURATED_RECIPE_SOURCES`, `CURATED_RECIPE_SCOPES`, or executable `mcp_api:*` entries.
- Preserve existing MCP resources, prompts, authentication, user/scope/provider/player filters, confirmation, compact projection, and response limits.
- Native Music Assistant commands are never wrapped merely for naming, schema, projection, or aliases.
- Provider commands are plain MA API handlers without FastMCP decorators or a second dispatcher.
- `player_queues/delete_item`, `player_queues/clear`, and `fastmcp/queue/remove_items_safe` always require destructive confirmation through MCP.
- System sensitivity is independent from `readOnlyHint`, `destructiveHint`, and `idempotentHint`.
- Keep Python `>=3.14` and `fastmcp>=3.2,<4.0`; add no runtime dependency.
- Preserve compatibility with both the installed MA `register_api_command(..., authenticated, required_role, alias)` signature and newer builds that additionally accept `required_scope`.
- Do not alter Music Assistant queue auto-fill behavior.
- Use test-first changes and a focused commit after every task.
- Treat `/Users/renso/Projects/ma-server` as the authoritative fresh Music
  Assistant `dev` source tree for this implementation. Run provider tests in a
  complete Linux Music Assistant virtual environment with that tree mounted as
  source; do not substitute a reduced host-only dependency installation.
- Tests that need a running `MusicAssistant` object reuse the canonical `mass`
  fixture from the MA source tree's `tests/conftest.py`. Mocks remain acceptable
  only for pure isolated behavior that does not depend on MA controller state.

---

## File Structure

New focused modules:

- `provider/dynamic_serialization.py` — deterministic conversion of MA values to JSON values.
- `provider/dynamic_signatures.py` — handler schema compilation and strict invocation binding.
- `provider/command_policy.py` — risk, annotations, tags, confirmation, and argument preflight policy.
- `provider/resource_helpers.py` — brief/resource conversion helpers that survive removal of `provider/tools/`.
- `provider/commands/__init__.py` — provider-command exports.
- `provider/commands/authorization.py` — in-handler MA user/scope/config-tag checks.
- `provider/commands/queue.py` — safe batch queue deletion command.
- `provider/commands/debug.py` — seven read-only provider diagnostics commands.
- `provider/commands/registry.py` — registration callbacks and provider-owned event-buffer lifecycle.
- `tests/test_dynamic_serialization.py`, `tests/test_dynamic_signatures.py`, `tests/test_command_policy.py` — isolated defect regressions.
- `tests/test_provider_command_registry.py`, `tests/test_provider_commands_queue.py`, `tests/test_provider_commands_debug.py` — extension behavior and lifecycle.
- `tests/integration/test_live_catalog.py` — opt-in authenticated Docker MCP verification.

The existing `provider/dynamic_api.py`, `provider/meta_discovery.py`,
`provider/command_profiles.py`, `provider/provider.py`, and `provider/server.py` remain
the integration points but lose responsibilities moved into the focused modules.

---

### Task 1: Safe Music Assistant Result Serialization

**Files:**
- Create: `provider/dynamic_serialization.py`
- Create: `tests/test_dynamic_serialization.py`
- Modify: `provider/dynamic_api.py:683-839`

**Interfaces:**
- Consumes: arbitrary return values from MA command handlers.
- Produces: `json_value(value: Any) -> JSONValue` for the response limiter and compact projector.

- [ ] **Step 1: Write failing regressions for MA collection models**

```python
@dataclass(frozen=True)
class Artist:
    item_id: str
    name: str


class UniqueList(list[Artist]):
    def __init__(self, values: list[Artist]) -> None:
        if any(not isinstance(value, Artist) for value in values):
            raise TypeError("UniqueList accepts Artist values")
        super().__init__(values)


@dataclass
class Track:
    uri: str
    artists: UniqueList


def test_dataclass_unique_list_is_converted_field_by_field() -> None:
    value = Track("library://track/1", UniqueList([Artist("7", "Artist")]))
    assert json_value(value) == {
        "uri": "library://track/1",
        "artists": [{"item_id": "7", "name": "Artist"}],
    }


def test_to_dict_precedes_dataclass_conversion() -> None:
    @dataclass
    class Item:
        secret: str

        def to_dict(self) -> dict[str, str]:
            return {"masked": "***"}

    assert json_value(Item("do-not-return")) == {"masked": "***"}


def test_set_output_is_deterministic() -> None:
    assert json_value({"beta", "alpha"}) == ["alpha", "beta"]
```

Also cover `model_dump(mode="json")`, enums, date/datetime, UUID, Path,
frozenset, nested mappings, repeated non-cyclic objects, and a cyclic dataclass.

- [ ] **Step 2: Run the focused tests and verify the missing module failure**

Run: `uv run pytest tests/test_dynamic_serialization.py -v`

Expected: FAIL during collection because `provider.dynamic_serialization` does not exist.

- [ ] **Step 3: Implement one deterministic recursive serializer**

```python
type JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]


def json_value(value: Any) -> JSONValue:
    """Convert one MA result without reconstructing custom collection types."""
    return _json_value(value, active_ids=set())


def _json_value(value: Any, active_ids: set[int]) -> JSONValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Enum):
        return _json_value(value.value, active_ids)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID | Path):
        return str(value)

    object_id = id(value)
    if object_id in active_ids:
        return f"<{type(value).__module__}.{type(value).__qualname__}:cycle>"
    active_ids.add(object_id)
    try:
        if callable(to_dict := getattr(value, "to_dict", None)):
            return _json_value(to_dict(), active_ids)
        if callable(model_dump := getattr(value, "model_dump", None)):
            return _json_value(model_dump(mode="json"), active_ids)
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return {
                field.name: _json_value(getattr(value, field.name), active_ids)
                for field in dataclasses.fields(value)
            }
        if isinstance(value, Mapping):
            return {str(key): _json_value(child, active_ids) for key, child in value.items()}
        if isinstance(value, set | frozenset):
            children = [_json_value(child, active_ids) for child in value]
            return sorted(children, key=lambda child: json.dumps(child, sort_keys=True))
        if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
            return [_json_value(child, active_ids) for child in value]
        return f"<{type(value).__module__}.{type(value).__qualname__}>"
    finally:
        active_ids.remove(object_id)
```

Replace `DynamicAPIAdapter._json_value_deep()` and scalar fallbacks with
`json_value()`. Keep bounding, projection, and byte measurement in
`dynamic_api.py`.

- [ ] **Step 4: Run serialization and existing response-bound tests**

Run: `uv run pytest tests/test_dynamic_serialization.py tests/test_dynamic_catalog.py -v`

Expected: PASS, including Track/Album/Player-shaped `UniqueList` values and existing compact/full envelopes.

- [ ] **Step 5: Commit**

```bash
git add provider/dynamic_serialization.py provider/dynamic_api.py tests/test_dynamic_serialization.py
git commit -m "fix: serialize Music Assistant models safely"
```

---

### Task 2: Truthful Handler Schemas and Variadic Binding

**Files:**
- Create: `provider/dynamic_signatures.py`
- Create: `tests/test_dynamic_signatures.py`
- Modify: `provider/dynamic_api.py:324-646`
- Modify: `provider/command_profiles.py:149-303`
- Modify: `tests/test_dynamic_catalog.py`

**Interfaces:**
- Consumes: `inspect.Signature`, handler `type_hints`, and validated MCP argument objects.
- Produces: `CompiledSignature.input_schema`, `CompiledSignature.output_schema()`, and `CompiledSignature.parse(arguments)`.

- [ ] **Step 1: Write failing tests for the seven `library_items` signature shape**

```python
async def library_items(
    favorite: bool | None = None,
    limit: int = 500,
    **kwargs: Any,
) -> list[Track]:
    return []


def test_kwargs_is_not_a_required_property() -> None:
    compiled = compile_signature(inspect.signature(library_items), get_type_hints(library_items))
    assert "kwargs" not in compiled.input_schema["properties"]
    assert "kwargs" not in compiled.input_schema.get("required", [])
    assert compiled.input_schema["additionalProperties"] is False


def test_named_arguments_execute_without_kwargs_container() -> None:
    compiled = compile_signature(inspect.signature(library_items), get_type_hints(library_items))
    assert compiled.parse({"favorite": True, "limit": 10}) == {
        "favorite": True,
        "limit": 10,
    }


def test_var_positional_handler_is_incompatible() -> None:
    def invalid(first: str, *values: str) -> None:
        pass

    with pytest.raises(UnsupportedSignatureError, match=r"\*values"):
        compile_signature(inspect.signature(invalid), get_type_hints(invalid))
```

Parametrize the real command names for albums, artists, audiobooks, genres,
playlists, podcasts, and tracks. Add a test proving `list[Track]` output is not
reported as `{"type": "string"}` and an unresolved type produces
`{"x-python-type": ...}` without a `type` key.

- [ ] **Step 2: Run the new tests and verify the current fake `kwargs` failure**

Run: `uv run pytest tests/test_dynamic_signatures.py -v`

Expected: FAIL because the compiler still emits a required `kwargs` property.

- [ ] **Step 3: Implement the compiler and binder**

```python
@dataclass(frozen=True, slots=True)
class CompiledSignature:
    signature: inspect.Signature
    parse_signature: inspect.Signature
    type_hints: Mapping[str, Any]
    input_schema: dict[str, Any]
    allow_extra_kwargs: bool

    def parse(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        known = set(self.parse_signature.parameters)
        extras = {key: value for key, value in arguments.items() if key not in known}
        if extras and not self.allow_extra_kwargs:
            names = ", ".join(sorted(extras))
            raise ValueError(f"Unexpected argument(s): {names}")
        parsed = parse_arguments(
            self.parse_signature,
            self.type_hints,
            {key: value for key, value in arguments.items() if key in known},
            strict=True,
        )
        parsed.update(extras)
        return parsed


def compile_signature(
    signature: inspect.Signature,
    type_hints: Mapping[str, Any],
    *,
    allow_extra_kwargs: bool = False,
) -> CompiledSignature:
    variadic = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind is inspect.Parameter.VAR_POSITIONAL
    ]
    if variadic:
        raise UnsupportedSignatureError(f"Unsupported variadic parameter *{variadic[0].name}")
    named = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind is not inspect.Parameter.VAR_KEYWORD
    ]
    parse_signature = signature.replace(parameters=named)
    schema = _input_schema(parse_signature, type_hints)
    schema["additionalProperties"] = allow_extra_kwargs
    return CompiledSignature(signature, parse_signature, type_hints, schema, allow_extra_kwargs)
```

Add `allow_extra_kwargs: bool = False` to `CommandProfile`; no current MA profile
enables it. Use Pydantic `TypeAdapter(...).json_schema()` for resolvable output
types, and use an unconstrained `x-python-type` fallback when resolution fails.

- [ ] **Step 4: Route compilation and invocation through `CompiledSignature`**

Store the compiled object on `DynamicEntry`; apply profile argument aliases before
`compiled_signature.parse()`. Remove `_input_schema`, `_output_schema`, and the
variadic placeholder handling from `DynamicAPIAdapter`.

Run: `uv run pytest tests/test_dynamic_signatures.py tests/test_dynamic_catalog.py -v`

Expected: PASS; all seven commands accept ordinary named arguments and no schema requires `kwargs`.

- [ ] **Step 5: Commit**

```bash
git add provider/dynamic_signatures.py provider/dynamic_api.py provider/command_profiles.py tests/test_dynamic_signatures.py tests/test_dynamic_catalog.py
git commit -m "fix: compile dynamic command signatures correctly"
```

---

### Task 3: Independent Command Policy, Annotations, and Secret Guards

**Files:**
- Create: `provider/command_policy.py`
- Create: `tests/test_command_policy.py`
- Modify: `provider/command_profiles.py`
- Modify: `provider/dynamic_api.py:51-87,280-348,592-646`
- Modify: `provider/config_io/secret_handler.py`

**Interfaces:**
- Produces: `CommandDecision` from `resolve_command_policy(command, scope, profile)`.
- Produces: `preflight_command(mass, decision, arguments, allowed_tags)` before confirmation/execution.
- Preserves imports of `DynamicRisk` and `DynamicPolicy` from `provider.dynamic_api` by re-exporting them during migration.

- [ ] **Step 1: Write the policy failures found in live testing**

```python
@pytest.mark.parametrize("command", ["player_queues/delete_item", "player_queues/clear"])
def test_direct_queue_deletes_are_confirmed_destructive_writes(command: str) -> None:
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
    decision = resolve_command_policy("fastmcp/debug/health", "system.read", profile=None)
    assert decision.risk is DynamicRisk.SYSTEM
    assert decision.annotations["readOnlyHint"] is True
    assert decision.annotations["destructiveHint"] is False
    assert decision.annotations["idempotentHint"] is True


def test_unknown_command_fails_into_system_gate() -> None:
    assert resolve_command_policy("future/new_command", None, None).risk is DynamicRisk.SYSTEM
```

Add tests for exact override before family override, MA scope fallback, required
tags, disabled user, provider/player filters, impersonation, and a secure config
value rejected unless `config:write:secret` is enabled.

- [ ] **Step 2: Run policy tests and verify delete/clear are currently control operations**

Run: `uv run pytest tests/test_command_policy.py tests/test_dynamic_catalog.py -v`

Expected: FAIL on queue classification and debug annotations.

- [ ] **Step 3: Implement policy data independent from behavior hints**

```python
class Confirmation(StrEnum):
    NEVER = "never"
    CONFIGURED = "configured"
    ALWAYS = "always"


@dataclass(frozen=True, slots=True)
class CommandDecision:
    risk: DynamicRisk
    annotations: Mapping[str, bool]
    required_tags: frozenset[str] = frozenset()
    confirmation: Confirmation = Confirmation.NEVER
    preflight: str | None = None


EXACT_POLICIES: dict[str, CommandDecision] = {
    "player_queues/delete_item": destructive_write(Tag.DELETE_QUEUE),
    "player_queues/clear": destructive_write(Tag.DELETE_QUEUE),
    "fastmcp/queue/remove_items_safe": destructive_write(Tag.DELETE_QUEUE),
    "fastmcp/debug/tail_log": readonly_system(Tag.DEBUG_LOGS),
    "fastmcp/debug/log_stats": readonly_system(Tag.DEBUG_LOGS),
    "fastmcp/debug/recent_events": readonly_system(Tag.DEBUG_EVENTS),
    "fastmcp/debug/event_buffer_stats": readonly_system(Tag.DEBUG_EVENTS),
    "fastmcp/debug/health": readonly_system(Tag.DEBUG_PROVIDERS),
    "fastmcp/debug/routes": readonly_system(Tag.DEBUG_PROVIDERS),
    "fastmcp/debug/packages": readonly_system(Tag.DEBUG_PROVIDERS),
}
```

Define family policies for native music, player, queue, config, diagnostics, and
provider commands using the existing `Tag` values:

```python
FAMILY_TAGS = (
    family("music/playlists/", read=Tag.QUERY_LIBRARY, write=Tag.EDIT_PLAYLISTS,
           delete=Tag.DELETE_PLAYLISTS),
    family("music/favorites/", read=Tag.QUERY_LIBRARY, write=Tag.EDIT_FAVORITES,
           delete=Tag.DELETE_FAVORITES),
    family("music/", read=Tag.QUERY_LIBRARY, control=Tag.CONTROL_MEDIA,
           write=Tag.EDIT_LIBRARY, delete=Tag.DELETE_LIBRARY),
    family("players/cmd/volume", control=Tag.CONTROL_VOLUME),
    family("players/cmd/", control=Tag.CONTROL_PLAYERS),
    family("players/", read=Tag.QUERY_PLAYERS),
    family("player_queues/", read=Tag.QUERY_QUEUE, control=Tag.EDIT_QUEUE,
           delete=Tag.DELETE_QUEUE),
    family("metadata/", read=Tag.QUERY_METADATA),
    family("config/providers/", read=Tag.CONFIG_READ, write=Tag.CONFIG_WRITE_PROVIDER),
    family("config/core/", read=Tag.CONFIG_READ, write=Tag.CONFIG_WRITE_CORE),
    family("config/players/", read=Tag.CONFIG_READ, write=Tag.CONFIG_WRITE_PLAYER),
    family("diagnostics/", read=Tag.DEBUG_INSPECT),
)
```

Resolve the operation column from the exact policy first, then the longest matching
family prefix, then destructive verbs, then MA scope. Config save families set
`preflight="config_secret_write"`; the preflight loads target entries through
`mass.config.get_provider_config_entries`, `get_core_config_entries`, or
`get_player_config_entries`, then calls `gate_secret_writes()` atomically.

- [ ] **Step 4: Apply decisions on discovery and again immediately before execution**

Visibility requires both `DynamicPolicy.allows(decision.risk)` and
`tags_visible(decision.required_tags, allowed_tags)`. Invocation re-resolves the
live entry, repeats scope/filter/tag checks, runs preflight, then confirms according
to `Confirmation.ALWAYS` or the configured confirmation flag.

Run: `uv run pytest tests/test_command_policy.py tests/test_dynamic_catalog.py tests/test_config_secret.py -v`

Expected: PASS; queue delete/clear cannot bypass elicitation and ordinary non-secret config saves do not require the secret tag.

- [ ] **Step 5: Commit**

```bash
git add provider/command_policy.py provider/command_profiles.py provider/dynamic_api.py provider/config_io/secret_handler.py tests/test_command_policy.py tests/test_dynamic_catalog.py tests/test_config_secret.py
git commit -m "fix: enforce unified command policy"
```

---

### Task 4: Cached Registry Snapshots and Diagnostic Errors

**Files:**
- Modify: `provider/dynamic_api.py:61-348,615-683`
- Modify: `tests/test_dynamic_catalog.py`

**Interfaces:**
- Produces: immutable `CatalogSnapshot(fingerprint, entries)` and request-filtered `CatalogView`.
- Produces: `DynamicAPIAdapter.base_snapshot()` for meta-discovery index construction.

- [ ] **Step 1: Add failing snapshot, concurrency, and empty-error tests**

```python
async def test_concurrent_catalog_reads_compile_once(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _real_adapter(_handler("music/search", search))
    compile_spy = MagicMock(wraps=adapter._compile_entry)
    monkeypatch.setattr(adapter, "_compile_entry", compile_spy)
    await asyncio.gather(*(adapter.visible_entries() for _ in range(20)))
    assert compile_spy.call_count == 1


async def test_registry_replacement_changes_fingerprint_without_restart() -> None:
    first = await adapter.base_snapshot()
    mass.command_handlers["music/search"] = replacement_handler
    second = await adapter.base_snapshot()
    assert second.fingerprint != first.fingerprint
    assert second.entries[0].handler is replacement_handler


async def test_empty_upstream_exception_names_type_and_command() -> None:
    handler.target.side_effect = IndexError()
    with pytest.raises(ToolError, match=r"music/search.*IndexError"):
        await adapter.call("ma_api:music/search", {}, response_mode="compact", fields=None, max_items=None, ctx=ctx)
```

Also prove cached base descriptors are shared while two users with different scopes
receive different `CatalogView.entries`.

- [ ] **Step 2: Run the focused adapter tests**

Run: `uv run pytest tests/test_dynamic_catalog.py -k 'concurrent or fingerprint or exception or visibility' -v`

Expected: FAIL because every request walks the registry and empty exceptions render no useful message.

- [ ] **Step 3: Add immutable snapshots and one single-flight lock**

```python
type CatalogFingerprint = tuple[int, tuple[tuple[str, int], ...]]


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    fingerprint: CatalogFingerprint
    entries: tuple[DynamicEntry, ...]


@dataclass(frozen=True, slots=True)
class CatalogView:
    fingerprint: CatalogFingerprint
    entries: tuple[DynamicEntry, ...]


async def base_snapshot(self) -> CatalogSnapshot:
    fingerprint = self._registry_fingerprint()
    if self._snapshot is not None and self._snapshot.fingerprint == fingerprint:
        return self._snapshot
    async with self._snapshot_lock:
        fingerprint = self._registry_fingerprint()
        if self._snapshot is None or self._snapshot.fingerprint != fingerprint:
            self._snapshot = self._compile_snapshot(fingerprint)
        return self._snapshot


async def visible_catalog(self) -> CatalogView:
    snapshot = await self.base_snapshot()
    auth = await self._authentication()
    visible = tuple(entry for entry in snapshot.entries if self._entry_is_visible(entry, auth))
    return CatalogView(snapshot.fingerprint, visible)
```

Build the fingerprint as `(CATALOG_REVISION, sorted_command_handler_pairs)`, where
each pair is `(command, id(handler))`. Increment `CATALOG_REVISION` whenever static
profile/policy compilation semantics change. Compile schemas, descriptions,
profiles, and annotations once. Filter
authentication, scopes, player/provider restrictions, risk gates, and tags on every
request without storing caller state in the snapshot.

- [ ] **Step 4: Normalize execution failures without masking actionable messages**

```python
def _command_error(command: str, exc: Exception) -> ToolError:
    detail = str(exc).strip() or type(exc).__name__
    return ToolError(f"Command {command!r} failed: {detail}")
```

Keep `ToolError` unchanged, include field names from parse/preflight failures, and
never include tokens or raw config objects.

Run: `uv run pytest tests/test_dynamic_catalog.py -v`

Expected: PASS, including live registry add/replace/remove behavior and per-user visibility.

- [ ] **Step 5: Commit**

```bash
git add provider/dynamic_api.py tests/test_dynamic_catalog.py
git commit -m "perf: cache dynamic command snapshots"
```

---

### Task 5: Direct Three-Tool Discovery and Cached BM25 Index

**Files:**
- Modify: `provider/meta_discovery.py`
- Modify: `tests/test_meta_discovery.py`
- Modify: `tests/test_dynamic_catalog.py`

**Interfaces:**
- Consumes: `DynamicAPIAdapter.base_snapshot()` and request-filtered visible entries.
- Produces: three ordinary FastMCP tools without `BM25SearchTransform` or virtual `Tool` objects.

- [ ] **Step 1: Write tests that prohibit transform-time ingestion and duplicate indexing**

```python
async def test_registers_exactly_three_real_tools() -> None:
    register_meta_discovery(mcp, dynamic_adapter=adapter)
    async with Client(mcp) as client:
        assert {tool.name for tool in await client.list_tools()} == {
            "search_tools", "get_tool_schema", "call_tool"
        }


async def test_parallel_search_builds_one_index() -> None:
    service = MetaDiscoveryService(adapter)
    await asyncio.gather(*(service.search("album") for _ in range(20)))
    assert service.index_build_count == 1


async def test_registry_change_rebuilds_index_immediately() -> None:
    before = await service.search("new command")
    mass.command_handlers["music/new_command"] = handler
    after = await service.search("new command")
    assert before == []
    assert after[0]["name"] == "ma_api:music/new_command"
```

Retain Unicode normalization, deterministic tie-breaking, five-result maximum,
schema-free search results, legacy aliases, and the 3 KiB aggregate schema budget.

- [ ] **Step 2: Run discovery tests and observe transform/virtual-tool behavior**

Run: `uv run pytest tests/test_meta_discovery.py tests/test_dynamic_catalog.py -k 'search or listing or index or registry' -v`

Expected: FAIL until `MetaDiscoveryTransform` is removed.

- [ ] **Step 3: Implement an immutable search index keyed by snapshot fingerprint**

```python
@dataclass(frozen=True, slots=True)
class SearchIndex:
    fingerprint: CatalogFingerprint
    documents: Mapping[str, tuple[str, ...]]
    frequencies: Mapping[str, Counter[str]]
    average_length: float


class MetaDiscoveryService:
    def __init__(self, adapter: DynamicAPIAdapter) -> None:
        self.adapter = adapter
        self._index: SearchIndex | None = None
        self._index_lock = asyncio.Lock()
        self.index_build_count = 0

    async def search(self, query: str) -> list[dict[str, str]]:
        view = await self.adapter.visible_catalog()
        index = await self._index_for(await self.adapter.base_snapshot())
        visible = {entry.name: entry for entry in view.entries}
        names = _rank(index, _tokens(query), allowed_names=set(visible))
        return [{"name": name, "description": visible[name].description} for name in names[:5]]

    async def _index_for(self, snapshot: CatalogSnapshot) -> SearchIndex:
        if self._index is not None and self._index.fingerprint == snapshot.fingerprint:
            return self._index
        async with self._index_lock:
            if self._index is None or self._index.fingerprint != snapshot.fingerprint:
                self._index = _build_search_index(snapshot)
                self.index_build_count += 1
            return self._index
```

The index may contain base metadata for hidden commands, but `_rank` receives only
the live request's visible name set and therefore cannot return hidden entries.
Move the current Unicode tokenizer and BM25 scoring constants unchanged into
`_build_search_index()` and `_rank()`; calculate token counters and average document
length only in `_build_search_index()`, never inside a request-time scoring loop.

- [ ] **Step 4: Register `search_tools`, `get_tool_schema`, and `call_tool` directly**

Use three `@mcp.tool` functions. Remove `MetaDiscoveryTransform`, `_entry_tool`,
`ingest_curated`, and the inherited FastMCP search transform. Update the `call_tool`
docstring to accept only canonical `ma_api:*` names.

Run: `uv run pytest tests/test_meta_discovery.py tests/test_dynamic_catalog.py -v`

Expected: PASS; concurrent discovery indexes once and tools/list remains exactly three.

- [ ] **Step 5: Commit**

```bash
git add provider/meta_discovery.py tests/test_meta_discovery.py tests/test_dynamic_catalog.py
git commit -m "perf: cache direct meta discovery index"
```

---

### Task 6: Register the Minimal Provider Command Set

**Files:**
- Create: `provider/commands/__init__.py`
- Create: `provider/commands/authorization.py`
- Create: `provider/commands/queue.py`
- Create: `provider/commands/debug.py`
- Create: `provider/commands/registry.py`
- Create: `tests/test_provider_commands_queue.py`
- Create: `tests/test_provider_commands_debug.py`
- Create: `tests/test_provider_command_registry.py`
- Modify: `provider/models.py`
- Modify: `provider/debug/event_buffer.py`
- Modify: `provider/debug/log_reader.py`

**Interfaces:**
- Produces: MA commands `fastmcp/queue/remove_items_safe`, `fastmcp/debug/tail_log`, `fastmcp/debug/log_stats`, `fastmcp/debug/recent_events`, `fastmcp/debug/event_buffer_stats`, `fastmcp/debug/health`, `fastmcp/debug/routes`, and `fastmcp/debug/packages`.
- Produces: `ProviderCommandSet.start()`, `.update_config(config)`, and `.stop()`.

- [ ] **Step 1: Move behavior-level tests away from FastMCP subservers**

Write direct async handler tests. The queue regression must preserve every requested
ID in exactly one result bucket:

```python
async def test_safe_remove_never_deletes_played_or_buffered_rows() -> None:
    result = await remove_items_safe(mass, "q1", ["played", "buffered", "future", "stale"])
    assert result.skipped_played == ["played"]
    assert result.skipped_buffered == ["buffered"]
    assert result.removed == ["future"]
    assert result.not_found == ["stale"]
    mass.player_queues.delete_item.assert_called_once_with("q1", "future")
```

Port existing log redaction/paging/stats, event snapshot/stats, health, routes, and
packages assertions from `tests/test_debug_*.py` so they call plain handlers. Move
provider-summary coverage to the native `providers` compact profile in Task 8. Add
authorization tests for missing/disabled user, wrong scope, and disabled provider
tag.

- [ ] **Step 2: Run provider-command tests and verify imports fail**

Run: `uv run pytest tests/test_provider_commands_queue.py tests/test_provider_commands_debug.py tests/test_provider_command_registry.py -v`

Expected: FAIL because `provider.commands` does not exist.

- [ ] **Step 3: Implement plain queue and debug handlers**

```python
async def remove_items_safe(mass: Any, queue_id: str, item_ids: list[str]) -> RemoveFromQueueResult:
    if not item_ids:
        raise InvalidDataError("Provide at least one queue item id")
    queue = mass.player_queues.get(queue_id)
    if queue is None:
        raise KeyError(f"Queue {queue_id!r} not found")
    result = RemoveFromQueueResult()
    for item_id in item_ids:
        index = mass.player_queues.index_by_id(queue_id, item_id)
        if index is None:
            result.not_found.append(item_id)
        elif queue.current_index is not None and index <= queue.current_index:
            result.skipped_played.append(item_id)
        elif queue.index_in_buffer is not None and index <= queue.index_in_buffer:
            result.skipped_buffered.append(item_id)
        else:
            mass.player_queues.delete_item(queue_id, item_id)
            bucket = result.removed if mass.player_queues.index_by_id(queue_id, item_id) is None else result.skipped_buffered
            bucket.append(item_id)
    return result
```

Extract the seven read-only implementations from `provider/tools/debug.py` into
plain callables/factories. Keep synchronous log scanning inside `asyncio.to_thread`,
the 10 MiB scan cap, redaction, event-buffer limits, route error handling, and the
current bounded response dataclasses.

- [ ] **Step 4: Implement compatible registration and in-handler authorization**

```python
@dataclass(frozen=True, slots=True)
class ProviderCommand:
    command: str
    handler: Callable[..., Any]
    required_scope: str
    required_tag: str


def _register(mass: Any, definition: ProviderCommand) -> Callable[[], None]:
    supported = inspect.signature(mass.register_api_command).parameters
    options: dict[str, Any] = {"authenticated": True}
    if "required_scope" in supported:
        options["required_scope"] = _scope(definition.required_scope)
    return mass.register_api_command(definition.command, definition.handler, **options)


def authorize_extension(
    config: ProviderConfig,
    *,
    required_scope: str,
    required_tag: str,
) -> User:
    user = get_current_user()
    if user is None or not user.enabled:
        raise AuthenticationRequired("An enabled Music Assistant user is required")
    if not scope_allowed(user, required_scope):
        raise InsufficientPermissions(f"Scope {required_scope!r} is required")
    if required_tag not in {str(tag) for tag in enabled_tags(config)}:
        raise InsufficientPermissions(f"Provider permission {required_tag!r} is disabled")
    return user
```

Every handler calls `authorize_extension(required_scope, required_tag, config)` so
older MA builds without `required_scope` remain protected even when the command is
called outside MCP. `ProviderCommandSet.start()` stores unregister callbacks and
rolls them back in reverse order on partial failure. `.stop()` is idempotent.
`scope_allowed()` delegates to MA's `has_scope` when that helper exists; on older
role-only builds it permits `system.*` and `config.*` only for `UserRole.ADMIN`,
permits queue control for `ADMIN` and `USER`, and never permits a disabled or guest
user.

Run: `uv run pytest tests/test_provider_commands_queue.py tests/test_provider_commands_debug.py tests/test_provider_command_registry.py -v`

Expected: PASS; the registry contains exactly the eight listed `fastmcp/*` commands and no duplicate survives failure/stop.

- [ ] **Step 5: Commit**

```bash
git add provider/commands provider/models.py provider/debug/event_buffer.py provider/debug/log_reader.py tests/test_provider_commands_queue.py tests/test_provider_commands_debug.py tests/test_provider_command_registry.py
git commit -m "feat: register provider extensions as MA commands"
```

---

### Task 7: Make Provider Lifecycle Own Extension Registrations

**Files:**
- Modify: `provider/provider.py:28-112`
- Modify: `provider/server.py:38-168,328-370`
- Modify: `tests/test_provider_command_registry.py`
- Modify: `tests/test_config_lifecycle.py`
- Modify: `tests/test_e2e_hotswap.py`

**Interfaces:**
- `MCPServerProvider` owns one `ProviderCommandSet` across MCP runtime restarts.
- `MCPServerRuntime.dynamic_diagnostics() -> dict[str, Any]` supplies health data through a lazy provider closure.

- [ ] **Step 1: Write lifecycle tests for ordering, rollback, restart, and unload**

```python
async def test_mcp_restart_does_not_reregister_provider_commands(provider: MCPServerProvider) -> None:
    await provider.handle_async_init()
    calls_after_start = provider.mass.register_api_command.call_count
    await provider.update_config(restarted_config, {"mount_path"})
    assert provider.mass.register_api_command.call_count == calls_after_start


async def test_runtime_start_failure_rolls_back_provider_commands(provider: MCPServerProvider) -> None:
    unregisters = [MagicMock() for _ in range(8)]
    provider.mass.register_api_command.side_effect = unregisters
    provider.mass.webserver.register_dynamic_route.side_effect = RuntimeError("mount failed")
    with pytest.raises(RuntimeError, match="mount failed"):
        await provider.handle_async_init()
    assert all(unregister.called for unregister in unregisters)


async def test_unload_stops_mcp_before_unregistering_commands(provider: MCPServerProvider) -> None:
    await provider.unload()
    assert call_order.index("runtime.stop") < call_order.index("commands.stop")
```

- [ ] **Step 2: Run lifecycle tests and verify registrations are not provider-owned yet**

Run: `uv run pytest tests/test_provider_command_registry.py tests/test_config_lifecycle.py tests/test_e2e_hotswap.py -v`

Expected: FAIL because `MCPServerProvider` currently owns only `_runtime`.

- [ ] **Step 3: Start commands transactionally before MCP**

```python
async def handle_async_init(self) -> None:
    self._commands = ProviderCommandSet(
        self.mass,
        config_provider=lambda: self.config,
        diagnostics_provider=lambda: (
            self._runtime.dynamic_diagnostics()
            if self._runtime is not None
            else {"available": False, "last_error": "MCP runtime not started"}
        ),
    )
    try:
        self._commands.start()
        self._runtime = MCPServerRuntime(self.mass, self.config, self.logger)
        await self._runtime.start()
    except BaseException:
        if self._runtime is not None:
            await self._runtime.stop()
        self._commands.stop()
        self._runtime = None
        self._commands = None
        raise
```

On config update, call `self._commands.update_config(config)` before hot-swapping or
restarting MCP. On unload, stop MCP first and commands second.

- [ ] **Step 4: Move event-buffer ownership and expose dynamic diagnostics**

Remove event-buffer startup/stop from `MCPServerRuntime`; `ProviderCommandSet`
starts/stops/reconfigures it because debug commands outlive an MCP-only restart. Add
a public read-only runtime method returning adapter diagnostics without exposing the
adapter object.

Run: `uv run pytest tests/test_provider_command_registry.py tests/test_config_lifecycle.py tests/test_e2e_hotswap.py tests/test_debug_lifecycle.py -v`

Expected: PASS with no leaked subscriptions or duplicate API registrations.

- [ ] **Step 5: Commit**

```bash
git add provider/provider.py provider/server.py tests/test_provider_command_registry.py tests/test_config_lifecycle.py tests/test_e2e_hotswap.py tests/test_debug_lifecycle.py
git commit -m "refactor: own MA commands in provider lifecycle"
```

---

### Task 8: Replace Recipes with Profiles and an Explicit Parity Matrix

**Files:**
- Modify: `provider/command_profiles.py`
- Modify: `provider/dynamic_api.py`
- Modify: `provider/meta_discovery.py`
- Modify: `tests/test_dynamic_catalog.py`
- Create: `tests/test_command_parity.py`

**Interfaces:**
- Produces: `LEGACY_MIGRATIONS: Mapping[str, LegacyMigration]` and registry-backed `COMMAND_PROFILES` only.
- Removes all recipe source, scope, schema, and executor paths.

- [ ] **Step 1: Write a machine-readable parity test for every retired tool**

```python
@pytest.mark.parametrize(("legacy", "target"), sorted(LEGACY_COMMAND_MAPPINGS.items()))
def test_legacy_mapping_targets_registry_or_explicit_retirement(
    legacy: str, target: LegacyMigration
) -> None:
    assert legacy and not legacy.startswith("ma_api:")
    if target.command is not None:
        assert target.command.startswith(("music/", "players/", "player_queues/", "config/", "providers", "diagnostics/", "fastmcp/"))
    else:
        assert target.message
```

Assert `CURATED_PROFILE_MAPPINGS` source names plus every former
`CURATED_RECIPE_SOURCES` source appears exactly once. Assert no target begins with
`mcp_api:` and old names are searchable but not executable.

- [ ] **Step 2: Run parity tests and observe current recipe targets**

Run: `uv run pytest tests/test_command_parity.py tests/test_dynamic_catalog.py -v`

Expected: FAIL because sixteen `mcp_api:*` recipe entries still exist.

- [ ] **Step 3: Encode exact non-trivial migrations**

Use these canonical mappings in addition to the existing one-command profile map:

```python
LEGACY_COMMAND_MAPPINGS.update({
    "players_list_players": migration("players/all"),
    "players_get_player": migration("players/get"),
    "queue_get_active_queue": migration("player_queues/get_active_queue"),
    "queue_add_to_queue": migration("player_queues/play_media"),
    "queue_remove_item": migration("fastmcp/queue/remove_items_safe"),
    "queue_clear_queue": migration("player_queues/clear"),
    "queue_move_item": migration("player_queues/move_item"),
    "queue_move_item_to_end": migration("player_queues/move_item_end"),
    "queue_transfer_queue": migration("player_queues/transfer"),
    "playlists_add_tracks": migration("music/playlists/add_playlist_tracks"),
    "debug_reload_provider": migration("config/providers/reload"),
    "debug_inspect_player": migration("players/get"),
    "debug_inspect_queue": migration("player_queues/get"),
    "debug_inspect_provider": migration("providers"),
    "debug_list_providers": migration("providers"),
    "debug_tail_log": migration("fastmcp/debug/tail_log"),
    "debug_log_stats": migration("fastmcp/debug/log_stats"),
    "debug_recent_events": migration("fastmcp/debug/recent_events"),
    "debug_event_buffer_stats": migration("fastmcp/debug/event_buffer_stats"),
    "debug_health_summary": migration("fastmcp/debug/health"),
    "debug_list_webserver_routes": migration("fastmcp/debug/routes"),
    "debug_list_package_versions": migration("fastmcp/debug/packages"),
    "config_get_provider": migration("config/providers/get"),
    "config_get_core": migration("config/core/get"),
    "config_get_player": migration("config/players/get"),
    "config_get_dsp": migration("config/players/dsp/get"),
    "config_set_provider_value": migration("config/providers/save"),
    "config_save_provider": migration("config/providers/save"),
    "config_trigger_provider_action": migration("config/providers/invoke_action"),
    "config_set_core_value": migration("config/core/save"),
    "config_save_core": migration("config/core/save"),
    "config_set_player_value": migration("config/players/save"),
    "config_save_player": migration("config/players/save"),
    "config_save_dsp": migration("config/players/dsp/save"),
})
```

Add a `providers` profile with compact fields `instance_id`, `domain`, `type`,
`name`, `available`, `enabled`, and `last_error`; this preserves the former provider
summary without adding a `fastmcp/debug/providers` wrapper.

Add explicit non-executable hints for aggregate names and multi-operation recipes:

```python
LEGACY_COMMAND_MAPPINGS.update({
    "config_list_targets": retired("Use search_tools('config providers core players')"),
    "config_get_entries": retired("Use the target-specific config/*/get_entries command"),
    "mcp_api:players/summary": migration("players/all"),
    "mcp_api:queue/snapshot": migration("player_queues/get_active_queue"),
    "mcp_api:queue/add": migration("player_queues/play_media"),
    "mcp_api:queue/remove": retired("Use fastmcp/queue/remove_items_safe or player_queues/clear"),
    "mcp_api:queue/move": retired("Use player_queues/move_item, move_item_end, or transfer"),
    "mcp_api:playlist/add_many": migration("music/playlists/add_playlist_tracks"),
    "mcp_api:config/targets": retired("Use search_tools('config targets')"),
    "mcp_api:config/entries": retired("Use the target-specific config/*/get_entries command"),
    "mcp_api:config/save": retired("Use the target-specific config/*/save command"),
    "mcp_api:config/save_dsp": migration("config/players/dsp/save"),
    "mcp_api:debug/inspect": retired("Use native players, queues, providers, config, or diagnostics commands"),
    "mcp_api:debug/logs": retired("Use fastmcp/debug/tail_log or fastmcp/debug/log_stats"),
    "mcp_api:debug/events": retired("Use fastmcp/debug/recent_events or fastmcp/debug/event_buffer_stats"),
    "mcp_api:debug/health": migration("fastmcp/debug/health"),
    "mcp_api:debug/routes": migration("fastmcp/debug/routes"),
    "mcp_api:debug/packages": migration("fastmcp/debug/packages"),
})
```

- [ ] **Step 4: Delete recipe logic and return migration hints only**

Remove `RecipeBinding`, `_recipe_entries`, `_recipe_schema`, `_execute_recipe`,
`ingest_curated`, recipe constants, and `mcp_api` kind branches. `call_tool` formats a
`LegacyMigration` message without redirecting execution.

Run: `uv run pytest tests/test_command_parity.py tests/test_dynamic_catalog.py tests/test_meta_discovery.py -v`

Expected: PASS; every catalog entry is `ma_api:*`, and every old name fails with a concrete migration hint.

- [ ] **Step 5: Commit**

```bash
git add provider/command_profiles.py provider/dynamic_api.py provider/meta_discovery.py tests/test_command_parity.py tests/test_dynamic_catalog.py tests/test_meta_discovery.py
git commit -m "refactor: replace MCP recipes with MA profiles"
```

---

### Task 9: Remove FastMCP Domain Subservers and Preserve Resources/Prompts

**Files:**
- Create: `provider/resource_helpers.py`
- Modify: `provider/resources/library_resources.py`
- Modify: `provider/resources/player_resources.py`
- Modify: `provider/server.py:169-281`
- Modify: `provider/models.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_resources.py`
- Modify: `tests/test_prompts.py`
- Modify: `tests/test_e2e_smoke.py`
- Modify: `tests/test_config_secret.py`
- Modify: `tests/test_models.py`
- Delete: `provider/tools/__init__.py`
- Delete: `provider/tools/_common.py`
- Delete: `provider/tools/config.py`
- Delete: `provider/tools/debug.py`
- Delete: `provider/tools/library.py`
- Delete: `provider/tools/media.py`
- Delete: `provider/tools/metadata.py`
- Delete: `provider/tools/playback.py`
- Delete: `provider/tools/players.py`
- Delete: `provider/tools/playlists.py`
- Delete: `provider/tools/queue.py`
- Delete: `provider/tools/volume.py`
- Delete: `provider/config_io/differ.py`
- Delete: `provider/config_io/validator.py`
- Delete: `provider/debug/inspect_serializer.py`

**Interfaces:**
- Root FastMCP server retains meta-tools, resources, prompts, middleware, auth, and HTTP bridge only.
- Resource helpers retain `to_resource_text`, `safe_active_queue`, `to_brief_player`, and `to_brief_queue` behavior.

- [ ] **Step 1: Pin the post-removal server and resource surface**

```python
async def test_runtime_has_three_tools_and_preserves_resources_and_prompts(runtime: MCPServerRuntime) -> None:
    async with Client(runtime._mcp) as client:
        assert {tool.name for tool in await client.list_tools()} == {
            "search_tools", "get_tool_schema", "call_tool"
        }
        assert {str(item.uri) for item in await client.list_resource_templates()} >= {
            "player://{player_id}", "queue://{queue_id}"
        }
        assert await client.list_prompts()
```

Update resource tests to import from `provider.resource_helpers`. Verify through
the public runtime surface that provider commands register as MA handlers without
creating or mounting a FastMCP subserver. Keep source-tree searches for retired
imports and decorators as a non-test migration audit in Task 11 rather than an AST
test coupled to implementation structure.

- [ ] **Step 2: Run server/resource tests before removing subservers**

Run: `uv run pytest tests/test_resources.py tests/test_prompts.py tests/test_e2e_smoke.py -v`

Expected before the implementation: FAIL because the public runtime still lists
the mounted domain tools; PASS once only the three meta-tools remain.

- [ ] **Step 3: Move only resource-shared helpers and simplify `server.py`**

Move the four resource helper functions and their private dependencies from
`provider/tools/_common.py` to `provider/resource_helpers.py`. In `_start_impl()`,
construct FastMCP, register resources and prompts, apply tag middleware, register
meta discovery, and mount HTTP; remove every `build_*_server` import and `.mount()`.

Update server instructions to:

```python
instructions=(
    "Music Assistant MCP server with on-demand discovery. Use search_tools, "
    "then get_tool_schema for one canonical ma_api:* command, then execute it "
    "through call_tool. Responses default to compact mode. Resources expose "
    "library://, player:// and queue:// views."
)
```

- [ ] **Step 4: Retire obsolete custom-tool tests and helpers**

Delete tests whose sole subject is an upstream-replaced FastMCP tool builder:

```text
tests/test_add_to_queue.py
tests/test_annotations.py
tests/test_config_differ.py
tests/test_config_read.py
tests/test_config_security.py
tests/test_config_validator.py
tests/test_config_write_core.py
tests/test_config_write_player.py
tests/test_config_write_provider.py
tests/test_context.py
tests/test_debug_events.py
tests/test_debug_health.py
tests/test_debug_inspect.py
tests/test_debug_inspect_serializer.py
tests/test_debug_logs.py
tests/test_debug_providers.py
tests/test_debug_reload.py
tests/test_debug_security.py
tests/test_elicitation.py
tests/test_get_active_queue.py
tests/test_lean_schema.py
tests/test_library_album_tracks.py
tests/test_library_list_tools.py
tests/test_media_resolve.py
tests/test_media_tools.py
tests/test_move_queue_item.py
tests/test_playback_tool.py
tests/test_players_tool.py
tests/test_playlists.py
tests/test_set_repeat.py
```

Do not delete behavior ported in Tasks 3, 6, and 8. Retarget log/event/health and
resource-helper tests to their new modules, remove obsolete mounted fixtures from
`tests/conftest.py`, and keep `provider/config_io/secret_handler.py` plus its focused
secret-gate tests.

Run: `uv run pytest tests/test_resources.py tests/test_prompts.py tests/test_provider_commands_queue.py tests/test_provider_commands_debug.py tests/test_command_parity.py tests/test_e2e_smoke.py -v`

Expected: PASS and `rg 'provider\.tools|build_.*_server|mcp_api:' provider tests` returns only explicit legacy-string assertions.

- [ ] **Step 5: Commit**

```bash
git add -A provider tests
git commit -m "refactor: remove custom FastMCP tool surface"
```

---

### Task 10: Authenticated Docker Integration Coverage

**Files:**
- Create: `tests/integration/test_live_catalog.py`
- Modify: `docker-compose.dev.yml`
- Modify: `README.md`

**Interfaces:**
- Reads: `MA_MCP_URL`, `MA_MCP_TOKEN`, and optional `MA_TEST_PLAYER_ID` environment variables.
- Uses: `fastmcp.client.transports.StreamableHttpTransport(url, auth=token)`.

- [ ] **Step 1: Add opt-in live-client fixture, call helper, and meta-surface test**

```python
async def _accept_elicitation(message: str, response_type: Any, params: Any, context: Any) -> bool:
    del message, response_type, params, context
    return True


async def call_ma(client: Client, command: str, arguments: Mapping[str, Any]) -> Any:
    result = await client.call_tool(
        "call_tool",
        {"name": f"ma_api:{command}", "arguments": dict(arguments)},
    )
    assert not result.is_error, result.content
    envelope = result.data
    assert envelope["command"] == f"ma_api:{command}"
    return envelope["data"]


@pytest.fixture
async def live_client() -> AsyncIterator[Client]:
    url = os.getenv("MA_MCP_URL")
    token = os.getenv("MA_MCP_TOKEN")
    if not url or not token:
        pytest.skip("set MA_MCP_URL and MA_MCP_TOKEN for Docker integration tests")
    transport = StreamableHttpTransport(url, auth=token)
    async with Client(transport, elicitation_handler=_accept_elicitation) as client:
        yield client


@pytest.mark.integration
async def test_live_meta_surface_and_discovery_latency(live_client: Client) -> None:
    assert {tool.name for tool in await live_client.list_tools()} == {
        "search_tools", "get_tool_schema", "call_tool"
    }
    started = time.monotonic()
    await asyncio.gather(*(live_client.call_tool("search_tools", {"query": "album tracks"}) for _ in range(10)))
    cold_elapsed = time.monotonic() - started
    started = time.monotonic()
    await live_client.call_tool("search_tools", {"query": "album tracks"})
    warm_elapsed = time.monotonic() - started
    assert cold_elapsed < 5.0
    assert warm_elapsed < 1.0
```

- [ ] **Step 2: Add real track, album, player, and kwargs regressions**

Search a provider-backed track and album, then invoke `music/item_by_uri`,
`music/albums/album_tracks`, `players/all`, `players/get`, and each of the seven
`music/*/library_items` commands through `call_tool`. Assert every response has
`is_error == False`, JSON-compatible `data`, and no schema contains a required
`kwargs` field or a false string output type for list/model results.

```python
LIBRARY_ITEM_COMMANDS = [
    "music/albums/library_items",
    "music/artists/library_items",
    "music/audiobooks/library_items",
    "music/genres/library_items",
    "music/playlists/library_items",
    "music/podcasts/library_items",
    "music/tracks/library_items",
]


@pytest.mark.integration
@pytest.mark.parametrize("command", LIBRARY_ITEM_COMMANDS)
async def test_live_library_items_have_truthful_schema_and_execute(
    live_client: Client, command: str
) -> None:
    schema_result = await live_client.call_tool(
        "get_tool_schema", {"tool_name": f"ma_api:{command}"}
    )
    schema = schema_result.data
    assert "kwargs" not in schema["inputSchema"].get("properties", {})
    assert "kwargs" not in schema["inputSchema"].get("required", [])
    output = schema.get("outputSchema", {})
    assert not (output.get("type") == "string" and "list[" in output.get("x-python-type", ""))
    data = await call_ma(live_client, command, {"limit": 2})
    json.dumps(data)
```

Run: `uv run pytest tests/integration/test_live_catalog.py -m integration -v`

Expected before deploying the implementation: FAIL on current Track/Album/Player serialization and `kwargs`; PASS after the new provider is mounted.

- [ ] **Step 3: Add a reversible non-current queue lifecycle**

```python
def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"set {name} to run the queue mutation test")
    return value


def item_id(item: Mapping[str, Any]) -> str:
    return str(item.get("queue_item_id") or item["item_id"])


async def queue_items(client: Client, queue_id: str) -> list[dict[str, Any]]:
    return await call_ma(client, "player_queues/items", {"queue_id": queue_id, "limit": 500})


async def wait_for_added_item(
    client: Client,
    queue_id: str,
    before_ids: set[str],
) -> dict[str, Any]:
    for _attempt in range(20):
        items = await queue_items(client, queue_id)
        if added := [item for item in items if item_id(item) not in before_ids]:
            return added[-1]
        await asyncio.sleep(0.25)
    raise AssertionError("added queue item did not appear within five seconds")


async def find_test_track_uri(client: Client) -> str:
    search = await call_ma(client, "music/search", {
        "search_query": "Daft Punk Random Access Memories",
        "media_types": ["track"],
        "limit": 5,
        "library_only": False,
    })
    tracks = search.get("tracks", [])
    if not tracks:
        pytest.skip("configured providers returned no track for the queue smoke test")
    return str(tracks[0]["uri"])


@pytest.mark.integration
async def test_live_reversible_queue_cycle(live_client: Client) -> None:
    player_id = require_env("MA_TEST_PLAYER_ID")
    queue = await call_ma(live_client, "player_queues/get_active_queue", {"player_id": player_id})
    before = await call_ma(live_client, "player_queues/items", {"queue_id": queue["queue_id"]})
    if not before or queue.get("current_index") is None:
        pytest.skip("queue test requires a dedicated player with an active non-empty queue")
    before_ids = {item_id(item) for item in before}
    track_uri = await find_test_track_uri(live_client)
    added_id: str | None = None
    try:
        await call_ma(live_client, "player_queues/play_media", {
            "queue_id": queue["queue_id"], "media": track_uri, "option": "add"
        })
        added = await wait_for_added_item(live_client, queue["queue_id"], before_ids)
        added_id = item_id(added)
        refreshed_queue = await call_ma(
            live_client, "player_queues/get", {"queue_id": queue["queue_id"]}
        )
        added_index = int(added["index"])
        current_index = refreshed_queue.get("current_index")
        buffer_index = refreshed_queue.get("index_in_buffer")
        protected_index = max(
            int(current_index) if current_index is not None else -1,
            int(buffer_index) if buffer_index is not None else -1,
        )
        assert added_index > protected_index
        await call_ma(live_client, "player_queues/move_item_end", {
            "queue_id": queue["queue_id"], "queue_item_id": added_id
        })
        removed = await call_ma(live_client, "fastmcp/queue/remove_items_safe", {
            "queue_id": queue["queue_id"], "item_ids": [added_id]
        })
        assert removed["removed"] == [added_id]
        added_id = None
    finally:
        if added_id is not None:
            await call_ma(live_client, "fastmcp/queue/remove_items_safe", {
                "queue_id": queue["queue_id"], "item_ids": [added_id]
            })
    after_order = [item_id(item) for item in await queue_items(live_client, queue["queue_id"])]
    assert after_order == [item_id(item) for item in before]
```

Skip unless `MA_TEST_PLAYER_ID` is explicitly provided. Refuse to mutate when the
selected added row is current, played, or at/before `index_in_buffer`. Always run the
safe removal cleanup in `finally` when the add succeeded.

- [ ] **Step 4: Verify confirmation and read-only system annotations live**

Fetch schemas for `player_queues/delete_item`, `player_queues/clear`,
`fastmcp/queue/remove_items_safe`, and `fastmcp/debug/health`. Assert the three queue
commands are write/destructive and the health command is system/read-only. Use a
declining elicitation handler for a harmless stale queue item ID and assert the
handler is never invoked after decline.

Run with Docker:

```bash
docker compose -f docker-compose.dev.yml up -d --build
MA_MCP_URL=http://127.0.0.1:8095/mcp/v1 MA_MCP_TOKEN="$MA_MCP_TOKEN" MA_TEST_PLAYER_ID="$MA_TEST_PLAYER_ID" uv run pytest tests/integration/test_live_catalog.py -m integration -v
```

Expected: PASS; the test restores the queue and prints measured cold/warm discovery durations.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_live_catalog.py docker-compose.dev.yml README.md
git commit -m "test: cover unified catalog in Docker"
```

---

### Task 11: Documentation, Full Catalog Audit, and Release Gates

**Files:**
- Modify: `README.md`
- Modify: `provider/strings.json`
- Modify: `specs/done/0026-dynamic-ma-api-catalog.md`
- Modify: `docs/superpowers/specs/2026-07-30-native-ma-command-catalog-design.md`
- Modify: tests discovered by the full-suite run only when they assert the retired surface.

**Interfaces:**
- Delivers the documented unified command model and a clean repository verification run.

- [ ] **Step 1: Update user-facing discovery and permissions documentation**

Replace references to ten namespaced tool subservers and `mcp_api:*` recipes with:

```text
The MCP surface contains three tools: search_tools, get_tool_schema, and call_tool.
They discover and invoke Music Assistant's live API registry as ma_api:* commands.
Provider-owned fastmcp/* commands use the same registry and exist only for safe queue
batch removal and provider diagnostics that Music Assistant does not expose natively.
```

Document that native config commands use existing config permission toggles, secret
writes still require `config:write:secret`, destructive queue commands elicit
confirmation, and resources/prompts are unchanged. Mark spec 0026's recipe design as
superseded by the new design document rather than rewriting its historical record.

- [ ] **Step 2: Run the full unit suite and resolve only migration regressions**

Run: `uv run pytest -v`

Expected: PASS with integration tests skipped when their three environment variables are absent.

- [ ] **Step 3: Run static and formatting gates**

Run:

```bash
uv run ruff check provider tests
uv run ruff format --check provider tests
uv run mypy provider tests
uv run pre-commit run --all-files
```

Expected: all commands exit 0 and leave no formatter changes.

- [ ] **Step 4: Run the full structural catalog audit**

Run:

```bash
uv run pytest tests/test_dynamic_catalog.py tests/test_command_parity.py tests/test_command_policy.py -v
rg -n "RecipeBinding|CURATED_RECIPE|ingest_curated|build_.*_server|mcp_api:" provider tests
git diff --check
```

Expected: tests PASS; `rg` reports only migration-hint strings/tests and no executable
recipe or custom-server implementation; `git diff --check` prints nothing.

- [ ] **Step 5: Run final Docker verification and commit documentation**

Run the Task 10 Docker command, then:

```bash
git add README.md provider/strings.json specs/done/0026-dynamic-ma-api-catalog.md docs/superpowers/specs/2026-07-30-native-ma-command-catalog-design.md
git commit -m "docs: describe unified MA command catalog"
git status --short
```

Expected: Docker tests PASS and `git status --short` is empty.

---

## Execution Checkpoints

- After Task 3: review the complete policy table and destructive confirmation paths.
- After Task 6: review the eight-command extension set; reject any wrapper that merely renames a native MA command.
- After Task 9: verify resources and prompts before accepting deletion of `provider/tools/`.
- After Task 10: inspect the live queue diff and discovery timings before final gates.

## Completion Evidence

The final handoff must include:

- unit-test, Ruff, formatting, mypy, and pre-commit outputs;
- Docker MCP URL and Music Assistant image/version used, without exposing the token;
- cold and warm discovery measurements;
- real track/album/player command results summarized without dumping the library;
- the queue item added, moved, removed, and the equality check against the captured queue;
- catalog counts by risk and confirmation class;
- `git status --short` proving no uncommitted implementation changes remain.
