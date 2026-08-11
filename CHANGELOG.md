# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.2] - 2026-08-11

### Fixed
- Upstream test synchronization now preserves the provider translation namespace,
  keeping the inlined Music Assistant test suite green.

## [2.1.1] - 2026-08-11

### Fixed
- Radio stations invoked through MCP now play directly instead of exposing
  dynamic-radio flags that could route them into unsupported track generation.
- Settings actions now return one-shot messages and URLs through Music
  Assistant's structured result contract without redrawing the form.
- User impersonation works with Music Assistant's auth-provider identities,
  and native action outcomes are localized before reaching MCP clients.

## [2.1.0] - 2026-08-06

### Added
- Optional `app_music_assistant` Prefab UI 0.20.2 player/queue App, disabled by
  default, with renderer-only state/action tools and text fallback.
- `search_tools(include_top_schema=true)` for one-shot top-result schema discovery.
- Bounded p50/p95/max health performance samples for discovery and execution.
- Declarative command/argument target-filter rules for player, queue, and music
  provider targets, including post-elicitation and impersonated-user enforcement.

### Changed
- Catalog fingerprints now digest authorization and schema descriptors; immutable
  snapshots expose O(1) name indexes and request views share one generation.
- Capability, policy, policy-config, catalog, execution, and serialization layers are
  separated; policy providers are mandatory and startup is transactional.
- Tool failures use stable `[code] message` values without arguments, secrets, token
  identifiers, bearer values, or raw exception text.
- The Connect Wizard exposes only `default_policy.profile`.
- FastMCP remains pinned to 3.4.6; docs use Astro 7.1.6, Starlight 0.41.7,
  Sharp 0.35.3, and Node.js 22.12 or newer.

### Removed
- Legacy discovery mappings/migrations, retired profiles, global tag-policy fallback,
  deprecated Connect `base_url`, and historical helper re-exports.

## [2.0.1] - 2026-08-06

### Changed
- Custom capability matrices are visible only in Music Assistant Advanced mode,
  while default and per-token selectors label the profile as
  `Custom (Advanced mode required)` without changing its stored value.
- Runtime-generated provider settings now use Music Assistant translation keys for
  endpoint guidance, per-token policy selectors, capability labels, and policy modes.
- The provider runtime now uses FastMCP 3.4.6, including patch fixes for JWKS
  handling, schema stability, and trusted-proxy OAuth metadata fetches.

### Fixed
- Provider config actions normalize Music Assistant's optional empty result to an
  empty entry tuple, keeping type compatibility across current MA development APIs.

## [2.0.0] - 2026-08-05

### Added
- Five named permission profiles, per-token overrides, and a 26-capability Custom
  matrix with `Deny`, `Allow`, and per-call `Confirm` modes.
- Value-free structured security audit records for confirmations, denials, and
  privileged execution outcomes, plus policy and token-resolution health diagnostics.

### Changed
- Discovery, resources, dynamic commands, and provider-owned commands now resolve one
  immutable policy for the exact authenticated Music Assistant token and revalidate it
  after elicitation and immediately before execution.
- Clients without elicitation receive an actionable capability-specific error and can
  be configured with a narrow `Allow` override when an operator accepts prompt-free use.

### Removed
- V1 permission booleans, dynamic API gates, the global confirmation toggle, and their
  parsing, warning, fallback, and compatibility behavior. Stored values are ignored.

### Security
- Authentication, enabled-user state, Music Assistant scopes, target filters, secret
  guards, hard-denied command families, and impersonation remain authoritative upper
  bounds regardless of configured policy.
- Audit and diagnostic output excludes bearer values and fingerprints, submitted
  secrets and arguments, unmasked secure configuration, and exception details.

## [1.0.3] - 2026-08-05

### Changed
- Provider configuration actions now follow Music Assistant's optional-result
  contract, allowing one-shot actions to complete without re-rendering entries.

## [1.0.2] - 2026-08-05

### Security
- Secure configuration reads are classified before and after native command
  execution so live schema changes and non-canonical entry types cannot expose
  raw credential values.
- Unknown Music Assistant scopes now fail closed, while hidden authentication
  handlers no longer affect catalog diagnostics, revisions, or cursors.

### Fixed
- Dynamic responses are normalized inside their depth, item, string, and strict
  JSON limits before byte fitting, preventing recursive or oversized payloads
  from bypassing the configured response bounds.

### Changed
- The development Compose runtime now defaults to a neighboring Music Assistant
  checkout and documents a fail-closed synchronization preflight for releases.

## [1.0.1] - 2026-08-05

### Changed
- Provider commands now use the current Music Assistant authorization,
  registration, and configuration-action APIs directly.
- Large dynamic API responses now fit their byte budget without repeatedly
  serializing the complete payload for every removed item.

### Fixed
- Catalog discovery now terminates predictably during persistent Music
  Assistant command-registry churn instead of retrying indefinitely.

### Security
- Secure provider, core, and player configuration values are masked from
  dynamic API responses according to their live Music Assistant schemas.
- Authentication commands are no longer exposed through the dynamic MCP
  catalog, preventing credential-management operations from bypassing its
  permission model.

## [1.0.0] — 2026-07-31

### Added
- Cursor-based pagination for blank and semantic `search_tools` discovery,
  with stable catalog revisions and deterministic ordering.
- A names-only `catalog://commands{?cursor,limit}` resource that exposes the
  same permission-filtered command set as tool discovery.
- Native provider-extension commands for queue and debug operations, registered
  through Music Assistant's command lifecycle.

### Changed
- Provider functionality now uses one unified Music Assistant command catalog;
  the duplicated custom FastMCP tool implementation and legacy recipes are
  replaced by native `ma_api:*` commands, declarative profiles, and provider
  extensions.
- Discovery, schema lookup, and execution share the same cached request-visible
  catalog while the public MCP surface remains limited to `search_tools`,
  `get_tool_schema`, and `call_tool`.
- Development and integration tests run against a real Music Assistant dev
  source slice, including connected MCP catalog, album, track, player, provider,
  and queue coverage.

### Fixed
- Dynamic command authorization is revalidated after confirmation and before
  execution, including impersonation, permission, scope, and target filters.
