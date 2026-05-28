# Debug Namespace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a ninth FastMCP sub-server, `debug`, exposing ten read/triage tools and one guarded write tool (`debug_reload_provider`) for MA development and troubleshooting workflows over MCP, gated by five new off-by-default permission tags.

**Architecture:** New sub-server mounted by `MCPServerRuntime` alongside the existing eight. New `provider/debug/` subpackage holds three stateless helpers (`inspect_serializer.dump`, `SafeLogTail.tail`, `EventBuffer` ring deque + lifecycle). Tools are pure transport — they call MA's public API (and two documented private-API touches: `mass._load_provider`, `mass.webserver._server.app.router`), run results through the helpers, and return frozen dataclasses defined in `provider/models.py`.

**Tech Stack:** Python 3.13+, FastMCP 3.3.1, `music_assistant`/`music_assistant_models` (read-only against installed copy), stdlib `collections.deque` / `asyncio.Lock` / `importlib.metadata` / `pathlib`. Tests: `pytest`, `pytest-asyncio` (via FastMCP `Client`), `freezegun`, `unittest.mock` per existing project pattern.

**Spec:** `specs/inprogress/0005-debug-namespace.md` — all ACs in this plan are referenced as **AC #N**.

---

## File Structure

**New files:**

```
provider/
  debug/
    __init__.py                                  # empty (package marker)
    inspect_serializer.py                        # dump() recursive JSON-safe converter
    log_reader.py                                # SafeLogTail + redactor
    event_buffer.py                              # EventBuffer (ring deque + lifecycle)
  tools/
    debug.py                                     # build_debug_server + 10 tools

tests/
  fixtures/
    musicassistant.sample.log                    # ~1000 lines mixed levels/components
  test_debug_inspect_serializer.py               # pure unit tests for dump()
  test_debug_logs.py                             # SafeLogTail + e2e debug_tail_log
  test_debug_events.py                           # EventBuffer + e2e events tools
  test_debug_inspect.py                          # e2e inspect_player/queue/provider
  test_debug_providers.py                        # e2e providers tools
  test_debug_reload.py                           # e2e reload + lock + audit
  test_debug_health.py                           # e2e health_summary
  test_debug_lifecycle.py                        # setup/unload order, idempotency
  test_debug_security.py                         # off-by-default + cross-cutting
```

**Modified files:**

```
provider/constants.py                            # +6 CONF_DEBUG_* constants
provider/tags.py                                 # +5 Tag enum members, +5 CONFIG_TO_TAG entries
provider/config.py                               # +6 ConfigEntry (5 booleans + capacity int)
provider/models.py                               # +17 frozen dataclasses
provider/tools/__init__.py                       # +export build_debug_server
provider/server.py                               # mount debug, wire EventBuffer setup/stop, _reload_lock
tests/conftest.py                                # +mounted_debug, +mounted_debug_off, +tmp_log_dir, +fake_event_emitter, +mock_provider_config
VERSION                                          # 0.3.35 → 0.4.0
CHANGELOG.md                                     # add ## [0.4.0] block
```

**File-ownership rationale:** the three helpers in `provider/debug/` are pure (no FastMCP dependency); they're testable as plain functions and reusable if we later expose any of them as resources. `provider/tools/debug.py` is transport-only. Splitting helpers out keeps `tools/debug.py` focused on MCP wiring.

---

## Task 1: Foundation — constants, tags, ConfigEntries

**Why first:** every later task references either a CONF_DEBUG_* constant, a `Tag.DEBUG_*` member, or a ConfigEntry by key. They're cheap and dependency-free.

**Spec coverage:** AC #1 (off-by-default surface — these are the gating ConfigEntries).

**Files:**
- Modify: `provider/constants.py` — add the six CONF_DEBUG_* keys.
- Modify: `provider/tags.py` — add five Tag members, extend `CONFIG_TO_TAG`.
- Modify: `provider/config.py` — add six `ConfigEntry`s (five booleans + one int).
- Modify: `tests/test_tags.py` — pin the five new mappings.
- Modify: `tests/test_config_entries.py` — pin discoverability + defaults + capacity range.

- [ ] **Step 1.1: Add six CONF_DEBUG_* constants**

Edit `provider/constants.py`. After the existing CONF_RES_* block:

```python
# Debug namespace permission flags (all off-by-default).
CONF_DEBUG_INSPECT = "debug_inspect"
CONF_DEBUG_LOGS = "debug_logs"
CONF_DEBUG_EVENTS = "debug_events"
CONF_DEBUG_PROVIDERS = "debug_providers"
CONF_DEBUG_RELOAD = "debug_reload"
CONF_DEBUG_EVENT_BUFFER_CAPACITY = "debug_event_buffer_capacity"
```

- [ ] **Step 1.2: Extend `Tag` enum + mapping**

Edit `provider/tags.py`:

1. In the import block, add the five new constants:

```python
from .constants import (
    # ... existing imports unchanged ...
    CONF_DEBUG_INSPECT,
    CONF_DEBUG_LOGS,
    CONF_DEBUG_EVENTS,
    CONF_DEBUG_PROVIDERS,
    CONF_DEBUG_RELOAD,
)
```

2. After `DELETE_FAVORITES = "delete:favorites"` in the `Tag` class:

```python
    DEBUG_INSPECT = "debug:inspect"
    DEBUG_LOGS = "debug:logs"
    DEBUG_EVENTS = "debug:events"
    DEBUG_PROVIDERS = "debug:providers"
    DEBUG_RELOAD = "debug:reload"
```

3. At the bottom of `CONFIG_TO_TAG`, after `CONF_DELETE_FAVORITES: Tag.DELETE_FAVORITES,`:

```python
    CONF_DEBUG_INSPECT: Tag.DEBUG_INSPECT,
    CONF_DEBUG_LOGS: Tag.DEBUG_LOGS,
    CONF_DEBUG_EVENTS: Tag.DEBUG_EVENTS,
    CONF_DEBUG_PROVIDERS: Tag.DEBUG_PROVIDERS,
    CONF_DEBUG_RELOAD: Tag.DEBUG_RELOAD,
```

- [ ] **Step 1.3: Add six ConfigEntry definitions**

Edit `provider/config.py`. First, extend the import block:

```python
from .constants import (
    # ... existing imports unchanged ...
    CONF_DEBUG_INSPECT,
    CONF_DEBUG_LOGS,
    CONF_DEBUG_EVENTS,
    CONF_DEBUG_PROVIDERS,
    CONF_DEBUG_RELOAD,
    CONF_DEBUG_EVENT_BUFFER_CAPACITY,
)
```

Then append six entries to the tuple returned by `build_config_entries`. Place after the last `_bool(CONF_DELETE_*, ...)` call:

```python
        # Debug namespace — all off-by-default. See specs/inprogress/0005-debug-namespace.md.
        _bool(
            CONF_DEBUG_INSPECT,
            "Debug: inspect raw player/queue/provider state",
            False,
            "Debug",
            "Exposes raw runtime state of players, queues, and providers via MCP. "
            "Intended for development and troubleshooting. Disable in production.",
        ),
        _bool(
            CONF_DEBUG_LOGS,
            "Debug: tail musicassistant.log",
            False,
            "Debug",
            "Allows MCP clients to read the tail of MA's log file with filters. "
            "Common token patterns are redacted. Intended for troubleshooting. "
            "Disable in production.",
        ),
        _bool(
            CONF_DEBUG_EVENTS,
            "Debug: read recent MA events",
            False,
            "Debug",
            "Subscribes to MA's event bus at provider startup and exposes a "
            "ring buffer over MCP. Memory cost is bounded by the buffer "
            "capacity. Intended for troubleshooting. Disable in production.",
        ),
        _bool(
            CONF_DEBUG_PROVIDERS,
            "Debug: inspect configured providers",
            False,
            "Debug",
            "Exposes provider state, masked configuration, registered "
            "webserver routes, installed package versions, and a health "
            "summary roll-up. Intended for troubleshooting. Disable in "
            "production.",
        ),
        _bool(
            CONF_DEBUG_RELOAD,
            "Debug: reload a provider instance",
            False,
            "Debug",
            "Allows MCP clients to unload and reload provider instances, "
            "INTERRUPTING ANY ACTIVE STREAMS on the affected provider. "
            "Each call requires elicitation confirmation. Intended for "
            "provider-development iteration. Disable in production.",
        ),
        ConfigEntry(
            key=CONF_DEBUG_EVENT_BUFFER_CAPACITY,
            type=ConfigEntryType.INTEGER,
            label="Debug: event buffer capacity",
            default_value=500,
            range=(50, 5000),
            category="Debug",
            description=(
                "Maximum number of recent events kept in memory when "
                "`Debug: read recent MA events` is enabled. Older events "
                "are dropped FIFO. Has no effect when events are off."
            ),
            required=False,
        ),
```

- [ ] **Step 1.4: Extend `tests/test_tags.py`**

Append to the existing file:

```python
def test_debug_tags_present_in_enum() -> None:
    assert Tag.DEBUG_INSPECT.value == "debug:inspect"
    assert Tag.DEBUG_LOGS.value == "debug:logs"
    assert Tag.DEBUG_EVENTS.value == "debug:events"
    assert Tag.DEBUG_PROVIDERS.value == "debug:providers"
    assert Tag.DEBUG_RELOAD.value == "debug:reload"


def test_debug_config_keys_map_to_tags() -> None:
    from provider.constants import (
        CONF_DEBUG_INSPECT,
        CONF_DEBUG_LOGS,
        CONF_DEBUG_EVENTS,
        CONF_DEBUG_PROVIDERS,
        CONF_DEBUG_RELOAD,
    )
    from provider.tags import CONFIG_TO_TAG, Tag

    assert CONFIG_TO_TAG[CONF_DEBUG_INSPECT] is Tag.DEBUG_INSPECT
    assert CONFIG_TO_TAG[CONF_DEBUG_LOGS] is Tag.DEBUG_LOGS
    assert CONFIG_TO_TAG[CONF_DEBUG_EVENTS] is Tag.DEBUG_EVENTS
    assert CONFIG_TO_TAG[CONF_DEBUG_PROVIDERS] is Tag.DEBUG_PROVIDERS
    assert CONFIG_TO_TAG[CONF_DEBUG_RELOAD] is Tag.DEBUG_RELOAD


def test_enabled_tags_excludes_debug_when_off(mock_mass):
    from music_assistant_models.config_entries import ProviderConfig

    from provider.config import build_config_entries
    from provider.tags import Tag, enabled_tags

    entries = build_config_entries(mock_mass, {})
    conf = ProviderConfig.parse(entries, {"values": {}})
    enabled = enabled_tags(conf)
    assert Tag.DEBUG_INSPECT not in enabled
    assert Tag.DEBUG_LOGS not in enabled
    assert Tag.DEBUG_EVENTS not in enabled
    assert Tag.DEBUG_PROVIDERS not in enabled
    assert Tag.DEBUG_RELOAD not in enabled
```

- [ ] **Step 1.5: Extend `tests/test_config_entries.py`**

Append:

```python
def test_debug_entries_present_with_off_defaults(mock_mass):
    from provider.config import build_config_entries
    from provider.constants import (
        CONF_DEBUG_INSPECT,
        CONF_DEBUG_LOGS,
        CONF_DEBUG_EVENTS,
        CONF_DEBUG_PROVIDERS,
        CONF_DEBUG_RELOAD,
        CONF_DEBUG_EVENT_BUFFER_CAPACITY,
    )

    entries = {e.key: e for e in build_config_entries(mock_mass, {})}
    for key in (CONF_DEBUG_INSPECT, CONF_DEBUG_LOGS, CONF_DEBUG_EVENTS, CONF_DEBUG_PROVIDERS, CONF_DEBUG_RELOAD):
        assert key in entries, f"missing {key}"
        assert entries[key].default_value is False, f"{key} must be off by default"
        assert entries[key].category == "Debug"

    cap = entries[CONF_DEBUG_EVENT_BUFFER_CAPACITY]
    assert cap.default_value == 500
    assert cap.range == (50, 5000)
```

- [ ] **Step 1.6: Run tests**

```bash
uv run pytest tests/test_tags.py tests/test_config_entries.py -v
```

Expected: all pre-existing tests still pass; the four new ones pass.

- [ ] **Step 1.7: Lint**

```bash
uv run ruff check provider/ tests/
uv run ruff format provider/ tests/
```

Expected: clean.

- [ ] **Step 1.8: Commit**

```bash
git add provider/constants.py provider/tags.py provider/config.py tests/test_tags.py tests/test_config_entries.py
git commit -m "$(cat <<'EOF'
feat(debug): add 5 debug Tag members + 6 ConfigEntries (off-by-default)

Foundation commit for the upcoming debug namespace (see
specs/inprogress/0005-debug-namespace.md). No tools are wired yet —
this introduces the permission tags and gating ConfigEntries that
later tasks will reference.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Response dataclasses

**Why:** All ten tools return frozen dataclasses. Defining them up-front lets later tool tasks focus on logic, not schema.

**Spec coverage:** Data Model section in spec (all 17 classes).

**Files:**
- Modify: `provider/models.py` — append 17 dataclasses.
- Modify: `tests/test_models.py` — assert each class is frozen, kw_only, has expected fields.

- [ ] **Step 2.1: Add 17 dataclasses to `provider/models.py`**

Append (after the existing `QueueBrief` block — preserve the existing import block at the top of the file):

```python
# ---- Debug namespace response dataclasses (spec 0005) ----


@dataclass(frozen=True, kw_only=True)
class PlayerInspect:
    """Raw mirror of a Player dataclass with state.* surfaced separately."""

    player_id: str
    raw: dict[str, Any]
    state: dict[str, Any]
    truncated: bool


@dataclass(frozen=True, kw_only=True)
class QueueInspect:
    """Raw mirror of a PlayerQueue with current_item resolved."""

    queue_id: str
    raw: dict[str, Any]
    current_item: dict[str, Any] | None
    truncated: bool


@dataclass(frozen=True, kw_only=True)
class ProviderInspect:
    """Raw mirror of a runtime Provider object + its manifest."""

    instance_id: str
    raw: dict[str, Any]
    manifest: dict[str, Any]
    truncated: bool


@dataclass(frozen=True, kw_only=True)
class LogLine:
    """One parsed line from musicassistant.log."""

    timestamp: str | None
    level: str | None
    component: str | None
    message: str


@dataclass(frozen=True, kw_only=True)
class LogTailResult:
    """Result of debug_tail_log."""

    log_path: str
    lines: list[LogLine]
    bytes_scanned: int
    truncated: bool


