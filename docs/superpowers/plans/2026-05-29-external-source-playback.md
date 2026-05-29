# External/Connect-Source Playback in Briefs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `players_*` and `queue_get_active_queue` briefs report real playback state (from the active queue), name the controlling provider, and show the real track title when a player streams from a plugin AUDIO_SOURCE (e.g. Yandex Ynison / Spotify Connect / AirPlay).

**Architecture:** The active `PlayerQueue.state` is the authoritative play/pause signal that MA's own UI reads — we adopt it as the source of truth in `to_brief_player`, keeping the existing blocking-state ladder (`unavailable > disabled > needs_setup > synced`) on top. A new shared helper `_external_now_playing` detects a plugin AUDIO_SOURCE current item and yields `(provider_instance_id, title)`, used both to populate a new `PlayerBrief.external_source` field / override `current_item`, and to relabel external queue items in `to_brief_queue`.

**Tech Stack:** Python 3.14, FastMCP, `music_assistant_models` (enums `MediaType`, `PlaybackState`), pytest (in-memory FastMCP `Client`), `uv`, ruff, mypy, pre-commit.

**Spec:** `specs/inprogress/0008-surface-external-source-playback.md`

**Conventions reminders:**
- Sphinx docstrings with `:param:`. No comments on obvious code.
- Run `uv run pytest <file>` per task; `pre-commit run --all-files` before the PR.
- Tests import via `from provider.X import …` (rewrite-safe), never `import provider.X as Y`.
- Branch already exists: `feat/0008-external-source-playback`.

---

### Task 1: Add `external_source` field to `PlayerBrief`

**Files:**
- Modify: `provider/models.py` (the `PlayerBrief` dataclass, around line 63-80)
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_models.py`:

```python
def test_player_brief_external_source_defaults_none() -> None:
    """A self-driven player exposes ``external_source = None`` by default."""
    player = SimpleNamespace(
        player_id="p1",
        name="Speaker",
        playback_state=SimpleNamespace(value="idle"),
        volume_level=None,
        current_media=None,
    )
    assert to_brief_player(player).external_source is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py::test_player_brief_external_source_defaults_none -v`
Expected: FAIL — `AttributeError: 'PlayerBrief' object has no attribute 'external_source'`.

- [ ] **Step 3: Add the field**

In `provider/models.py`, inside `@dataclass class PlayerBrief`, add the field after `group_volume_muted`:

```python
    group_volume_muted: bool | None = None
    external_source: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py::test_player_brief_external_source_defaults_none -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add provider/models.py tests/test_models.py
git commit -m "feat(models): add PlayerBrief.external_source field"
```

---

### Task 2: Add `_external_now_playing` helper

**Files:**
- Modify: `provider/tools/_common.py` (imports + new private helper in the `# ── private helpers ──` section, after `_str_or_none`, around line 327)
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_models.py` (add `from provider.tools._common import _external_now_playing` to the imports at the top of the file):

```python
def _audio_source_item(*, provider: str, title: str | None, name: str = "Wrapper") -> SimpleNamespace:
    """A queue item whose current stream is a plugin AUDIO_SOURCE."""
    return SimpleNamespace(
        name=name,
        streamdetails=SimpleNamespace(
            media_type=SimpleNamespace(value="audio_source"),
            provider=provider,
            stream_metadata=SimpleNamespace(title=title),
        ),
    )


def test_external_now_playing_returns_provider_and_title() -> None:
    item = _audio_source_item(provider="yandex_ynison--PL8BnL7a", title="Behind Your Walls")
    assert _external_now_playing(item) == ("yandex_ynison--PL8BnL7a", "Behind Your Walls")


def test_external_now_playing_none_for_normal_track() -> None:
    item = SimpleNamespace(
        name="Real Track",
        streamdetails=SimpleNamespace(
            media_type=SimpleNamespace(value="track"),
            provider="yandex_music--abc",
            stream_metadata=None,
        ),
    )
    assert _external_now_playing(item) is None


