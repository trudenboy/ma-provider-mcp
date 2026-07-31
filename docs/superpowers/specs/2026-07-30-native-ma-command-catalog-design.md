# Native Music Assistant Command Catalog Design

Date: 2026-07-30

## Status

Approved in conversation. This document replaces the `mcp_api:*` recipe portion of
`specs/done/0026-dynamic-ma-api-catalog.md`. The three-meta-tool discovery model from
that specification remains in force.

## Problem

The provider currently has two execution surfaces:

1. Music Assistant commands discovered from `mass.command_handlers` and exposed as
   `ma_api:*`.
2. Hand-written FastMCP tool subservers mounted under namespaces such as `library`,
   `queue`, `players`, `config`, and `debug`, then re-ingested as `mcp_api:*`
   recipes.

The second surface duplicates Music Assistant behavior, creates a parallel schema,
authorization, annotation, and lifecycle system, and allows native commands to
bypass safety behavior implemented only by recipes. It also contributes to several
confirmed defects:

- Music Assistant dataclasses containing `UniqueList` fail during recursive
  `dataclasses.asdict()` conversion. This affects real tracks, albums, players, and
  related results.
- Functions accepting `**kwargs` produce a fictitious required `kwargs` input and
  still fail invocation. Seven `music/*/library_items` commands are affected.
- Direct `player_queues/delete_item` and `player_queues/clear` calls are classified
  as control operations and bypass destructive confirmation.
- System sensitivity is incorrectly conflated with MCP behavior annotations, making
  read-only diagnostics appear destructive.
- Unknown result types are advertised as strings even when they are collections or
  Music Assistant models.
- Discovery repeatedly reconstructs virtual tools and BM25 documents. The first
  concurrent searches took about 60 seconds in the test environment, while warm
  searches took about 0.7 seconds.
- Empty or low-context upstream exceptions produce poor MCP diagnostics.

## Goals

- Expose one unified command catalog backed by Music Assistant's runtime command
  registry.
- Keep only `search_tools`, `get_tool_schema`, and `call_tool` in MCP `tools/list`.
- Remove hand-written FastMCP tool subservers and `mcp_api:*` recipes without losing
  required capabilities.
- Prefer native Music Assistant commands. Add provider-owned commands only for
  semantics Music Assistant does not already provide.
- Preserve MCP resources, prompts, authentication, authorization, confirmation,
  bounded output, compact projections, and legacy discovery hints.
- Fix serialization, signature compilation, schema accuracy, policy classification,
  error quality, and discovery latency.
- Verify real track, album, player, and queue behavior against the Docker test
  instance.

## Non-goals

- Changing Music Assistant's internal queue auto-fill behavior.
- Reimplementing native Music Assistant commands behind provider wrappers.
- Keeping old curated tool names executable.
- Exposing transport-bound commands such as dashboard registration.
- Building a second provider-specific dispatcher or public API registry.
- Changing the MCP resource or prompt surface except where imports must move after
  removal of the tool subservers.

## Decision

FastMCP remains the MCP transport and hosts the three meta-tools, existing resources,
and existing prompts. It no longer hosts domain-specific tool subservers.

The catalog reads only `mass.command_handlers`:

- Native Music Assistant commands appear as `ma_api:<command>`.
- A small number of provider-owned extensions, when needed, register through
  `mass.register_api_command("fastmcp/...", handler, ...)` and therefore appear by
  the same mechanism as `ma_api:fastmcp/...`.
- There is no `mcp_api:*` source kind, recipe registry, or recipe dispatcher.

Provider-extension handlers are not a separate runtime mechanism. They are ordinary
Music Assistant command handlers owned by the provider lifecycle. A separate module
or `provider/commands/` package may be used only to keep `provider.py` focused and to
make non-trivial handlers independently testable.

An extension command is allowed only when at least one of these conditions holds:

- the operation must enforce an atomic server-side invariant;
- a batch operation needs one verified acknowledgement;
- the result aggregates provider state not exposed by native commands;
- a safe operation cannot be expressed as a declarative profile over one native
  command.

Wrapping an existing Music Assistant command for naming, projection, argument
conversion, or search convenience is explicitly prohibited. Those concerns belong
in declarative command profiles.

## Architecture

```text
MCP client
   |
   | tools/list: search_tools, get_tool_schema, call_tool
   v
Meta discovery and invocation
   |
   +-- catalog descriptors and search index
   +-- CommandPolicy / CommandProfile overlay
   +-- argument compiler and binder
   +-- response serializer and limiter
   |
   v
mass.command_handlers
   |
   +-- native Music Assistant commands
   +-- rare provider-owned fastmcp/* commands
```

