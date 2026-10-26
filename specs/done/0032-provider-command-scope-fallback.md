---
id: "0032"
title: "Classify provider-registered commands by their Music Assistant scope"
size: S
status: done
priority: P1
effort_minutes: 20
feature_id:
---

## Problem Statement

Music Assistant providers register their own API commands at runtime, for
example `party/*`, `smart_playlists/*`, `sonic_similarity/*`,
`ambient_sounds/*`, `sendspin/*` and `yandex_station/*`. The MCP catalog
hides every one of them. The command classifier only knows a fixed list of
core command families and hard-denies anything else, so a new provider
command never reaches MCP clients until this provider is changed to name its
family. Specs 0027 and 0030 made unknown commands fail closed.

## Solution Summary

A command outside every known family is classified by the Music Assistant
scope it declares at registration. Each known scope maps to the capability
that already guards the matching core family, for example `players.control`
to `control:players` and `library.read` to `query:library`. A command
without a scope, or with a scope that has no capability mapping, still fails
closed. Known families, exact policies and the auth/dashboard hard-deny keep
priority over the scope. `yandex_station/command`, which sends free text to
Alice and can drive a whole smart home, is pinned to `system:admin` because
its declared `players.control` scope understates its reach.

## Acceptance Criteria

1. A command in an unknown family with scope `players.control` appears in
   the catalog and requires `control:players`.
2. Scopes `library.read`, `library.write`, `library.manage`, `players.read`,
   `queues.read`, `queues.control`, `providers.read`, `config.*.read`,
   `config.players.write`, `config.providers.write`, `config.providers.own`,
   `config.core.write`, `system.read` and `system.manage` each map to one
   fixed capability; a destructive verb in the command name selects the
   delete capability where the scope has one and marks the tool destructive.
3. A command in an unknown family with no scope, a `users.*` scope, `*`, or
   an unrecognised scope stays hard-denied.
4. A tuple scope is classified by its weakest member, matching how Music
   Assistant grants it; any unmapped member keeps the command hard-denied.
5. `yandex_station/command` requires `system:admin`; `yandex_station/say`
   requires `control:players` through the scope fallback.
6. Known families, exact policies and `auth/` / `dashboard/register` keep
   their current classification.

## Test Plan

- Unit tests in `tests/test_command_policy.py` for each scope mapping, the
  destructive-verb case, tuple scopes, the unmapped and unscoped deny cases,
  and the `yandex_station/command` pin.
- Update the old fail-closed test: unscoped unknown commands still fail
  closed, scoped ones now classify by scope.
- Live check on the dev stand: `search_tools("yandex_station")` and
  `search_tools("party")` return the provider commands.
