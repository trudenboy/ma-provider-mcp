# Non-interactive confirmation policy

**Status:** Approved  
**Date:** 2026-07-31  
**Scope:** FastMCP Server provider confirmation policy, queue permissions, and
FastMCP 3.4.5

## Context

The provider uses MCP elicitation for command confirmation. Some clients,
including Codex CLI, can approve the outer MCP tool call but do not implement
MCP elicitation. The MCP server does not receive a standardized proof of the
client-side approval.

The current dispatcher already treats unsupported elicitation as a compatible
fallback for configured write confirmations. It still fails closed for commands
whose confirmation policy is `ALWAYS`, including system commands, queue clear
and removal operations, and impersonated calls. This prevents non-interactive
clients from using operations that the Music Assistant operator has already
enabled through authentication, scopes, risk gates, and provider permissions.

Queue curation is not considered destructive for this provider. Clearing,
removing, and reordering queue items are ordinary queue edits.

## Goals

- Support clients without elicitation while preserving explicit operator
  control over confirmation behavior.
- Keep standard write confirmations and system confirmations independently
  configurable.
- Treat impersonation confirmation as a system confirmation.
- Classify all queue mutations as non-destructive operations protected by the
  existing `edit_queue` permission.
- Upgrade the runtime dependency from FastMCP 3.4.4 to 3.4.5.
- Preserve all authorization checks independently of confirmation settings.

## Non-goals

- Per-client or per-token confirmation policies.
- A cryptographic proof of a client's local tool approval.
- Out-of-band approval tokens or approval workflows.
- Compatibility or migration for unreleased `delete_queue` configuration.
- Changes to Music Assistant users, scopes, provider/player filters, or bearer
  token semantics.

## Configuration

The provider exposes two independent boolean settings:

### Standard confirmations

`require_confirmation` remains enabled by default. It controls confirmation for
ordinary write and delete operations. Its UI description must clarify that the
prompt is requested only when the connected client supports MCP elicitation.

When disabled, standard operations execute without an elicitation request after
all normal authorization checks pass.

### System confirmations

Add `require_system_confirmation`, enabled by default and marked advanced. It
controls confirmation for system-risk commands and impersonated calls.

When disabled, those operations execute without elicitation after all normal
authorization checks pass. The setting description must explicitly warn that it
also permits impersonation without an additional interactive prompt.

Both settings are hot-swappable and must take effect for subsequent calls
without remounting the MCP endpoint.

## Confirmation policy model

Replace the ambiguous `Confirmation.ALWAYS` policy with explicit confirmation
classes:

- `NEVER`: no server-side confirmation;
- `STANDARD`: governed by `require_confirmation`;
- `SYSTEM`: governed by `require_system_confirmation`.

Default policy resolution is:

- read and control commands: `NEVER`;
- write and delete commands: `STANDARD`;
- system-risk commands: `SYSTEM`;
- impersonated calls: force `SYSTEM` regardless of the underlying command.

Exact command policies may override the default class, but no policy may bypass
authentication, scope, permission, target, or request-specific preflight checks.

### Runtime matrix

| Class | Setting | Client supports elicitation | Client lacks elicitation |
|---|---|---|---|
| `STANDARD` | enabled | Prompt; execute only on acceptance | Execute after authorization |
| `STANDARD` | disabled | Execute without prompting | Execute after authorization |
| `SYSTEM` | enabled | Prompt; execute only on acceptance | Reject with an actionable tool error |
| `SYSTEM` | disabled | Execute without prompting | Execute after authorization |

An unexpected protocol or transport failure is not equivalent to an unsupported
capability and remains fail-closed.

## Queue permission and annotation model

Remove the unreleased queue-delete permission completely:

- delete `CONF_DELETE_QUEUE`;
- delete `Tag.DELETE_QUEUE` and its config mapping;
- remove the `delete_queue` config entry and localized strings;
- remove tests and documentation that count or expose it.

