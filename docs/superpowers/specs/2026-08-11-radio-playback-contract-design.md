# Radio Playback MCP Contract Design

## Problem

The legacy MCP playback tool exposes a `radio` boolean whose name can be
misread as identifying the submitted media as a radio station. In reality it
requests a dynamic radio playlist derived from the submitted media. Passing
that flag for a Music Assistant `Radio` item reaches dynamic-track generation,
which does not support radio streams, instead of playing the station directly.

The native-command catalog introduced in provider 2.1.0 still publishes the
deprecated `radio_mode` argument for `player_queues/play_media` and adds
`radio` as a compatibility alias. Its generated schema does not carry the
native Sphinx parameter description, so an MCP model can repeat the same
mistake.

## Goals

- Publish `ma_api:player_queues/play_media` without `radio` or `radio_mode`.
- Reject either argument when submitted manually through `call_tool`.
- Preserve direct radio-station playback through the canonical `media`
  argument.
- Preserve the unrelated `uri` compatibility alias for `media`.
- Keep the solution declarative so another command can exclude an unsafe or
  deprecated argument without adding command-specific execution branches.

## Non-goals

- Retain compatibility for callers that submit `radio` or `radio_mode`.
- Change Music Assistant's native `player_queues/play_media` signature.
- Change dynamic-radio behavior for explicit `radio_playlist://` media URIs.
- Modify or publish directly to `music-assistant/server`.

## Design

`CommandProfile` gains an immutable `excluded_arguments` set. Schema
generation removes those canonical properties and any corresponding required
entry. Argument conversion checks the submitted mapping before alias
conversion and raises `ValueError` when an excluded name is present. The
existing execution boundary maps that error to the stable
`[invalid_arguments] Arguments do not match the tool schema` failure.

The `player_queues/play_media` profile excludes `radio_mode` and removes the
`radio -> radio_mode` alias. Consequently, `radio_mode` is rejected by the
profile, while `radio` is rejected by the existing strict signature parser as
an unexpected argument. Both produce the same public failure contract.

The profile keeps `uri -> media`. Calls containing a radio-station URI in
`media` or `uri` proceed unchanged to the native handler, whose default
`radio_mode=False` performs direct playback.

## Data Flow

1. Catalog compilation builds the native input schema.
2. Profile schema projection removes `radio_mode` and does not add `radio`.
3. `get_tool_schema` returns the reduced contract.
4. `call_tool` runs profile argument conversion.
5. An explicit `radio_mode` is rejected before binding; `radio` is rejected by
   strict binding.
6. A normal `media=<radio URI>` call binds and invokes the native handler
   without a dynamic-radio flag.

## Testing

Regression tests use the real catalog compiler and execution adapter:

- the published schema omits both `radio` and `radio_mode` while retaining
  `media` and `uri`;
- explicit `radio` and `radio_mode` calls fail with `invalid_arguments` and do
  not invoke the native handler;
- a radio URI submitted through `media` reaches the handler unchanged.

Tests are written and observed failing before production changes. Focused
tests run first, followed by the complete test suite and
`pre-commit run --all-files`.

## Release Notes

Add one user-facing `Fixed` entry to the next changelog section. Do not change
`VERSION`; it is maintainer-owned.