def test_external_now_playing_none_when_no_streamdetails() -> None:
    assert _external_now_playing(SimpleNamespace(name="x", streamdetails=None)) is None
    assert _external_now_playing(None) is None


def test_external_now_playing_title_may_be_none() -> None:
    item = _audio_source_item(provider="airplay--1", title=None)
    assert _external_now_playing(item) == ("airplay--1", None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py -k external_now_playing -v`
Expected: FAIL — `ImportError: cannot import name '_external_now_playing'`.

- [ ] **Step 3: Implement the helper**

In `provider/tools/_common.py`, add the import near the other `music_assistant_models` usage is not yet present — add at the top with the existing imports block:

```python
from music_assistant_models.enums import MediaType
```

Then add the helper in the `# ── private helpers ──` section (after `_str_or_none`):

```python
def _external_now_playing(queue_item: Any) -> tuple[str, str | None] | None:
    """Return ``(provider_instance_id, track_title)`` for a plugin source item.

    Detects a "Connect"-style external source (Spotify Connect, AirPlay,
    Yandex Ynison) — these surface as a single queue item whose stream is a
    :attr:`MediaType.AUDIO_SOURCE`. Returns ``None`` for normal tracks, for
    items without stream details, and for ``None``.

    :param queue_item: a queue item to inspect (may be ``None``).
    """
    sd = getattr(queue_item, "streamdetails", None)
    if sd is None:
        return None
    media_type = getattr(sd, "media_type", None)
    media_type_val = str(getattr(media_type, "value", media_type)) if media_type is not None else None
    if media_type_val != MediaType.AUDIO_SOURCE.value:
        return None
    provider = _str_or_none(getattr(sd, "provider", None))
    if provider is None:
        return None
    metadata = getattr(sd, "stream_metadata", None)
    title = _str_or_none(getattr(metadata, "title", None)) if metadata is not None else None
    return provider, title
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -k external_now_playing -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add provider/tools/_common.py tests/test_models.py
git commit -m "feat(common): add _external_now_playing source detector"
```

---

### Task 3: Reconcile player state + external_source + title in `to_brief_player`

**Files:**
- Modify: `provider/tools/_common.py` (`to_brief_player`, signature at line 147; ladder at 227-240; return at 242-257)
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_models.py`:

```python
def _queue(*, state: str, current_item: SimpleNamespace | None) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(value=state), current_item=current_item)


def test_to_brief_player_external_source_playing() -> None:
    """Idle player + active queue playing an AUDIO_SOURCE reports the real state."""
    player = SimpleNamespace(
        player_id="lenco",
        name="Lenco LS-500",
        playback_state=SimpleNamespace(value="idle"),
        volume_level=None,
        current_media=None,
    )
    queue = _queue(
        state="playing",
        current_item=_audio_source_item(
            provider="yandex_ynison--PL8BnL7a", title="Behind Your Walls"
        ),
    )
    brief = to_brief_player(player, active_queue=queue)
    assert brief.state == "playing"
    assert brief.external_source == "yandex_ynison--PL8BnL7a"
    assert brief.current_item == "Behind Your Walls"


def test_to_brief_player_normal_active_queue_unchanged() -> None:
    """A normal track in the active queue leaves external_source None."""
    player = SimpleNamespace(
        player_id="p",
        name="Speaker",
        playback_state=SimpleNamespace(value="playing"),
        volume_level=None,
        current_media=SimpleNamespace(uri="ym://track/1", title="Song"),
    )
    normal_item = SimpleNamespace(
        name="Song",
        streamdetails=SimpleNamespace(
            media_type=SimpleNamespace(value="track"), provider="yandex_music--x",
            stream_metadata=None,
        ),
    )
    brief = to_brief_player(player, active_queue=_queue(state="playing", current_item=normal_item))
    assert brief.external_source is None
    assert brief.state == "playing"
    assert brief.current_item == "Song"