All queue mutations, including `player_queues/clear`,
`player_queues/delete_item`, and `fastmcp/queue/remove_items_safe`, require
`Tag.EDIT_QUEUE`.

Queue clear and removal remain write-risk operations, but their MCP annotations
must use `destructiveHint=false`. Their confirmation class is `STANDARD`, so
they follow `require_confirmation` and remain usable by clients without
elicitation.

No read-through, alias, compatibility constant, or migration shim for
`delete_queue` is retained. Existing development configurations may need
`edit_queue` enabled manually.

## Execution flow

Every dynamic call follows this sequence:

1. Resolve the command from the current Music Assistant command registry.
2. Parse and normalize arguments.
3. Authenticate the bearer token and resolve the current MA user.
4. Enforce MA scopes, dynamic risk gates, provider permission tags, target
   filters, and request-specific preflight checks.
5. Resolve the effective confirmation class, including the impersonation
   override.
6. Apply the relevant provider setting and capability fallback from the runtime
   matrix.
7. Revalidate the token, user identity, command handler, scopes, permissions,
   target filters, and preflight checks.
8. Execute under MA's request authentication context and serialize the bounded
   result.

Disabling either confirmation setting affects only step 6.

## Error handling

- A declined or cancelled elicitation returns `Operation cancelled by user`.
- A `SYSTEM` confirmation required by configuration but unsupported by the
  client returns an actionable error that names the advanced
  `require_system_confirmation` setting.
- An unsupported elicitation request for `STANDARD` is a documented
  compatibility fallback and proceeds to post-confirmation revalidation.
- Unexpected MCP errors, timeouts, malformed elicitation responses, and
  transport failures remain fail-closed.
- Authorization failures occur before elicitation and do not reveal hidden
  command metadata.

## FastMCP 3.4.5

Update the canonical provider manifest requirement to `fastmcp==3.4.5`. The
auto-generated project metadata may retain its compatible FastMCP 3.x range;
installation and CI must additionally assert that the manifest pin resolves to
3.4.5.

FastMCP 3.4.5 is a patch release in the supported 3.x line. Its fixes cover
unsupported keys in JWKS sets, Azure scope fallback, deep-object query
serialization, deterministic transformed-tool required-field ordering, and
non-mutating schema compression. No provider adaptation to FastMCP 4 elicitation
guards is included.

## Testing

Add focused tests for:

- the complete `STANDARD`/`SYSTEM` setting and client-capability matrix;
- accepted, declined, unsupported, malformed, and unexpected-error elicitation;
- impersonation following the `SYSTEM` setting;
- confirmation settings hot-swapping without endpoint remount;
- post-confirmation revalidation after both prompted and skipped confirmation;
- every queue mutation requiring `edit:queue` and no queue command requiring
  `delete:queue`;
- queue clear/removal annotations reporting `destructiveHint=false`;
- removal of the queue-delete config entry, constant, tag, strings, and public
  permission counts;
- deterministic generated schemas under FastMCP 3.4.5;
- an in-process client without an elicitation handler, representing Codex CLI.

Regression tests must prove that disabling confirmations cannot bypass bearer
authentication, MA scopes, risk gates, permission tags, target filters, secret
write guards, flow-category guards, or the second authorization pass.

Verification uses the canonical Music Assistant `dev` source slice in its Linux
virtual environment, followed by Ruff, formatting, mypy, pre-commit, and the
upstream rewrite checks.

## Acceptance criteria

1. A client without elicitation can execute authorized standard write commands.
2. System and impersonated calls fail closed for such a client while
   `require_system_confirmation` is enabled.
3. Disabling `require_system_confirmation` permits authorized system and
   impersonated calls without elicitation.
4. Disabling `require_confirmation` suppresses all standard prompts.
5. Queue clear, remove, move, and reorder operations require only `edit_queue`
   and are not marked destructive.
6. No runtime or configuration reference to `delete_queue` remains.
7. All authorization and post-confirmation revalidation tests continue to pass
   in every confirmation mode.
8. The provider installs and passes its canonical suite with FastMCP 3.4.5.
