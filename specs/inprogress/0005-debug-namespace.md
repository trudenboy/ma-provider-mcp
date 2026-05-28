---
id: "0005"
title: "Debug namespace for MA development and troubleshooting via MCP"
size: L
status: inprogress
priority: P1
effort_minutes: 480
feature_id:
---

## Problem Statement

Today the provider exposes a *consumer* surface — library, queue, playback,
players, playlists, volume, media, metadata — all shaped around "listen to
and control music". A developer or operator troubleshooting Music Assistant
itself has no MCP-accessible window into the system:

- They cannot inspect the **raw runtime state** of a player or queue. The
  current `PlayerBrief` / `QueueBrief` deliberately hide internals to keep
  payloads small for LLM context. The recent 0.3.32 → 0.3.34 → 0.3.35
  release train demonstrated the cost: each missing field
  (`active_group`, `synced_to`, `volume_muted`, `group_volume`,
  `group_volume_muted`) required a code-and-release cycle just to surface
  state that already existed inside `Player`. A diagnostic agent needs an
  escape hatch that mirrors the full dataclass on demand.
- They cannot **tail `musicassistant.log` over MCP**, even though
  `CLAUDE.md` already names this file as the canonical local debug
  artifact. Shelling out is fine for the human at the keyboard but invisible
  to an LLM agent driving the session.
- They cannot read the **MA event bus**. Events vanish unless somebody
  has subscribed; by the time a user notices a behaviour and asks the
  agent "what just happened?", the evidence is gone.
- They cannot inspect **configured providers**: their state, their
  ConfigEntry values (with secrets masked), the webserver routes they
  registered, or the installed package versions backing them. Every
  question of the form "is provider X loaded? what manifest? what URL
  did it claim?" requires a shell + SQL session today.
- They cannot **reload a single provider** without restarting the whole
  MA process — slow feedback loop when iterating on a provider.

The gap is not a feature gap in MA itself; it is an *accessibility* gap.
Every one of these things is already in memory in a running MA. We just
do not expose it through MCP.

## Solution Summary

Add a ninth FastMCP sub-server, `debug`, mounted by `MCPServerRuntime`
alongside the existing eight. It exposes ten read tools plus one guarded write tool spread across five
new permission tags — `debug:inspect`, `debug:logs`, `debug:events`,
`debug:providers`, `debug:reload` — each gated by its own off-by-default
`ConfigEntry`. One of the ten read tools — `debug_health_summary` — is the
intended **entry point** for an LLM agent triaging an unknown problem:
a single read returns a roll-up of provider state, queue health, event
rates, and log error counts, so the agent does not need to fan out
to four separate tools to ask "is anything broken?". Inspection tools return a recursive, JSON-safe mirror of the
underlying MA dataclass (state-first, with locks/tasks/cycles stringified
or capped). Log tailing reads `$HOME/.musicassistant/musicassistant.log`
with strict path-allowlisting and a redactor for common token patterns.
Event access is backed by a bounded in-memory ring buffer subscribed to
`mass.subscribe(...)` at provider setup and cleanly torn down at unload.
Provider tools dump configs through `ProviderConfig.to_dict()`, which
relies on MA's built-in `__post_serialize__` hook to replace
`SECURE_STRING` values with `SECURE_STRING_SUBSTITUTE` — we never carry
our own masking logic and therefore cannot drift from upstream. The
single write tool — `debug_reload_provider` — wraps a single call to
`mass._load_provider` (which itself unloads first when needed) behind
the existing elicitation `confirm_or_raise` flow, a global reload
`asyncio.Lock`, and an INFO-level audit log line.

The surface lands as a single PR, in-tree, intended to be inlined upstream
together with the rest of the provider — not stripped at sync-to-fork.

## Acceptance Criteria

1. With each of the five new tag-gating `ConfigEntry` booleans left at
   its default (`False`), an in-memory FastMCP `Client` enumerating
   tools sees **zero** entries under the `debug` namespace. Enabling a
   single tag exposes only that group's tools and nothing else. This
   invariant is pinned by a regression test that must fail if any
   debug tool leaks through `restrict_tag` middleware.
