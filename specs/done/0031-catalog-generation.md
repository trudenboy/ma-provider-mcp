---
id: "0031"
title: "One catalog generation type"
size: S
status: done
priority: P1
effort_minutes: 15
feature_id:
---

## Problem Statement

A request-visible catalog and its compiled registry snapshot were two identical
bags. Understanding whether a command is visible required bouncing between
them, and the catalog resource lived in a third file that only formatted JSON.

## Solution Summary

One generation type owns fingerprint, entries, and lookup. A request view is
the same generation with a filtered entry set. The catalog resource is
registered next to the meta-tools that already own discovery.

## Acceptance Criteria

1. A request-filtered catalog shares its fingerprint with the compiled
   snapshot it came from.
2. An unauthenticated request still receives an empty view of that same
   generation.
3. `catalog://commands` still pages visible command names with `next_uri`.
4. Search, schema lookup, and `call_tool` still read the same generation.
5. The compatibility facade still re-exports the public catalog names.

## Test Plan

- Existing catalog and meta-discovery tests remain the contract.
- `test_catalog_resource_*` still pin the resource transport.