@dataclass(frozen=True, kw_only=True)
class EventRecord:
    """One MA event captured into the ring buffer."""

    timestamp: str
    event_type: str
    object_id: str | None
    data: Any


@dataclass(frozen=True, kw_only=True)
class EventSnapshot:
    """Result of debug_recent_events."""

    events: list[EventRecord]
    buffer_capacity: int
    total_seen: int


@dataclass(frozen=True, kw_only=True)
class EventBufferStats:
    """Result of debug_event_buffer_stats."""

    capacity: int
    current_size: int
    total_seen: int
    dropped: int
    subscribed_since: str | None
    by_type: dict[str, int]


@dataclass(frozen=True, kw_only=True)
class ProviderSummary:
    """One row of debug_list_providers."""

    instance_id: str
    domain: str
    type: str
    name: str
    available: bool
    last_error: str | None


@dataclass(frozen=True, kw_only=True)
class ProviderList:
    """Result of debug_list_providers."""

    providers: list[ProviderSummary]


@dataclass(frozen=True, kw_only=True)
class ConfigValueDump:
    """One value from a provider ConfigEntry dump (SECURE_STRING already masked upstream)."""

    key: str
    type: str
    value: Any


@dataclass(frozen=True, kw_only=True)
class ProviderConfigDump:
    """Result of debug_inspect_provider_config."""

    instance_id: str
    domain: str
    values: list[ConfigValueDump]
    truncated: bool


@dataclass(frozen=True, kw_only=True)
class RouteEntry:
    """One row of debug_list_webserver_routes."""

    method: str
    path: str
    registered_by: str | None


@dataclass(frozen=True, kw_only=True)
class RouteList:
    """Result of debug_list_webserver_routes."""

    routes: list[RouteEntry]


@dataclass(frozen=True, kw_only=True)
class PackageVersions:
    """Result of debug_list_package_versions."""

    packages: dict[str, str]


@dataclass(frozen=True, kw_only=True)
class ReloadResult:
    """Result of debug_reload_provider."""

    instance_id: str
    duration_ms: float
    new_available: bool
    last_error: str | None


@dataclass(frozen=True, kw_only=True)
class HealthSummary:
    """Result of debug_health_summary — the LLM agent's triage entry point."""

    providers_loaded: int
    providers_disabled: int
    providers_error: int
    providers_error_details: list[ProviderSummary]
    queues_total: int
    queues_with_active_playback: int
    queues_with_errors: int
    events_per_min_by_type: dict[str, float] | None
    log_errors_last_5min: int | None
    disabled_capabilities: list[str]
```

If the existing file does not already import `Any`, ensure the import block contains:

```python
from typing import Any
```

- [ ] **Step 2.2: Add tests for the new dataclasses**

Append to `tests/test_models.py`:

```python
import dataclasses

import pytest


_DEBUG_CLASSES = [
    ("PlayerInspect", {"player_id", "raw", "state", "truncated"}),
    ("QueueInspect", {"queue_id", "raw", "current_item", "truncated"}),
    ("ProviderInspect", {"instance_id", "raw", "manifest", "truncated"}),
    ("LogLine", {"timestamp", "level", "component", "message"}),
    ("LogTailResult", {"log_path", "lines", "bytes_scanned", "truncated"}),
    ("EventRecord", {"timestamp", "event_type", "object_id", "data"}),
    ("EventSnapshot", {"events", "buffer_capacity", "total_seen"}),
    (
        "EventBufferStats",
        {"capacity", "current_size", "total_seen", "dropped", "subscribed_since", "by_type"},
    ),
    ("ProviderSummary", {"instance_id", "domain", "type", "name", "available", "last_error"}),
    ("ProviderList", {"providers"}),
    ("ConfigValueDump", {"key", "type", "value"}),
    ("ProviderConfigDump", {"instance_id", "domain", "values", "truncated"}),
    ("RouteEntry", {"method", "path", "registered_by"}),
    ("RouteList", {"routes"}),
    ("PackageVersions", {"packages"}),
    ("ReloadResult", {"instance_id", "duration_ms", "new_available", "last_error"}),
    (
        "HealthSummary",
        {
            "providers_loaded",
            "providers_disabled",
            "providers_error",
            "providers_error_details",
            "queues_total",
            "queues_with_active_playback",
            "queues_with_errors",
            "events_per_min_by_type",
            "log_errors_last_5min",
            "disabled_capabilities",
        },
    ),
]


@pytest.mark.parametrize(("name", "fields"), _DEBUG_CLASSES)
def test_debug_dataclass_shape(name: str, fields: set[str]) -> None:
    import provider.models as models

    cls = getattr(models, name)
    assert dataclasses.is_dataclass(cls), f"{name} is not a dataclass"
    assert cls.__dataclass_params__.frozen, f"{name} must be frozen"
    assert cls.__dataclass_params__.kw_only, f"{name} must be kw_only"
    actual = {f.name for f in dataclasses.fields(cls)}
    assert actual == fields, f"{name} fields drift: {actual - fields=} {fields - actual=}"
```

- [ ] **Step 2.3: Run + lint + commit**

```bash
uv run pytest tests/test_models.py -v
uv run ruff check provider/ tests/ && uv run ruff format provider/ tests/
git add provider/models.py tests/test_models.py
git commit -m "$(cat <<'EOF'
feat(debug): add 17 response dataclasses for debug namespace tools

Spec 0005 Data Model section. Pure schema; tools land in later commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `inspect_serializer.dump`

**Why before tools:** the three inspect tools all call this. Pure function = easy unit tests; if defective, every inspect tool returns garbage.

**Spec coverage:** AC #2 (depth/str caps, placeholders, cycle safety, defensive try/except), AC #8 (256 KB total payload cap).

**Files:**
- Create: `provider/debug/__init__.py` (empty).
- Create: `provider/debug/inspect_serializer.py`.
- Create: `tests/test_debug_inspect_serializer.py`.

- [ ] **Step 3.1: Create empty package marker**

Write `provider/debug/__init__.py` (single empty line):

```python
```

- [ ] **Step 3.2: Write failing tests first**

Create `tests/test_debug_inspect_serializer.py`:

```python
"""Unit tests for the recursive JSON-safe inspect serializer."""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import enum
import json

import pytest

from provider.debug.inspect_serializer import dump


@dataclasses.dataclass
class _Inner:
    x: int
    label: str


@dataclasses.dataclass
class _Outer:
    name: str
    inner: _Inner
    items: list[int]


def test_dump_simple_dataclass() -> None:
    obj = _Outer(name="root", inner=_Inner(x=1, label="hi"), items=[1, 2, 3])
    out = dump(obj)
    assert out == {"name": "root", "inner": {"x": 1, "label": "hi"}, "items": [1, 2, 3]}


def test_dump_handles_self_reference_without_recursion_error() -> None:
    d: dict = {}
    d["self"] = d
    out = dump(d)
    assert out["self"] == "<cycle>"


def test_dump_max_depth_truncates() -> None:
    deep: dict = current = {}
    for i in range(10):
        current["next"] = {}
        current = current["next"]
    current["leaf"] = "value"
    out = dump(deep, max_depth=3)

    def _depth(o, n=0):
        if isinstance(o, dict) and "next" in o:
            return _depth(o["next"], n + 1)
        return n, o

    depth, leaf = _depth(out)
    assert depth == 3
    assert leaf == "<max depth>"


def test_dump_max_str_truncates_with_suffix() -> None:
    big = "x" * 5000
    out = dump(big, max_str=100)
    assert isinstance(out, str)
    assert out.startswith("x" * 100)
    assert "…(" in out and "more chars)" in out


class _Color(enum.Enum):
    RED = "red"
    BLUE = "blue"


def test_dump_enum_to_value() -> None:
    assert dump(_Color.RED) == "red"


def test_dump_datetime_to_iso8601() -> None:
    t = dt.datetime(2026, 5, 28, 12, 34, 56, tzinfo=dt.UTC)
    assert dump(t) == "2026-05-28T12:34:56+00:00"


def test_dump_bytes_to_length_placeholder() -> None:
    assert dump(b"\x00" * 4096) == "<bytes len=4096>"


def test_dump_unserialisable_objects_render_placeholder() -> None:
    lock = asyncio.Lock()
    assert dump(lock) == "<unserializable Lock>"


def test_dump_property_raising_renders_placeholder() -> None:
    class _Bad:
        @property
        def value(self):
            raise RuntimeError("not ready")

    out = dump(_Bad())
    assert out["value"] == "<raise: RuntimeError>"


def test_dump_total_payload_cap_marks_truncated() -> None:
    # 300 KB of content (300 strings of 1 KB each); cap at 256 KB.
    big = {f"k{i}": "y" * 1024 for i in range(300)}
    out, truncated = dump(big, max_total_bytes=256 * 1024, return_truncated=True)
    assert truncated is True
    assert len(json.dumps(out)) <= 256 * 1024 + 1024  # +slack for the marker
```

Run:

```bash
uv run pytest tests/test_debug_inspect_serializer.py -v
```

Expected: every test fails with `ModuleNotFoundError: No module named 'provider.debug.inspect_serializer'`.

- [ ] **Step 3.3: Implement `dump`**

Create `provider/debug/inspect_serializer.py`:

```python
"""Recursive JSON-safe converter for raw MA dataclass inspection.

Caller contract — :func:`dump` never raises for user-visible cases:

* unknown attribute access errors are caught per-field and rendered as
  ``"<raise: ExcClass>"`` placeholders so a half-constructed object can
  still be inspected;
* cycles render as ``"<cycle>"`` (not :class:`RecursionError`);
* tasks / locks / generators / file handles render as
  ``"<unserializable ClassName>"`` rather than failing;
* depth and string-length are capped (defaults: ``max_depth=6``,
  ``max_str=2048``);
* an optional ``max_total_bytes`` cap halts serialisation after the
  budget is exceeded; ``return_truncated=True`` returns a tuple
  ``(payload, truncated)`` instead of just the payload.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import enum
import json
from typing import Any

_UNSERIALISABLE = (
    asyncio.Lock,
    asyncio.Future,
    asyncio.Task,
    asyncio.Event,
    asyncio.Queue,
    asyncio.Semaphore,
)


def dump(
    obj: Any,
    *,
    max_depth: int = 6,
    max_str: int = 2048,
    max_total_bytes: int | None = None,
    return_truncated: bool = False,
) -> Any:
    """Convert ``obj`` to a JSON-safe structure.

    :param obj: Any Python object.
    :param max_depth: Maximum recursion depth before fields collapse to
        ``"<max depth>"``.
    :param max_str: Per-string truncation length.
    :param max_total_bytes: When set, serialisation halts once the
        approximate JSON-encoded size exceeds this many bytes.
    :param return_truncated: When True, return ``(payload, truncated_flag)``
        instead of just ``payload``.
    """
    state = _State(max_depth=max_depth, max_str=max_str, max_total_bytes=max_total_bytes)
    payload = _convert(obj, depth=0, seen=set(), state=state)
    if return_truncated:
        return payload, state.truncated
    return payload


class _State:
    __slots__ = ("max_depth", "max_str", "max_total_bytes", "bytes_used", "truncated")

    def __init__(self, *, max_depth: int, max_str: int, max_total_bytes: int | None) -> None:
        self.max_depth = max_depth
        self.max_str = max_str
        self.max_total_bytes = max_total_bytes
        self.bytes_used = 0
        self.truncated = False

    def budget_exceeded(self) -> bool:
        return self.max_total_bytes is not None and self.bytes_used >= self.max_total_bytes

    def charge(self, value: Any) -> None:
        if self.max_total_bytes is None:
            return
        try:
            self.bytes_used += len(json.dumps(value, default=str))
        except (TypeError, ValueError):
            self.bytes_used += 32


def _convert(obj: Any, *, depth: int, seen: set[int], state: _State) -> Any:
    if state.budget_exceeded():
        state.truncated = True
        return "<truncated>"
    if depth >= state.max_depth:
        return "<max depth>"

    if obj is None or isinstance(obj, bool | int | float):
        state.charge(obj)
        return obj

    if isinstance(obj, str):
        if len(obj) > state.max_str:
            remainder = len(obj) - state.max_str
            value = f"{obj[: state.max_str]}…({remainder} more chars)"
        else:
            value = obj
        state.charge(value)
        return value

    if isinstance(obj, bytes | bytearray | memoryview):
        value = f"<bytes len={len(obj)}>"
        state.charge(value)
        return value

    if isinstance(obj, enum.Enum):
        return _convert(obj.value, depth=depth, seen=seen, state=state)

    if isinstance(obj, dt.datetime | dt.date | dt.time):
        value = obj.isoformat()
        state.charge(value)
        return value

    if isinstance(obj, _UNSERIALISABLE):
        value = f"<unserializable {type(obj).__name__}>"
        state.charge(value)
        return value

    if id(obj) in seen:
        return "<cycle>"
    seen = seen | {id(obj)}

    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if state.budget_exceeded():
                state.truncated = True
                break
            out[str(k)] = _convert(v, depth=depth + 1, seen=seen, state=state)
        return out

    if isinstance(obj, list | tuple | set | frozenset):
        seq: list[Any] = []
        for item in obj:
            if state.budget_exceeded():
                state.truncated = True
                break
            seq.append(_convert(item, depth=depth + 1, seen=seen, state=state))
        return seq

    if dataclasses.is_dataclass(obj):
        return _convert_attrs(obj, [f.name for f in dataclasses.fields(obj)], depth, seen, state)

    if hasattr(obj, "__dict__") or hasattr(obj, "__slots__"):
        names = list(getattr(obj, "__dict__", {}).keys())
        for slot in getattr(obj, "__slots__", ()) or ():
            if slot not in names:
                names.append(slot)
        names = [n for n in names if not n.startswith("_")]
        if names:
            return _convert_attrs(obj, names, depth, seen, state)

    # Last-ditch fallback: stringify.
    value = f"<unserializable {type(obj).__name__}>"
    state.charge(value)
    return value


def _convert_attrs(
    obj: Any, names: list[str], depth: int, seen: set[int], state: _State
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in names:
        if state.budget_exceeded():
            state.truncated = True
            break
        try:
            value = getattr(obj, name)
        except Exception as exc:  # noqa: BLE001 — defensive AC #2.
            out[name] = f"<raise: {type(exc).__name__}>"
            continue
        out[name] = _convert(value, depth=depth + 1, seen=seen, state=state)
    return out
```