2. `debug_inspect_player(player_id)` returns a recursive JSON-safe mirror
   of the `Player` dataclass that includes both raw attributes and a
   `state: {...}` sub-object, with depth ≤ 6, individual string fields
   capped at 2048 chars, `asyncio.Lock` / `Task` / `Future` rendered as
   `"<unserializable …>"`, byte buffers rendered as `"<bytes len=N>"`,
   `Enum` rendered as its `.value`, `datetime` rendered as ISO 8601, and
   self-referential cycles broken without raising. The tool returns
   state for any player **present in `mass.players` regardless of
   `available`, `enabled`, or `hidden`** — troubleshooting a broken
   player requires inspecting it precisely when it is not working.
   Only players unknown to MA raise `ToolError`. Per-attribute access
   inside the serializer is wrapped in `try/except`; an attribute whose
   getter raises is rendered as `"<raise: ExceptionClassName>"` and does
   not propagate. The same guarantees apply to `debug_inspect_queue` and
   `debug_inspect_provider`.
3. `debug_inspect_provider_config(instance_id)` produces its response by
   walking the dict returned by `ProviderConfig.to_dict()`, which
   already replaces every `ConfigEntryType.SECURE_STRING` value with
   `music_assistant_models.constants.SECURE_STRING_SUBSTITUTE` via MA's
   `__post_serialize__` hook. The provider does **not** carry its own
   masking pass — drift between the provider and MA-core is therefore
   impossible. The original secret string must not appear anywhere in
   the serialised response.
4. `debug_tail_log` opens only files whose resolved path lives under
   `$HOME/.musicassistant/` **and** whose basename matches the fixed
   allowlist `{musicassistant.log, musicassistant.log.1 … .log.5}`.
   Inputs containing `..`, absolute paths, NUL bytes, empty strings,
   `.`, or symlinks escaping the allowlisted root raise `ToolError`
   rather than producing a traceback. Common token patterns
   (`Authorization: Bearer …`, `token=…`, `password=…`) in the log
   text are replaced with `<redacted>` before the line is returned.
   Scanning from end-of-file is hard-capped at **10 MB** of bytes
   examined per call regardless of `lines` or `since_seconds`; when
   the cap is reached before the requested line count is gathered,
   `LogTailResult.truncated = True` and `LogTailResult.bytes_scanned`
   carries the cap value. This is a self-DoS prevention for the
   provider process itself, not a privacy boundary.
5. With `DEBUG_EVENTS=True`, the provider subscribes to `mass.subscribe`
   exactly once at `setup()` and unsubscribes exactly once at `unload()`,
   in that order, **before** the FastMCP transport is torn down. Calling
   `EventBuffer.stop()` twice is a no-op. With `DEBUG_EVENTS=False`, no
   subscription is created and `unload()` does not raise.
6. `EventBuffer` with `capacity=N` holding N+k events returns at most N
   on `snapshot()`, reports `total_seen=N+k`, `dropped=k`, and supports
   filtering by `event_types`, `id_filter`, and `since_seconds`.
7. `debug_reload_provider(instance_id, ctx)` first calls
   `confirm_or_raise` (when `require_confirmation=True`), then calls
   `mass._load_provider(conf)` — which internally unloads the existing
   instance and re-runs setup — and finally polls up to 5 seconds for
   `Provider.available == True`. Two concurrent reloads serialise
   through `MCPServerRuntime._reload_lock`. A reload that times out
   returns `ReloadResult.last_error` populated rather than raising. An
   INFO-level audit log line is written **before** `_load_provider` is
   invoked and is observable via `caplog` in tests.
8. Total payload of `debug_inspect_provider_config` and
   `debug_inspect_player` is hard-capped at ~256 KB after serialisation;
   responses exceeding the cap have `truncated: True` and a shortened
   dump rather than being silently truncated mid-field.
9. All debug tools raise `fastmcp.exceptions.ToolError` (not bare
   `Exception`) for user-visible error cases, matching the existing
   pattern in `media.py` and `playlists.py`. Error messages include the
   offending identifier verbatim (e.g. `f"player_id={id!r} not found"`).
