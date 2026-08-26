# Music Assistant MCP Server

The provider lets an MCP client discover and invoke Music Assistant's live
command catalog under a per-token capability policy.

## Language

**Catalog**:
The live set of Music Assistant commands an MCP client may discover and invoke.
_Avoid_: tool list, API surface, dynamic API

**Catalog generation**:
One compiled snapshot of the live command registry together with the
request-filtered view of that snapshot.
_Avoid_: catalog snapshot, catalog view (as separate concepts)

**Meta-tools**:
The three tools a client always sees: search the catalog, inspect one command
schema, and invoke one command.
_Avoid_: discovery tools, BM25 tools

**Capability**:
One named permission that gates catalog visibility and command execution.
_Avoid_: scope, permission bit, role

**Capability policy**:
The immutable assignment of deny, confirm, or allow to every capability for one
token.
_Avoid_: permission profile (except as a named starting template), ACL

**Safe queries**:
The default restrictive capability policy. Stored `Read-only` selections resolve
to this name.
_Avoid_: Read-only

**Command authorization**:
The decision that one command invocation may proceed for this request identity,
including any required confirmation.
_Avoid_: policy check, preflight (as the whole decision)

**Request identity**:
The sealed binding of bearer token, Music Assistant user, and token id for one
request.
_Avoid_: auth context, session, current user

**Token identity**:
The non-secret binding of a bearer to a Music Assistant user and token id,
retained across requests.
_Avoid_: token fingerprint, client id (as the whole binding)

**Collection visibility**:
Which rows of a listing the current user is allowed to see, given their player
and music-provider filters.
_Avoid_: target filter (that term is the input-argument half only)

**Response budget**:
The size and depth limit applied to anything returned to an MCP client.
_Avoid_: payload cap, serializer bound (as separate limits)

**Connect Wizard**:
The onboarding page that mints a per-client token and shows connection methods.
_Avoid_: setup page, pairing UI