The command registry remains the source of truth. Profiles may enrich a command but
must not create an independently executable catalog entry.

## Component Boundaries

### Catalog adapter

The dynamic adapter enumerates the live Music Assistant registry, excludes denied
transport commands, compiles stable descriptors, applies profiles and policies, and
filters descriptors for the current caller.

`CatalogEntry` no longer has a recipe binding or source kind. It references exactly
one Music Assistant command and its live handler metadata.

The following concepts are removed:

- `CURATED_RECIPE_SOURCES`
- `CURATED_RECIPE_SCOPES`
- `RecipeBinding`
- `ingest_curated()`
- FastMCP-mounted domain tool servers used only for the tool surface

### Command profiles and policy

Profiles are declarative metadata keyed by canonical Music Assistant command. They
may define:

- search aliases and legacy terminology;
- argument aliases or converters;
- compact output projections;
- display descriptions;
- behavioral MCP annotations;
- explicit risk and confirmation overrides.

Profiles do not execute business logic and do not combine arbitrary commands.

`CommandPolicy` is evaluated independently from the schema and from MCP annotations.
It carries the command's risk class, required gate, confirmation requirement, and
any provider/player visibility constraints.

### Provider extensions

Only functionality that passes the extension-command criteria is registered under
`fastmcp/*`. The implemented set is exactly eight commands: one server-side safe
queue batch-removal command plus bounded log-tail, log-statistics, recent-event,
event-buffer-statistics, health, route, and package diagnostics. Each command was
checked against the target Music Assistant registry; native commands remain the
only path whenever MA already provides equivalent behavior.

Extension handlers are plain typed Python callables with no FastMCP decorators or
FastMCP request context. They return Music Assistant models or JSON-compatible
values and rely on the common adapter for serialization and response limits.

Native `config/*` commands retain the existing Config permission toggles. Secret
writes additionally require `config:write:secret`, while destructive native queue
commands and `fastmcp/queue/remove_items_safe` retain mandatory elicitation. The
resource and prompt surfaces are unchanged by the tool migration.

### FastMCP server

The root server registers the three meta-tools and preserves current resources and
prompts. It does not mount `build_library_server`, `build_queue_server`, or any other
domain-specific subserver. Existing shared model and helper code may remain after
tool builders are removed when it is used by resources, prompts, profiles, or
extension commands.

## Functional Migration

Native commands are used directly for common operations:

| Existing behavior | Unified replacement |
| --- | --- |
| Player summaries and lookup | `players/all`, `players/get` |
| Active queue and queue items | `player_queues/get_active_queue`, `player_queues/items` |
| Add or play media in a queue | profile over `player_queues/play_media` |
| Remove, move, or clear queue rows | native queue commands with corrected policy; an extension only for additional server-side safety or batch acknowledgement |
| Search, browse, track, and album details | native `music/*` commands |
| Playlist operations | native music and playlist commands |
| Player playback and volume | native player and queue commands |
| Music Assistant configuration | native config commands where available |
| Provider-only diagnostics or actions | `fastmcp/*` only when no native equivalent exists |

Compact output, friendly aliases, and argument normalization move to profiles rather
than wrappers. The parity matrix from the existing dynamic-catalog implementation is
updated so every retired custom tool resolves to a native command, a justified
extension command, a resource/prompt, or an explicit retirement reason.

## Registration Lifecycle

Provider-owned commands are registered before the MCP runtime starts. Each
`mass.register_api_command()` call returns an unregister callback, which the provider
stores as part of its active runtime state.

Startup follows transactional semantics:

1. Validate command registry compatibility.
2. Register the required `fastmcp/*` commands once.
3. Start the MCP runtime and routes.
4. If any later startup step fails, stop partial MCP state and invoke all new
   unregister callbacks in reverse order.

A runtime-only MCP restart reuses the existing provider registrations and must not
create duplicates. Provider unload first stops MCP request handling and then invokes
all extension unregister callbacks. Repeated stop/unload calls are idempotent.

The target installed Music Assistant version exposes authentication and role
parameters on `register_api_command()` but not the granular `required_scope`
parameter shown in newer development documentation. Registration therefore uses
the capabilities available at runtime, while the provider policy layer retains the
granular scope and filter checks. Compatibility detection must not assume one fixed
Music Assistant signature.

## Authorization and Safety

Authorization is layered:

