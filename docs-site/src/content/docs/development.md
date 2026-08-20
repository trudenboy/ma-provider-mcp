---
title: Dev Environment
description: Setting up the development environment for FastMCP Server provider
---


## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- ffmpeg 6.1+ (for MA integration tests)
  - macOS: `brew install ffmpeg`
  - Ubuntu: `sudo apt-get install ffmpeg`
- Fork of [trudenboy/ma-server](https://github.com/trudenboy/ma-server) (for dev server)

## Setup

```bash
./scripts/setup.sh
```

Re-run after `git pull` — MA model versions may change.

## Running Tests

```bash
# Unit tests only (no MA server needed)
uv run pytest tests/ -m "not integration"

# Full test suite
uv run pytest tests/

# With coverage report
uv run pytest tests/ --cov=provider/ --cov-report=html
```

## Branch Naming

```
feature/<description>    # new features
fix/<description>        # bug fixes
chore/<description>      # maintenance
```

## Feature Branch Lifecycle

```bash
git checkout dev && git pull
git checkout -b feature/my-feature

# develop + test
uv run pytest tests/
pre-commit run --all-files

# PR: feature/* → dev
git push origin feature/my-feature
gh pr create --base dev
```

## Dev Server

```bash
./scripts/dev-server.sh
# UI: http://localhost:8095
```

## Conventional Commits

```
feat: add feature X
fix: fix bug Y
chore: update dependencies
test: add test for Z
```

## Release Process

1. Bump version in `VERSION` file (e.g. `1.2.0` or `1.2.0b1`)
2. Push to `dev` — pipeline auto-tags and releases
3. Manual fallback: Actions → Release → Run workflow → enter version

## Shared Workspace (multi-provider)

For simultaneous development of multiple providers with a shared MA server:

```bash
# From the ma-provider-tools repository:
python3 scripts/dev-workspace.py init --dir ~/ma-workspace --all

# Add a specific provider to an existing workspace:
python3 scripts/dev-workspace.py add fastmcp_server

# Connect this repository to a workspace:
./scripts/setup.sh --workspace ~/ma-workspace

# Update everything to latest:
python3 scripts/dev-workspace.py update --dir ~/ma-workspace

# Start MA server:
python3 scripts/dev-workspace.py run --dir ~/ma-workspace

# Workspace status:
python3 scripts/dev-workspace.py status --dir ~/ma-workspace
```

The workspace uses a single `trudenboy/ma-server` fork and shared `.venv`.
Each provider is connected via symlink into `ma-server/music_assistant/providers/`.
