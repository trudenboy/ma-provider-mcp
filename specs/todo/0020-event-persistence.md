---
id: "0020"
title: "Optional on-disk event retention for retrospective analysis"
size: M
status: todo
priority: P2
effort_minutes: 20
feature_id:
---

## Problem Statement

The event buffer is an in-memory ring (50–5000 records) that is cleared on
every provider reload or server restart (deferred deliberately in spec
0005). At typical event rates the retention is minutes to a few hours, and a
restart — often the very thing being debugged — wipes the evidence. The
troubleshooting workflows from specs 0018/0019 (timeline, correlation,
retrospective windows) are therefore blind on the event side for any period
that predates the current process.

## Solution Summary

An opt-in, size-capped JSONL journal of events next to the MA log: when the
`event_persistence` debug toggle is enabled, the event buffer's subscriber
also appends one JSON line per event to
`<storage_path>/mcp_events.jsonl`, rotating by size with a bounded number of
generations. Windowed event queries (`debug_recent_events`,
`debug_timeline`, `debug_correlate`) transparently read from disk when the
requested window extends beyond the in-memory buffer. Writes are batched and
never block MA's event loop; the journal is subject to the same redaction as
log output when read back.

## Acceptance Criteria

1. With the toggle off (default), behaviour and disk usage are unchanged —
   no journal file is created.
2. With the toggle on, events are appended as JSONL with timestamp, type,
   object_id and the size-capped data digest; the writer batches appends and
   runs off the event loop.
3. The journal rotates by size (cap + generation count configurable in code,
   not exposed as user settings) and total disk use never exceeds the cap.
4. A windowed event query older than the in-memory buffer returns records
   from the journal, merged seamlessly with in-memory ones and de-duplicated
   at the boundary.
5. Journal files live only under `storage_path`, are covered by the same
   path-allowlist discipline as log files, and their content passes the
   redactor when returned to clients.
6. A corrupt or truncated journal line is skipped with a counted warning in
   the result, never a tool error.

## Test Plan

- Toggle off: no file created after event bursts (regression pin).
- Toggle on: synthetic events land as parseable JSONL; batch flush verified
  off-loop (thread assertion like the tail_log test).
- Rotation: write events until the size cap trips; generation count and total
  size stay bounded.
- Retrospective read: query a window predating a simulated restart (fresh
  buffer, existing journal) returns journal records; overlap window returns
  no duplicates.
- Corrupt-line fixture: skipped with counter, remaining records returned.
- E2E: `debug_recent_events(since=...)` spanning the restart boundary.