- Paginated discovery rejects stale, malformed, oversized, conflicting, and
  non-strict cursor or limit inputs without leaking hidden command metadata.

## [0.18.0] — 2026-07-29

### Added
- Dynamic discovery of Music Assistant's live API command registry under
  canonical `ma_api:*` names, including MA-native authentication, scope
  checks, impersonation context, independent risk gates, confirmation, and
  bounded compact/full responses.
- Sixteen `mcp_api:*` recipes retain composite provider-specific behavior;
  declarative profiles and recipes cover all 86 curated operations, including
  the recommendation-row API from provider PR #199.
- Command profiles now provide executable compatibility aliases, compact
  projectors, risk overrides and MCP annotations while schemas remain derived
  from the live MA handler signatures.

### Changed
- The MCP tool surface is permanently reduced to `search_tools`,
  `get_tool_schema`, and `call_tool`. Full schemas are fetched only for the
  selected command, minimizing client context usage while newly registered MA
  domains become available without provider changes or restarts.
- Former curated public names are removed. They remain search aliases and
  produce migration hints pointing to their canonical replacement.
- The opt-in `meta_tool_discovery` setting is replaced by independent
  `dynamic_api_read`, `dynamic_api_control`, `dynamic_api_write`, and
  `dynamic_api_system` gates.
- Provider configuration now follows MA's instance-owned config contract;
  config actions use `invoke_provider_config_action` and the Connect Wizard
  returns a one-shot URL instead of the retired `AUTH_SESSION` event.
- New installations use MA's guided setup flow. The Connect Wizard keeps the
  flow open until a client configuration is generated, including behind a
  Home Assistant ingress prefix.

### Fixed
- Provider sources and tests remain compatible with the current inlined
  `music-assistant/server` layout and its strict type checks.
- Recipe operations preserve their individual required arguments, permission
  tags and MA scopes, and execute inside MA's request authentication context.
- Compact response limits now cover nested collections; registry contract drift
  is isolated to the dynamic MA catalog and reported by the debug health summary.

## [0.17.0] — 2026-07-16

### Added
- Opt-in **Simplified tool discovery** mode (Server settings, default off,
  applies without restart): the server exposes only three meta-tools —
  `search_tools` (ranked keyword search over the tool catalog returning
  lightweight name/description results), `get_tool_schema` (full schema for
  one tool, fetched on demand), and `call_tool` (executes any catalogued
  tool by name). Cuts the per-session context cost for MCP hosts that load
  every tool schema up-front; permission flags and destructive-operation
  confirmation still apply to proxied calls.

## [0.16.0] — 2026-07-16

### Added
- New queue curation tools mirroring Music Assistant's native queue
  operations: `queue_remove_item` removes one or more up-next rows by item
  id and returns a per-item acknowledgement (`removed`, `skipped_played`,
  `skipped_buffered`, `not_found`) — a stale id never aborts the batch and
  removal is verified rather than assumed; `queue_move_item` moves a row up,
  down, or to play next; `queue_move_item_to_end` sends a row to the queue
  tail. Both movers return the reordered queue so agents confirm the new
  order in a single call.
- `queue_remove_item` honours the "Confirm destructive operations" setting;
  the setting's description now lists it.

## [0.15.0] — 2026-07-16

### Added
- `queue_get_active_queue` accepts `queue_id` as a convenience alias for
  `player_id` — agents frequently pass the queue identifier under the wrong
  parameter name, and for a player-backed queue the two values coincide.
  Calling the tool with neither identifier now returns a clear error naming
  both parameters.

### Changed
- The `find_and_play` prompt stops gracefully and reports "not found" when
  every search returns no results (instead of retrying in a loop), and
  resolves the target player via `players_list_players` before starting
  playback.

## [0.14.4] — 2026-07-13

### Changed
- **Bundled FastMCP bumped from `3.3.1` to `3.4.4`.** Picks up upstream
  security hardening (SSRF protections for IPv6 transition addresses,
  OAuth redirect validation, event-store replay isolation) plus fixes for
  proxy session teardown races and JSON-schema discriminator handling.
  The 3.4.3 Host/Origin guard that broke reverse-proxied ASGI deployments
  is opt-in again in 3.4.4, so the MCP endpoint keeps working unchanged
  behind Music Assistant's webserver.

## [0.14.3] — 2026-07-10

### Changed
- Adding items to the queue now builds them through Music Assistant's
  memory-efficient queue-item helper, reducing memory usage with very large
  play queues.

## [0.14.2] — 2026-07-10

### Fixed
- Library list tools (tracks, albums, artists, playlists, radio) keep
  returning full item details after Music Assistant switched its library
  list endpoints to slim summary items by default.

## [0.14.1] — 2026-07-07

### Fixed
- The provider now passes Music Assistant's method-ordering lint when inlined
  upstream (private helpers moved below public methods). No user-facing
  behaviour change.

## [0.14.0] — 2026-07-07

### Added
- New `debug_log_stats` tool: a cheap aggregate view of the server log —
  record counts per level, the most active components, and the covered time
  range — for scoping a problem before pulling raw log lines.
- `debug_tail_log` gained a `search` parameter (case-insensitive regex over
  the full record text, including traceback lines) and a `before` timestamp
  cursor for paging into older entries.
- `debug_tail_log` results now report `has_more` and `response_truncated`
  flags plus a ready-to-use `next_call_hint` describing how to fetch the rest
  when a page is incomplete.

### Changed
- `debug_tail_log` filters (level, component, search, time window) now apply
  *before* the line limit, so `lines=5` with a level filter returns the five
  most recent matching records — previously filters only ran within the last
  N raw lines, making rare errors unreachable in chatty logs.
- The `level` filter is now a case-insensitive minimum-severity threshold
  (e.g. `warning` also returns errors); unknown level names are rejected with
  the list of valid values.
- Tool responses are bounded by an internal size budget so very long records
  can no longer overflow the MCP client's per-result limits.

### Fixed
- Multi-line log records are returned whole: a traceback following an error
  line is now part of that error's message instead of being silently dropped
  when filtering by level.