1. Music Assistant enforces command authentication and any role metadata exposed by
   the installed version.
2. The adapter evaluates the current user, disabled-user state, required scopes,
   provider filters, player filters, and impersonation constraints.
3. `CommandPolicy` applies configured read/control/write/system gates and mandatory
   confirmation rules.

Policy classification order is deterministic:

1. exact explicit override;
2. family-level explicit override;
3. known destructive semantics such as delete, clear, remove, revoke, or reset;
4. Music Assistant role/scope metadata;
5. conservative `system` fallback for unknown commands.

`player_queues/delete_item` and `player_queues/clear` are destructive writes and
cannot execute without confirmation. Deleting the current item may trigger Music
Assistant queue auto-fill; the provider prevents accidental bypass and tests the
condition but does not alter upstream queue behavior.

Risk and MCP behavior annotations are independent. For example, a diagnostic health
command may require the system gate while still advertising `readOnlyHint=true`,
`destructiveHint=false`, and `idempotentHint=true`.

Cached catalog state never contains caller authorization decisions. Base descriptors
and search documents may be shared, but visibility and authorization are evaluated
against the live request context on every discovery and invocation request.

## Argument and Schema Compilation

The adapter compiles a handler signature into both an input schema and an invocation
binder.

- Named positional and keyword parameters retain their current annotations,
  defaults, enum handling, unions, and collection schemas.
- `**kwargs` is not emitted as a required property named `kwargs`.
- When arbitrary keyword arguments are intentionally supported, the schema uses
  `additionalProperties` and the binder validates and expands those values into the
  target call.
- When extras are not intentionally exposed, the schema remains closed and the
  binder rejects unknown keys.
- `*args` cannot be represented safely by the meta-tool object schema and is marked
  incompatible rather than generating a misleading callable tool.
- The signature passed through Music Assistant argument parsing excludes variadic
  placeholder parameters that the binder handles itself.

This fixes the seven confirmed `music/{albums,artists,audiobooks,genres,playlists,
podcasts,tracks}/library_items` failures while retaining strict input validation.

Output schemas must describe known types accurately. If the adapter cannot derive a
safe JSON Schema for a Python type, it emits an unconstrained schema with
`x-python-type` metadata instead of claiming the value is a string.

## Serialization and Response Processing

Results use one recursive serializer with this precedence:

1. JSON primitives and `None`;
2. objects exposing `to_dict()`;
3. objects exposing `model_dump(mode="json")`;
4. dataclasses converted field by field;
5. mappings;
6. ordered sequences;
7. sets and frozensets converted using a deterministic ordering;
8. explicitly supported scalar adapters such as enums, paths, dates, and UUIDs;
9. a safe final representation for unsupported objects.

`dataclasses.asdict()` is not used because it reconstructs nested collection types
and fails when Music Assistant's `UniqueList` contains dataclasses that become
unhashable dictionaries.

The complete response flow is:

```text
bind and validate arguments
  -> invoke live MA handler
  -> recursively serialize
  -> apply optional compact projection
  -> enforce item, byte, and depth limits
  -> return the standard dynamic response envelope
```

The existing compact/full bounds remain unchanged unless measurements show that a
specific native command needs a stricter profile.

## Error Handling

Errors returned through `call_tool` include the canonical command and preserve an
actionable Music Assistant message. If an exception has an empty string
representation, the adapter supplies its class name and command rather than
returning an empty failure.

Validation errors identify the rejected field or unsupported signature. Policy
errors distinguish hidden, disabled, unauthorized, confirmation-required, and
unsupported transport commands without leaking credentials, secret configuration,
or raw internal objects.

Provider extension handlers raise domain-specific Music Assistant exceptions when
available. They do not catch and flatten exceptions merely to manufacture a success
envelope.

## Discovery Cache

Catalog construction is split into immutable base work and request-specific policy
work.

The base cache contains compiled descriptors, virtual discovery documents, and BM25
tokens. Its fingerprint includes registry command names and handler identities plus
the active profile/policy revision. Registry registration or unregistration changes
the fingerprint and becomes visible without restarting MCP.

An `asyncio.Lock` provides single-flight construction so concurrent cold searches do
not rebuild the same catalog. The lock guards only cache construction; authorization
filtering and execution do not serialize unrelated requests.

Success targets in the reference Docker environment are:

- no duplicate base-index construction for concurrent calls with one fingerprint;
- immediate cache invalidation after command registration or unregistration;
- warmed `search_tools` response below one second;
- cold construction below five seconds under the existing approximately 299-command
  catalog.

