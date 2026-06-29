---
id: "0013"
title: "Expose queue insert indices for agent ergonomics"
size: S
status: inprogress
priority: P1
effort_minutes: 15
feature_id:
---

## Problem Statement

Agents calling ``queue_add_to_queue`` with an ``index`` cannot see absolute row
positions or the minimum insertable index. They guess indices from stale queue
snapshots and hit ToolErrors when playback advances the buffered region beyond
``current_index``.

## Solution Summary

Extend ``get_active_queue`` / ``QueueBrief`` with ``next_insertable_index``,
``index_in_buffer``, ``items_start_index``, and per-item ``index``. Improve
``add_to_queue`` errors to point agents at ``get_active_queue`` fields.

## Acceptance Criteria

1. ``QueueItemBrief`` includes absolute ``index`` for each materialised row.
2. ``QueueBrief`` exposes ``index_in_buffer``, ``next_insertable_index``, and
   ``items_start_index``.
3. ``get_active_queue`` docstring explains the index fields and optional
   ``items_from_current`` lookahead window.
4. ``add_to_queue`` ToolError for invalid ``index`` includes ``current_index``,
   ``index_in_buffer``, and guidance to use ``next_insertable_index``.
5. ``items_from_current=True`` fetches items from ``current_index`` with correct
   ``items_start_index`` and per-item ``index`` values.

## Test Plan

- ``tests/test_models.py`` — ``to_brief_queue`` populates index fields.
- ``tests/test_get_active_queue.py`` — tool returns new fields; ``items_from_current``
  uses offset.
- ``tests/test_add_to_queue.py`` — invalid index ToolError mentions ``index_in_buffer``.
- Manual: interleave task in OpenCode sandbox reads ``next_insertable_index`` before
  index inserts.