- The error counter in `debug_health_summary` now counts CRITICAL entries and
  is no longer capped by the previous 2000-line window.

## [0.13.4] — 2026-07-06

### Changed
- The `playback_play_media` tool's `radio_mode` parameter is renamed to
  `radio`. With `radio` enabled the queue now plays an endless dynamic radio
  playlist seeded from the given artist, album, track, playlist, or genre —
  powered by Music Assistant's radio playlist engine — instead of the
  deprecated queue-level radio mode. Unresolvable URIs and browse folders are
  rejected with a clear error before anything is enqueued.

## [0.13.3] — 2026-07-03

### Changed
- All provider settings — including the permission, resources, debug, and
  config toggles — now have their labels and descriptions authored in
  `strings.json`, completing the localization migration. The displayed English
  text is unchanged.

## [0.13.1] — 2026-07-01

### Fixed
- Adding a track at a specific position in the queue (`queue_add_to_queue` with
  an `index`) no longer fails on recent Music Assistant releases; the media to
  enqueue is now resolved in a version-tolerant way.
- Reading configuration entries (`config_get_entries`) now returns the localized
  label and description for server settings instead of empty values, matching
  the text shown in the Music Assistant UI.

## [0.13.0] — 2026-07-01

### Added
- A `trust_forwarded_proto` server setting (advanced, off by default). When MA
  runs behind a TLS-terminating reverse proxy (nginx, Nginx Proxy Manager,
  Traefik, Caddy, …), enabling it lets the Connect Wizard mint tokens by
  trusting the proxy's `X-Forwarded-Proto: https` / `X-Forwarded-Scheme: https`
  header as proof the public hop was HTTPS. Leave it off when MA is directly
  reachable — the header is otherwise spoofable by any client on the network.

### Fixed
- The Connect Wizard now populates the "Pick your AI client" list immediately
  after a username/password sign-in, instead of showing an empty list until the
  page was reloaded.

## [0.12.2] — 2026-06-30

### Fixed
- The config drift-guard test now locates `strings.json` relative to the
  provider package, so the bundled test suite passes when the provider is
  inlined into Music Assistant core. No user-facing change.

## [0.12.1] — 2026-06-29

### Fixed
- Event and log timestamps now use Music Assistant's shared datetime helper,
  keeping the provider compatible when inlined into Music Assistant core. No
  user-facing behaviour change.

## [0.12.0] — 2026-06-29

### Changed
- Provider config settings now source their labels and descriptions from a
  translation file (`strings.json`), so they can be localized. The available
  settings, their defaults, and behaviour are unchanged.

## [0.11.1] — 2026-06-29

### Fixed
- The bundled test suite imports its shared fixtures cleanly when the provider
  is inlined into Music Assistant core; two modules used an import form the
  upstream import-path rewrite does not translate, which broke the upstream
  test run.

## [0.11.0] — 2026-06-29

### Added
- A `queue_add_to_queue` tool to enqueue media with explicit placement modes
  (append, play next, play now, replace next, replace) and an optional absolute
  `index`, returning a confirmation that names the newly added row.
- `queue_get_active_queue` now reports `next_insertable_index`, `index_in_buffer`,
  and a per-item absolute `index`, so an agent can choose a valid
  `queue_add_to_queue(index=…)` position instead of guessing. An optional
  `items_from_current` flag fetches the lookahead window from the current
  playback position.

## [0.10.0] — 2026-06-29

### Added
- Explicit `playback_pause` and `playback_resume` tools that always pause or
  resume, instead of the `playback_play_pause` toggle flipping the wrong way
  when the current state is unknown.
- A `players_ungroup_player` tool to remove a player from its sync group.
- A `queue_set_repeat` tool to set the repeat mode (`off` / `one` / `all`).

## [0.9.0] — 2026-06-26

### Added
- Library tools to resolve a Music Assistant URI directly to a typed brief for
  tracks, albums, artists, playlists, and radio stations.
- Drill-down tools to list an album's tracks or an artist's albums without
  repeating a library search.
- Track briefs now include disc and track numbers when the source item provides
  them.

## [0.8.2] — 2026-06-26

### Fixed
- The provider failed to load after an automated formatter pass corrupted
  multi-exception `except` clauses into invalid syntax. Restored valid syntax
  and constrained the formatter to a known-good version so the corruption
  cannot recur.

## [0.8.1] — 2026-06-24

### Fixed
- Config entries that carry no display label no longer break type checking
  against the latest Music Assistant models, restoring the automated release
  build. User-facing behaviour is unchanged.

## [0.8.0] — 2026-05-29

### Added
- New advanced server setting "Lean schemas for Config/Debug tools"
  (off by default). When enabled, the Config and Debug tools omit their
  machine-readable output schemas, cutting roughly 5,000 tokens of per-request
  context on MCP hosts that load every tool schema up-front. Tool results are
  unchanged; only the structured-output type hints are dropped. Leave it off
  for Claude clients, which defer tool schemas automatically.

## [0.7.1] — 2026-05-29

### Fixed
- The log-tail and health-summary debug tools no longer perform their log-file
  scan on Music Assistant's event loop, preventing playback stutter on
  low-power hardware while a scan runs.
- `debug_health_summary` no longer reads the log file when the log-access
  capability is disabled; it reports the capability as disabled instead of
  silently bypassing the permission.
- Provider reloads triggered over MCP no longer serialize against unrelated
  Music Assistant server instances.
- Reduced CPU overhead when the debug inspect tools serialize large objects.

## [0.7.0] — 2026-05-29

### Added
- Player views now report the controlling provider via `external_source` when
  audio is driven by an external "Connect"-style source (Spotify Connect,
  AirPlay, Yandex Ynison).

### Changed
- A player streaming from an external source now correctly shows `playing` /
  `paused` instead of `idle`: playback state is read from the active queue,
  matching what Music Assistant's own interface shows.
- The currently playing item (in player and queue views) shows the real track
  title for external sources instead of the source wrapper name.

## [0.6.2] — 2026-05-29

### Fixed
- Two more test modules now pass when the provider is inlined into Music
  Assistant core: a debug-reload test used an import form the upstream
  import-path rewrite does not translate, and the OpenClaw-bundle tests now
  skip cleanly where the bundle artifact is not part of the inlined tree.

