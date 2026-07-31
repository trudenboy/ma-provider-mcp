# CLAUDE.md — ma-provider-mcp

## Repo purpose

Provider repo for the Music Assistant `mcp_server` plugin. Synced into the
`trudenboy/ma-server` fork via `ma-provider-tools` automation
(`reusable-sync-to-fork.yml`).

## Architecture

- `provider/` — runtime code; `manifest.json` declares `type=plugin`, `domain=mcp_server`.
- `provider/server.py::MCPServerRuntime` builds one root `FastMCP` with exactly three
  permanent meta-tools: `search_tools`, `get_tool_schema`, and `call_tool`.
- `provider/dynamic_api.py::DynamicAPIAdapter` exposes native `ma_api` commands from
  MA's live command-handler registry. Eight registered provider-extension handlers
  remain available through that catalog rather than a sub-server tool surface.
- `provider/catalog_pagination.py` compiles stable paginated catalog pages and
  `provider/catalog_resource.py` exposes the matching `catalog://commands` resource.
- Resources and prompts are registered directly on the root `FastMCP`.
- The runtime applies custom `TagFilterMiddleware` and mounts the streamable-HTTP ASGI app
  under MA's webserver via `http_bridge.py`.
- `provider/auth.py::MASTokenVerifier` is the only auth code — delegates to
  `mass.webserver.auth.authenticate_with_token`.
- `provider/tags.py` maps the 25 permission `ConfigEntry` booleans to FastMCP tags.

## Conventions

- Sphinx-style docstrings with `:param:` syntax (matches MA core).
- No comments explaining obvious code; only WHY-comments for non-obvious decisions.
- Stdlib `dataclass` for response shapes (FastMCP auto-generates JSON schema).
- Reuse `music_assistant_models` types in resource responses; use `*Brief` dataclasses
  in tool responses to keep payloads small for LLM context.
- Domain-component tool decorators always include `tags={Tag.…}`. The catalog
  resource is intentionally untagged infrastructure and applies visibility per entry.

## AI assistants — commit attribution

Per `CLAUDE.md` rule 5, add a `Co-Authored-By:` trailer to commits you create on
the contributor's behalf. **Use the identity of the agent actually doing the work**
— never copy an example from `CLAUDE.md`, `AGENTS.md`, or another tool's docs
unless that example matches this session.

| If the contributor uses… | Co-author trailer (high-level) |
| --- | --- |
| **Cursor** | Product name + Cursor's documented co-author address |
| **Claude Code** (or other Anthropic Claude products) | `Claude` + **actual** model name + Anthropic noreply address |
| **GitHub Copilot, OpenCode, or other assistants** | That product's documented attribution line |
| **Any agent** | When unsure, check the tool's docs — do not guess or borrow another agent's line |

**Do not** invent model strings or impersonate a product you are not running.
Wrong attribution is worse than omitting a trailer.

Some tools inject attribution automatically (e.g. Cursor **Settings → Agents →
Attribution**). If the environment already adds a correct trailer, do not
duplicate it with a second line from a different agent.

## Key external APIs

- `mass.webserver.register_dynamic_route(path, handler, method="*") -> Callable[[], None]`
- `mass.webserver.auth.authenticate_with_token(token) -> User | None`
- `mass.webserver.base_url`, `mass.webserver.publish_ip`
- `mass.music.{search,artists,albums,tracks,playlists,radio,podcasts,audiobooks}`
- `mass.players`, `mass.player_queues`

## Testing