def test_to_brief_player_blocking_ladder_wins_over_queue() -> None:
    """An unavailable player keeps state=unavailable even with a playing queue."""
    player = SimpleNamespace(
        player_id="p",
        name="Offline",
        playback_state=SimpleNamespace(value="idle"),
        volume_level=None,
        current_media=None,
        available=False,
    )
    queue = _queue(
        state="playing",
        current_item=_audio_source_item(provider="airplay--1", title="X"),
    )
    assert to_brief_player(player, active_queue=queue).state == "unavailable"


def test_to_brief_player_synced_wins_over_queue() -> None:
    """A sync follower keeps state=synced even though its leader's queue plays."""
    player = SimpleNamespace(
        player_id="p",
        name="Follower",
        playback_state=SimpleNamespace(value="idle"),
        volume_level=None,
        current_media=None,
        synced_to="leader",
    )
    queue = _queue(
        state="playing",
        current_item=_audio_source_item(provider="airplay--1", title="X"),
    )
    assert to_brief_player(player, active_queue=queue).state == "synced"


def test_to_brief_player_no_active_queue_legacy_behaviour() -> None:
    """With active_queue omitted, state comes from player.playback_state."""
    player = SimpleNamespace(
        player_id="p",
        name="Speaker",
        playback_state=SimpleNamespace(value="idle"),
        volume_level=None,
        current_media=None,
    )
    brief = to_brief_player(player)
    assert brief.state == "idle"
    assert brief.external_source is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py -k "to_brief_player_external or to_brief_player_normal_active or blocking_ladder_wins or synced_wins or no_active_queue_legacy" -v`
Expected: FAIL — `TypeError: to_brief_player() got an unexpected keyword argument 'active_queue'`.

- [ ] **Step 3: Implement the reconciliation**

In `provider/tools/_common.py`:

(a) Change the signature (line 147):

```python
def to_brief_player(player: Any, active_queue: Any = None) -> PlayerBrief:
    """Convert a Player-like object to ``PlayerBrief``.

    :param player: a Player-like object.
    :param active_queue: the player's active ``PlayerQueue`` (or ``None``).
        When present, its ``state`` is the authoritative play/pause signal —
        it is what MA's own UI reads — and an external plugin source surfaces
        through it.
    """
```

(b) In the blocking ladder (currently ending at the `synced` branch, line 239-240), add a new branch **after** the `synced` branch and **before** the `return`:

```python
    elif synced_to_val is not None or active_group_val is not None:
        state_value = "synced"
    elif active_queue is not None:
        queue_state = getattr(active_queue, "state", None)
        state_value = str(getattr(queue_state, "value", queue_state)) if queue_state is not None else state_value
