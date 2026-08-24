# Code audit for 2.1.0

Reviewed on 2026-08-06 with Python 3.14 using Ruff, mypy, pytest/coverage,
Vulture (80% confidence), Radon (grade C and worse), and Bandit. Vulture and
Bandit complete without findings; the test suite enforces the import-layer,
capability, live-command classification, authorization, and transport contracts.

## Reviewed complexity findings

The grade-D findings are retained deliberately:

- `MetaDiscoveryService.discover` is the single cursor/search/schema state machine.
- `to_brief_player` normalizes several version-dependent MA player shapes without
  trusting optional attributes.
- `DynamicAPIAdapter._finalize_invocation` is the fail-closed final authorization
  state machine immediately before a handler call.
- `_bounded_json_value` is the depth, item, string, and byte-bound serializer.
- `SafeLogTail.tail` combines bounded reverse reading, decoding, and redaction.
- `health` aggregates independent, optional diagnostics and does not authorize work.

The grade-C findings are finite decision tables or defensive boundary parsers:

- discovery/policy: `_rank`, `_validate_state`, `policy_event_buffer_enabled`,
  `policy_snapshot`, `resolve_command_policy`, `_operation`,
  `_config_value_is_secure`, and `_preflight_setup_flow_submit`;
- authorization: `TagFilterMiddleware._reject_if_hidden`,
  `ResourceAuthorizer._authentication_is_valid`, `_ma_denial`,
  `authorize_extension`, and the authorization/catalog methods in `execution.py`;
- bounded conversion: `_json_value`, `_bounded_envelope`, `_load_state`,
  `_execute_action`, `to_brief_player`, and `SafeLogTail.stats`;
- protocol/lifecycle boundaries: `compute_origin_allowlist`, `_build_scope`,
  `MCPServerRuntime._start_impl`, `parse_resource_uri`,
  `handle_open_connect_action`, `remove_items_safe`, and `health`.

Splitting these functions further would separate checks from the state they guard or
turn explicit bounded decision tables into indirect dispatch. Each security-sensitive
branch is covered by tests; payload, token, URI, argument, and raw exception contents
remain outside public errors, audit events, health data, and span attributes.

## Broad exception catches

Every remaining `except Exception` is at a framework or untyped extension boundary:
MA lifecycle rollback, FastMCP/ASGI transport cleanup, provider/config lookup,
third-party model normalization, log/event decoding, or audit-safe handler wrapping.
Known local validation contracts use narrower exceptions. Boundary catches either
fail closed, return a controlled unavailable value, or perform rollback; public
surfaces never include the caught exception text.

## False positives

Bandit B105 exclusions are limited to fixed audit-category strings, capability names,
configuration-key names, and a UI label prefix. Inline comments identify every
exclusion; none of the values is credential material.