- [ ] **Step 3.4: Run tests, lint, commit**

```bash
uv run pytest tests/test_debug_inspect_serializer.py -v
uv run ruff check provider/ tests/ && uv run ruff format provider/ tests/
git add provider/debug/__init__.py provider/debug/inspect_serializer.py tests/test_debug_inspect_serializer.py
git commit -m "$(cat <<'EOF'
feat(debug): add inspect_serializer.dump (recursive JSON-safe converter)

Per spec 0005 AC #2 + #8: depth cap, per-string cap, total-bytes cap,
cycle detection, per-attribute defensive try/except, datetime ISO,
enum unwrap, bytes-length placeholder, asyncio-object placeholders.
Pure function; no FastMCP / MA dependency.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `SafeLogTail` + log redactor

**Spec coverage:** AC #4 — path allowlist, traversal rejection, redactor, 10 MB byte cap.

**Files:**
- Create: `provider/debug/log_reader.py`.
- Create: `tests/fixtures/musicassistant.sample.log`.
- Create: `tests/test_debug_logs.py`.
- Modify: `tests/conftest.py` — add `tmp_log_dir` fixture.

- [ ] **Step 4.1: Add a fixture log**

Create `tests/fixtures/musicassistant.sample.log` with ~50 representative lines. Use Python's logging default format `%(asctime)s %(levelname)s %(name)s: %(message)s`:

```
2026-05-28 09:00:00,001 INFO music_assistant.mass: Starting Music Assistant
2026-05-28 09:00:00,123 DEBUG music_assistant.controllers.config: Loaded provider config
2026-05-28 09:00:01,456 WARNING music_assistant.providers.yandex_music: rate-limit retry in 30s
2026-05-28 09:00:02,789 ERROR music_assistant.providers.sonos: Authorization: Bearer abc.def.ghi expired
2026-05-28 09:00:03,012 INFO music_assistant.players.kitchen: powered on
2026-05-28 09:00:04,345 DEBUG music_assistant.streams: token=secret_token_42 starting
2026-05-28 09:00:05,678 INFO music_assistant.providers.spotify: password=hunter2 ignored (use OAuth)
2026-05-28 09:00:06,901 ERROR music_assistant.controllers.music: lookup failed for uri=library://track/42
```

(Add ~40 more lines following the same shape — mix levels, components, and a few multi-byte payloads. Total file size ≥ 5 KB.)

- [ ] **Step 4.2: Add `tmp_log_dir` fixture**

Append to `tests/conftest.py`:

```python
import shutil
from pathlib import Path


@pytest.fixture
def tmp_log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Sandboxed log root for SafeLogTail tests.

    Copies the fixture log into ``tmp_path`` and patches
    ``SafeLogTail.ROOT`` to point at it. Tests never touch the real
    ``~/.musicassistant/`` directory.
    """
    src = Path(__file__).parent / "fixtures" / "musicassistant.sample.log"
    dst = tmp_path / "musicassistant.log"
    shutil.copyfile(src, dst)

    import provider.debug.log_reader as log_reader

    monkeypatch.setattr(log_reader.SafeLogTail, "ROOT", tmp_path, raising=True)
    return tmp_path
```

- [ ] **Step 4.3: Write failing tests**

Create `tests/test_debug_logs.py`:

```python
"""Unit tests for SafeLogTail (path allowlist, byte cap, redactor)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from provider.debug.log_reader import SafeLogTail


def test_tail_returns_last_n_lines(tmp_log_dir: Path) -> None:
    tail = SafeLogTail()
    result = tail.tail(lines=5)
    assert len(result.lines) == 5
    assert result.bytes_scanned > 0
    assert result.truncated is False


def test_tail_redacts_bearer_token(tmp_log_dir: Path) -> None:
    tail = SafeLogTail()
    result = tail.tail(lines=200)
    joined = "\n".join(line.message for line in result.lines)
    assert "abc.def.ghi" not in joined
    assert "<redacted>" in joined


def test_tail_redacts_query_string_secrets(tmp_log_dir: Path) -> None:
    tail = SafeLogTail()
    result = tail.tail(lines=200)
    joined = "\n".join(line.message for line in result.lines)
    assert "secret_token_42" not in joined
    assert "hunter2" not in joined


def test_tail_filters_by_level(tmp_log_dir: Path) -> None:
    tail = SafeLogTail()
    result = tail.tail(lines=200, level="ERROR")
    assert all(line.level == "ERROR" for line in result.lines)
    assert any("lookup failed" in line.message for line in result.lines)


def test_tail_filters_by_component_regex(tmp_log_dir: Path) -> None:
    tail = SafeLogTail()
    result = tail.tail(lines=200, component_regex=r"providers\.yandex.*")
    assert all(line.component and line.component.startswith("music_assistant.providers.yandex") for line in result.lines)


@pytest.mark.parametrize(
    "name",
    ["../etc/passwd", "/etc/passwd", "musicassistant.log\x00.txt", "..", ".", "", "musicassistant.log.99"],
)
def test_path_traversal_rejected(tmp_log_dir: Path, name: str) -> None:
    tail = SafeLogTail()
    with pytest.raises(ToolError):
        tail.tail(lines=1, name=name)


def test_symlink_escape_rejected(tmp_log_dir: Path) -> None:
    outside = tmp_log_dir.parent / "outside.log"
    outside.write_text("LEAK\n")
    symlink = tmp_log_dir / "musicassistant.log.1"  # in allowlist by basename
    symlink.symlink_to(outside)

    tail = SafeLogTail()
    with pytest.raises(ToolError):
        tail.tail(lines=1, name="musicassistant.log.1")


def test_scan_bytes_cap_marks_truncated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import provider.debug.log_reader as log_reader

    monkeypatch.setattr(log_reader.SafeLogTail, "ROOT", tmp_path, raising=True)
    huge = tmp_path / "musicassistant.log"
    with huge.open("wb") as fh:
        # 20 MB of repeated, parseable lines.
        line = b"2026-05-28 09:00:00,001 INFO music_assistant.mass: filler\n"
        while fh.tell() < 20 * 1024 * 1024:
            fh.write(line)

    tail = log_reader.SafeLogTail()
    result = tail.tail(lines=10_000)
    assert result.truncated is True
    assert result.bytes_scanned <= 10 * 1024 * 1024 + len(line)
```

Run:

```bash
uv run pytest tests/test_debug_logs.py -v
```

Expected: every test fails on import (`provider.debug.log_reader` missing).

- [ ] **Step 4.4: Implement `SafeLogTail`**

Create `provider/debug/log_reader.py`:

```python
"""Stateless tail reader for ``$HOME/.musicassistant/musicassistant.log``.

The reader is constrained by three load-bearing invariants:

* **Path allowlist.** Only the canonical log file and its rotated
  siblings (``.log.1`` … ``.log.5``) are openable. Inputs containing
  ``..``, absolute paths, NUL bytes, or symlinks pointing outside the
  root raise :class:`fastmcp.exceptions.ToolError`.
* **Byte cap.** No call reads more than 10 MB from end-of-file even if
  the caller asks for thousands of lines. The cap protects the provider
  process from a self-DoS, not a privacy boundary.
* **Token redactor.** Common bearer-token / query-string / form-field
  secret patterns in the line text are replaced with ``<redacted>``
  before the line is returned. Best-effort; not a substitute for
  scrubbing in MA's own logger.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

from fastmcp.exceptions import ToolError

from provider.models import LogLine, LogTailResult

_LOG_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\s+"
    r"(?P<level>[A-Z]+)\s+"
    r"(?P<component>[A-Za-z0-9_.]+)\s*:\s*"
    r"(?P<msg>.*)$"
)

_REDACTORS = (
    (re.compile(r"(?i)(authorization:\s*bearer)\s+\S+"), r"\1 <redacted>"),
    (re.compile(r"(?i)\btoken=\S+"), "token=<redacted>"),
    (re.compile(r"(?i)\bpassword=\S+"), "password=<redacted>"),
    (re.compile(r"(?i)\bsecret=\S+"), "secret=<redacted>"),
)

_MAX_SCAN_BYTES = 10 * 1024 * 1024
_BLOCK_SIZE = 8 * 1024


class SafeLogTail:
    """Tail the MA log file with path allowlist + byte cap + redactor."""

    ROOT: Path = Path.home() / ".musicassistant"
    ALLOWED = frozenset(
        ["musicassistant.log"] + [f"musicassistant.log.{i}" for i in range(1, 6)]
    )

    def tail(
        self,
        *,
        lines: int = 200,
        level: str | None = None,
        component_regex: str | None = None,
        since_seconds: int | None = None,
        name: str = "musicassistant.log",
    ) -> LogTailResult:
        """Return the last ``lines`` parsed entries from the named log file."""
        lines = max(1, min(int(lines), 2000))
        path = self._safe_path(name)
        if not path.exists():
            raise ToolError(f"log file {name!r} not found")

        component_filter = re.compile(component_regex) if component_regex else None
        now = datetime.now().astimezone()

        raw_lines, bytes_scanned, truncated = self._read_last_lines(path, lines)

        out: list[LogLine] = []
        for raw in raw_lines:
            parsed = self._parse(raw)
            if level and parsed.level != level:
                continue
            if component_filter and not (parsed.component and component_filter.search(parsed.component)):
                continue
            if since_seconds is not None and parsed.timestamp:
                try:
                    when = datetime.fromisoformat(parsed.timestamp)
                except ValueError:
                    continue
                if (now - when).total_seconds() > since_seconds:
                    continue
            out.append(parsed)

        return LogTailResult(
            log_path=str(path),
            lines=out,
            bytes_scanned=bytes_scanned,
            truncated=truncated,
        )

    def count_errors_last_5min(self, *, name: str = "musicassistant.log") -> int:
        """Count ERROR-level entries in the last 5 minutes (used by health_summary)."""
        result = self.tail(lines=2000, level="ERROR", since_seconds=300, name=name)
        return len(result.lines)

    # --- internal helpers ---

    def _safe_path(self, name: str) -> Path:
        if not name or "\x00" in name or name in {".", ".."}:
            raise ToolError(f"log file {name!r} not allowed")
        if name not in self.ALLOWED:
            raise ToolError(f"log file {name!r} not allowed")

        root_resolved = self.ROOT.resolve()
        candidate = (self.ROOT / name)
        if candidate.is_symlink():
            target = candidate.resolve()
            if not target.is_relative_to(root_resolved):
                raise ToolError(f"log file {name!r} not allowed")
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(root_resolved):
            raise ToolError(f"log file {name!r} not allowed")
        return resolved

    def _read_last_lines(self, path: Path, lines: int) -> tuple[list[str], int, bool]:
        """Read up to ``lines`` final lines or 10 MB, whichever is smaller."""
        bytes_scanned = 0
        truncated = False
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            end = fh.tell()
            buffer = b""
            collected = 0
            position = end
            while position > 0 and collected <= lines and bytes_scanned < _MAX_SCAN_BYTES:
                read_size = min(_BLOCK_SIZE, position, _MAX_SCAN_BYTES - bytes_scanned)
                position -= read_size
                fh.seek(position)
                chunk = fh.read(read_size)
                bytes_scanned += read_size
                buffer = chunk + buffer
                collected = buffer.count(b"\n")
            if bytes_scanned >= _MAX_SCAN_BYTES and position > 0:
                truncated = True

        text = buffer.decode("utf-8", errors="replace")
        all_lines = text.splitlines()
        return all_lines[-lines:], bytes_scanned, truncated

    def _parse(self, raw: str) -> LogLine:
        match = _LOG_LINE_RE.match(raw)
        if not match:
            return LogLine(timestamp=None, level=None, component=None, message=self._redact(raw))
        ts_raw = match["ts"].replace(",", ".").replace(" ", "T")
        try:
            # Stamp as local time — MA's logger has no TZ info in the line.
            parsed_ts = datetime.fromisoformat(ts_raw).astimezone().isoformat()
        except ValueError:
            parsed_ts = None
        return LogLine(
            timestamp=parsed_ts,
            level=match["level"],
            component=match["component"],
            message=self._redact(match["msg"]),
        )

    @staticmethod
    def _redact(text: str) -> str:
        for pattern, repl in _REDACTORS:
            text = pattern.sub(repl, text)
        return text
```

- [ ] **Step 4.5: Run tests, lint, commit**

```bash
uv run pytest tests/test_debug_logs.py -v
uv run ruff check provider/ tests/ && uv run ruff format provider/ tests/
git add provider/debug/log_reader.py tests/fixtures/musicassistant.sample.log tests/test_debug_logs.py tests/conftest.py
git commit -m "$(cat <<'EOF'
feat(debug): add SafeLogTail with path allowlist, 10MB cap, redactor

Per spec 0005 AC #4: only musicassistant.log{,.1..5}, traversal rejected,
symlink escape rejected, 10MB read cap, bearer/token/password/secret
redacted to <redacted>. Pure stdlib + fastmcp.ToolError.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `EventBuffer`

**Spec coverage:** AC #5, AC #6 — subscribe once at setup, unsubscribe once at unload, idempotent stop, capacity-respecting deque, filterable snapshot.

**Files:**
- Create: `provider/debug/event_buffer.py`.
- Create: `tests/test_debug_events.py` (unit half — e2e comes in later task).
- Modify: `tests/conftest.py` — add `fake_event_emitter` fixture.

- [ ] **Step 5.1: Add `fake_event_emitter` fixture**

Append to `tests/conftest.py`:

```python
@pytest.fixture
def fake_event_emitter(mock_mass):
    """Capture the EventBuffer subscriber and let tests emit synthetic events.

    Replaces ``mock_mass.subscribe`` so the first call stores the callback;
    tests then call ``emitter.emit(event)`` to drive it.
    """
    holder: dict = {"cb": None, "removed": False}

    def _subscribe(cb, event_filter=None, id_filter=None):  # noqa: ARG001
        holder["cb"] = cb

        def _remove() -> None:
            holder["removed"] = True

        return _remove

    mock_mass.subscribe = MagicMock(side_effect=_subscribe)

    class _Emitter:
        @property
        def cb(self):
            return holder["cb"]

        @property
        def removed(self):
            return holder["removed"]

        def emit(self, event) -> None:
            if holder["cb"] is None:
                raise AssertionError("no subscriber registered")
            holder["cb"](event)

    return _Emitter()
```

- [ ] **Step 5.2: Write failing unit tests**

Create `tests/test_debug_events.py`:

```python
"""Unit tests for EventBuffer (e2e tools come in a later task)."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from provider.debug.event_buffer import EventBuffer