```

(c) Just before `return PlayerBrief(`, add the external-source detection and title override:

```python
    external_source: str | None = None
    if active_queue is not None:
        now_playing = _external_now_playing(getattr(active_queue, "current_item", None))
        if now_playing is not None:
            external_source = now_playing[0]
            if now_playing[1]:
                current_item = now_playing[1]
```

(d) Add the field to the returned dataclass:

```python
        group_volume_muted=group_volume_muted_val,
        external_source=external_source,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS (all model tests, including the 5 new ones and the Task 1/2 additions).

- [ ] **Step 5: Commit**

```bash
git add provider/tools/_common.py tests/test_models.py
git commit -m "feat(common): reconcile player state from active queue + external_source"
```

---

### Task 4: Relabel external items in `to_brief_queue`

**Files:**
- Modify: `provider/tools/_common.py` (`to_brief_queue`, items loop at lines 268-278)
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_models.py`:

```python
def test_to_brief_queue_relabels_external_item() -> None:
    """An AUDIO_SOURCE item shows the real track title; normal items keep theirs."""
    external = _audio_source_item(
        provider="yandex_ynison--PL8BnL7a",
        title="Behind Your Walls",
        name="Yandex Music Connect (Ynison)",
    )
    external.queue_item_id = "ext"
    external.duration = None
    external.media_item = None
    normal = SimpleNamespace(
        queue_item_id="n1",
        name="Ordinary Song",
        duration=120,
        media_item=SimpleNamespace(artists=[SimpleNamespace(name="A")]),
        streamdetails=None,
    )
    queue = SimpleNamespace(
        queue_id="q",
        current_index=0,
        items=2,
        shuffle_enabled=False,
        repeat_mode=SimpleNamespace(value="off"),
        available=True,
    )
    brief = to_brief_queue(queue, items=[external, normal])
    names = [it.name for it in brief.items]
    assert names == ["Behind Your Walls", "Ordinary Song"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py::test_to_brief_queue_relabels_external_item -v`
Expected: FAIL — `assert ['Yandex Music Connect (Ynison)', 'Ordinary Song'] == ['Behind Your Walls', 'Ordinary Song']`.

- [ ] **Step 3: Implement the relabel**

In `provider/tools/_common.py`, replace the items loop body in `to_brief_queue` (lines 269-278):

```python
    if items:
        for it in items:
            now_playing = _external_now_playing(it)
            item_name = now_playing[1] if now_playing and now_playing[1] else str(getattr(it, "name", ""))
            brief_items.append(
                QueueItemBrief(
                    item_id=str(getattr(it, "queue_item_id", "")),
                    name=item_name,
                    duration=_int(getattr(it, "duration", None)),
                    artists=_names(getattr(getattr(it, "media_item", None), "artists", None)),
                )
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py::test_to_brief_queue_relabels_external_item -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add provider/tools/_common.py tests/test_models.py
git commit -m "feat(common): relabel external AUDIO_SOURCE queue items with real title"
```

---

### Task 5: Wire active queue into `players.py` callers

**Files:**
- Modify: `provider/tools/players.py` (`list_players` return at line 69; `get_player` return at line 92)
- Test: `tests/test_players_tool.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_players_tool.py` (it already imports `SimpleNamespace`, `Client`, `FastMCP`, `mock_mass`, `mounted_players`):

```python
async def test_get_player_reports_external_source(
    mock_mass: Any, mounted_players: FastMCP
) -> None:
    """An idle player driven by a Connect source reports playing + provider."""
    player = _player(player_id="lenco", name="Lenco LS-500", state="idle")
    mock_mass.players.get_player.return_value = player
    queue = SimpleNamespace(
        state=SimpleNamespace(value="playing"),
        current_item=SimpleNamespace(
            name="Yandex Music Connect (Ynison)",
            streamdetails=SimpleNamespace(
                media_type=SimpleNamespace(value="audio_source"),
                provider="yandex_ynison--PL8BnL7a",
                stream_metadata=SimpleNamespace(title="Behind Your Walls"),
            ),
        ),
    )
    mock_mass.player_queues.get_active_queue.return_value = queue
    async with Client(mounted_players) as client:
        result = await client.call_tool("players_get_player", {"player_id": "lenco"})
    assert result.data.state == "playing"
    assert result.data.external_source == "yandex_ynison--PL8BnL7a"
    assert result.data.current_item == "Behind Your Walls"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_players_tool.py::test_get_player_reports_external_source -v`
Expected: FAIL — `state == "idle"` (caller does not yet pass `active_queue`).

- [ ] **Step 3: Wire the callers**

In `provider/tools/players.py`, change `list_players`'s return (line 69):

```python
        return [
            to_brief_player(p, mass.player_queues.get_active_queue(p.player_id))
            for p in players
        ]
```

And `get_player`'s return (line 92):

```python
        player = mass.players.get_player(player_id)
        if player is None:
            return None
        return to_brief_player(player, mass.player_queues.get_active_queue(player_id))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_players_tool.py -v`
Expected: PASS (new test + all existing — `get_active_queue` returns `None` in the shared `mock_mass`, so legacy assertions like `state == "idle"` hold).

- [ ] **Step 5: Commit**

```bash
git add provider/tools/players.py tests/test_players_tool.py
git commit -m "feat(players): pass active queue into briefs for list/get"
```

---

### Task 6: End-to-end fixture + `queue_get_active_queue` integration test

**Files:**
- Create: `tests/fixtures/queue_external_audio_source.json`
- Test: `tests/test_players_tool.py` (or a focused queue test file if one exists — confirm with `ls tests/test_queue*`)

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/queue_external_audio_source.json` (trimmed from the real Ynison `debug_inspect_queue` payload):

```json
{
  "queue_id": "lenco",
  "state": "playing",
  "active": true,
  "current_index": 0,
  "items": 1,
  "shuffle_enabled": false,
  "repeat_mode": "off",
  "available": true,
  "current_item": {
    "queue_item_id": "a54db550805244fdb3728f583ef1e554",
    "name": "Yandex Music Connect (Ynison)",
    "duration": null,
    "media_type": "audio_source",
    "streamdetails": {
      "provider": "yandex_ynison--PL8BnL7a",
      "media_type": "audio_source",
      "stream_metadata": { "title": "Behind Your Walls", "duration": 201 }
    }
  }
}
```

- [ ] **Step 2: Write the failing test**

Add to `tests/test_players_tool.py`:

```python
import json
from pathlib import Path


def _ns(obj: Any) -> Any:
    """Recursively turn dicts/lists into attribute-accessible namespaces."""
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: _ns(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_ns(v) for v in obj]
    return obj


async def test_queue_get_active_queue_external_item_title(mock_mass: Any) -> None:
    """queue_get_active_queue surfaces the real title for an AUDIO_SOURCE item."""
    from fastmcp import Client, FastMCP

    from provider.tools import build_queue_server

    raw = json.loads(
        Path(__file__).parent.joinpath("fixtures/queue_external_audio_source.json").read_text()
    )
    queue = _ns(raw)
    mock_mass.player_queues.get_active_queue.return_value = queue
    mock_mass.player_queues.items.return_value = [queue.current_item]

    mcp = FastMCP(name="test")
    mcp.mount(build_queue_server(mock_mass), namespace="queue")
    async with Client(mcp) as client:
        result = await client.call_tool("queue_get_active_queue", {"player_id": "lenco"})
    assert result.data.items[0].name == "Behind Your Walls"
```

> Confirm the queue server builder name first: `grep -n "def build_queue_server" provider/tools/__init__.py provider/tools/queue.py`. Use the actual exported name.

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_players_tool.py::test_queue_get_active_queue_external_item_title -v`
Expected: FAIL initially only if Task 4 not yet merged; since Task 4 is done it should PASS once the fixture + wiring exist. If it fails, the failure is the import/builder-name mismatch — fix the import per the grep above.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_players_tool.py -k queue_get_active_queue_external -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/queue_external_audio_source.json tests/test_players_tool.py
git commit -m "test(queue): e2e external AUDIO_SOURCE title via fixture"
```

---

### Task 7: Update tool docstrings for the new behaviour

**Files:**
- Modify: `provider/tools/players.py` (`list_players` docstring, lines ~41-58)
- Modify: `provider/tools/queue.py` (`get_active_queue` docstring, lines ~38-55)

- [ ] **Step 1: Update `list_players` docstring**

In `provider/tools/players.py`, extend the `list_players` docstring's field description to mention that `state` reflects the active queue and the new field:

```
        ``needs_setup``, ``active_group``, ``synced_to``, ``external_source``
        and the currently playing item (if any). When a player streams from an
        external "Connect"-style source (e.g. Spotify Connect, AirPlay, Yandex
        Ynison), ``state`` reflects the active queue (``playing`` / ``paused``)
        and ``external_source`` holds the controlling provider instance id;
        ``current_item`` then shows the real track title, not the source name.
```

- [ ] **Step 2: Update `get_active_queue` docstring**

In `provider/tools/queue.py`, add to the `get_active_queue` docstring:

```
        For a queue fed by an external plugin source (Connect / AirPlay /
        Ynison), the current item's ``name`` is the real track title rather
        than the source wrapper name.
```

- [ ] **Step 3: Verify nothing broke**

Run: `uv run pytest tests/test_players_tool.py tests/test_models.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add provider/tools/players.py provider/tools/queue.py
git commit -m "docs(tools): document external_source + active-queue state in briefs"
```

---

### Task 8: Full gate + spec move + version/changelog (PR prep)

**Files:**
- Move: `specs/inprogress/0008-surface-external-source-playback.md` → `specs/done/`
- Modify: `VERSION`, `CHANGELOG.md`

> Per CLAUDE.md the `VERSION`/`CHANGELOG` bump lands **after** review feedback is addressed. Do this step only when the PR is ready to finalize.

- [ ] **Step 1: Run the full gate**

Run:
```bash
uv run ruff format provider/ tests/
uv run ruff check provider/ tests/
uv run mypy provider/
uv run pytest
pre-commit run --all-files
```
Expected: all green.

- [ ] **Step 2: Bump VERSION**

Set `VERSION` to `0.7.0` (new feature → minor bump from `0.6.2`).

- [ ] **Step 3: Add CHANGELOG entry**

Prepend a new block above the current top version in `CHANGELOG.md` (canonical category order; bare headings only):

```markdown
## [0.7.0] - 2026-05-29

### Added
- Player briefs now report the controlling provider via `external_source`
  when audio is driven by an external "Connect"-style source (Spotify
  Connect, AirPlay, Yandex Ynison).

### Changed
- Player `state` now reflects the active queue's playback state, so a player
  streaming from an external source correctly shows `playing`/`paused`
  instead of `idle`.
- The currently playing item (in player and queue views) shows the real
  track title for external sources instead of the source wrapper name.
```

- [ ] **Step 4: Move the spec to done**

```bash
git mv specs/inprogress/0008-surface-external-source-playback.md specs/done/0008-surface-external-source-playback.md
```
Update its frontmatter `status: done`.

- [ ] **Step 5: Commit and open PR**

```bash
git add VERSION CHANGELOG.md specs/
git commit -m "chore(release): 0.7.0 — external-source playback in briefs"
git push -u origin feat/0008-external-source-playback
```
Then open a PR targeting `dev`. Run the `/code-review` self-review pass, triage Copilot, and request maintainer approval before merge (do not self-merge).

---

## Self-Review

**Spec coverage:**
- AC1 (state playing) → Task 3 + Task 5.
- AC2 (external_source instance_id, None for normal) → Task 1 + Task 3.
- AC3 (real title in current_item) → Task 3.
- AC4 (queue item title) → Task 4 + Task 6.
- AC5 (blocking ladder wins) → Task 3 (two tests).
- AC6 (no active queue / normal unchanged) → Task 3 + Task 5 (mock returns None).
- AC7 (callable without active_queue) → Task 3 (`test_to_brief_player_no_active_queue_legacy_behaviour`).
- Test Plan fixture → Task 6.

**Placeholder scan:** none — every code/test step contains full code. Task 6 carries one explicit "confirm the builder name" instruction with the exact grep to run; this is a verification step, not a placeholder.

**Type consistency:** `_external_now_playing` returns `tuple[str, str | None] | None` and is consumed consistently (`now_playing[0]`, `now_playing[1]`) in Tasks 3 and 4. `external_source: str | None` added in Task 1 and populated in Task 3. `to_brief_player(player, active_queue=None)` signature used consistently in Tasks 3 and 5.