10. The full `pytest` suite continues to complete in under 30 seconds on
    a clean checkout; no debug test starts a real MA process.
11. `debug_health_summary` is gated by `DEBUG_PROVIDERS` alone. It
    always returns provider roll-up and queue counts; fields whose
    underlying capability is disabled (`events_per_min_by_type`
    requires `DEBUG_EVENTS`; `log_errors_last_5min` requires
    `DEBUG_LOGS`) are returned as `None` with a `disabled_capabilities:
    list[str]` field naming what was skipped — so the agent sees the
    distinction between "no errors" and "we couldn't check".

## Test Plan

- **`tests/test_debug_security.py`**
  - `test_off_by_default_hides_all_debug_tools` — `mounted_debug_off`
    client `list_tools()` returns nothing in the `debug` namespace.
  - `test_secret_string_value_is_masked` — config value of type
    `SECURE_STRING="actual-secret-1234"` round-trips as
    `SECURE_STRING_SUBSTITUTE`, original substring absent from
    `json.dumps(result)`. Pins the contract that we *do* go through
    `ProviderConfig.to_dict()` and never bypass `__post_serialize__`.
  - `test_log_line_bearer_token_redacted` — fixture line
    `Authorization: Bearer abc.def.ghi` → response contains
    `<redacted>` and not the token.

- **`tests/test_debug_logs.py`**
  - Parametrised `test_path_traversal_rejected` over
    `["../etc/passwd", "/etc/passwd", "musicassistant.log\x00.txt",
    "..", ".", "", "musicassistant.log.99"]` — each raises `ToolError`.
  - `test_symlink_escape_rejected` — symlink in `tmp_log_dir` pointing
    outside the root → `ToolError`.
  - `test_tail_returns_last_n_lines` — 1000-line fixture, `lines=50` →
    50 entries, all matching the last 50 source lines after parsing.
  - `test_filter_by_level_and_component_regex`.
  - `test_scan_bytes_cap_marks_truncated` — synthetic 20 MB log,
    `lines=10_000` → result has `truncated=True`, `bytes_scanned` near
    the 10 MB cap, returned entries are the latest fully-parsed lines.
    Pins AC #4 self-DoS guarantee.

- **`tests/test_debug_events.py`**
  - `test_event_buffer_respects_capacity_and_reports_dropped` — emit
    503 events into capacity=500 buffer → snapshot len 500,
    `stats.dropped == 3`.
  - `test_snapshot_filters_event_types_and_id` — emit mixed batch, ask
    for `event_types=["player_updated"]`, `id_filter="kitchen"` → only
    matching entries returned.
  - `test_since_seconds_against_frozen_time` — `freezegun` + emit at
    `T0`, advance time, emit at `T+10`, query `since_seconds=2` → only
    the latest is returned.

- **`tests/test_debug_lifecycle.py`**
  - `test_setup_subscribes_when_debug_events_enabled` — `mock_mass.subscribe`
    called exactly once.
  - `test_unload_calls_event_buffer_stop_before_unmount` — verify
    `call_order` on `MagicMock.method_calls`.
  - `test_event_buffer_stop_is_idempotent`.
  - `test_unload_does_not_raise_when_events_disabled`.

- **`tests/test_debug_reload.py`**
  - `test_confirm_required_before_reload` — confirm denied → `ToolError`,
    `mass._load_provider` never called.
  - `test_reload_calls_load_provider_with_resolved_config` — fetches
    `ProviderConfig` via `mass.config.get_provider_config(instance_id)`,
    then passes the exact same object into `mass._load_provider`.
  - `test_reload_timeout_populates_last_error` — `Provider.available`
    stays `False` past 5s → result returned with `last_error`, no
    exception raised.
  - `test_concurrent_reloads_serialise_through_lock` — two
    `asyncio.gather`-ed calls, second one observes the first finished.
  - `test_audit_log_written_before_load_provider` — `caplog` shows INFO
    line referencing `instance_id` prior to the `_load_provider` call.