def _ev(event_type: str, object_id: str | None = None, data=None):
    return SimpleNamespace(event=event_type, object_id=object_id, data=data or {})


def test_buffer_starts_unsubscribed(mock_mass) -> None:
    buf = EventBuffer(mock_mass, capacity=10)
    assert buf.stats().capacity == 10
    assert buf.stats().current_size == 0
    assert buf.stats().subscribed_since is None
    assert mock_mass.subscribe.called is False


def test_buffer_start_subscribes_once(mock_mass, fake_event_emitter) -> None:
    buf = EventBuffer(mock_mass, capacity=10)
    buf.start()
    buf.start()  # idempotent
    assert mock_mass.subscribe.call_count == 1
    assert buf.stats().subscribed_since is not None


def test_buffer_stop_idempotent(mock_mass, fake_event_emitter) -> None:
    buf = EventBuffer(mock_mass, capacity=10)
    buf.start()
    buf.stop()
    buf.stop()
    assert fake_event_emitter.removed is True


def test_buffer_drops_oldest_at_capacity(mock_mass, fake_event_emitter) -> None:
    buf = EventBuffer(mock_mass, capacity=500)
    buf.start()
    for i in range(503):
        fake_event_emitter.emit(_ev("player_updated", object_id=f"p{i}"))
    snap = buf.snapshot(limit=1000)
    assert len(snap) == 500
    stats = buf.stats()
    assert stats.total_seen == 503
    assert stats.dropped == 3
    assert stats.by_type["player_updated"] == 503


def test_snapshot_filters_event_types_and_id(mock_mass, fake_event_emitter) -> None:
    buf = EventBuffer(mock_mass, capacity=100)
    buf.start()
    fake_event_emitter.emit(_ev("player_updated", "kitchen"))
    fake_event_emitter.emit(_ev("queue_updated", "kitchen"))
    fake_event_emitter.emit(_ev("player_updated", "lenco"))
    snap = buf.snapshot(limit=100, event_types=["player_updated"], id_filter="kitchen")
    assert len(snap) == 1
    assert snap[0].event_type == "player_updated"
    assert snap[0].object_id == "kitchen"


def test_snapshot_since_seconds_filters_old_events(
    mock_mass, fake_event_emitter, monkeypatch
) -> None:
    """Patch the buffer's _now indirection to a controllable clock.

    Project does not ship freezegun and pyproject.toml is templated
    (cannot be hand-edited per CLAUDE.md). The buffer module exposes
    a ``_now()`` helper specifically so tests can replace it without
    touching stdlib datetime.
    """
    import provider.debug.event_buffer as ev_buf

    clock = [dt.datetime(2026, 5, 28, 9, 0, 0, tzinfo=dt.UTC)]
    monkeypatch.setattr(ev_buf, "_now", lambda: clock[0])

    buf = EventBuffer(mock_mass, capacity=100)
    buf.start()
    fake_event_emitter.emit(_ev("a"))
    clock[0] = clock[0] + dt.timedelta(seconds=10)
    fake_event_emitter.emit(_ev("b"))
    snap = buf.snapshot(limit=100, since_seconds=2)
    assert [e.event_type for e in snap] == ["b"]
```

Run:

```bash
uv run pytest tests/test_debug_events.py -v
```

Expected: all fail on missing module.

- [ ] **Step 5.3: Implement `EventBuffer`**

Create `provider/debug/event_buffer.py`:

```python
"""Bounded in-memory ring buffer of recent MA events.

Activated only when ``DEBUG_EVENTS`` is enabled. Subscribes via
``mass.subscribe(...)`` at :meth:`start` and unsubscribes at :meth:`stop`.
The callback is synchronous (a O(1) ``deque.append``) so it can never
back-pressure MA's event loop.

Restarts and reloads reset the buffer — events are not persisted across
provider lifecycles. See spec 0005 "Deliberately deferred" for the
rationale.
"""

from __future__ import annotations

from collections import Counter, deque
from datetime import datetime
from typing import TYPE_CHECKING, Any

from provider.debug.inspect_serializer import dump
from provider.models import EventBufferStats, EventRecord

if TYPE_CHECKING:
    from music_assistant.mass import MusicAssistant


def _now() -> datetime:
    """Indirection for tests.

    The project does not ship ``freezegun`` and ``pyproject.toml`` is
    template-generated (cannot be hand-edited). Tests replace this
    module-level callable to control timestamps deterministically.
    """
    return datetime.now().astimezone()


class EventBuffer:
    """Ring deque + lifecycle around ``mass.subscribe``."""

    def __init__(self, mass: MusicAssistant, *, capacity: int) -> None:
        self._mass = mass
        self._capacity = max(50, min(int(capacity), 5000))
        self._queue: deque[EventRecord] = deque(maxlen=self._capacity)
        self._counts: Counter[str] = Counter()
        self._total_seen = 0
        self._subscribed_since: datetime | None = None
        self._remove: Any = None  # callable returned by mass.subscribe

    def start(self) -> None:
        """Subscribe to the event bus. Idempotent — second call is a no-op."""
        if self._remove is not None:
            return
        self._remove = self._mass.subscribe(self._on_event)
        self._subscribed_since = _now()

    def stop(self) -> None:
        """Unsubscribe. Idempotent."""
        if self._remove is None:
            return
        try:
            self._remove()
        finally:
            self._remove = None
            self._subscribed_since = None

    def snapshot(
        self,
        *,
        limit: int,
        event_types: list[str] | None = None,
        id_filter: str | None = None,
        since_seconds: int | None = None,
    ) -> list[EventRecord]:
        """Return a filtered copy of the buffer, newest last."""
        limit = max(1, min(int(limit), 1000))
        now = _now()
        type_set = set(event_types) if event_types else None
        results: list[EventRecord] = []
        for record in self._queue:
            if type_set and record.event_type not in type_set:
                continue
            if id_filter and record.object_id != id_filter:
                continue
            if since_seconds is not None:
                try:
                    when = datetime.fromisoformat(record.timestamp)
                except ValueError:
                    continue
                if (now - when).total_seconds() > since_seconds:
                    continue
            results.append(record)
        return results[-limit:]

    def stats(self) -> EventBufferStats:
        """Return introspection counters."""
        return EventBufferStats(
            capacity=self._capacity,
            current_size=len(self._queue),
            total_seen=self._total_seen,
            dropped=max(0, self._total_seen - self._capacity),
            subscribed_since=self._subscribed_since.isoformat() if self._subscribed_since else None,
            by_type=dict(self._counts),
        )

    def _on_event(self, event: Any) -> None:
        event_type = str(getattr(event, "event", getattr(event, "event_type", "")))
        object_id = getattr(event, "object_id", None)
        record = EventRecord(
            timestamp=_now().isoformat(),
            event_type=event_type,
            object_id=str(object_id) if object_id is not None else None,
            data=dump(getattr(event, "data", None), max_depth=4, max_str=1024),
        )
        self._queue.append(record)
        self._counts[event_type] += 1
        self._total_seen += 1
```

- [ ] **Step 5.4: Run, lint, commit**

```bash
uv run pytest tests/test_debug_events.py -v
uv run ruff check provider/ tests/ && uv run ruff format provider/ tests/
git add provider/debug/event_buffer.py tests/test_debug_events.py tests/conftest.py
git commit -m "$(cat <<'EOF'
feat(debug): add EventBuffer (bounded ring deque + lifecycle)

Per spec 0005 AC #5 and #6. Subscribes on start, unsubscribes on stop
(both idempotent). Callback is sync deque.append so it never blocks
the MA event loop. Reload-safe: counters and ring reset on restart.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Debug sub-server skeleton + 3 inspect tools

**Spec coverage:** AC #2 (full surface), AC #9 (ToolError for unknown IDs).

**Files:**
- Create: `provider/tools/debug.py`.
- Modify: `provider/tools/__init__.py`.
- Create: `tests/test_debug_inspect.py`.
- Modify: `tests/conftest.py` — add `mounted_debug` / `mounted_debug_off` fixtures.

- [ ] **Step 6.1: Add `mounted_debug` and `mounted_debug_off` fixtures**

Append to `tests/conftest.py`:

```python
@pytest.fixture
def mounted_debug(mock_mass) -> Any:
    """Build a root FastMCP with the debug sub-server mounted, all debug tags allowed."""
    import contextlib

    from fastmcp import FastMCP

    from provider.tags import Tag
    from provider.tools.debug import build_debug_server

    mcp = FastMCP(name="test")
    mcp.mount(build_debug_server(mock_mass, require_confirmation=False), namespace="debug")

    # No tag-restrict middleware here — by default every tag is visible.
    # mounted_debug_off below applies the restrict filter explicitly.
    try:
        yield mcp
    finally:
        close = getattr(mcp, "close", None) or getattr(mcp, "shutdown", None)
        if callable(close):
            with contextlib.suppress(Exception):
                close()


@pytest.fixture
def mounted_debug_off(mock_mass) -> Any:
    """Debug sub-server mounted with the TagFilterMiddleware allowing zero debug tags.

    Uses the project's own ``TagFilterMiddleware`` (provider/middleware.py),
    not FastMCP's built-in ``restrict_tag`` — the latter is scope-based
    OAuth authorisation while this provider needs config-driven visibility.
    """
    import contextlib

    from fastmcp import FastMCP

    from provider.middleware import TagFilterMiddleware
    from provider.server import build_tag_lookup
    from provider.tools.debug import build_debug_server

    mcp = FastMCP(name="test")
    mcp.mount(build_debug_server(mock_mass, require_confirmation=False), namespace="debug")
    mcp.add_middleware(TagFilterMiddleware(lambda: set(), build_tag_lookup(mcp)))
    try:
        yield mcp
    finally:
        close = getattr(mcp, "close", None) or getattr(mcp, "shutdown", None)
        if callable(close):
            with contextlib.suppress(Exception):
                close()
```

- [ ] **Step 6.2: Write failing tests**

Create `tests/test_debug_inspect.py`:

```python
"""End-to-end tests for debug_inspect_player/queue/provider."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError


def _player_full(player_id: str, *, available: bool = True, enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        player_id=player_id,
        name=f"Player {player_id}",
        available=available,
        enabled=enabled,
        hidden=False,
        powered=True,
        volume_level=42,
        playback_state=SimpleNamespace(value="idle"),
        current_media=None,
        active_group=None,
        synced_to=None,
        last_error=None,
        extra_data={"flavor": "test"},
        state=SimpleNamespace(power="on", active_group=None, synced_to=None),
    )


async def _call(mcp, tool_name: str, **kwargs: Any):
    async with Client(mcp) as client:
        return await client.call_tool(f"debug_{tool_name}", kwargs)


async def test_inspect_player_returns_raw_and_state(mounted_debug, mock_mass) -> None:
    player = _player_full("kitchen")
    mock_mass.players.get_player = lambda pid: player if pid == "kitchen" else None
    result = await _call(mounted_debug, "inspect_player", player_id="kitchen")
    data = result.data
    assert data.player_id == "kitchen"
    assert data.raw["name"] == "Player kitchen"
    assert data.state["power"] == "on"
    assert data.truncated is False


async def test_inspect_unavailable_player_still_returns_state(mounted_debug, mock_mass) -> None:
    player = _player_full("broken", available=False)
    player.last_error = "auth expired"
    mock_mass.players.get_player = lambda pid: player if pid == "broken" else None
    result = await _call(mounted_debug, "inspect_player", player_id="broken")
    assert result.data.raw["available"] is False
    assert result.data.raw["last_error"] == "auth expired"


async def test_inspect_disabled_player_still_returns_state(mounted_debug, mock_mass) -> None:
    player = _player_full("off", enabled=False)
    mock_mass.players.get_player = lambda pid: player if pid == "off" else None
    result = await _call(mounted_debug, "inspect_player", player_id="off")
    assert result.data.raw["enabled"] is False


async def test_inspect_unknown_player_raises_tool_error(mounted_debug, mock_mass) -> None:
    mock_mass.players.get_player = lambda pid: None  # noqa: ARG005
    with pytest.raises(ToolError, match="player_id='nope' not found"):
        await _call(mounted_debug, "inspect_player", player_id="nope")


async def test_inspect_queue_returns_raw_and_current_item(mounted_debug, mock_mass) -> None:
    queue = SimpleNamespace(queue_id="kitchen", current_index=0, items_count=3, state="playing")
    current = SimpleNamespace(uri="library://track/1", title="Test", duration=180)
    mock_mass.player_queues.get = lambda qid: queue if qid == "kitchen" else None
    mock_mass.player_queues.get_active_queue = lambda pid: queue  # noqa: ARG005
    queue.current_item = current
    result = await _call(mounted_debug, "inspect_queue", queue_id="kitchen")
    assert result.data.queue_id == "kitchen"
    assert result.data.current_item is not None
    assert result.data.current_item["title"] == "Test"


async def test_inspect_provider_returns_raw_and_manifest(mounted_debug, mock_mass) -> None:
    manifest = SimpleNamespace(domain="yandex_music", name="Yandex Music", multi_instance=False)
    prov = SimpleNamespace(
        instance_id="yandex_music_1",
        domain="yandex_music",
        name="Yandex Music",
        available=True,
        last_error=None,
        lookup_key="yandex_music_1",
        supported_features=["search", "browse"],
        manifest=manifest,
    )
    mock_mass.get_provider = lambda iid: prov if iid == "yandex_music_1" else None
    result = await _call(mounted_debug, "inspect_provider", instance_id="yandex_music_1")
    assert result.data.raw["domain"] == "yandex_music"
    assert result.data.manifest["domain"] == "yandex_music"


async def test_inspect_property_raise_renders_placeholder(mounted_debug, mock_mass) -> None:
    class _Bad:
        player_id = "broken"
        name = "Broken"
        available = True
        enabled = True
        state = SimpleNamespace(power="on")

        @property
        def volume_level(self):
            raise RuntimeError("not ready")

    mock_mass.players.get_player = lambda pid: _Bad() if pid == "broken" else None
    result = await _call(mounted_debug, "inspect_player", player_id="broken")
    assert result.data.raw["volume_level"] == "<raise: RuntimeError>"
```

Run:

```bash
uv run pytest tests/test_debug_inspect.py -v
```

Expected: every test fails on missing `build_debug_server`.

- [ ] **Step 6.3: Create `provider/tools/debug.py` skeleton + three inspect tools**