## [0.6.1] — 2026-05-29

### Fixed
- The bundled test suite now imports cleanly when the provider is inlined into
  Music Assistant core. One debug-events test used an import form the upstream
  import-path rewrite does not translate, which surfaced as a collection error
  and a lint failure in the inlined build.

## [0.6.0] — 2026-05-29

### Added
- **Connect Wizard presets for OpenClaw and Hermes.** The wizard now mints a
  per-client token and renders a ready-to-paste snippet for the OpenClaw CLI
  (`openclaw mcp set …`) and for Hermes (`~/.hermes/config.yaml`), alongside
  the existing clients. Both target the server's streamable-HTTP endpoint with
  a bearer token.
- **Installable OpenClaw plugin bundle** under `packaging/openclaw/`. The
  Claude-format bundle pre-declares the Music Assistant MCP server over
  streamable-HTTP — with the token supplied via the `MA_TOKEN` environment
  variable — and ships a skill guide so the agent knows when to use the tools.

## [0.5.2] — 2026-05-29

### Fixed
- Completed the `0.5.1` upstream-rewrite test compatibility fix: two more test
  modules carried import suppressions that the import-path rewrite would
  detach, which `0.5.1` missed. The full bundled test suite now passes
  unchanged when the provider is inlined into Music Assistant core.

## [0.5.1] — 2026-05-29

### Fixed
- Provider test suite is now compatible with the upstream import-path
  rewrite, so the bundled tests pass unchanged when the provider is inlined
  into Music Assistant core.

## [0.5.0] — 2026-05-29

### Added
- **New `config` MCP namespace for viewing and editing settings.** Adds
  fourteen tools across five off-by-default permission flags
  (`Config: read core/provider/player settings`, `Config: edit provider
  settings`, `Config: edit core settings`, `Config: edit player settings`,
  and the orthogonal `Config: allow writing secret values`). Default
  installations see no new surface; an operator opts in per capability.
  Read tools dump provider, core, and player configuration with
  `SECURE_STRING` values masked by Music Assistant's own serialiser.
  Writes delegate to MA's atomic save primitives — which validate,
  encrypt, persist, and reload (with rollback) — so the provider performs
  no raw writes and never encrypts or logs a plaintext secret.
  SECURE_STRING writes require the secret flag in addition to the
  category flag. Every write validates each value (type, range, and
  options), elicits confirmation (core-config prompts warn about
  subsystem restarts), writes a value-free audit log line, and supports
  a `dry_run` preview that returns a before/after diff without mutating.
  A `config_trigger_provider_action` tool relays provider config actions
  such as QR login.

### Fixed
- **The destructive-operation confirmation gate now fails closed on
  unexpected MCP errors.** Previously a transient protocol error could
  be mistaken for "client cannot confirm" and let the operation through;
  now only genuine missing-capability errors pass through and any other
  error re-raises.
- **Confirmation-gated tools no longer time out mid-confirmation.** The
  tool timeout wraps the interactive confirmation prompt, so the previous
  10-second limit could expire while a human was still reading and
  answering it (and the provider-reload that follows can itself take
  several seconds). Config writes and the provider-reload tool now use a
  generous interactive timeout; read-only tools keep the fast one.

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

## [0.3.35] — 2026-05-28