Run tests through the project's `uv` virtual environment. Use the canonical fresh-MA
fixture and source slice (including MA's `tests/conftest.py` `mass` fixture) for
integration behavior; keep focused unit tests isolated from unrelated MA services.

## Auto-generated files

`pyproject.toml`, `ruff.toml`, `.pre-commit-config.yaml`, and `.github/workflows/*.yml`
are templated by `ma-provider-tools` and will be regenerated on registry update —
do not hand-edit.

## Reverse-sync (upstream → this repo)

Forward-sync (`reusable-sync-to-fork.yml`) only pushes **us → fork → upstream**.
When someone edits our provider **directly** in `music-assistant/server`
(`music_assistant/providers/fastmcp_server/`), the change must be ported back
here by hand — there is no automated reverse channel. Two cases, two procedures.

### Path / import mapping

| Upstream (in the PR diff) | This repo | Transform |
| --- | --- | --- |
| `music_assistant/providers/fastmcp_server/<f>` | `provider/<f>` | strip path prefix |
| `tests/providers/fastmcp_server/<f>` | `tests/<f>` | strip prefix **+ rewrite imports** |
| `…/fastmcp_server/strings.json` | inline `description=` in `provider/config.py` | manual map (no file here) |
| `music_assistant/translations/en.json` | n/a | drop the hunk |

- **Source files** use relative imports (`from ..models import`, `from ._common import`)
  — identical upstream and here, so they transplant 1:1 once the path is fixed.
- **Test files** need `music_assistant.providers.fastmcp_server.` → `provider.`
  (the same rewrite forward-sync does in reverse; see rewrite-safe import note).

### Case 1 — mechanical lint/format sweep (e.g. ruff `D213`, `RUF012`)

These carry **no logic**, only rule-driven reformatting, so **do not port the diff** —
regenerate our slice deterministically:

1. The rule must reach our `ruff.toml` first. It is auto-synced from upstream
   `pyproject.toml` via `ma-provider-tools` (`sync_upstream_config.py`, weekly cron) —
   **never hand-edit `ruff.toml`.** If the cron lags (the consumer-side
   `check-config-sync.yml` compares against the hub's reference, so drift stays
   green here until the hub re-ingests upstream), trigger `sync_upstream_config.py`
   in `ma-provider-tools` or wait for the distribute PR.
2. After the updated `ruff.toml` lands, regenerate locally:
   ```bash
   uv run ruff check --fix --unsafe-fixes provider/ tests/   # --unsafe-fixes needed for RUF012 (ClassVar)
   uv run ruff format provider/ tests/
   ```
   ruff is deterministic, so this reproduces upstream's edits byte-for-byte.
   Note: `ruff.toml` sets `fix = true`, so a bare `ruff check` already writes —
   use `git checkout` to undo if you only meant to preview.
3. Land as `chore:`/`ci:` (spec-exempt). Pure reformat is usually not
   changelog-worthy; add a `### Changed` line only if user-observable.

### Case 2 — feature PR (new tools / logic)

Port the diff as a **starting scaffold**, then land through the normal feature flow:

1. `gh pr diff <N> --repo music-assistant/server > /tmp/pr.diff`, then rewrite
   paths + test imports (`sed` the two prefixes from the table) and `git apply --3way`
   (expect rejects where our files have diverged — reconcile by hand).
2. Watch shared files: `tools/queue.py`, `tools/_common.py`, and `models.py` are
   touched by several open MCP PRs at once — apply in dependency order on one branch.
3. Land per CLAUDE.md: spec (`specs/inprogress/<NNNN>`, WIP=1) → TDD red/green
   (PR's tests are the red) → `CHANGELOG` + `VERSION` bump → PR to `dev`.
   Credit the upstream author with a `Co-Authored-By` trailer.

> **Direction policy (decided for the steamEngineer MCP PR wave, 2026-06):**
> split by size / conflict surface.
>
> - **Small, clean, non-overlapping** (e.g. #4390 pause/resume, #4391 ungroup,
>   #4392 ergonomics, #4377 set_repeat): let the contributor's PR **merge upstream
>   first**, then reverse-sync the merged result here, preserving their authorship in
>   the upstream history. **Hazard:** `sync-to-fork` replaces the whole `provider/`
>   tree, so a forward-sync run *between* their upstream merge and our reverse-sync
>   will **revert their work** upstream. Close that window — reverse-sync before the
>   next release/forward-sync.
> - **Larger or structurally overlapping** (e.g. #4376 add_to_queue — touches
>   `_common.py`/`models.py`/`config.py` and collides with #4409; #4410 remove/move —
>   needs the `strings.json`→`config.py` manual map): ask the contributor to
>   **retarget the PR at this repo** so it lands through our spec/TDD flow and the
>   conflict is resolved here, canonically. Their upstream PR then closes as
>   superseded.
>
> Either way we never act in `music-assistant/*` directly (AI Policy rule 2); any
> reply to the contributor or maintainer is human-written (rule 3).
