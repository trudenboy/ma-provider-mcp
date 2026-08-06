# Advanced-only Custom policy fields

## Problem

The default and per-token policy selectors must remain available in the normal
provider settings view. Their 26 capability mode fields are specialist controls,
however, and currently become visible whenever `Custom` is selected. This makes
the standard settings view unnecessarily large and exposes low-level policy
details to users who have not enabled Advanced mode.

## Design

Every capability entry returned by `config._custom_matrix()` will set
`advanced=True` while retaining its existing conditional fields:

- `depends_on` points to the corresponding default or token policy selector;
- `depends_on_value` remains `Custom`.

The Music Assistant frontend therefore applies both independent visibility
conditions. A capability field is shown only when Advanced mode is enabled and
its owning selector is set to `Custom`.

The default and per-token selectors remain non-advanced. Music Assistant's native
translation mechanism owns all selector UI text: the default selector uses its
structural `policy_default` key, while dynamic selectors use the stable
`policy_token` translation key and pass the token name through
`translation_params`. Both translation entries define the profile option titles.
The Custom option therefore keeps the stored value `Custom` but renders as
`Custom (Advanced mode required)`, and selector descriptions explain where its
capability settings appear.

## Configuration behavior

This is a presentation-only change. Configuration keys, stored values, defaults,
profile resolution, hot swapping, and the v2 policy schema remain unchanged.
Changing the visible option title does not change the value passed to or returned
by Music Assistant configuration APIs.
Hashed per-token entry keys never need matching `strings.json` records because
their labels, descriptions, and option titles resolve through `policy_token`.

Selecting `Custom` while Advanced mode is disabled does not remove existing mode
values. Previously unset Custom modes continue to resolve as `deny`. Enabling
Advanced mode reveals the stored matrix for editing. Selecting a named profile
keeps the matrix hidden even when Advanced mode is enabled.

The same behavior applies to the global default matrix, discovered MCP token
matrices, and manual-token matrices.

## Validation

Tests will verify that:

- every default and per-token Custom capability entry has `advanced=True`;
- every matrix retains the correct `depends_on` and `depends_on_value=Custom`;
- default and per-token profile selectors remain `advanced=False`;
- both selectors expose `Custom (Advanced mode required)` as the Custom option
  title while retaining `Custom` as its value;
- dynamic selectors expose `translation_key=policy_token` and pass their token
  name as the sole translation parameter instead of embedding UI text;
- selector labels, descriptions, and profile option titles live in `strings.json`;
- all 26 capabilities are still emitted for every matrix;
- policy parsing and stored Custom values are unchanged.

## Non-goals

- Hiding the `Custom` option itself in normal mode;
- changing Music Assistant frontend or config APIs;
- adding another visibility toggle or configuration key;
- changing capability defaults, profiles, or enforcement behavior.
