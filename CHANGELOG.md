# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.9] — 2026-05-12

### Fixed
- **Player "state" field always read as `"unknown"`** in MCP tool / resource
  responses. The brief reader looked up `player.state`, but Music
  Assistant's `Player` exposes the canonical enum at `player.playback_state`
  (`state` is only a serialisation alias on the wire). Now reads
  `playback_state` first and keeps the legacy `state` lookup as a fallback
  for older shims.
- **`current_item` rendered the whole `PlayerMedia` dataclass** —
  responses leaked `PlayerMedia(uri=…, media_type=…, …)` blobs that
  inflated LLM context for no value. Prefer `PlayerMedia.title`, fall
  back to `PlayerMedia.uri`.
- **`get_active_queue` materialised an unbounded queue** when a client
  passed a large `include_items`. Clamp to 500 (Music Assistant's own
  queue page size and the `queue://` resource cap).

## [0.3.8] — 2026-05-12

### Fixed
- **Connect Wizard login form appeared under Home Assistant add-on
  ingress** even after v0.3.6 made the URL itself ingress-aware — the
  browser's `Origin: https://<ha>` was never on the strict allowlist
  (it's built from the Docker-internal `base_url`), so
  `POST /mcp/v1/connect/exchange` returned 403 and the wizard fell back
  to the username/password form. Origin checks now accept a request
  when (a) it arrives on the trusted HA-ingress socket (verified via
  Music Assistant's `is_request_from_ingress`) and (b) the `Origin`
  matches the request's `X-Forwarded-Host`. Same fallback applies to
  the main `/mcp/v1` MCP endpoint. Users no longer need to copy their
  HA hostname into `extra_allowed_origins`.

## [0.3.7] — 2026-05-12

### Fixed
- **Info label rendered an invalid URL when `mount_path` was entered
  without a leading slash** — a value like `mcp/v1` produced
  `…:8095mcp/v1` even though the runtime itself normalises it. The label
  now mirrors the runtime's `"/" + raw.strip("/")` normalisation.

## [0.3.6] — 2026-05-12

### Added
- **Connect Wizard external-URL config (`connect_external_url`)** — optional
  fallback that prepends an explicit base URL to the wizard link when the
  reverse-proxy / ingress headers aren't visible to Music Assistant. Use it
  only when the auto-detection below cannot reach the right URL.

### Fixed
- **Open Connect Wizard opened the wrong URL behind Home Assistant add-on
  ingress** — the action emitted a path-only link (`/mcp/v1/connect?…`)
  which the browser resolved against the HA origin and stripped the
  `/<addon-slug>` ingress prefix, landing on a 404. The wizard now reuses
  the active client's forwarded host + ingress path (the value Music
  Assistant already derives from `X-Forwarded-Host` / `X-Ingress-Path`) so
  the link opens at the same origin the user is on.

## [0.3.5] — 2026-05-10

### Fixed
- **`conftest.py` added `tests/providers/` to `sys.path` in upstream CI** — when
  the synced copy lives at `tests/providers/fastmcp_server/conftest.py`, the
  `parent.parent` path resolves to `tests/providers/`, which shadowed every
  installed provider package (`yandex-music`, `zvuk-music`, `snapcast`, etc.)
  and caused 21 pytest collection errors. The `sys.path.insert` is now guarded
  by a `provider/` directory check so it only fires in the source repo.
- **`__version__` out of sync** — updated to match the `VERSION` file.

## [0.3.4] — 2026-05-10

### Changed
- **`fastmcp` dependency pinned to `==3.2.4`** in `manifest.json` to prevent
  silent breakage from upstream API changes between minor releases.

## [0.3.3] — 2026-05-10

### Fixed
- **`get_active_queue` fetched all 500 MA items then sliced in Python** — passes
  `limit=include_items` directly to `mass.player_queues.items()` so MA only
  materialises the requested number of queue entries.
- **`queue://` resource had no item limit** — now explicitly passes `limit=500`
  (MA's page size) and documents the cap in the docstring; removes stale
  `hasattr` guards now that `player_queues.get` is confirmed present.
- **`parse_resource_uri` silently parsed `player://foo/bar` as having a type
  segment** — non-library schemes now raise `ValueError` on any `/` in the path,
  preventing ambiguous parses and potential traversal confusion.
- **`mount_path` not normalised at init** — values without a leading `/` (e.g.
  `mcp/v1`) would produce broken routes; `MCPServerRuntime` now normalises with
  `"/" + raw.strip("/")`.

## [0.3.2] — 2026-05-10

## [0.3.1] — 2026-05-10

### Fixed
- **`isinstance` union syntax** in the JWT audience decoder used `str | list`
  which raises `TypeError` on Python 3.9; replaced with `isinstance(aud, (str, list))`.
- **`clear_queue` awaited a sync call** — `mass.player_queues.clear` is a
  synchronous method in MA; removed the erroneous `await`.
- **Permission hot-swap never triggered** — MA passes `changed_keys` with a
  `values/` prefix (e.g. `values/control_playback`); the bare-key subset check
  always failed, forcing a full runtime restart for every permission toggle.
  Keys are now normalised before the check and `self.config` is updated in the
  hot-swap branch.
- **`mass.players.get(player_id)` unavailable** — MA's `PlayersController`
  exposes `get_player()`, not `get()`. Fixed in both the tool and the resource
  handler.
- **Test helper `build_aiohttp_app` mapped wildcard routes to `GET` only** —
  wizard `POST` handlers registered with `method="*"` were unreachable in
  tests. The wildcard is now forwarded verbatim to aiohttp.
- **MCP endpoint label showed hardcoded default path** — the info label in
  provider settings always displayed `/mcp/v1` even when the user had
  configured a custom `mount_path`. The label now reads the live config value.

## [0.3.0] — 2026-05-10

### Added
- **Connect Wizard** — one-click `Open Connect Wizard` button in the
  provider's settings opens a single-page UI that mints a per-client
  long-lived token (`MCP — <Client>`) and renders ready-to-paste config
  snippets for Claude Desktop, Claude Code, Cursor, Windsurf, VSCode,
  ChatGPT (Connectors), Codex CLI, Gemini CLI, Cline, and Zed. Replaces
  the manual `Settings → Security → Tokens` step entirely. Cursor users
  get an extra **Add to Cursor** deeplink button. Falls back to a
  username/password form when opened outside the settings panel (e.g.
  bookmark, mobile browser).

## [0.2.4] — 2026-05-10

### Fixed
- **Standalone-SSE keep-alive ping noisy traceback** when the client
  closed the long-lived ``GET /mcp/v1`` stream (Claude Code does this
  routinely after the initial handshake). ``sse_starlette`` would try
  to send the next keep-alive, the bridge's ``send`` raised
  ``ClientConnectionResetError`` from aiohttp, and the bridge logged
  it as ERROR with a full traceback. Now the bridge:

    * catches ``ConnectionResetError`` / ``ConnectionError`` /
      ``CancelledError`` in both the send-direction and the
      request-body pump,
    * marks the response state as disconnected and feeds an ASGI
      ``http.disconnect`` event upstream so the app's loops can wind
      down,
    * suppresses subsequent ``send()`` calls (no-op),
    * logs at DEBUG instead of ERROR — this is a normal flow for
      long-lived streams.

## [0.2.3] — 2026-05-10

### Fixed
- **First MCP request crashed with ``Task group is not initialized``.**
  The bridge dispatched ASGI requests to the FastMCP app but never sent
  the ASGI ``lifespan.startup`` event, so FastMCP's
  ``StreamableHTTPSessionManager`` task group never entered its
  ``run()`` loop. Now ``mount_into_mass`` runs the ASGI lifespan as a
  background task, awaits the ``startup.complete`` ack before returning,
  and emits ``shutdown`` on unmount. Fixes runtime errors visible in MA
  logs when a real client (Claude Code etc.) connects.

## [0.2.2] — 2026-05-10

### Fixed
- **Streamable-HTTP endpoint returned 404** for every request. The
  bridge stripped ``mount_path`` (``/mcp/v1``) before handing the
  request to FastMCP's ASGI app, but FastMCP's internal Starlette
  router lives at its default ``streamable_http_path`` (``/mcp``) — so
  after the strip the path no longer matched any FastMCP route. Fix:
  pass our ``mount_path`` to ``mcp.http_app(path=…)`` and stop
  stripping in the bridge so the URL FastMCP receives is the URL it
  routes on. Caught manually by ``claude mcp add`` reporting "Failed
  to connect"; e2e tests didn't catch it because the in-test ``_Mcp``
  fake exposed an ASGI app that ignored path-routing entirely.

## [0.2.1] — 2026-05-10

### Added
- ``provider/icon.svg`` and ``provider/icon_monochrome.svg`` — the canonical
  Model Context Protocol logo (973-byte SVG from Wikimedia Commons),
  picked up by Music Assistant via the standard ``icon.svg`` /
  ``icon_monochrome.svg`` convention next to ``manifest.json``.

### CI
- Drop ``pytest.importorskip("fastmcp")`` from test files so ruff's isort
  hook keeps a single contiguous third-party group after sync into
  ``music_assistant/providers/fastmcp_server/``.
- File-level ``# mypy: disable-error-code="..."`` in test files (quoted
  CSV — unquoted form trips mypy's option parser).
- ``# type: ignore[..., unused-ignore]`` on every suppression so both
  the relaxed ``ma-provider-tools/reusable-test`` mypy and upstream
  ``music-assistant/server`` strict mypy pass without complaining
  about each other's unused suppressions.

## [0.2.0] — 2026-05-10

### Renamed
- Provider domain ``mcp_server`` → ``fastmcp_server``: the upstream
  sync target is now ``music_assistant/providers/fastmcp_server/``,
  disambiguating the plugin from the generic MCP-server term.

### Spec compliance (MCP 2025-06-18 / draft, RFC 8707, RFC 9728)
- ``Origin`` header validation in the ASGI bridge (Streamable HTTP
  MUST). Allowlist auto-derived from ``mass.webserver.{base_url,
  publish_ip}``; ``extra_allowed_origins`` config for reverse-proxy /
  HA ingress. IPv6 hosts re-bracketed correctly after URL parsing.
- RFC 9728 Protected Resource Metadata published at
  ``/.well-known/oauth-protected-resource[/<mount>]``;
  ``WWW-Authenticate: Bearer ... resource_metadata=…`` on 401.
  Live ``scopes_supported`` reflects permission hot-swaps.
- RFC 8707 audience binding via opt-in ``enforce_audience``
  (soft-mode default); ``AccessToken.resource`` populated.
- ``TagFilterMiddleware`` now blocks direct invocation of disabled
  tools / resources / prompts (closes the listing-only filter hole),
  raising the spec-correct error class per component kind.

### Tool UX
- ``ToolAnnotations`` (``title`` / ``readOnlyHint`` /
  ``destructiveHint`` / ``idempotentHint`` / ``openWorldHint``) on
  every tool — clients render labels and prompt before destructive
  ops.
- Per-tool execution timeouts (10s fast / 15s mutation / 30s query /
  60s bulk).
- ``ctx.info`` on search & recommendations; ``ctx.report_progress``
  on playlist bulk-add (per-item path for >10 tracks, with a
  partial-state warning on cancel/error).
- ``ctx.elicit(...)`` confirmation prompts on destructive ops
  (``clear_queue``, ``remove_tracks``, ``remove_from_favorites``,
  ``remove_from_library``); falls through gracefully when the client
  doesn't support elicitation.
- ``RecommendationFolderBrief`` dataclass for typed
  ``metadata.recommendations`` output.

### Bug fixes
- ``playlists.create_playlist``: kwarg ``provider_instance_or_domain``
  (was ``provider_instance_id_or_domain``).
- ``playlists.remove_playlist_tracks``: positions now passed as
  ``tuple[int, ...]`` (MA expects immutable).
- ``media.{add,remove}_from_{favorites,library}`` and ``mark_played``:
  resolve URI to a typed MediaItem first; MA expects
  ``(media_type, library_item_id)`` or a typed instance, not a raw
  URI.
- ``QueueBrief.item_count``: read from ``PlayerQueue.items`` (canonical
  total) instead of falling back to the truncated lookahead length.

### Tests
- 116 passing tests + e2e bridge loop (streaming, DELETE/GET, well-known).
- Consolidated ``FakeWebserver`` + ``build_aiohttp_app`` helpers in
  ``tests/conftest.py``; relative imports so the fixture resolves
  both locally and after sync into the fork's
  ``tests/providers/fastmcp_server/``.

### CI
- ``contents: read`` permission added to ``.github/workflows/test.yml``
  so reusable-test workflow can checkout the repo.
- Per-decorator ``# type: ignore[untyped-decorator]`` on every
  ``@sub.tool`` / ``@mcp.{prompt,resource}`` site for upstream
  ``music-assistant/server``'s strict mypy.
- ``# type: ignore[misc]`` on ``TagFilterMiddleware(Middleware)`` for
  ``disallow_subclassing_any``.
- Pre-existing TID252 (relative imports) / D401 / PLR0915 silenced
  with file-level pragmas.

### Notes
- ``enforce_audience`` ships in soft mode (default off). Switch to
  default-on once an upstream MA-core PR adds ``aud`` to issued JWTs.

## [0.1.0] — initial scaffold

### Added
- Initial scaffold of the MCP Server plugin provider for Music Assistant.
- PrefectHQ FastMCP v3 integration (no manual SDK glue).
- 16-permission tag-based access control (query / control / edit / delete × 4 categories).
- ASGI bridge mounting FastMCP into MA's main aiohttp webserver under `/mcp/v1`.
- 8 sub-servers (`library`, `queue`, `playback`, `players`, `playlists`,
  `volume`, `media`, `metadata`); `library://`, `player://`, `queue://`
  resources; canned prompts.