- **`tests/test_debug_inspect_serializer.py`**
  - `test_recursion_with_self_reference` — cyclic graph → no
    `RecursionError`, cycle placeholder rendered.
  - `test_max_depth_truncates`.
  - `test_max_str_truncates_with_suffix`.
  - `test_lock_and_task_rendered_as_unserialisable_placeholder`.
  - `test_bytes_rendered_as_length_placeholder`.
  - `test_enum_rendered_as_value`.
  - `test_datetime_rendered_as_iso8601`.
  - `test_total_payload_cap_marks_truncated`.
  - `test_property_raising_renders_as_placeholder` — object with a
    `@property` that raises `RuntimeError("not ready")` → field
    rendered as `"<raise: RuntimeError>"`; the dump as a whole
    completes without propagating the exception.

- **`tests/test_debug_inspect.py`** (in addition to the end-to-end
  signature tests already noted)
  - `test_inspect_unavailable_player_still_returns_state` — `Player`
    with `available=False` and a populated `last_error` → tool returns
    the dump, response contains `state.power` and `last_error`. Pins
    AC #2: troubleshooting requires inspecting precisely the broken
    object.
  - `test_inspect_disabled_player_still_returns_state` — same with
    `enabled=False`.
  - `test_inspect_unknown_player_raises_tool_error` — `player_id`
    absent from `mass.players` → `ToolError`, not the silent
    "available=False" path.

- **`tests/test_debug_health.py`**
  - `test_health_summary_rolls_up_provider_state` — roster of 5
    providers (3 loaded, 1 disabled, 1 with `last_error`) → counts
    match, `providers_error_details` contains exactly the failing one.
  - `test_health_summary_marks_capabilities_disabled_when_tags_off` —
    only `DEBUG_PROVIDERS` enabled → `events_per_min_by_type` is
    `None`, `log_errors_last_5min` is `None`,
    `disabled_capabilities == ["DEBUG_EVENTS", "DEBUG_LOGS"]`. Pins
    AC #11: agent must distinguish "no errors" from "we couldn't check".
  - `test_health_summary_events_rate_uses_buffer_when_enabled` — with
    `DEBUG_EVENTS` on, emit known mix via `fake_event_emitter`, assert
    per-type rate matches.
  - `test_health_summary_log_errors_uses_safe_log_tail` — `DEBUG_LOGS`
    on, fixture log with 3 `ERROR` lines in last 5 min → count `3`.

- **`tests/test_debug_inspect.py`**, **`tests/test_debug_providers.py`** —
  end-to-end through in-memory FastMCP `Client` over `mounted_debug`,
  asserting tool signatures, returned dataclass field presence, and
  `ToolError` on unknown IDs.

- **Manual verification step (post-merge, local).** With the provider
  installed in a dev MA instance, an MCP client with all five debug
  tags enabled should:
  (a) get a populated `EventBufferStats.by_type` after toggling a
  player's volume from the MA UI;
  (b) tail the last 50 lines of `musicassistant.log` filtered to
  `level="WARNING"`;
  (c) reload a configured provider and observe `new_available=True`
  within 5 seconds.

## Sequence Diagram

