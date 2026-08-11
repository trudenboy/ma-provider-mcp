# Durable Upstream–Provider Synchronization Design

## Context

The FastMCP provider repository is the source of truth for
`music_assistant/providers/fastmcp_server`, while `ma-provider-tools` is the
source of truth for generated repository wrappers. Two independent forms of
drift are currently present:

1. Upstream Music Assistant changed provider-facing APIs in merged PRs #5402
   and #5417. The provider still uses the previous config-action and
   impersonation contracts, producing three mypy failures against current MA
   `dev`.
2. Wrapper distribution commits #247 and #248 replaced FastMCP-specific Docker
   source-overlay behavior and removed the `prefab-ui` runtime dependency from
   the generated `pyproject.toml`. This broke the provider repository's own
   Docker contract test and made a clean environment incomplete.

The automatically opened reverse-sync PRs #241 and #243 do not contain the
upstream changes. They contain only placeholder specs and changelog entries.

## Goals

- Make the provider compatible with the current upstream config-action and
  impersonation APIs.
- Restore the FastMCP-specific development environment durably at the wrapper
  generator rather than patching generated files by hand.
- Close the empty reverse-sync PRs with an accurate explanation.
- Preserve the provider repository as the canonical implementation and treat
  upstream as read-only.
- Restore a green `dev` baseline before updating radio-contract PR #253.

## Non-goals

- Do not make the provider and upstream trees byte-for-byte identical. The
  provider repository intentionally contains newer canonical architecture.
- Do not port unrelated Bandcamp or Tidal changes from upstream PR #5452.
- Do not introduce compatibility shims for the synthetic
  `connect_wizard_url` config entry.
- Do not edit generated `pyproject.toml`, `docker-compose.dev.yml`,
  `scripts/docker-init.sh`, or workflow files directly in the provider repo.
- Do not change or comment on `music-assistant/server` directly.

## Repository Ownership

### `trudenboy/ma-provider-tools`

This repository owns durable wrapper generation. Its FastMCP registry entry
must render the provider's complete runtime dependency set:

- `fastmcp==3.4.6`
- `prefab-ui==0.20.2`

The wrapper renderer must support an explicit provider metadata flag for a
checked-out MA source overlay. For FastMCP this renders:

- `PYTHONPATH: /ma-server`;
- `${MA_SERVER_ROOT:-../ma-server}:/ma-server:ro`;
- the provider mounted directly at
  `/ma-server/music_assistant/providers/fastmcp_server`;
- the provider tests mounted at `/tmp/provider-tests`;
- Docker init validation that both MA and provider imports resolve from the
  mounted source tree.

Providers without the flag retain the current generic site-packages symlink
mode. Renderer tests must cover both branches so the FastMCP exception cannot
silently become a global behavior change.

### `trudenboy/ma-provider-mcp`

This repository owns provider behavior. Generated wrapper corrections arrive
only through the normal `ma-provider-tools` distribution path.

Provider code adapts to current upstream contracts:

1. `MCPServerProvider.handle_config_action` matches the upstream return union:
   `tuple[ConfigEntry, ...] | ConfigActionResult | None`.
2. `open_connect` returns `ConfigActionResult(open_url=url)` without redrawing
   the form.
3. A missing wizard URL raises `ActionUnavailable` with translation key
   `connect_wizard_unavailable` and the provider translation owner.
4. The obsolete `connect_wizard_url` config-entry string is removed and the
   new error string is added.
5. Non-FastMCP actions pass through the base handler result unchanged,
   including `None` and `ConfigActionResult`.
6. Impersonation resolves the requested built-in MA user with
   `AuthProviderType.BUILTIN` and the new upstream helper signature.

## Upstream PR Classification

### PR #5402

This is a behavioral contract change and must be adapted to the current local
architecture. The local repository no longer has upstream's dedicated
`tools/config.py`; native MA commands are exposed through `DynamicAPIAdapter`.
Tests must prove that `ConfigActionResult` values remain useful when returned
through that dynamic path, including `open_url` and translated messages. A
serialization adapter is added only if the RED test demonstrates that the
current generic serializer loses the user-facing outcome.

### PR #5417

This is an upstream authentication API change. The public MCP impersonation
input remains a user identifier, but the upstream call must identify the
built-in auth provider explicitly. Existing authorization and target-filter
behavior remains unchanged.

### PR #5452

This is test-only fixture deduplication for upstream test modules that no
longer exist in the local flattened suite. There is no applicable source or
test hunk, so the correct reverse-sync result is a documented no-op.

## Test Strategy

All behavioral changes follow RED/GREEN TDD.

### Provider tests

- Config lifecycle: successful `open_connect` returns a structured one-shot
  URL and does not call `get_config_entries`.
- Config lifecycle: failed dispatch raises the translated
  `ActionUnavailable` error.
- Config lifecycle: an unrelated action passes through `ConfigActionResult`
  and `None` without tuple coercion.
- Authentication adapter: the upstream helper receives
  `(mass, AuthProviderType.BUILTIN, requested_user)`.
- Dynamic result path: config-action `open_url` and translated message outcomes
  survive MCP serialization.
- Full provider suite, Ruff, mypy, and pre-commit run against current MA
  `dev`.

### Wrapper-generator tests

- Rendering FastMCP includes both exact runtime dependencies.
- Rendering FastMCP includes the MA source overlay, provider overlay, tests
  mount, and import-origin validation.
- Rendering an ordinary provider retains generic symlink mode and does not
  receive FastMCP-only mounts.
- Existing generator validation and distribution tests remain green.

### Generated provider verification

After distribution, `docker compose -f docker-compose.dev.yml config --format
json` must expose `environment.PYTHONPATH == /ma-server` and the neighbouring
MA source bind mount. The complete provider test and pre-commit suites then run
on the generated tree.

## Delivery and Sequencing

1. Create and validate a focused `ma-provider-tools` branch and draft PR for
   registry/template changes.
2. Create and validate a focused provider branch and draft PR for upstream API
   adaptations.
3. Close provider PR #243 as a test-only no-op and PR #241 as an empty,
   superseded reverse-sync scaffold, linking the replacement provider PR.
4. Merge the tools correction after review and use its normal distribution
   workflow to produce the generated provider update; do not hand-edit the
   generated files.
5. Merge the generated wrapper update and provider API adaptation into `dev`
   only after their required checks pass.
6. Update PR #253 with the green `dev`, rerun all checks, and mark it ready for
   review when no branch-specific failure remains.

Worktrees and feature branches remain available while their PRs are under
review. No upstream Music Assistant branch, issue, or PR is mutated.

## Failure Handling

- If a tools renderer change affects providers without the opt-in flag, stop
  and narrow the template conditional.
- If current MA `dev` advances during implementation, re-run the API contract
  tests and adapt only confirmed new drift.
- If a generated provider PR differs from the locally expected rendering,
  diagnose the generator/distribution inputs rather than editing its output.
- If #253 gains a branch-specific failure after rebasing, keep it draft and
  address that failure on its existing branch.
