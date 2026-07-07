---
id: "0019"
title: "Log pattern mining: message templates, time histograms, co-occurrence"
size: M
status: todo
priority: P2
effort_minutes: 20
feature_id:
---

## Problem Statement

Finding regularities in the MA log is currently the LLM's job: it must pull
raw records into its context and eyeball them. There is no way to see the
log's shape — which message templates dominate, when error bursts happened,
or what consistently co-occurs with a given failure — without spending
thousands of tokens on raw lines. Dedicated log-platform MCP servers (Loki
`patterns`, CloudWatch `analyze_log_group`, Datadog `analyze_logs`) all ship
aggregate-analysis tools for exactly this reason.

## Solution Summary

Three aggregate views over the existing windowed record scan. (1) A new
`debug_log_patterns` tool masks volatile fragments (numbers, UUIDs, URIs,
quoted strings) and groups records into templates, returning count, level,
first/last seen and one example per template. (2) `debug_log_stats` gains a
`bucket_seconds` parameter returning per-level counts over time buckets, so
bursts are visible in one call. (3) A new `debug_correlate` tool takes an
anchor (a search regex or an event type), finds its occurrences, collects
log/event neighbours within ±N seconds of each, and reports which
templates/components appear near the anchor significantly more often than
their baseline frequency.

## Acceptance Criteria

1. `debug_log_patterns(window)` groups records into masked templates;
   each row reports `template`, `count`, `level`, `first_seen`, `last_seen`
   and one raw `example`, sorted by count; the row count is capped and the
   cap is reported.
2. Masking collapses numbers, hex ids/UUIDs, MA URIs and quoted strings so
   that two records differing only in those fragments share one template.
3. `debug_log_stats(bucket_seconds=N)` adds a `buckets` list with
   `bucket_start` and per-level counts; without the parameter the result is
   unchanged (no schema bloat for the common call).
4. `debug_correlate(anchor_search=... | anchor_event_type=...,
   window_seconds)` returns, for the anchor's occurrences in the queried
   window: occurrence count, and the top co-occurring templates/components
   with their near-anchor count, baseline count and a lift ratio.
5. Anchors with zero occurrences return an empty result with a clear note,
   not an error; conflicting anchor params are rejected.
6. All three run within the existing scan/response budgets, off the event
   loop, over the same absolute-window vocabulary as spec 0018.

## Test Plan

- Template masking table-driven test: numbers/UUID/URI/quoted variants of one
  message collapse to a single template; distinct messages stay distinct.
- Patterns: synthetic log with known template frequencies returns correct
  counts/first/last; cap honoured and reported.
- Histogram: records spread over known minutes produce expected buckets;
  omitted `bucket_seconds` leaves the result shape unchanged (snapshot).
- Correlate: fixture where template B precedes anchor A in 4 of 5 cases and
  template C is uniform background — B ranks above C with lift > 1; zero-hit
  anchor returns the empty-note shape.
- E2E for each tool via the in-memory MCP client.

## Sequence Diagram

```mermaid
sequenceDiagram
    participant LLM as MCP client
    participant Stats as debug_log_stats
    participant Pat as debug_log_patterns
    participant Corr as debug_correlate

    LLM->>Stats: since=..., bucket_seconds=60
    Stats-->>LLM: level histogram (burst at 14:03)
    LLM->>Pat: around=14:03, window=120
    Pat-->>LLM: 14 templates; "buffer underrun on {player}" x37
    LLM->>Corr: anchor_search="buffer underrun", window_seconds=5
    Corr-->>LLM: airplay reconnect template: near=34, baseline=41, lift=8.2
```
