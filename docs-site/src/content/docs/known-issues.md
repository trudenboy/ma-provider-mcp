---
title: Known Issues
---

# Known Issues

## Client cannot confirm an operation

**Symptoms:** A command fails with an error naming a capability and suggesting `Allow`
or an elicitation-capable client.

**Cause:** The token's effective mode is `Confirm`, but the MCP client does not support
elicitation.

**Fix:** Prefer an elicitation-capable client. Otherwise, review the requested access
and set only that capability for that token to `Allow`. Confirm-mode resource reads
remain unavailable because resources cannot safely elicit.

## Commands disappear after upgrading to v2

**Symptoms:** Only query commands are visible after a version 2 upgrade.

**Cause:** V1 permission booleans, `dynamic_api_*`, and `require_confirmation` are
ignored. Missing v2 policy configuration resolves to `Read-only`.

**Fix:** Select a v2 default profile and configure any per-token overrides. Do not
restore the old keys; they have no effect.

## Token override does not follow a replacement token

**Symptoms:** A newly minted token uses the default profile instead of a revoked
token's override.

**Cause:** Overrides are keyed by exact Music Assistant token ID so replacement
credentials cannot inherit prior authority.

**Fix:** Add an explicit override for the new token after verifying its owner and use.