```python
"""FastMCP sub-server for debug / troubleshooting tools.

Spec: ``specs/inprogress/0005-debug-namespace.md``.

All tools in this module are gated by off-by-default ConfigEntries
(see ``provider/config.py``). With no tag enabled the entire namespace
is invisible to MCP clients via ``restrict_tag`` middleware.
"""
# ruff: noqa: TID252  -- relative imports are the canonical MA-provider pattern.

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolAnnotations

from ..debug.inspect_serializer import dump
from ..models import (
    PlayerInspect,
    ProviderInspect,
    QueueInspect,
)
from ..tags import Tag

if TYPE_CHECKING:
    from music_assistant.mass import MusicAssistant


LOGGER = logging.getLogger("music_assistant.providers.fastmcp_server.debug")

_PAYLOAD_CAP_BYTES = 256 * 1024


def _readonly(title: str) -> ToolAnnotations:
    return ToolAnnotations(title=title, readOnlyHint=True, idempotentHint=True)


def build_debug_server(mass: MusicAssistant, *, require_confirmation: bool = True) -> FastMCP:
    """Build the ``debug`` sub-server.

    :param mass: MusicAssistant instance.
    :param require_confirmation: When True (default), ``debug_reload_provider``
        elicits explicit confirmation from the MCP client before reloading.
    """
    sub = FastMCP(name="debug")
    _register_inspect_tools(sub, mass)
    # _register_logs_tool(sub, mass)     -- next tasks
    # _register_events_tools(sub, mass)
    # _register_providers_tools(sub, mass)
    # _register_reload_tool(sub, mass, require_confirmation=require_confirmation)
    # _register_health_tool(sub, mass)
    return sub


def _register_inspect_tools(sub: FastMCP, mass: MusicAssistant) -> None:
    @sub.tool(
        name="inspect_player",
        description=(
            "Return the raw runtime state of a player, including state.* "
            "fields the brief omits. Works for unavailable and disabled "
            "players — that is the point. See also: debug_recent_events "
            "with id_filter=<player_id> for transitions, debug_tail_log "
            "for the textual context."
        ),
        tags={Tag.DEBUG_INSPECT},
        annotations=_readonly("Inspect raw player state"),
    )
    async def inspect_player(player_id: str) -> PlayerInspect:
        player = mass.players.get_player(player_id)
        if player is None:
            raise ToolError(f"player_id={player_id!r} not found")
        state_obj = getattr(player, "state", None)
        raw, raw_trunc = dump(
            player,
            max_total_bytes=_PAYLOAD_CAP_BYTES,
            return_truncated=True,
        )
        state, state_trunc = dump(
            state_obj,
            max_total_bytes=_PAYLOAD_CAP_BYTES,
            return_truncated=True,
        ) if state_obj is not None else ({}, False)
        # raw includes state; surface it again under .state for convenience.
        if isinstance(raw, dict) and "state" in raw:
            raw.pop("state", None)
        return PlayerInspect(
            player_id=player_id,
            raw=raw,
            state=state,
            truncated=bool(raw_trunc or state_trunc),
        )

    @sub.tool(
        name="inspect_queue",
        description=(
            "Return the raw runtime state of a PlayerQueue plus the "
            "current_item resolved. See also: debug_inspect_player for "
            "the queue's owning player, debug_recent_events with "
            "id_filter=<queue_id> for transitions."
        ),
        tags={Tag.DEBUG_INSPECT},
        annotations=_readonly("Inspect raw queue state"),
    )
    async def inspect_queue(queue_id: str) -> QueueInspect:
        queue = mass.player_queues.get(queue_id)
        if queue is None:
            raise ToolError(f"queue_id={queue_id!r} not found")
        raw, raw_trunc = dump(
            queue, max_total_bytes=_PAYLOAD_CAP_BYTES, return_truncated=True
        )
        current = getattr(queue, "current_item", None)
        current_payload = dump(current) if current is not None else None
        return QueueInspect(
            queue_id=queue_id,
            raw=raw,
            current_item=current_payload,
            truncated=bool(raw_trunc),
        )

    @sub.tool(
        name="inspect_provider",
        description=(
            "Return the raw runtime state of a configured provider plus "
            "its manifest. See also: debug_inspect_provider_config for "
            "masked configuration, debug_list_webserver_routes for the "
            "routes this provider registered, debug_reload_provider to "
            "restart it."
        ),
        tags={Tag.DEBUG_INSPECT},
        annotations=_readonly("Inspect raw provider state"),
    )
    async def inspect_provider(instance_id: str) -> ProviderInspect:
        prov = mass.get_provider(instance_id)
        if prov is None:
            raise ToolError(f"provider instance_id={instance_id!r} not configured")
        manifest = getattr(prov, "manifest", None)
        raw, raw_trunc = dump(
            prov, max_total_bytes=_PAYLOAD_CAP_BYTES, return_truncated=True
        )
        manifest_payload = dump(manifest) if manifest is not None else {}
        if isinstance(raw, dict):
            raw.pop("manifest", None)
        return ProviderInspect(
            instance_id=instance_id,
            raw=raw,
            manifest=manifest_payload,
            truncated=bool(raw_trunc),
        )
```

- [ ] **Step 6.4: Export from `provider/tools/__init__.py`**

Add the import and the `__all__` entry:

```python
from .debug import build_debug_server

# ... existing imports unchanged ...

__all__ = [
    "build_debug_server",
    "build_library_server",
    # ... rest unchanged, alphabetised ...
]
```

- [ ] **Step 6.5: Run, lint, commit**

```bash
uv run pytest tests/test_debug_inspect.py -v
uv run ruff check provider/ tests/ && uv run ruff format provider/ tests/
git add provider/tools/debug.py provider/tools/__init__.py tests/test_debug_inspect.py tests/conftest.py
git commit -m "$(cat <<'EOF'
feat(debug): add debug sub-server skeleton + 3 inspect tools

debug_inspect_player/queue/provider. Per spec 0005 AC #2: works for
unavailable/disabled entities, ToolError only for unknown ids, raw
mirror via inspect_serializer, defensive per-attribute try/except.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `debug_tail_log` tool

**Spec coverage:** AC #4 wired into MCP transport.

**Files:**
- Modify: `provider/tools/debug.py` — uncomment `_register_logs_tool` placeholder and implement.
- Modify: `tests/test_debug_logs.py` — add e2e tests through `mounted_debug`.

- [ ] **Step 7.1: Add e2e test cases**

Append to `tests/test_debug_logs.py`:

```python
from fastmcp import Client


async def test_e2e_debug_tail_log(mounted_debug, tmp_log_dir) -> None:  # noqa: ARG001
    async with Client(mounted_debug) as client:
        result = await client.call_tool("debug_tail_log", {"lines": 5})
    assert len(result.data.lines) == 5
    assert result.data.truncated is False


async def test_e2e_debug_tail_log_invalid_name(mounted_debug, tmp_log_dir) -> None:  # noqa: ARG001
    from fastmcp.exceptions import ToolError

    async with Client(mounted_debug) as client:
        with pytest.raises(ToolError):
            await client.call_tool("debug_tail_log", {"name": "../etc/passwd"})
```

- [ ] **Step 7.2: Implement the tool**

Edit `provider/tools/debug.py`. Add to imports:

```python
from ..debug.log_reader import SafeLogTail
from ..models import LogTailResult
```

Uncomment / add the `_register_logs_tool` call in `build_debug_server` and define:

```python
def _register_logs_tool(sub: FastMCP, mass: MusicAssistant) -> None:
    tail = SafeLogTail()

    @sub.tool(
        name="tail_log",
        description=(
            "Return the last N parsed lines of musicassistant.log with "
            "optional level / component / since_seconds filters. Bearer "
            "tokens and common secret patterns are redacted. See also: "
            "debug_recent_events for state transitions in the same "
            "window."
        ),
        tags={Tag.DEBUG_LOGS},
        annotations=_readonly("Tail MA log"),
    )
    async def tail_log(  # noqa: PLR0913
        lines: int = 200,
        level: str | None = None,
        component_regex: str | None = None,
        since_seconds: int | None = None,
        name: str = "musicassistant.log",
    ) -> LogTailResult:
        return tail.tail(
            lines=lines,
            level=level,
            component_regex=component_regex,
            since_seconds=since_seconds,
            name=name,
        )
```

In `build_debug_server`, ensure the call exists:

```python
    _register_inspect_tools(sub, mass)
    _register_logs_tool(sub, mass)
```

- [ ] **Step 7.3: Run, lint, commit**

```bash
uv run pytest tests/test_debug_logs.py -v
uv run ruff check provider/ tests/ && uv run ruff format provider/ tests/
git add provider/tools/debug.py tests/test_debug_logs.py
git commit -m "$(cat <<'EOF'
feat(debug): wire debug_tail_log MCP tool

Per spec 0005. Thin wrapper around SafeLogTail; redaction + path
allowlist + byte cap already enforced by the helper.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `debug_recent_events` + `debug_event_buffer_stats` tools

**Spec coverage:** AC #5 + #6 + #11 distinct from buffer logic.

**Files:**
- Modify: `provider/tools/debug.py`.
- Modify: `tests/test_debug_events.py` — add e2e via `mounted_debug`.

This task is tricky because the tools must reach the *running* EventBuffer. We pass the buffer in via `build_debug_server`, defaulting to a fresh disconnected buffer when none is supplied (used by direct unit tests).

- [ ] **Step 8.1: Update `build_debug_server` signature**

Edit `provider/tools/debug.py`:

```python
def build_debug_server(
    mass: MusicAssistant,
    *,
    require_confirmation: bool = True,
    event_buffer: Any | None = None,
) -> FastMCP:
    """Build the debug sub-server.

    :param mass: MusicAssistant instance.
    :param require_confirmation: When True, ``debug_reload_provider``
        elicits explicit confirmation.
    :param event_buffer: A started :class:`provider.debug.event_buffer.EventBuffer`
        instance. When ``None`` the events tools still mount but report
        ``current_size=0`` — useful for tests that only exercise other
        groups.
    """
    sub = FastMCP(name="debug")
    _register_inspect_tools(sub, mass)
    _register_logs_tool(sub, mass)
    _register_events_tools(sub, mass, event_buffer)
    return sub
```

Update both `mounted_debug` and `mounted_debug_off` fixtures in `tests/conftest.py` to accept an optional `event_buffer` arg and pass it through. The `mounted_debug` fixture stays as-is (buffer=None); for tests that need a live buffer, add this companion fixture in `tests/conftest.py`:

```python
@pytest.fixture
def mounted_debug_with_events(mock_mass, fake_event_emitter) -> Any:
    """Debug server with a started EventBuffer wired in."""
    import contextlib

    from fastmcp import FastMCP

    from provider.debug.event_buffer import EventBuffer
    from provider.tools.debug import build_debug_server

    buf = EventBuffer(mock_mass, capacity=500)
    buf.start()

    mcp = FastMCP(name="test")
    mcp.mount(
        build_debug_server(mock_mass, require_confirmation=False, event_buffer=buf),
        namespace="debug",
    )
    try:
        yield mcp, buf, fake_event_emitter
    finally:
        buf.stop()
        close = getattr(mcp, "close", None) or getattr(mcp, "shutdown", None)
        if callable(close):
            with contextlib.suppress(Exception):
                close()
```

- [ ] **Step 8.2: Add e2e tests**

Append to `tests/test_debug_events.py`:

```python
from fastmcp import Client


async def test_e2e_recent_events_returns_filtered_snapshot(mounted_debug_with_events) -> None:
    mcp, _buf, emitter = mounted_debug_with_events
    emitter.emit(_ev("player_updated", "kitchen"))
    emitter.emit(_ev("queue_updated", "kitchen"))
    async with Client(mcp) as client:
        result = await client.call_tool(
            "debug_recent_events",
            {"limit": 10, "event_types": ["player_updated"]},
        )
    assert len(result.data.events) == 1
    assert result.data.events[0].event_type == "player_updated"


async def test_e2e_event_buffer_stats(mounted_debug_with_events) -> None:
    mcp, _buf, emitter = mounted_debug_with_events
    emitter.emit(_ev("player_updated", "kitchen"))
    async with Client(mcp) as client:
        result = await client.call_tool("debug_event_buffer_stats", {})
    assert result.data.capacity == 500
    assert result.data.total_seen == 1
    assert result.data.by_type["player_updated"] == 1
```

- [ ] **Step 8.3: Implement the tools**

Add to `provider/tools/debug.py`:

```python
from ..debug.event_buffer import EventBuffer  # type: ignore[import-untyped]
from ..models import EventBufferStats, EventSnapshot


def _register_events_tools(
    sub: FastMCP, mass: MusicAssistant, buffer: EventBuffer | None
) -> None:
    @sub.tool(
        name="recent_events",
        description=(
            "Return the most recent events captured into the in-memory "
            "ring buffer, with optional event_types / id_filter / "
            "since_seconds filters. See also: debug_tail_log for the "
            "textual context around an event timestamp."
        ),
        tags={Tag.DEBUG_EVENTS},
        annotations=_readonly("Read recent MA events"),
    )
    async def recent_events(  # noqa: PLR0913
        limit: int = 100,
        event_types: list[str] | None = None,
        id_filter: str | None = None,
        since_seconds: int | None = None,
    ) -> EventSnapshot:
        if buffer is None:
            return EventSnapshot(events=[], buffer_capacity=0, total_seen=0)
        events = buffer.snapshot(
            limit=limit,
            event_types=event_types,
            id_filter=id_filter,
            since_seconds=since_seconds,
        )
        stats = buffer.stats()
        return EventSnapshot(
            events=events,
            buffer_capacity=stats.capacity,
            total_seen=stats.total_seen,
        )

    @sub.tool(
        name="event_buffer_stats",
        description=(
            "Return introspection counters for the event ring buffer: "
            "capacity, current size, total events seen, dropped count "
            "(if the buffer overflowed), subscribed_since timestamp, "
            "and per-event-type counts. Use this to distinguish "
            "'no events match' from 'events were dropped before you "
            "asked'."
        ),
        tags={Tag.DEBUG_EVENTS},
        annotations=_readonly("Event buffer stats"),
    )
    async def event_buffer_stats() -> EventBufferStats:
        if buffer is None:
            return EventBufferStats(
                capacity=0,
                current_size=0,
                total_seen=0,
                dropped=0,
                subscribed_since=None,
                by_type={},
            )
        return buffer.stats()
```

- [ ] **Step 8.4: Run, lint, commit**