```mermaid
sequenceDiagram
    participant Client as MCP Client (LLM)
    participant Runtime as MCPServerRuntime
    participant Debug as build_debug_server
    participant Buf as EventBuffer
    participant MA as mass

    Note over Runtime,Buf: setup() — once per provider lifecycle
    Runtime->>Runtime: load tag_set from config
    Runtime->>Debug: mount(build_debug_server(mass))
    alt Tag.DEBUG_EVENTS enabled
        Runtime->>Buf: EventBuffer(mass, capacity)
        Runtime->>Buf: start()
        Buf->>MA: mass.subscribe(self._on_event)
        MA-->>Buf: remove_listener
    end

    Note over Client,MA: steady state — entry point for triage
    Client->>Debug: debug_health_summary()
    Debug->>MA: mass.providers (roll-up)
    Debug->>MA: mass.player_queues (counts)
    Debug->>Buf: stats() (when DEBUG_EVENTS on)
    Debug->>Debug: SafeLogTail.count_errors_last_5min() (when DEBUG_LOGS on)
    Debug-->>Client: HealthSummary{providers_error_details, disabled_capabilities, ...}

    Note over Client,MA: steady state — read paths
    Client->>Debug: debug_tail_log(lines=200, level="ERROR")
    Debug->>Debug: SafeLogTail.tail() (path allowlist + redactor)
    Debug-->>Client: LogTailResult

    Client->>Debug: debug_recent_events(limit=50, event_types=...)
    Debug->>Buf: snapshot(...)
    Buf-->>Debug: list[EventRecord]
    Debug-->>Client: EventSnapshot

    Client->>Debug: debug_inspect_player("kitchen")
    Debug->>MA: mass.players.get("kitchen")
    MA-->>Debug: Player
    Debug->>Debug: inspect_serializer.dump(player)
    Debug-->>Client: PlayerInspect

    Note over Client,MA: write path — single guarded action
    Client->>Debug: debug_reload_provider("yandex_music")
    Debug->>Client: elicit confirm via ctx (confirm_or_raise)
    Client-->>Debug: confirm=True
    Debug->>Runtime: _reload_lock.acquire()
    Debug->>MA: LOGGER.info(audit, instance_id=...)
    Debug->>MA: await mass._load_provider(conf)
    Note right of MA: _load_provider unloads<br/>existing instance internally<br/>then re-runs setup
    loop up to 50 × 100ms
        Debug->>MA: mass.get_provider(id).available
    end
    Debug-->>Client: ReloadResult{new_available, duration_ms, last_error}

    Note over Runtime,Buf: unload() — teardown, order is load-bearing
    Runtime->>Buf: stop() (idempotent; runs BEFORE FastMCP teardown)
    Buf->>MA: remove_listener()
    Runtime->>Runtime: unregister dynamic route + close FastMCP
```

## Data Model

### New `Tag` enum members (`provider/tags.py`)

```python
class Tag(StrEnum):
    # ... existing 16 ...
    DEBUG_INSPECT   = "debug:inspect"
    DEBUG_LOGS      = "debug:logs"
    DEBUG_EVENTS    = "debug:events"
    DEBUG_PROVIDERS = "debug:providers"
    DEBUG_RELOAD    = "debug:reload"
```

The existing `CONFIG_TAG_MAP` is extended with five entries pointing at
the five new `ConfigEntry` keys below.

### New `ConfigEntry`s (`provider/config.py`)

Five booleans, `default_value=False`, `category="Debug"`,
`description` carrying an explicit "exposes raw runtime state — disable
in production" warning. `DEBUG_RELOAD`'s description additionally warns
that reload interrupts active streams. A sixth, non-tag entry
`debug_event_buffer_capacity` (`ConfigEntryType.INTEGER`, range
`[50, 5000]`, default `500`) controls ring-buffer size when
`DEBUG_EVENTS` is enabled.

### Response dataclasses (`provider/models.py`)

Conventions match the existing `*Brief` family — stdlib `@dataclass`,
flat field set, no inheritance.

