---
title: Promotion & SEO
description: Visual presentation and SEO settings for the FastMCP Server repository
---

This document describes how the **FastMCP Server** repository's visual presentation and search-engine surface are maintained.

## What is auto-synced

Through `ma-provider-tools`:

- **`About` block** (`description`, `homepage`, `topics`) — driven by `providers.yml` (fields `github_description`, `github_topics`, `github_homepage`) and applied by `scripts/sync_repo_settings.py` + the `sync-repo-settings.yml` workflow.
- **README header block** — between markers `<!-- >>> ma-provider-tools sync (readme header) >>> -->` and `<!-- <<< ma-provider-tools sync (readme header) <<< -->`. Contains badges (CI / Release / License / Music Assistant / Stars), quick-links, and a cross-link row for related providers.
- **Docs-site landing page** (this site) — hero block reads `github_description`, followed by a topic-pill row from `github_topics` and the same badge row as the README.

Hand-edits to these blocks are **not preserved**: the next `distribute.yml` run overwrites them. To change a description or topic — open a PR in `ma-provider-tools`.

## Social preview image

GitHub does **not** expose social-preview upload via its API — this is a UI-only operation. Recommended:

1. PNG, 1280×640 px.
2. Visual content: provider icon/logo + project name + 1–2 key keywords.
3. Upload at: **Repo Settings → Social preview → Edit**.

Auto-generation via a GitHub Action is a P1 follow-up; until then, manual upload is the only path.
