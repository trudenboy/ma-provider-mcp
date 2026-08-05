# Permissions & Confirmations v2 Implementation Plan

## Global Constraints

- Release as breaking version `2.0.0`; preserve command names and `/mcp/v1`.
- Define exactly 26 stable capabilities: the existing 25 capability strings plus `system:admin`.
- Policy modes are exactly `deny`, `allow`, and `confirm`; capability precedence is `deny > confirm > allow`.
- Profiles are exactly `Read-only`, `Home control`, `Interactive admin`, `Trusted`, and `Custom` with the defaults specified below.
- Missing v2 configuration is `Read-only`; v1 permission keys, `dynamic_api_*`, and `require_confirmation` are ignored with no migration or compatibility logic.
- Token overrides are keyed by the Music Assistant token ID, never user ID, bearer hash, or client name.
- Never retain or log raw bearer tokens, submitted secret values, or unmasked secure configuration.
- MA scopes, disabled-user state, player/provider filters, and fresh authentication remain authoritative upper bounds.
- `auth/*` and dashboard registration commands are always hard-denied; impersonation always escalates to per-call confirmation.
- Use red/green/refactor TDD. Do not weaken existing tests to accommodate implementation changes; replace tests only where the public v1 contract is intentionally removed by this breaking release.
- Keep provider-local Docker acceptance excluded from upstream synchronization.

## Task 1: Policy model, profiles, and command classification

Introduce the v2 policy primitives and classification foundation.

- Add `PolicyMode` with `deny`, `allow`, and `confirm`.
- Add `PolicyProfile`, immutable policy snapshots, and a resolver keyed by `token_id`.
- Keep all existing 25 capability strings and add `system:admin`.
- Implement these exact profile snapshots:
  - `Read-only`: `query:* = allow`, everything else `deny`.
  - `Home control`: `query:*`, `control:*`, and `edit:* = allow`; `delete:* = confirm`; debug/config/system `deny`.
  - `Interactive admin`: query/control `allow`; edit/delete/debug/config/system `confirm`.
  - `Trusted`: all capabilities `allow`.
  - `Custom`: explicit per-capability modes; unset values become `deny`.
- Model default and per-token overrides with `Inherit`, profile, and Custom choices.
- Rework command classification so every live command either receives one or more capabilities or is explicitly hard-denied. Unknown/unclassified commands fail closed.
- Combine required capabilities with `deny > confirm > allow`; preserve request-dependent alternative-capability and secret-write preflight classification.
- Remove risk-gate and mandatory-confirmation behavior from classification. Destructive, read-only debug, and system commands are decided only by their capability modes.
- Add a size-L feature spec at `specs/inprogress/0027-permissions-confirmations-v2.md`, including sequence and data-model sections, before production-code changes.
- Add snapshots/tests for every profile and all 26 capabilities, precedence, Custom defaults, hard-denied command families, and registry classification parity.

## Task 2: Token identity and native dynamic configuration

Connect authenticated requests and provider configuration to immutable v2 snapshots.

- Extend `MASTokenVerifier` to call MA's sanctioned `get_token_id_from_token` API after successful authentication.
- Add a bounded registry keyed only by the SHA-256 fingerprint of a bearer token and storing `{user_id, token_id}`. It must never retain raw tokens.
- On token-ID lookup failure, resolve `Read-only`; authenticated legacy tokens without an ID inherit the global default.
- Build native dynamic config entries from tokens belonging to the current settings user whose names start with `MCP — `.
- Add `Default policy`, conditional default Custom matrix, `Manual MCP token IDs` multi-value input, and one `Inherit/Profile/Custom` selector plus conditional Custom matrix per discovered/manual token.
- Use deterministic hashed suffixes for all token-specific config keys so raw IDs are not embedded in keys. Replacement tokens never inherit revoked-token overrides.
- Remove legacy permission, `dynamic_api_*`, and `require_confirmation` entries and parsing. Existing stored keys remain ignored.
- Hot-swap the immutable policy snapshot and debug event-buffer activation on relevant config changes.
- Test default, per-token, Custom, manual, unknown, authenticated legacy, lookup-failure, and revoked/replacement resolution; native entry conditionality and current-user filtering; and hot swapping.

## Task 3: Request-aware enforcement and discovery/resources behavior

Use one request policy consistently for all MCP surfaces and executions.

- Resolve policy from the authenticated request for discovery, schema lookup, execution, provider-owned commands, and resources.
- Revalidate authentication, user state, token ID, scope, target filters, effective policy, alternatives, and secret guards immediately before execution and again after elicitation.
- Implement `confirm` outcomes exactly:
  - accepted: execute only after successful revalidation;
  - declined: raise `Operation cancelled by user`;
  - unsupported: actionable error naming the capability and suggesting `Allow` or an elicitation-capable client.
- Confirmations are never remembered. Impersonation always escalates to confirmation.
- Resource reads require the associated capability to be `allow`; `confirm` cannot bypass elicitation via `library://`, `player://`, or `queue://`.
- Prompts remain only globally configurable and do not execute operations.
- Provider-owned debug commands use the request resolver instead of a global enabled-tag guard.
- Add `policy_mode: allow|confirm` to `search_tools` results and `get_tool_schema`; report `allow` only when every executable path is prompt-free, otherwise `confirm`.
- Include effective mode in catalog revision/fingerprint so policy changes invalidate cursors and cached discovery.
- Advertise all 26 supported capabilities in protected-resource metadata.
- Test separate tokens for the same user, cached names/cursors/direct URIs after policy changes, all confirmation outcomes, multi-capability/alternative/secret behavior, and all revocation-during-prompt paths.

## Task 4: Audit, diagnostics, configuration text, and breaking release documentation

Complete security observability and the public breaking-release surface.

- Audit confirmation, denial, and privileged write/delete/config/system execution with user, token ID/client label, command, capability, effective mode, and outcome.
- Ensure audits/logs exclude bearer values, token fingerprints, submitted secrets, and unmasked secure configuration.
- Extend health diagnostics with policy schema version, effective profile name, token-resolution failure count, and active event-buffer state.
- Update `strings.json`, README, SECURITY, docs-site content, and changelog for the breaking transition and clients without elicitation.
- Delete all legacy parsing/conversion/warning/fallback paths for v1 policy configuration.
- Bump `provider/VERSION` directly to `2.0.0` as explicitly required by this plan.
- Keep auth, endpoint, Origin, resource, and prompt configuration surfaces.
- Add tests for diagnostics and audit redaction plus documentation/string/config contracts.

## Task 5: Full verification and provider-local acceptance

Verify the complete release against the specification.

- Run `uv run pytest -q`.
- Run `uv run ruff check provider tests`.
- Run `uv run ruff format --check provider tests`.
- Run `uv run mypy provider tests`.
- Run `pre-commit run --all-files` per repository policy.
- Run provider-local Docker acceptance when the local MA/Docker prerequisites are available:
  - Codex can execute `debug/health` when `debug:providers=allow`;
  - the same call does not execute when `debug:providers=confirm` and the client lacks elicitation;
  - two tokens observe their assigned profiles.
- Document any unavailable external prerequisite precisely; do not claim skipped acceptance passed.
- Move the feature spec to `specs/done/` only when implementation and verification are complete.