```python
@dataclass(frozen=True, kw_only=True)
class PlayerInspect:
    player_id: str
    raw: dict[str, Any]      # recursive dump of Player (excluding state.*)
    state: dict[str, Any]    # recursive dump of Player.state
    truncated: bool

@dataclass(frozen=True, kw_only=True)
class QueueInspect:
    queue_id: str
    raw: dict[str, Any]
    current_item: dict[str, Any] | None
    truncated: bool

@dataclass(frozen=True, kw_only=True)
class ProviderInspect:
    instance_id: str
    raw: dict[str, Any]      # runtime Provider object dump
    manifest: dict[str, Any]
    truncated: bool

@dataclass(frozen=True, kw_only=True)
class LogLine:
    timestamp: str | None    # ISO 8601 when parseable, else None
    level: str | None
    component: str | None
    message: str             # already redactor-applied

@dataclass(frozen=True, kw_only=True)
class LogTailResult:
    log_path: str
    lines: list[LogLine]
    bytes_scanned: int       # how many bytes the tailer read from EOF
    truncated: bool          # True iff the 10 MB scan cap was reached

@dataclass(frozen=True, kw_only=True)
class EventRecord:
    timestamp: str           # ISO 8601
    event_type: str
    object_id: str | None
    data: Any                # serializer output

@dataclass(frozen=True, kw_only=True)
class EventSnapshot:
    events: list[EventRecord]
    buffer_capacity: int
    total_seen: int

@dataclass(frozen=True, kw_only=True)
class EventBufferStats:
    capacity: int
    current_size: int
    total_seen: int
    dropped: int
    subscribed_since: str | None     # ISO 8601, None if not subscribed
    by_type: dict[str, int]

@dataclass(frozen=True, kw_only=True)
class ProviderSummary:
    instance_id: str
    domain: str
    type: str                # "music" / "player" / "metadata" / "plugin"
    name: str
    available: bool
    last_error: str | None

@dataclass(frozen=True, kw_only=True)
class ProviderList:
    providers: list[ProviderSummary]

@dataclass(frozen=True, kw_only=True)
class ConfigValueDump:
    key: str
    type: str                # ConfigEntryType.value
    value: Any               # SECURE_STRING already replaced upstream by __post_serialize__

@dataclass(frozen=True, kw_only=True)
class ProviderConfigDump:
    instance_id: str
    domain: str
    values: list[ConfigValueDump]
    truncated: bool

@dataclass(frozen=True, kw_only=True)
class RouteEntry:
    method: str
    path: str
    registered_by: str | None        # best-effort attribution

@dataclass(frozen=True, kw_only=True)
class RouteList:
    routes: list[RouteEntry]

@dataclass(frozen=True, kw_only=True)
class PackageVersions:
    packages: dict[str, str]

@dataclass(frozen=True, kw_only=True)
class ReloadResult:
    instance_id: str
    duration_ms: float
    new_available: bool
    last_error: str | None

@dataclass(frozen=True, kw_only=True)
class HealthSummary:
    providers_loaded: int
    providers_disabled: int
    providers_error: int                       # count where last_error is set
    providers_error_details: list[ProviderSummary]   # the offending ones
    queues_total: int
    queues_with_active_playback: int
    queues_with_errors: int                    # heuristic: state==error or unavailable players
    events_per_min_by_type: dict[str, float] | None    # None if DEBUG_EVENTS off
    log_errors_last_5min: int | None           # None if DEBUG_LOGS off
    disabled_capabilities: list[str]           # ["DEBUG_EVENTS", "DEBUG_LOGS"] when off
```

### New file layout

```
provider/
  tools/
    debug.py                       # build_debug_server + 10 tool defs
  debug/
    __init__.py
    event_buffer.py                # EventBuffer
    log_reader.py                  # SafeLogTail + redactor
    inspect_serializer.py          # dump()
  models.py                        # +17 new dataclasses (above)
  config.py                        # +6 ConfigEntry
  tags.py                          # +5 Tag members, +5 CONFIG_TAG_MAP entries
  server.py                        # mount debug sub-server, lifecycle wiring,
                                   # _reload_lock = asyncio.Lock()

tests/
  conftest.py                      # +mounted_debug, +mounted_debug_off,
                                   #  +tmp_log_dir, +fake_event_emitter,
                                   #  +mock_provider_config (ProviderConfig
                                   #   with a SECURE_STRING entry whose
                                   #   to_dict() exercises __post_serialize__)
  test_debug_inspect.py
  test_debug_inspect_serializer.py
  test_debug_logs.py
  test_debug_events.py
  test_debug_providers.py
  test_debug_reload.py
  test_debug_lifecycle.py
  test_debug_security.py
  test_debug_health.py
  fixtures/
    musicassistant.sample.log      # ~1000 lines, mixed levels and components
```

### Tool descriptions — designed for LLM-driven workflows