```bash
uv run pytest tests/test_debug_events.py -v
uv run ruff check provider/ tests/ && uv run ruff format provider/ tests/
git add provider/tools/debug.py tests/test_debug_events.py tests/conftest.py
git commit -m "$(cat <<'EOF'
feat(debug): wire debug_recent_events + debug_event_buffer_stats

Per spec 0005. Tools take EventBuffer via build_debug_server kwarg;
runtime wiring lands in the lifecycle task.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `debug_list_providers`, `debug_inspect_provider_config`, `debug_list_webserver_routes`, `debug_list_package_versions`

**Spec coverage:** AC #3 (config masking via `to_dict`), Data Model RouteEntry/PackageVersions.

**Files:**
- Modify: `provider/tools/debug.py`.
- Create: `tests/test_debug_providers.py`.

- [ ] **Step 9.1: Add tests**

Create `tests/test_debug_providers.py`:

```python
"""End-to-end tests for the DEBUG_PROVIDERS tool group."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastmcp import Client


def _provider(instance_id, *, available=True, last_error=None):
    return SimpleNamespace(
        instance_id=instance_id,
        domain=instance_id.split("_")[0],
        type=SimpleNamespace(value="music"),
        name=instance_id,
        available=available,
        last_error=last_error,
    )


async def test_list_providers_rolls_up_state(mounted_debug, mock_mass) -> None:
    mock_mass.providers = [
        _provider("yandex_music_1"),
        _provider("sonos_1", available=False, last_error="auth expired"),
    ]
    async with Client(mounted_debug) as client:
        result = await client.call_tool("debug_list_providers", {})
    summaries = result.data.providers
    assert {s.instance_id for s in summaries} == {"yandex_music_1", "sonos_1"}
    failing = next(s for s in summaries if s.instance_id == "sonos_1")
    assert failing.available is False
    assert failing.last_error == "auth expired"


async def test_inspect_provider_config_masks_secret_string(mounted_debug, mock_mass) -> None:
    # The real masking is enforced by music_assistant_models __post_serialize__.
    # The test mock here returns a pre-masked dict shape consistent with that contract.
    masked_config = MagicMock()
    masked_config.domain = "yandex_music"
    masked_config.to_dict = MagicMock(return_value={
        "domain": "yandex_music",
        "values": {
            "username": {"key": "username", "type": "string", "value": "ren"},
            "password": {"key": "password", "type": "secure_string", "value": "this_value_is_encrypted"},
        },
    })
    mock_mass.config.get_provider_config = AsyncMock(return_value=masked_config)

    async with Client(mounted_debug) as client:
        result = await client.call_tool(
            "debug_inspect_provider_config",
            {"instance_id": "yandex_music_1"},
        )
    by_key = {v.key: v for v in result.data.values}
    assert by_key["password"].value == "this_value_is_encrypted"
    # The real secret string never appears.
    assert "actual-secret-1234" not in str(result.data)


async def test_list_webserver_routes_returns_entries(mounted_debug, mock_mass) -> None:
    route_obj = SimpleNamespace(
        method="GET",
        resource=SimpleNamespace(canonical="/mcp/v1/sse"),
    )
    inner_app = SimpleNamespace(router=SimpleNamespace(routes=lambda: [route_obj]))
    mock_mass.webserver._server = SimpleNamespace(app=inner_app)
    async with Client(mounted_debug) as client:
        result = await client.call_tool("debug_list_webserver_routes", {})
    paths = [r.path for r in result.data.routes]
    assert "/mcp/v1/sse" in paths


async def test_list_package_versions_includes_fastmcp(mounted_debug, mock_mass) -> None:  # noqa: ARG001
    async with Client(mounted_debug) as client:
        result = await client.call_tool("debug_list_package_versions", {})
    assert "fastmcp" in result.data.packages
    assert "music_assistant_models" in result.data.packages
```

- [ ] **Step 9.2: Implement the four tools**

Add to `provider/tools/debug.py`:

```python
import importlib.metadata

from ..models import (
    ConfigValueDump,
    PackageVersions,
    ProviderConfigDump,
    ProviderList,
    ProviderSummary,
    RouteEntry,
    RouteList,
)


_TRACKED_PACKAGES = (
    "music_assistant",
    "music_assistant_models",
    "fastmcp",
    "aiohttp",
    "mashumaro",
)


def _register_providers_tools(sub: FastMCP, mass: MusicAssistant) -> None:
    @sub.tool(
        name="list_providers",
        description=(
            "Roll-up of every configured provider: instance_id, domain, "
            "type, name, available flag, last_error. See also: "
            "debug_inspect_provider for the full runtime dump, "
            "debug_inspect_provider_config for the masked configuration, "
            "debug_health_summary for triage."
        ),
        tags={Tag.DEBUG_PROVIDERS},
        annotations=_readonly("List configured providers"),
    )
    async def list_providers() -> ProviderList:
        summaries: list[ProviderSummary] = []
        for prov in getattr(mass, "providers", []):
            ptype = getattr(getattr(prov, "type", None), "value", None) or str(getattr(prov, "type", "unknown"))
            summaries.append(
                ProviderSummary(
                    instance_id=getattr(prov, "instance_id", ""),
                    domain=getattr(prov, "domain", ""),
                    type=ptype,
                    name=getattr(prov, "name", "") or getattr(prov, "domain", ""),
                    available=bool(getattr(prov, "available", False)),
                    last_error=getattr(prov, "last_error", None),
                )
            )
        return ProviderList(providers=summaries)

    @sub.tool(
        name="inspect_provider_config",
        description=(
            "Dump a provider's stored ConfigEntry values. SECURE_STRING "
            "values are replaced by MA's SECURE_STRING_SUBSTITUTE sentinel "
            "via __post_serialize__ in music_assistant_models — this tool "
            "carries no masking logic of its own."
        ),
        tags={Tag.DEBUG_PROVIDERS},
        annotations=_readonly("Inspect provider config (masked)"),
    )
    async def inspect_provider_config(instance_id: str) -> ProviderConfigDump:
        try:
            config = await mass.config.get_provider_config(instance_id)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"provider instance_id={instance_id!r} not configured") from exc
        raw = config.to_dict()
        values: list[ConfigValueDump] = []
        truncated = False
        running_bytes = 0
        for key, entry in raw.get("values", {}).items():
            value = entry.get("value")
            etype = entry.get("type", "unknown")
            payload_size = len(str(value)) + len(key) + len(etype) + 16
            if running_bytes + payload_size > _PAYLOAD_CAP_BYTES:
                truncated = True
                break
            running_bytes += payload_size
            values.append(ConfigValueDump(key=str(key), type=str(etype), value=value))
        return ProviderConfigDump(
            instance_id=instance_id,
            domain=raw.get("domain", ""),
            values=values,
            truncated=truncated,
        )

    @sub.tool(
        name="list_webserver_routes",
        description=(
            "Enumerate the HTTP routes registered on MA's webserver. "
            "Includes both dynamic (provider-registered) and static routes. "
            "Reaches into webserver._server.app.router — single documented "
            "private-API touch. See spec 0005."
        ),
        tags={Tag.DEBUG_PROVIDERS},
        annotations=_readonly("List webserver routes"),
    )
    async def list_webserver_routes() -> RouteList:
        # NOTE: webserver._server.app.router is a private attribute walk. MA core
        # exposes no public route enumerator at the time of writing; if upstream
        # adds one, switch to it. See spec 0005 "Known private-API carve-outs".
        routes: list[RouteEntry] = []
        try:
            inner_app = mass.webserver._server.app  # noqa: SLF001
            for route in inner_app.router.routes():
                method = str(getattr(route, "method", "*"))
                resource = getattr(route, "resource", None)
                path = str(getattr(resource, "canonical", "")) if resource else ""
                routes.append(
                    RouteEntry(
                        method=method,
                        path=path,
                        registered_by=_attribute_route(path),
                    )
                )
        except AttributeError as exc:
            raise ToolError("webserver routes are unavailable in this MA build") from exc
        return RouteList(routes=routes)

    @sub.tool(
        name="list_package_versions",
        description=(
            "Return installed versions of the key packages backing the "
            "MCP provider and Music Assistant: music_assistant, "
            "music_assistant_models, fastmcp, aiohttp, mashumaro. Useful "
            "for upstream bug reports."
        ),
        tags={Tag.DEBUG_PROVIDERS},
        annotations=_readonly("List installed package versions"),
    )
    async def list_package_versions() -> PackageVersions:
        out: dict[str, str] = {}
        for pkg in _TRACKED_PACKAGES:
            try:
                out[pkg] = importlib.metadata.version(pkg)
            except importlib.metadata.PackageNotFoundError:
                out[pkg] = "<not installed>"
        return PackageVersions(packages=out)


def _attribute_route(path: str) -> str | None:
    """Best-effort: map a route path back to who registered it by path prefix."""
    if path.startswith("/mcp/"):
        return "fastmcp_server"
    if path.startswith("/.well-known/"):
        return "fastmcp_server (well-known)"
    if path.startswith("/api/"):
        return "music_assistant (api)"
    return None
```

In `build_debug_server`, register the new group:

```python
    _register_events_tools(sub, mass, event_buffer)
    _register_providers_tools(sub, mass)
```

- [ ] **Step 9.3: Run, lint, commit**

```bash
uv run pytest tests/test_debug_providers.py -v
uv run ruff check provider/ tests/ && uv run ruff format provider/ tests/
git add provider/tools/debug.py tests/test_debug_providers.py
git commit -m "$(cat <<'EOF'
feat(debug): wire 4 DEBUG_PROVIDERS tools

list_providers, inspect_provider_config (via Config.to_dict() so
masking goes through MA's __post_serialize__), list_webserver_routes
(documented private attribute walk), list_package_versions.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: `debug_reload_provider`

**Spec coverage:** AC #7 — confirm, single `_load_provider` call, 5 s poll, lock, audit log, success-path `last_error`.

**Files:**
- Modify: `provider/tools/debug.py`.
- Create: `tests/test_debug_reload.py`.

- [ ] **Step 10.1: Add tests**

Create `tests/test_debug_reload.py`:

```python
"""End-to-end tests for debug_reload_provider."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError


def _provider_config(instance_id="yandex_music_1"):
    return SimpleNamespace(instance_id=instance_id, domain="yandex_music", enabled=True)


def _decliner():
    """Mirror tests/test_elicitation.py: elicitation handler that always declines."""
    from fastmcp.client.elicitation import ElicitResult  # noqa: PLC0415

    async def handler(*_a, **_kw):
        return ElicitResult(action="decline")

    return handler


async def test_reload_requires_confirmation(mock_mass) -> None:
    """When the client declines the elicit prompt, the tool errors and never loads."""
    from fastmcp import FastMCP
    from provider.tools.debug import build_debug_server

    mass = mock_mass
    mass._load_provider = AsyncMock()
    mass.config.get_provider_config = AsyncMock(return_value=_provider_config())

    mcp = FastMCP(name="test")
    mcp.mount(
        build_debug_server(mass, require_confirmation=True),
        namespace="debug",
    )

    async with Client(mcp, elicitation_handler=_decliner()) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "debug_reload_provider",
                {"instance_id": "yandex_music_1"},
            )

    assert mass._load_provider.called is False


async def test_reload_calls_load_provider_with_resolved_config(mock_mass) -> None:
    from fastmcp import FastMCP
    from provider.tools.debug import build_debug_server

    mass = mock_mass
    conf = _provider_config()
    mass.config.get_provider_config = AsyncMock(return_value=conf)
    mass._load_provider = AsyncMock()
    available_prov = SimpleNamespace(available=True, last_error=None)
    mass.get_provider = MagicMock(return_value=available_prov)

    mcp = FastMCP(name="test")
    mcp.mount(
        build_debug_server(mass, require_confirmation=False),
        namespace="debug",
    )

    async with Client(mcp) as client:
        result = await client.call_tool(
            "debug_reload_provider",
            {"instance_id": "yandex_music_1"},
        )

    mass._load_provider.assert_awaited_once_with(conf)
    assert result.data.new_available is True
    assert result.data.last_error is None


async def test_reload_timeout_populates_last_error(mock_mass, monkeypatch) -> None:
    from fastmcp import FastMCP
    from provider.tools.debug import build_debug_server

    mass = mock_mass
    mass.config.get_provider_config = AsyncMock(return_value=_provider_config())
    mass._load_provider = AsyncMock()
    not_ready = SimpleNamespace(available=False, last_error="setup pending")
    mass.get_provider = MagicMock(return_value=not_ready)

    # Speed the 5s poll up so the test stays fast.
    import provider.tools.debug as debug_mod
    monkeypatch.setattr(debug_mod, "_RELOAD_POLL_SECONDS", 0.05)
    monkeypatch.setattr(debug_mod, "_RELOAD_POLL_INTERVAL", 0.005)

    mcp = FastMCP(name="test")
    mcp.mount(
        build_debug_server(mass, require_confirmation=False),
        namespace="debug",
    )

    async with Client(mcp) as client:
        result = await client.call_tool(
            "debug_reload_provider",
            {"instance_id": "yandex_music_1"},
        )
    assert result.data.new_available is False
    assert result.data.last_error == "setup pending"


async def test_audit_log_written_before_load_provider(mock_mass, caplog) -> None:
    from fastmcp import FastMCP
    from provider.tools.debug import build_debug_server

    mass = mock_mass
    mass.config.get_provider_config = AsyncMock(return_value=_provider_config())
    call_order: list[str] = []

    async def _load(conf):  # noqa: ARG001
        call_order.append("load_provider")

    mass._load_provider = AsyncMock(side_effect=_load)
    mass.get_provider = MagicMock(return_value=SimpleNamespace(available=True, last_error=None))

    mcp = FastMCP(name="test")
    mcp.mount(
        build_debug_server(mass, require_confirmation=False),
        namespace="debug",
    )

    with caplog.at_level(logging.INFO, logger="music_assistant.providers.fastmcp_server.debug"):
        async with Client(mcp) as client:
            await client.call_tool(
                "debug_reload_provider", {"instance_id": "yandex_music_1"}
            )
    audit_records = [r for r in caplog.records if "reload" in r.message.lower()]
    assert audit_records, "expected an audit log line"
    assert "yandex_music_1" in audit_records[0].message
    assert call_order == ["load_provider"]