The implementation records or exposes enough timing information in tests to
distinguish registry enumeration, schema compilation, indexing, and request-time
visibility filtering.

## Legacy Behavior

`mcp_api:*` names and old curated tool names are not executable. `call_tool` returns
a concise migration hint when `LEGACY_MIGRATIONS` has an unambiguous replacement.
Search aliases may match legacy terminology but return only canonical `ma_api:*`
names.

The legacy map points either to a native command or to a justified
`ma_api:fastmcp/*` extension. It must not silently redirect execution because a
redirect could change confirmation, arguments, or side effects.

## Testing Strategy

### Unit tests

- Serialize real-shaped Track, Album, Player, nested provider mappings,
  `UniqueList`, set, and frozenset values.
- Verify serializer precedence and deterministic output.
- Compile normal, defaulted, enum, union, `**kwargs`, and unsupported `*args`
  signatures.
- Verify the seven affected `library_items` schemas and invocation binders.
- Verify accurate output-schema fallback behavior.
- Normalize empty and actionable upstream exceptions.
- Audit destructive queue commands and independent annotation values.
- Verify exact, family, metadata-derived, and conservative policy precedence.

### Catalog and lifecycle tests

- Confirm `tools/list` exposes only the three meta-tools.
- Confirm the catalog contains only registry-backed `ma_api:*` entries.
- Register and unregister a fake command and observe immediate discovery changes.
- Exercise concurrent cold searches and assert one index build.
- Verify cached descriptors do not leak visibility between users.
- Verify provider setup, MCP-only restart, startup rollback, unload, and repeated
  unload without duplicate or leaked extension registrations.
- Verify every removed custom tool has an explicit parity-matrix outcome.
- Verify retired names produce hints but cannot execute.

### Docker integration tests

- Discover and invoke real player commands.
- Search real tracks and albums, retrieve details, and enumerate album tracks without
  serialization failures.
- Exercise the affected library-list commands without a fictitious `kwargs` field.
- Run a reversible queue lifecycle using a non-current test item: capture state, add,
  inspect, move when safe, remove with confirmation, and verify final state.
- Assert direct clear/delete commands cannot bypass destructive confirmation.
- Exercise provider diagnostics with read-only annotations and the system gate.
- Measure cold and warm discovery latency.

The queue test must not remove the current, played, or buffered row and must leave the
isolated test queue in its captured state.

### Repository gates

Run the full pytest suite, Ruff, mypy, pre-commit, and the existing upstream-copy or
compatibility checks defined by the repository. A full catalog smoke pass validates
every schema and safely route-tests non-read commands without executing their side
effects.

## Acceptance Criteria

1. MCP `tools/list` exposes only `search_tools`, `get_tool_schema`, and `call_tool`;
   current resources and prompts remain available.
2. All executable catalog entries come from `mass.command_handlers` and use the
   `ma_api:*` namespace.
3. No FastMCP domain-tool subserver, `RecipeBinding`, curated recipe source map, or
   executable `mcp_api:*` entry remains.
4. Every retired custom tool has a tested native mapping, justified extension,
   preserved resource/prompt, or explicit retirement reason.
5. Track, Album, Player, and `UniqueList` results from the Docker instance serialize
   without error.
6. Variadic-keyword handlers expose truthful schemas and execute without a required
   `kwargs` property; unsupported positional variadics are not advertised as usable.
7. Direct queue clear and delete operations cannot execute without destructive
   confirmation.
8. Risk gates and MCP behavior annotations are independently correct, including
   read-only system diagnostics.
9. Unknown output types are not falsely represented as strings.
10. Dynamic errors always include the command and either an actionable upstream
    message or the exception type.
11. Concurrent discovery performs one base build, reacts immediately to registry
    changes, and meets the agreed Docker cold/warm latency targets.
12. Provider load, MCP restart, failed startup rollback, and unload leave no duplicate
    or leaked `fastmcp/*` registrations.
13. Real Docker tests pass for providers, tracks, albums, players, and reversible
    queue operations.
14. The full repository quality and compatibility gates pass.

## Rollout

Implementation should proceed in test-backed slices: first harden serialization and
signature binding, then separate policy from annotations, introduce shared catalog
caching, migrate custom behavior to profiles or the smallest justified extension
set, remove recipe/subserver infrastructure, and finally run the complete Docker and
repository verification matrix.

No compatibility flag keeps the old executable tool surface. Migration is a clean
cut to the unified registry, with search aliases and explicit invocation errors as
the compatibility aid.
