# Security Policy

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Use GitHub's built-in [Private Vulnerability Reporting](../../security/advisories/new) to report security issues confidentially.

This ensures the issue can be assessed and a fix prepared before any public disclosure.

### What to include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fix (optional)

We aim to acknowledge reports within 72 hours and provide a fix timeline within 7 days.

## Permissions & Confirmations v2

The secure default is the `Read-only` profile. Policy is resolved by the exact Music
Assistant token ID, never by user ID, token name, bearer hash, or client display name.
Music Assistant authentication, enabled-user state, scopes, and target filters remain
upper bounds even when a capability is configured as `Allow`.

`Confirm` grants are scoped to one dispatcher task and one command invocation. They
are revalidated after elicitation and are never cached. Clients without elicitation
must not be granted a broad profile merely to avoid prompts; set a narrowly selected
capability to `Allow` only after reviewing the command access it enables.

Provider audit records contain fixed authorization fields and controlled outcomes.
They intentionally exclude raw bearer tokens, internal bearer fingerprints, submitted
arguments and secret values, unmasked secure configuration, and exception text. The
debug health summary exposes only aggregate token-resolution failures; it never lists
token IDs or fingerprints.

After upgrading from v1, old permission booleans, `dynamic_api_*`, and
`require_confirmation` values are ignored. Review the v2 default and per-token
overrides before granting mutation, debug, configuration, or system capabilities.