Each debug tool's FastMCP `description=` parameter is more than a
one-liner: it includes (a) the one-sentence purpose, (b) a "see also"
cross-reference naming the complementary tool in the troubleshooting
chain, and (c) for the inspect family, a hint about which fields tend
to be diagnostic. This gives an LLM agent bread-crumbs across the
ten-tool surface without an external prompt library. The chains the
descriptions encode:

- `debug_health_summary` → "if a section flags errors, drill into the
  named tool: `debug_inspect_provider` for provider errors,
  `debug_inspect_queue` for queue errors, `debug_tail_log` for the
  log error count".
- `debug_tail_log` → "for state transitions in the same time window
  see `debug_recent_events`; for the configured provider whose
  component name appears in a line see `debug_inspect_provider`".
- `debug_recent_events` → "for the textual context of an event see
  `debug_tail_log` with `since_seconds` matching the event timestamp".
- `debug_inspect_player` → "for the queue this player is driving see
  `debug_inspect_queue`; for transitions of this player see
  `debug_recent_events` with `id_filter=<player_id>`".
- `debug_inspect_provider` → "for masked configuration see
  `debug_inspect_provider_config`; for routes this provider registered
  see `debug_list_webserver_routes`; to reload it see
  `debug_reload_provider`".
- `debug_reload_provider` → "to verify the reload landed use
  `debug_inspect_provider`; to see the reload's own log lines use
  `debug_tail_log`".

These descriptions are part of the public MCP surface — pinned in
tests via `await client.list_tools()` snapshot assertions to prevent
silent drift.

### Deliberately deferred / out-of-scope

Documented so a future spec does not re-litigate the same trade-offs:

- **Repro orchestration tools** ("play URI X on player Y, capture
  state-transitions for 30 s, return trace") — explicitly deferred in
  the brainstorming round. Once `debug_inspect_*` and
  `debug_recent_events` exist, an LLM agent can chain them manually
  for ad-hoc repro; a dedicated orchestrator can be added when that
  manual chain becomes painful enough to justify the surface.
- **Library DB read-only SELECT sandbox** — deferred. `library.db`
  is on disk and `sqlite3` CLI is fine for the human at the keyboard.
  Revisit if an LLM-driven workflow needs query-by-URI repeatedly.
- **Trace-ID correlation across logs and events** — not applicable in
  this layer. MA core does not carry trace-ids today; a debug tool
  cannot fabricate them. If MA adopts structured logging with
  trace-ids, the spec is extended then.
- **Audit-logging of read-only debug calls** — intentionally absent.
  Reads are already gated by off-by-default `ConfigEntry`; auditing
  every inspect call would drown the audit signal that matters
  (writes via `debug_reload_provider`). If a deployment requires
  read-audit, it belongs at the MCP transport layer, not in each tool.
- **Persistent event buffer across provider restart** — out of scope.
  The ring buffer is in-memory; on `unload`/`setup` it resets.
  Postmortem of crashes uses the on-disk log instead. A persistent
  buffer would require a schema and rotation, which is disproportionate
  for the debug surface.
- **Following log rotation mid-call** — accepted limitation. A line
  that rotates from `musicassistant.log` to `.log.1` between two
  `debug_tail_log` calls is not stitched together. The agent can read
  both files in sequence; a "tail-with-follow-rotation" mode would
  require persistent file handles that conflict with the stateless
  design of the log tool.
- **State-diff before/after reload** — out of scope for v1. The
  agent can call `debug_inspect_provider` before and after and diff
  itself.

### Known private-API carve-outs

Documented up front so reviewers don't have to grep:

- `mass._load_provider(conf)` — private in MA core (`mass.py:946`).
  It is the only reload primitive (it internally unloads any existing
  instance before re-running setup). Used by `debug_reload_provider`
  as the sole reload entry point. Single call site, single
  `# noqa`-justified comment. If upstream review requests a public
  wrapper, an issue is filed against `music-assistant/server` *before*
  the provider lands upstream.
- `mass.webserver._server.app.router.routes()` — private attribute walk
  in `debug_list_webserver_routes`. Same treatment: single call site,
  documented comment, optional upstream issue for a public
  `list_routes()`.

These are the only two private-API touches in the spec. No other MA
internals are reached into.