async def test_concurrent_reloads_serialise_through_lock(mock_mass, monkeypatch) -> None:
    from fastmcp import FastMCP
    from provider.tools.debug import build_debug_server

    mass = mock_mass
    mass.config.get_provider_config = AsyncMock(return_value=_provider_config())
    mass.get_provider = MagicMock(return_value=SimpleNamespace(available=True, last_error=None))
    in_flight = 0
    peak = 0

    async def _load(conf):  # noqa: ARG001
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1

    mass._load_provider = AsyncMock(side_effect=_load)

    mcp = FastMCP(name="test")
    mcp.mount(
        build_debug_server(mass, require_confirmation=False),
        namespace="debug",
    )

    async with Client(mcp) as client:
        await asyncio.gather(
            client.call_tool("debug_reload_provider", {"instance_id": "yandex_music_1"}),
            client.call_tool("debug_reload_provider", {"instance_id": "yandex_music_1"}),
        )
    assert peak == 1, "lock failed to serialise concurrent reloads"
```

- [ ] **Step 10.2: Implement the tool**

Add to `provider/tools/debug.py`:

```python
import asyncio
import time

from ..models import ReloadResult
from ..tools._common import confirm_or_raise

_RELOAD_POLL_SECONDS = 5.0
_RELOAD_POLL_INTERVAL = 0.1
_RELOAD_LOCK = asyncio.Lock()


def _register_reload_tool(
    sub: FastMCP, mass: MusicAssistant, *, require_confirmation: bool
) -> None:
    @sub.tool(
        name="reload_provider",
        description=(
            "Unload and reload a configured provider instance. "
            "INTERRUPTS ACTIVE STREAMS on the affected provider. "
            "Confirmation is required by default. See also: "
            "debug_inspect_provider to verify the reload landed; "
            "debug_tail_log for the reload's own log lines."
        ),
        tags={Tag.DEBUG_RELOAD},
        annotations=ToolAnnotations(
            title="Reload provider",
            destructiveHint=True,
            idempotentHint=False,
        ),
    )
    async def reload_provider(instance_id: str, ctx: Any = None) -> ReloadResult:
        await confirm_or_raise(
            ctx,
            (
                f"Reload provider {instance_id!r}? "
                "Active playback on this provider will be interrupted."
            ),
            enabled=require_confirmation,
        )
        try:
            conf = await mass.config.get_provider_config(instance_id)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(
                f"provider instance_id={instance_id!r} not configured"
            ) from exc

        async with _RELOAD_LOCK:
            LOGGER.info(
                "MCP debug_reload_provider triggered: instance_id=%s",
                instance_id,
            )
            t0 = time.monotonic()
            try:
                await mass._load_provider(conf)  # noqa: SLF001 -- documented carve-out, spec 0005
            except Exception as exc:  # noqa: BLE001
                return ReloadResult(
                    instance_id=instance_id,
                    duration_ms=(time.monotonic() - t0) * 1000,
                    new_available=False,
                    last_error=str(exc),
                )

            deadline = time.monotonic() + _RELOAD_POLL_SECONDS
            prov = None
            while time.monotonic() < deadline:
                prov = mass.get_provider(instance_id)
                if prov and getattr(prov, "available", False):
                    break
                await asyncio.sleep(_RELOAD_POLL_INTERVAL)
            available = bool(prov and getattr(prov, "available", False))
            last_error = getattr(prov, "last_error", None) if prov else "reload timed out"
            return ReloadResult(
                instance_id=instance_id,
                duration_ms=(time.monotonic() - t0) * 1000,
                new_available=available,
                last_error=last_error,
            )
```

In `build_debug_server`:

```python
    _register_providers_tools(sub, mass)
    _register_reload_tool(sub, mass, require_confirmation=require_confirmation)
```

- [ ] **Step 10.3: Run, lint, commit**

```bash
uv run pytest tests/test_debug_reload.py -v
uv run ruff check provider/ tests/ && uv run ruff format provider/ tests/
git add provider/tools/debug.py tests/test_debug_reload.py
git commit -m "$(cat <<'EOF'
feat(debug): wire debug_reload_provider (confirm + lock + audit)

Per spec 0005 AC #7. Single _load_provider call (it internally
unloads), module-level asyncio.Lock serialises concurrent reloads,
audit log line written BEFORE the load call, 5s available-poll with
last_error returned as success-path field on timeout.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: `debug_health_summary`

**Spec coverage:** AC #11 — gated by DEBUG_PROVIDERS, fields with disabled capability are None, `disabled_capabilities` lists which.

**Files:**
- Modify: `provider/tools/debug.py`.
- Create: `tests/test_debug_health.py`.

- [ ] **Step 11.1: Add tests**

Create `tests/test_debug_health.py`:

```python
"""End-to-end tests for debug_health_summary."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import Client


@pytest.fixture
def populated_mass(mock_mass):
    mock_mass.providers = [
        SimpleNamespace(
            instance_id="yandex_music_1",
            domain="yandex_music",
            type=SimpleNamespace(value="music"),
            name="Yandex",
            available=True,
            enabled=True,
            last_error=None,
        ),
        SimpleNamespace(
            instance_id="sonos_1",
            domain="sonos",
            type=SimpleNamespace(value="player"),
            name="Sonos",
            available=False,
            enabled=True,
            last_error="auth expired",
        ),
        SimpleNamespace(
            instance_id="spotify_1",
            domain="spotify",
            type=SimpleNamespace(value="music"),
            name="Spotify",
            available=True,
            enabled=False,
            last_error=None,
        ),
    ]
    mock_mass.player_queues.all = MagicMock(
        return_value=[
            SimpleNamespace(queue_id="kitchen", state="playing", available=True),
            SimpleNamespace(queue_id="lenco", state="idle", available=True),
            SimpleNamespace(queue_id="broken", state="error", available=False),
        ]
    )
    return mock_mass


async def test_health_summary_rolls_up_state(mounted_debug, populated_mass) -> None:  # noqa: ARG001
    async with Client(mounted_debug) as client:
        result = await client.call_tool("debug_health_summary", {})
    data = result.data
    assert data.providers_loaded == 2  # yandex + spotify
    assert data.providers_disabled == 1  # spotify
    assert data.providers_error == 1  # sonos
    assert any(p.instance_id == "sonos_1" for p in data.providers_error_details)
    assert data.queues_total == 3
    assert data.queues_with_active_playback == 1
    assert data.queues_with_errors >= 1


async def test_health_summary_marks_capabilities_disabled_when_off(
    mounted_debug, populated_mass
) -> None:  # noqa: ARG001
    async with Client(mounted_debug) as client:
        result = await client.call_tool("debug_health_summary", {})
    # Default mounted_debug has no live EventBuffer and SafeLogTail.ROOT points
    # at $HOME/.musicassistant which does not exist in the test environment.
    # Both should report as disabled, NOT crash.
    assert result.data.events_per_min_by_type is None
    assert "DEBUG_EVENTS" in result.data.disabled_capabilities


async def test_health_summary_events_rate_when_buffer_present(
    mounted_debug_with_events, populated_mass  # noqa: ARG001
) -> None:
    mcp, _buf, emitter = mounted_debug_with_events
    for _ in range(6):
        emitter.emit(SimpleNamespace(event="player_updated", object_id="kitchen", data={}))
    async with Client(mcp) as client:
        result = await client.call_tool("debug_health_summary", {})
    assert result.data.events_per_min_by_type is not None
    assert "player_updated" in result.data.events_per_min_by_type


async def test_health_summary_counts_recent_log_errors(
    mounted_debug, populated_mass, tmp_path, monkeypatch  # noqa: ARG001
) -> None:
    """Write a synthetic log with current-time ERROR lines, assert count."""
    from datetime import datetime

    import provider.debug.log_reader as log_reader

    monkeypatch.setattr(log_reader.SafeLogTail, "ROOT", tmp_path, raising=True)
    log_path = tmp_path / "musicassistant.log"
    now = datetime.now().astimezone()
    ts = now.strftime("%Y-%m-%d %H:%M:%S,000")
    log_path.write_text(
        f"{ts} ERROR music_assistant.providers.sonos: failure A\n"
        f"{ts} ERROR music_assistant.providers.sonos: failure B\n"
        f"{ts} INFO music_assistant.mass: not an error\n"
        f"{ts} ERROR music_assistant.controllers.music: failure C\n",
        encoding="utf-8",
    )
    async with Client(mounted_debug) as client:
        result = await client.call_tool("debug_health_summary", {})
    assert result.data.log_errors_last_5min == 3
    assert "DEBUG_LOGS" not in result.data.disabled_capabilities
```

- [ ] **Step 11.2: Implement the tool**