### Added
- **`PlayerBrief` now carries `volume_muted`, `group_volume`, and
  `group_volume_muted`.** Sync groups hold their volume on a
  separate `group_volume` property — without these fields a
  caller looking at a SyncGroupPlayer's brief saw only
  `volume_level=null` and had no signal at all about how loud the
  group was set or whether it was muted. The mute state of
  individual players is now visible too. All three fields default
  to `None` so the brief stays back-compatible with every existing
  caller, and the values are read from `Player.state` first (the
  canonical view populated by MA's volume-state machinery), with
  the raw dataclass attributes as a fallback for legacy stubs.

## [0.3.34] — 2026-05-28

### Fixed
- **`state="synced"` and `active_group` / `synced_to` now resolve for
  real Music-Assistant sync followers.** The `0.3.32` release wired
  three new fields into `PlayerBrief` but read them from the raw
  `Player` dataclass attributes — those stay `None` for
  SyncGroupPlayer followers even while they are streaming the group's
  audio. The canonical values live on `Player.state.active_group` and
  `Player.state.synced_to`, populated by MA's `__final_active_group`
  / `__final_synced_to` cached properties (which walk every GROUP
  player and resolve protocol-id translation). The brief now uses
  the same state-first / raw-fallback pattern already in place for
  `powered` and `current_media`, so a follower captured by an active
  group surfaces as `state="synced"` with the resolved group id.
  Live verification on a SyncGroupPlayer streaming to Kitchen +
  Lenco previously left both at `state="idle", active_group=null`;
  after this fix they correctly report `state="synced"`.

## [0.3.33] — 2026-05-28

### Changed
- **One inline test import is now pre-split into multi-line form** so
  the upstream-PR rewrite cannot push it past the upstream ruff
  line-length (99). When the wrapper rewrites `provider.tools` to its
  longer upstream path, the original single-line `from … import a, b`
  would exceed the limit, ruff would split it across multiple lines,
  and the trailing `# noqa: PLC0415` would land on the wrong row —
  ruff then deletes it as `RUF100 unused-noqa` and the underlying
  `import inside function` violation goes uncovered. Writing the
  import as multi-line with the noqa on the opening `(` line up-front
  keeps the marker stable through every formatter pass. The wrapper
  itself is being patched in `ma-provider-tools` so future sync runs
  normalise formatting after rewrite.

## [0.3.32] — 2026-05-28

### Added
- **`list_players` and `get_player` now expose three more
  Music-Assistant signals**: `needs_setup` (device awaiting first-run
  configuration), `active_group` (id of the active sync group the
  device belongs to, when set), and `synced_to` (id of the sync
  leader, when set). The previous response shape is a strict subset,
  so existing callers keep working.
- **`list_players` accepts a new `include_disabled` parameter**
  (default `False`, matching MA's own `return_disabled` default).
  Without it, admin-disabled players are filtered out by MA before
  they reach the brief — the `enabled` field added in `0.3.30` was
  therefore always `True` and effectively dead. Flipping the flag
  exposes them with `state="disabled"` so an LLM can act on the
  signal.
- **`QueueBrief.available`** now mirrors `PlayerQueue.available` for
  every queue tool response. The same triage problem the player
  surface closed in `0.3.30` is now closed for queues as well.

### Changed
- **`state` on `PlayerBrief` summarises usability across four
  blocker axes, not one.** The previous single override
  (`state="unavailable"` when `available=False`) is now a priority
  ladder: `unavailable` > `disabled` > `needs_setup` > `synced` >
  the underlying `playback_state`. A device that is both offline
  and a sync follower still reports `"unavailable"` (the most
  blocking signal wins). The new state values are additive — any
  client doing equality checks against `idle`/`playing`/`paused`
  keeps working as before.
- **`now_playing_summary` prompt** now reflects the default filter
  (`include_unavailable=True` for offline devices,
  `include_disabled=True` for admin-disabled devices) and tells the
  LLM what `state="synced"` means for queue routing.

## [0.3.31] — 2026-05-27

### Changed
- **Connect-wizard bootstrap helpers moved from the package root to
  `provider._init_helpers`** with a back-compat re-export from
  `provider.__init__`. Existing callers (`from provider import
  _detect_external_base_url, …`) keep working, but tests now use the
  dotted-path import — the upstream-PR rewrite only translates
  ``from provider.<sub> import …`` forms, so a bare
  ``from provider import …`` slipped through the rename and broke
  upstream CI with `ModuleNotFoundError`. The wrapper itself is being
  patched in `ma-provider-tools`; this change unblocks the next sync
  in the meantime.
- **`tests/test_origins_module.py`** switches from
  `from provider import origins` (namespace import, also missed by
  the rewrite) to explicit ``from provider.origins import …`` names
  — the same contract is still pinned by the from-import failing at
  collection time if a name disappears.

## [0.3.30] — 2026-05-27

### Added
- `list_players` now reports `available` and `enabled` on every player
  brief, mirroring the same flags Music Assistant exposes for each
  device. The previous response shape (without these fields) is a
  strict subset, so existing callers keep working.
- `list_players` accepts a new `include_unavailable` parameter
  (default `False`) that controls whether offline / unreachable
  players appear in the result.

### Fixed
- **Offline players were indistinguishable from quiet ones in
  `list_players`.** Music Assistant never receives push updates from
  a device it has lost contact with, so the cached `state` stayed at
  `"idle"` and `powered` stayed at `True` — the brief looked
  identical to a working speaker that simply wasn't playing
  anything. The default `list_players` response now omits
  unavailable devices entirely, and when they're requested
  explicitly (`include_unavailable=True`) their `state` is reported
  as `"unavailable"` so callers can tell the two cases apart.

## [0.3.29] — 2026-05-27

### Fixed
- **Connect Wizard rejected the Home-Assistant ingress flow with
  ``Plaintext credential traffic from non-loopback hosts is not
  allowed``.** The plaintext-credential guard introduced in
  ``0.3.26`` waved through HTTPS and loopback but not HA ingress —
  HA terminates TLS at its public front door and forwards the
  request to Music Assistant over a *local* socket, so the wizard
  sees ``request.scheme == "http"`` and a non-loopback
  ``request.host`` even though the public hop is HTTPS. As a
  result, opening the wizard via the ingress URL (e.g.
  ``https://ha.example/api/hassio_ingress/<id>/mcp/v1/connect``)
  fell through to the login form and rejected the user's
  credentials on submit. The guard now mirrors the existing
  ``Origin``-check pattern and trusts requests that MA's
  ``is_request_from_ingress`` helper confirms are on the trusted
  ingress socket — direct LAN plaintext requests are still
  refused.

## [0.3.28] — 2026-05-27

### Changed
- **Test suite quality + coverage backfill.** Six tests that
  silently passed for the wrong reason are tightened — most
  notably the ``test_context.py`` log-handler wiring (the
  previous version no-op'd via a non-existent ``Client`` method),
  the ``apply_permission_change`` hot-swap assertion (the preset
  tag was also in defaults, so the test held whether the rebuild
  ran or not), and the ``test_models.py`` ``to_brief_player``
  powered-source check (now parametrized with a contradictory
  case so a precedence swap is caught). Five new test files /
  extensions add coverage for ``provider/prompts.py`` (was zero),
  ``MCPServerProvider.update_config`` (was zero), every
  malformed-JWT path in ``_extract_jwt_audience`` (now nine
  parametrized cases), all five library resource kinds (was
  artist-only) plus the ``queue_resource`` (was uncovered), and
  an end-to-end hot-swap test that mounts a real FastMCP root
  and verifies the visible tool surface flips on
  ``apply_permission_change``. Test count: **296** (up from
  **194** before the audit cycle).

## [0.3.27] — 2026-05-27

### Changed
- **Origin-allowlist helpers split into a dedicated
  ``provider/origins.py`` module**, with the previous
  ``http_bridge`` symbols re-exported under their historical
  names for back-compat. The Connect Wizard no longer reaches
  into ``http_bridge`` via ``importlib`` to look up private
  symbols — a rename of either helper would silently break the
  wizard mount with an opaque ``RuntimeError`` if there were no
  test to catch it. Two new contract tests pin both the public
  module names and the back-compat aliases.
- **External-base-URL detection prefers a public
  ``client.authenticated_user`` attribute** when available,
  falling back to the underscore-prefixed internal form Music
  Assistant exposes today. A future MA rename to a public
  property is then picked up transparently.

## [0.3.26] — 2026-05-27

### Security
- **Bearer-token audience is now verified BEFORE Music Assistant
  is consulted.** Previously every request hit
  ``authenticate_with_token`` first, which refreshed MA's
  sliding-window expiry on the token even when the audience was
  about to fail; an attacker holding a non-MCP MA token could keep
  it alive indefinitely by polling the MCP endpoint. The audience
  check now runs first, short-circuiting before MA is touched.
- **Connect Wizard credential endpoints refuse plaintext-HTTP
  requests from non-loopback hosts.** ``/connect/login``,
  ``/connect/exchange`` and ``/connect/token`` all carry secrets
  (admin password, bootstrap, session token); over plain HTTP from
  a LAN host they were sniffable. HTTPS and loopback are still
  accepted; everything else returns a JSON 400 with an actionable
  message.
- **``play_announcement`` validates the supplied URL scheme.**
  The ``url`` parameter is user-controlled and previously flowed
  to MA's player API as-is, so a prompt-injected
  ``file:///etc/passwd``, ``data:`` URL, etc. would dutifully be
  fetched by the audio backend. Non-``http(s)`` schemes now raise
  ``ToolError`` before reaching MA, and ``volume_level`` is
  clamped to ``[0, 100]`` to match the rest of the volume surface.

### Changed
- **Dead ``try/except`` around the wizard's external-base-URL
  detection removed.** ``getattr(mass.webserver, "clients", None)
  or ()`` cannot raise, so the bare ``except Exception`` only
  suppressed future real bugs without catching anything today.

## [0.3.25] — 2026-05-27

### Changed
- **Media-tool errors are now more actionable.** ``_resolve_uri``
  in the media tools surfaces a distinct ``ToolError`` per failure
  class (``MediaNotFoundError`` / ``InvalidProviderURI`` /
  ``ProviderUnavailableError``) instead of flattening every
  failure to "Item not found"; the LLM caller can now distinguish
  "URI typo" from "provider offline" and respond accordingly.
- **``QueueBrief.item_count`` is now ``int | None``.** When the
  upstream queue exposes no canonical total, the field is
  ``None`` rather than ``0`` (silent zero on a non-empty queue
  was worse than acknowledging the value is unknown).

### Fixed
- **Failed mount no longer leaves the runtime half-mounted.**
  If ``MCPServerRuntime.start`` raises after a partial mount
  (e.g. the well-known route registered but the main route
  failed), the rollback path tears the in-progress state down
  before re-raising so a retry starts from a clean slate.
- **``get_track_by_uri`` and ``get_lyrics`` reject non-track
  URIs with a clean ``ToolError``** instead of silently coercing
  an album/playlist into a garbage ``TrackBrief`` (or returning
  ``None`` for non-track lyrics queries).
- **Connect Wizard login is shape-agnostic on the MA response.**
  If Music Assistant migrates the ``auth.login`` return type to
  a typed result object, the wizard surfaces the success/failure
  correctly instead of silently reporting "invalid credentials"
  for valid logins.

## [0.3.24] — 2026-05-27

### Security
- **Connect Wizard bootstrap tokens no longer ride in the URL
  query string.** Query strings end up in aiohttp's access log and
  every reverse-proxy log on the path (HA ingress, nginx, …), and
  could leak via ``Referer`` on outbound links before the wizard's
  ``history.replaceState`` strip ran. The bootstrap now travels in
  the URL fragment (``#bootstrap=…``), which is never sent to
  servers or proxies and not included in cross-origin ``Referer``.

### Changed
- **Wizard HTML response now carries ``Referrer-Policy:
  no-referrer`` and a stricter ``Content-Security-Policy``** —
  ``default-src 'none'`` plus narrowly-scoped ``script-src``,
  ``style-src``, ``connect-src`` and ``img-src`` directives. The
  previous policy only restricted framing; the new one bars
  exfiltration of cached long-lived MA tokens via fetch / img if a
  future inline-data edit accidentally introduces XSS.

## [0.3.23] — 2026-05-27

### Fixed
- **Permission hot-swap could race the previous ASGI lifespan
  shutdown.** The ``unmount`` returned from mounting the MCP
  endpoint scheduled the FastMCP session-manager teardown as a
  fire-and-forget background task and returned immediately, so a
  follow-up ``apply_permission_change`` that needed a full restart
  could start a new lifespan while the previous one was still
  draining. Worst case the orphan task was garbage-collected before
  it ran, leaking the session-manager task group and triggering
  ``Task was destroyed but it is pending`` warnings. The unmount
  now awaits the shutdown to completion before returning.

## [0.3.22] — 2026-05-27

### Changed
- **`playlists/add_track`, `add_tracks` and `remove_tracks` now
  accept both the integer library id and the
  `library://playlist/<n>` URI for `playlist_id`** and normalise
  internally to the integer form that Music Assistant requires.
  Previously, passing the URI raised a Python `ValueError` deep
  inside MA; passing an unsupported URI now raises a clean tool
  error with guidance.

### Fixed
- **`playlists/add_tracks` no longer claims that batches of ten
  or fewer tracks are added atomically.** The claim was incorrect
  — Music Assistant performs no atomicity at any batch size — and
  could mislead clients into believing rollback was available on
  partial failure. The tool now always adds tracks one at a time
  with progress reporting and an explicit "not atomic" notice.
- **`playlists` tool docstrings no longer reference a
  non-existent `PlaylistBrief.item_id` field.** Returned playlist
  briefs expose `uri` only; pass that URI back to add/remove
  tools as documented.

## [0.3.21] — 2026-05-27

### Changed
- **Tool descriptions across all 45 tools are now Sphinx-style with
  `:param:` blocks, sibling-tool disambiguation and return-shape
  hints.** Every parameter previously surfaced to clients with an
  empty description in the JSON Schema. The updated docstrings give
  the LLM the constraints it needs to construct correct calls and
  pick the right tool out of similar siblings (search vs. list,
  favorites vs. library, play_media vs. play_index, volume_set vs.
  volume_up/down vs. volume_mute, etc.).
- **`play_media` is now flagged as a destructive operation** in its
  tool annotations and timeouts to `30s` instead of `15s`. Loading
  fresh media into a queue replaces whatever the queue was playing,
  which is a destructive side effect from the caller's perspective;
  hosts will prompt for confirmation accordingly. The longer
  timeout matches `play_announcement`, where fetching audio from a
  slow provider can exceed the default mutation timeout.
- **`transfer_queue` is now flagged as a destructive operation**
  for the same reason — the source player stops and its queue is
  emptied.
- **`play_announcement` timeout raised from `15s` to `30s`** —
  fetching the announcement audio may take longer than the
  mutation timeout allows on slow connections.

### Fixed
- **`search_tracks`, `search_albums`, `search_artists`,
  `recently_added_tracks` and `recently_played` did not clamp
  caller-supplied `limit` values,** while every sibling pagination
  tool clamped via `page_args`. A sloppy or hostile client could
  ask for an unbounded result set. All five now clamp to the
  `[1, 200]` range that the rest of the library tools already
  enforce.
- **`previous_track`'s subtle restart-then-step-back behaviour is
  now documented in the tool description** instead of being a
  hidden semantic trap. Music Assistant restarts the current
  track if it has been playing past the rewind threshold; the
  caller has to invoke the tool a second time to actually move to
  the previous item.

## [0.3.20] — 2026-05-26

### Changed
- **Defensive `hasattr` / `getattr` shims around stable Music
  Assistant APIs are gone.** `mass.players.all_players()`,
  `mass.player_queues.clear()`, `mass.webserver.base_url` and
  `mass.webserver.publish_ip` are documented stable surfaces, so
  the provider now calls them directly. A latent bug in the
  ``list_players`` shim — a double-invoke of `all_players()` that
  would have raised `TypeError` had the (unreachable) fallback ever
  fired — is incidentally removed.
- **Test conftest and `__init__` docstrings are now repo-agnostic,
  and the `sys.path` injection in `tests/conftest.py` is gone.**
  The `provider` package is already importable through the editable
  install performed by `./scripts/setup.sh`, so the injection was
  dead code in every supported test environment. The end-to-end
  smoke logger is renamed from `ma-provider-mcp.smoke` to
  `fastmcp_server.smoke` to match the provider domain.

## [0.3.19] — 2026-05-22

### Fixed
- **The ASGI lifespan task could leak across plugin reloads if the
  upstream app failed to acknowledge `lifespan.startup` within the
  30-second timeout, or replied with an unrecognised event type.**
  The startup negotiation now cancels and drains the lifespan task
  on any non-success exit before re-raising, so failed mounts no
  longer accumulate orphan background tasks across retries.

## [0.3.18] — 2026-05-22

### Changed
- **Bundled FastMCP bumped from `3.2.4` to `3.3.1`.** Picks up
  reentrant lifespan handling for mounted servers (relevant — we
  mount 8 sub-servers under one root), clean ping-loop exit on
  stream close, HTTP-transport teardown ordered before lifespan
  shutdown, OTEL instrumentation of `list_*` operations, and
  hardened OAuth-proxy silent-consent. No code changes required;
  all 193 tests pass unmodified. The `fastmcp-slim` client-only
  distribution introduced in 3.3 is **not** used — this provider is
  a server.
- **`manifest.json` `documentation` field now points to the official
  Music Assistant docs site (`music-assistant.io/plugins/fastmcp-server/`)
  instead of the external source repository,** so the *Documentation*
  link in the provider config panel takes the user to the in-house docs
  the rest of the MA UI links to.

### Fixed
- **`asyncio.get_event_loop()` deprecation warning on Python 3.14
  during plugin unload.** The unmount path now uses
  `asyncio.get_running_loop()`. The unreachable sync-context
  fallback was dropped — `MCPServerRuntime.stop` is `async`, so the
  unmount closure always runs with a live event loop and the
  fallback only added noise.
- **`pytest_addoption` and `pytest_collection_modifyitems` hooks in
  the test conftest leaked a global `--run-integration` CLI flag and
  a whole-session marker-skip into the surrounding pytest run.** When
  the test tree is collected alongside the broader Music Assistant
  suite, those hooks would have added an unsolicited CLI option and
  iterated every collected item — including tests outside this
  provider — looking for an `integration` marker. The hooks have
  been removed (no test in the repo actually used the marker).

## [0.3.17] — 2026-05-13

### Fixed
- **Test harness `build_aiohttp_app` did not mirror MA's real
  dynamic-route matching for bare-stem URLs.** A path registered as
  `"/mcp/v1/*"` in MA matches both `/mcp/v1` (no trailing slash) and
  any descendant `/mcp/v1/...`, per
  `helpers/webserver.py::_handle_catch_all`. Our harness emitted
  aiohttp pattern `/{stem}/{tail:.*}`, which requires a trailing slash,
  so the wizard-advertised MCP entry-point URL (`<base_url>/mcp/v1` —
  no trailing slash, exactly what clients connect to) was silently
  excluded from coverage. The harness now adds an explicit route for
  the bare stem alongside the wildcard; new regression test
  `test_bare_mount_path_without_trailing_slash_reaches_asgi` locks the
  behaviour in.

## [0.3.16] — 2026-05-13

### Fixed
- **`Open Connect Wizard` raised `AttributeError: 'sqlite3.Row' object
  has no attribute 'get'` on real MA installs.** The provider was reaching
  directly into `mass.webserver.auth.database` for token GC, name-based
  dedup, and ownership checks; at runtime those queries return
  `sqlite3.Row` instances which only support bracket indexing, so
  `row.get(...)` raised. The provider now goes through the sanctioned
  public API instead — `auth.revoke_token` (which enforces user ownership
  internally and handles WS disconnect itself), `auth.get_user_tokens`
  (returns typed `AuthToken` dataclasses, never raw rows), and
  `auth.get_token_id_from_token` (handles both JWT and legacy hash
  tokens) — using the same `set_current_user` context-impersonation
  pattern that MA's own test suite uses
  (`tests/test_webserver_auth.py:336-354`). As a side effect, the
  encapsulation concern from the upstream review is resolved.

### Changed
- **Connect Wizard no longer relies on the client-supplied
  `prev_token_id` hint.** Re-generate now revokes prior tokens entirely
  via server-side name-dedup using `auth.get_user_tokens`. The
  `sessionStorage` `ma_token_ids` cache and the `token_id` field
  previously returned from `/connect/token` are gone — they were
  defense-in-depth on top of a hardened dedup path that is now
  self-sufficient.

## [0.3.15] — 2026-05-13

### Changed
- **Re-generating a per-client token in the Connect Wizard now revokes
  the previous token automatically.** Previously the old long-lived
  token remained valid for 10 years and could only be removed manually
  from Profile → Long-lived access tokens. The wizard now deletes any
  prior rows with the same client name for the same user before
  minting; the frontend also tracks the new `token_id` in
  `sessionStorage` and passes it back on the next re-generate as a
  fast-path hint. Note: the same client label on two devices against
  one MA shares a name, so re-generating on one device revokes the
  other — revoke manually if you need independent tokens.

### Fixed
- **Stale `MCP — wizard bootstrap` / `MCP — wizard session` rows
  accumulating in the user's token list.** Every wizard open + every
  page load was adding ephemeral rows that lingered 30 days. Opening
  the Connect Wizard now garbage-collects any prior wizard
  bootstrap/session rows for the same user before minting the new
  one. Per-client tokens (`MCP — <Client>`) are not touched.
- **Connect Wizard snippets for Codex CLI, Cline, and Zed corrected
  against upstream syntax drift.** Codex CLI's streamable-HTTP
  transport reads custom headers from `http_headers` (not `headers`);
  Cline's JSON schema does not define a `transportType` field (it's a
  UI-only picker); Zed has had native remote-MCP support for a while,
  so the `npx mcp-remote` stdio bridge is no longer needed. Users
  pasting any of these snippets will now get a working server entry
  without silent failures.

### Security
- **Connect Wizard bootstrap tokens are now single-use on a
  best-effort basis.** Previously a bootstrap (the token embedded in
  the wizard URL) could be exchanged for session tokens repeatedly
  for up to 30 days. `/connect/exchange` now deletes the bootstrap
  immediately after authenticating it and before minting the session,
  so each bootstrap exchanges at most once under normal operation.
  Revocation is best-effort: if the delete fails (DB error etc.) it
  is logged and the mint still proceeds, matching the pre-patch
  reusable behaviour only in that failure case.
- **Connect Wizard `/connect/token` revoke is scoped to the
  authenticated user.** The optional `prev_token_id` hint from the
  frontend is now verified against the session user before any delete
  — a caller cannot name a token owned by a different user and have
  it revoked. The server-side name-dedup path was already scoped via
  the `user_id` filter on the row lookup.

## [0.3.14] — 2026-05-13

### Fixed
- **Provider settings and Connect Wizard pointed users at the wrong path
  for managing per-client tokens.** The info label, the **Open Connect
  Wizard** action description, and the wizard's post-mint banner all said
  *Settings → Security → Tokens*, but Music Assistant exposes the page as
  *Profile → Long-lived access tokens*. The displayed path now matches the
  UI, so users following the wizard can find and revoke their tokens
  without hunting through the wrong menu. `README.md` references updated
  to match.

## [0.3.13] — 2026-05-13

### Changed
- **Connect Wizard no longer displays the provider version.** The
  `v0.3.x` tag in the wizard's permissions panel and the `version`
  field in `GET /connect/info` are gone. The wizard is purely an
  onboarding flow and didn't need the label; removing it lets the
  release number live in exactly one place — the `VERSION` file at
  the repo root — instead of being threaded through Python imports,
  HTML, JavaScript, and the `/connect/info` payload.

### Removed
- **`provider.__version__`** is no longer defined. Two prior releases
  (v0.3.11 and v0.3.12) shipped with `__version__ = "0.3.10"` because
  the constant was hand-edited separately from the `VERSION` file. No
  in-tree consumer reads it anymore (the wizard was the only one);
  dropping it eliminates the drift surface entirely.

## [0.3.12] — 2026-05-13

### Fixed
- **`media_remove_from_favorites` and `media_remove_from_library` silently
  mis-targeted or raised for non-library URIs.** The tools cast the
  resolved item's id to `int(...)`, but a provider URI (e.g.
  `yandex_music://track/abc`) resolves to a `MediaItem` whose `item_id`
  is the **provider's** native id, not a library id. The destructive
  controllers expect a library item id, so the call either failed on
  the `int()` cast or pointed at the wrong row. The tools now resolve
  the library counterpart explicitly and raise a clear error when the
  URI is not in the library.
- **Resource-toggle config changes (`res_library`, `res_player`,
  `res_prompts`) silently took the hot-swap code path and never
  reloaded resources.** Music Assistant updates `ProviderConfig` in
  place, so the runtime's internal old-vs-new diff was always empty
  and incorrectly classified resource toggles as permission-only.
  The provider's `changed_keys` set is now passed through and used
  directly; resource toggles trigger a full runtime restart so the
  user's change actually takes effect.

## [0.3.11] — 2026-05-12

### Fixed
- **Player `powered` and `current_item` reported stale or inverted values**
  in MCP tool and resource responses. For some virtual player types
  (Web, Universal) `powered` showed `false` while playback was active,
  and `current_item` retained the previous track's title after stop.
  Brief responses now follow Music Assistant's canonical player state
  — the same shape its REST API serialises — so the values stay in
  sync with the server's view of the world.
- **`resources/read` on every `library://`, `player://`, and `queue://`
  URI returned `-32002 Resource not found`** even when the matching
  permission was enabled. The permission middleware resolved a request
  URI only against statically registered resources and missed all
  URI-template-backed ones. Concrete URIs are now matched against
  registered templates as well, so library / player / queue resource
  reads succeed.
- **Library resource reads failed with `contents must be str, bytes, or
  list[ResourceContent]`.** Resource handlers returned the underlying
  domain objects directly, which FastMCP refuses to serialise. Handlers
  now emit JSON text so `library://artist/{id}`, `library://album/{id}`,
  `library://track/{id}`, `library://playlist/{id}`, `library://radio/{id}`,
  `player://{id}`, and `queue://{id}` actually load.

## [0.3.10] — 2026-05-12

### Fixed
- **Claude Code wizard snippet used a non-existent `--url` flag** —
  `claude mcp add` takes the server URL as the positional argument
  after the name, so the previous template (`claude mcp add ma
  --transport http --url <URL> …`) silently registered an
  unreachable server. Snippet now renders `claude mcp add ma <URL>
  --transport http --header "Authorization: Bearer <TOKEN>"`.

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