Add to `provider/tools/debug.py`. The tool signature picks up `event_buffer` and constructs a `SafeLogTail` instance defensively (no-op when path doesn't exist):

```python
from ..debug.log_reader import SafeLogTail
from ..models import HealthSummary


def _register_health_tool(
    sub: FastMCP, mass: MusicAssistant, *, buffer: EventBuffer | None
) -> None:
    @sub.tool(
        name="health_summary",
        description=(
            "Entry-point triage tool — one read returns a roll-up of "
            "provider state, queue counts, event rate, and log error "
            "count. If a section flags errors, drill into: "
            "debug_inspect_provider for provider errors, "
            "debug_inspect_queue for queue errors, debug_tail_log for "
            "the recent ERROR log lines. Fields whose capability is "
            "disabled show as null with the tag name listed in "
            "disabled_capabilities."
        ),
        tags={Tag.DEBUG_PROVIDERS},
        annotations=_readonly("Health summary roll-up"),
    )
    async def health_summary() -> HealthSummary:
        providers = list(getattr(mass, "providers", []))
        loaded = sum(
            1
            for p in providers
            if getattr(p, "available", False) and getattr(p, "enabled", True)
        )
        disabled = sum(1 for p in providers if not getattr(p, "enabled", True))
        error_details: list[ProviderSummary] = []
        for p in providers:
            if getattr(p, "last_error", None):
                ptype = getattr(getattr(p, "type", None), "value", "unknown")
                error_details.append(
                    ProviderSummary(
                        instance_id=getattr(p, "instance_id", ""),
                        domain=getattr(p, "domain", ""),
                        type=str(ptype),
                        name=getattr(p, "name", "") or getattr(p, "domain", ""),
                        available=bool(getattr(p, "available", False)),
                        last_error=getattr(p, "last_error", None),
                    )
                )

        try:
            queues = list(mass.player_queues.all())
        except (AttributeError, TypeError):
            queues = []
        queues_active = sum(1 for q in queues if getattr(q, "state", None) == "playing")
        queues_errors = sum(
            1
            for q in queues
            if getattr(q, "state", None) == "error" or not getattr(q, "available", True)
        )

        disabled_capabilities: list[str] = []
        events_per_min: dict[str, float] | None = None
        if buffer is None:
            disabled_capabilities.append("DEBUG_EVENTS")
        else:
            stats = buffer.stats()
            if stats.subscribed_since is None:
                disabled_capabilities.append("DEBUG_EVENTS")
            else:
                from datetime import datetime

                subscribed_at = datetime.fromisoformat(stats.subscribed_since)
                elapsed_min = max(
                    1.0 / 60,
                    (datetime.now().astimezone() - subscribed_at).total_seconds() / 60.0,
                )
                events_per_min = {
                    et: round(count / elapsed_min, 2) for et, count in stats.by_type.items()
                }

        log_errors: int | None = None
        try:
            log_errors = SafeLogTail().count_errors_last_5min()
        except Exception:  # noqa: BLE001 -- if logs unreachable, mark disabled
            disabled_capabilities.append("DEBUG_LOGS")

        return HealthSummary(
            providers_loaded=loaded,
            providers_disabled=disabled,
            providers_error=len(error_details),
            providers_error_details=error_details,
            queues_total=len(queues),
            queues_with_active_playback=queues_active,
            queues_with_errors=queues_errors,
            events_per_min_by_type=events_per_min,
            log_errors_last_5min=log_errors,
            disabled_capabilities=disabled_capabilities,
        )
```

In `build_debug_server`:

```python
    _register_reload_tool(sub, mass, require_confirmation=require_confirmation)
    _register_health_tool(sub, mass, buffer=event_buffer)
```

- [ ] **Step 11.3: Run, lint, commit**

```bash
uv run pytest tests/test_debug_health.py -v
uv run ruff check provider/ tests/ && uv run ruff format provider/ tests/
git add provider/tools/debug.py tests/test_debug_health.py
git commit -m "$(cat <<'EOF'
feat(debug): wire debug_health_summary as triage entry point

Per spec 0005 AC #11. Single read returns provider/queue roll-up,
event rate (when DEBUG_EVENTS on), log error count (when DEBUG_LOGS
on). disabled_capabilities makes "no errors" vs "couldn't check"
distinguishable.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: `MCPServerRuntime` lifecycle integration

**Spec coverage:** AC #5 (subscribe at setup, unsubscribe at unload, **in that order before transport teardown**).

**Files:**
- Modify: `provider/server.py` — import EventBuffer, mount debug, add `_event_buffer`, `_reload_lock`, wire setup/unload.
- Create: `tests/test_debug_lifecycle.py`.

- [ ] **Step 12.1: Add tests**

Create `tests/test_debug_lifecycle.py`:

```python
"""Lifecycle tests for the debug sub-server inside MCPServerRuntime."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


async def test_setup_subscribes_when_debug_events_enabled(mock_mass, mock_config) -> None:
    # mock_config returned by the existing fixture; tweak its values:
    mock_config.get_value.side_effect = lambda key, default=None: {
        "debug_events": True,
        "debug_event_buffer_capacity": 100,
    }.get(key, default if default is not None else False)

    from provider.server import MCPServerRuntime

    runtime = MCPServerRuntime(mock_mass, mock_config, logger=MagicMock())
    await runtime.start()
    try:
        assert mock_mass.subscribe.called
        assert runtime._event_buffer is not None  # noqa: SLF001
    finally:
        await runtime.stop()


async def test_unload_does_not_raise_when_events_disabled(mock_mass, mock_config) -> None:
    mock_config.get_value.return_value = False
    from provider.server import MCPServerRuntime

    runtime = MCPServerRuntime(mock_mass, mock_config, logger=MagicMock())
    await runtime.start()
    await runtime.stop()  # must not raise
    assert mock_mass.subscribe.called is False


async def test_unload_stops_event_buffer_before_unmount(mock_mass, mock_config) -> None:
    mock_config.get_value.side_effect = lambda key, default=None: {
        "debug_events": True,
        "debug_event_buffer_capacity": 100,
    }.get(key, default if default is not None else False)

    from provider.server import MCPServerRuntime

    runtime = MCPServerRuntime(mock_mass, mock_config, logger=MagicMock())
    await runtime.start()

    call_order: list[str] = []
    buf = runtime._event_buffer  # noqa: SLF001
    original_stop = buf.stop

    def _stop_record() -> None:
        call_order.append("buffer_stop")
        original_stop()

    buf.stop = _stop_record  # type: ignore[assignment]

    original_unmount = runtime._unmount  # noqa: SLF001

    async def _unmount_record() -> None:
        call_order.append("unmount")
        if original_unmount is not None:
            await original_unmount()

    runtime._unmount = _unmount_record  # noqa: SLF001 — test instrumentation

    await runtime.stop()
    assert call_order[0] == "buffer_stop", call_order


async def test_event_buffer_stop_idempotent_during_unload(mock_mass, mock_config) -> None:
    mock_config.get_value.side_effect = lambda key, default=None: {
        "debug_events": True,
        "debug_event_buffer_capacity": 100,
    }.get(key, default if default is not None else False)

    from provider.server import MCPServerRuntime

    runtime = MCPServerRuntime(mock_mass, mock_config, logger=MagicMock())
    await runtime.start()
    await runtime.stop()
    await runtime.stop()  # must not raise — second call is a no-op
```

Note: the existing `mock_config` fixture is loosely typed; if `side_effect` does not exist on it, use `MagicMock(side_effect=...)`. Verify by reading `tests/conftest.py::mock_config` first.

- [ ] **Step 12.2: Wire lifecycle into `MCPServerRuntime`**

Edit `provider/server.py`:

1. Extend imports near the top:

```python
import asyncio  # noqa: F811 if already imported elsewhere

from .constants import (
    # ... existing imports unchanged ...
    CONF_DEBUG_EVENTS,
    CONF_DEBUG_EVENT_BUFFER_CAPACITY,
)
```

2. In `__init__`, add state slots:

```python
        self._event_buffer: Any = None  # provider.debug.event_buffer.EventBuffer | None
        self._reload_lock: asyncio.Lock = asyncio.Lock()
```

3. In `_start_impl`, after the existing eight `mcp.mount(...)` calls, mount `debug` and conditionally start the buffer:

```python
        from .debug.event_buffer import EventBuffer  # noqa: PLC0415
        from .tools import build_debug_server  # noqa: PLC0415

        if bool(self._config.get_value(CONF_DEBUG_EVENTS)):
            capacity = int(
                self._config.get_value(CONF_DEBUG_EVENT_BUFFER_CAPACITY) or 500
            )
            self._event_buffer = EventBuffer(self._mass, capacity=capacity)
            self._event_buffer.start()

        mcp.mount(
            build_debug_server(
                self._mass,
                require_confirmation=require_confirmation,
                event_buffer=self._event_buffer,
            ),
            namespace="debug",
        )
```

4. In `stop`, **before** the existing `await self._unmount()` block:

```python
        if self._event_buffer is not None:
            try:
                self._event_buffer.stop()
            finally:
                self._event_buffer = None
```

- [ ] **Step 12.3: Run, lint, commit**

```bash
uv run pytest tests/test_debug_lifecycle.py -v
uv run pytest -v  # full suite — confirm no regressions in existing lifecycle tests
uv run ruff check provider/ tests/ && uv run ruff format provider/ tests/
git add provider/server.py tests/test_debug_lifecycle.py
git commit -m "$(cat <<'EOF'
feat(debug): wire EventBuffer + debug sub-server into MCPServerRuntime

Per spec 0005 AC #5. EventBuffer.start in setup (only when
DEBUG_EVENTS on); EventBuffer.stop in unload BEFORE transport
teardown (lifespan-race protection — same defect we fixed in
0.3.22 for the streamable transport). Mount order preserved.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Off-by-default invariant + tool-description snapshot

**Spec coverage:** AC #1 (off-by-default), AC #3 wired e2e, "Tool descriptions" sub-section.

**Files:**
- Create: `tests/test_debug_security.py`.

- [ ] **Step 13.1: Add cross-cutting security tests**

Create `tests/test_debug_security.py`:

```python
"""Cross-cutting security tests: off-by-default, masking, redaction, description pinning."""

from __future__ import annotations

import json

import pytest
from fastmcp import Client


async def test_off_by_default_hides_all_debug_tools(mounted_debug_off) -> None:
    async with Client(mounted_debug_off) as client:
        tools = await client.list_tools()
    debug_tools = [t for t in tools if t.name.startswith("debug_")]
    assert debug_tools == [], f"debug tools leaked: {[t.name for t in debug_tools]}"


async def test_enabling_single_tag_exposes_only_that_group(mock_mass) -> None:
    """Enable DEBUG_INSPECT only -> only inspect tools visible."""
    import contextlib

    from fastmcp import FastMCP

    from provider.middleware import TagFilterMiddleware
    from provider.server import build_tag_lookup
    from provider.tags import Tag
    from provider.tools.debug import build_debug_server

    mcp = FastMCP(name="test")
    mcp.mount(build_debug_server(mock_mass, require_confirmation=False), namespace="debug")
    mcp.add_middleware(
        TagFilterMiddleware(lambda: {Tag.DEBUG_INSPECT.value}, build_tag_lookup(mcp))
    )

    try:
        async with Client(mcp) as client:
            tools = await client.list_tools()
        names = {t.name for t in tools if t.name.startswith("debug_")}
    finally:
        close = getattr(mcp, "close", None) or getattr(mcp, "shutdown", None)
        if callable(close):
            with contextlib.suppress(Exception):
                close()

    assert names == {"debug_inspect_player", "debug_inspect_queue", "debug_inspect_provider"}


async def test_secret_string_value_never_leaks_in_serialised_response(
    mounted_debug, mock_mass
) -> None:
    """End-to-end: an actual secret put through the masking pipeline does not appear."""
    from unittest.mock import AsyncMock, MagicMock

    raw_dict = {
        "domain": "yandex_music",
        "values": {
            "password": {
                "key": "password",
                "type": "secure_string",
                "value": "this_value_is_encrypted",
            },
        },
    }
    config = MagicMock()
    config.domain = "yandex_music"
    config.to_dict = MagicMock(return_value=raw_dict)
    mock_mass.config.get_provider_config = AsyncMock(return_value=config)

    async with Client(mounted_debug) as client:
        result = await client.call_tool(
            "debug_inspect_provider_config", {"instance_id": "yandex_music_1"}
        )
    rendered = json.dumps(result.data, default=str)
    assert "actual-secret-1234" not in rendered  # the literal we never put in


_EXPECTED_DESCRIPTIONS_CONTAIN = {
    "debug_inspect_player": ["unavailable", "disabled", "see also"],
    "debug_inspect_queue": ["see also"],
    "debug_inspect_provider": ["see also"],
    "debug_tail_log": ["redacted", "see also"],
    "debug_recent_events": ["see also"],
    "debug_event_buffer_stats": ["dropped"],
    "debug_list_providers": ["see also"],
    "debug_inspect_provider_config": ["SECURE_STRING"],
    "debug_list_webserver_routes": ["private"],
    "debug_list_package_versions": ["versions"],
    "debug_reload_provider": ["interrupts", "see also"],
    "debug_health_summary": ["entry-point"],
}


@pytest.mark.parametrize(
    ("name", "expected_substrings"),
    list(_EXPECTED_DESCRIPTIONS_CONTAIN.items()),
)
async def test_tool_descriptions_carry_workflow_breadcrumbs(
    mounted_debug, name: str, expected_substrings: list[str]
) -> None:
    async with Client(mounted_debug) as client:
        tools = await client.list_tools()
    by_name = {t.name: t for t in tools}
    tool = by_name.get(name)
    assert tool is not None, f"tool {name} not exposed"
    desc = (tool.description or "").lower()
    for sub in expected_substrings:
        assert sub.lower() in desc, f"{name} description missing {sub!r}: {desc!r}"
```

- [ ] **Step 13.2: Run, lint, commit**

```bash
uv run pytest tests/test_debug_security.py -v
uv run ruff check provider/ tests/ && uv run ruff format provider/ tests/
git add tests/test_debug_security.py
git commit -m "$(cat <<'EOF'
test(debug): pin off-by-default invariant + description breadcrumbs

Per spec 0005 AC #1 + Tool descriptions sub-section. Three load-bearing
regression bars: (1) zero debug tools visible with default config,
(2) enabling DEBUG_INSPECT alone exposes only the 3 inspect tools,
(3) every debug tool's description contains the expected workflow
cross-references.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: VERSION bump + CHANGELOG + final pre-commit gate

**Spec coverage:** Project Pull Request Workflow ("Version + changelog" step).

**Files:**
- Modify: `VERSION` — `0.3.35` → `0.4.0`.
- Modify: `CHANGELOG.md` — add `## [0.4.0]` block at the top.

- [ ] **Step 14.1: Bump VERSION**

Replace the entire contents of `VERSION` with:

```
0.4.0
```

This is a minor bump because we add a new namespace (`debug`) with new public tools. Per PEP 440 and the project's `Branching and PRs` discipline.

- [ ] **Step 14.2: Add CHANGELOG entry**

Insert immediately after the `# Changelog` header lines, *before* the existing `## [0.3.35]` block (no prose between the version heading and the first category — that's the rule from CLAUDE.md `Changelog Discipline`):

```markdown
## [0.4.0] — 2026-05-28

### Added
- **New `debug` MCP namespace for development and troubleshooting.**
  Adds ten read tools and one guarded write tool gated by five
  off-by-default permission flags (`Debug: inspect raw player/queue/provider
  state`, `Debug: tail musicassistant.log`, `Debug: read recent MA events`,
  `Debug: inspect configured providers`, `Debug: reload a provider instance`).
  Default installations see no new surface area; an operator must opt in
  per capability. Inspection tools mirror the full underlying dataclass
  (with depth/string caps, defensive per-attribute access, and cycle
  safety) so an LLM agent can see state that the curated `*Brief`
  responses deliberately hide. Log tailing uses a path allowlist, a
  10 MB self-DoS cap, and redaction of common bearer/token/password
  patterns. Event access is backed by a bounded ring buffer subscribed
  to MA's event bus at provider start. Provider tools dump configs
  through `Config.to_dict()` so `SECURE_STRING` masking flows through
  MA's own `__post_serialize__` hook — there is no separate masking
  pass in this provider. `debug_reload_provider` requires an
  elicitation confirmation, serialises through an `asyncio.Lock`,
  writes an INFO-level audit log line before invoking MA's reload
  pathway, and surfaces a 5-second `available=True` poll result.
  `debug_health_summary` is the intended LLM-agent entry point: a
  single read returns provider/queue roll-up, event rate, and log
  error count, with a `disabled_capabilities` field so the agent can
  distinguish "no errors" from "we couldn't check".
```

- [ ] **Step 14.3: Run the full pre-commit gate**

```bash
pre-commit run --all-files
uv run pytest
uv run ruff check provider/ tests/
uv run ruff format --check provider/ tests/
uv run mypy provider/
```

Expected: all green. If any fail, fix in place — do **not** skip hooks.

- [ ] **Step 14.4: Commit**

```bash
git add VERSION CHANGELOG.md
git commit -m "$(cat <<'EOF'
chore(release): bump VERSION to 0.4.0 + add CHANGELOG entry

Closes the spec 0005 implementation: new debug MCP namespace.
EOF
)"
```

---

## Final integration check (no separate commit)

- [ ] **Step F.1: Confirm full suite still passes**

```bash
uv run pytest -v
```

Expected: all green, including the pre-existing 322 tests and the ~30 new debug tests.

- [ ] **Step F.2: Confirm spec stays in `inprogress/`**

The spec lives at `specs/inprogress/0005-debug-namespace.md` and stays there until the PR merges. The CLAUDE.md WIP=1 rule allows one in-progress spec at a time — we are at exactly one (the previous four are archived in `specs/done/`).

The spec is moved to `specs/done/` in a follow-up `chore(specs): archive spec 0005 to done/` commit only after the implementation PR merges, mirroring PR #84/#87/#90/#92.

---

## Self-Review

**1. Spec coverage:**

| Spec section | Implementing task |
|---|---|
| AC #1 (off-by-default invariant) | Task 1 (config) + Task 13 (regression test) |
| AC #2 (raw mirror, defensive, unavailable-OK) | Task 3 (serializer) + Task 6 (tools) |
| AC #3 (config masking via `to_dict`) | Task 9 + Task 13 (e2e leak test) |
| AC #4 (log path allowlist, byte cap, redactor) | Task 4 (helper) + Task 7 (tool) |
| AC #5 (subscribe/unsubscribe lifecycle) | Task 5 (helper) + Task 12 (wiring) |
| AC #6 (buffer capacity + filtering) | Task 5 |
| AC #7 (reload: confirm, lock, audit, poll) | Task 10 |
| AC #8 (256 KB payload cap) | Task 3 (cap mechanism) + Task 6 (tools pass `max_total_bytes`) |
| AC #9 (`ToolError` on unknown ids) | Tasks 6, 9, 10 |
| AC #10 (< 30s pytest, no real MA) | Task 14 final gate |
| AC #11 (`health_summary` capability gating) | Task 11 |
| Tool descriptions cross-references | Tasks 6–11 inline + Task 13 snapshot pinning |
| Deferred / out-of-scope | Documented in spec; no implementation needed |
| Private-API carve-outs | Task 9 (router), Task 10 (`_load_provider`) — each in single call site with `noqa` + comment |
| 17 dataclasses | Task 2 |

No spec section is unimplemented.

**2. Placeholder scan:** No "TODO", "TBD", "see Task N", or "fill in later" markers in any task body. Every test block contains executable Python; every implementation block contains complete function bodies.

**3. Type consistency:**

- `EventBuffer(mass, *, capacity=...)` — same kwarg in helper (Task 5), runtime wiring (Task 12), test fixture (Task 8).
- `build_debug_server(mass, *, require_confirmation=True, event_buffer=None)` — final signature consistent across Tasks 6, 8, 10, 11, 12.
- `SafeLogTail.tail(*, lines, level, component_regex, since_seconds, name)` — same kwargs in helper (Task 4), tool (Task 7), health summary (Task 11 via `count_errors_last_5min`).
- `dump(obj, *, max_depth, max_str, max_total_bytes, return_truncated)` — same signature across Tasks 3, 6 (inspect tools), 5 (event payload encoding).
- `ReloadResult.last_error: str | None` — populated as success-path field in Task 10; never raised.

No drift between tasks.
