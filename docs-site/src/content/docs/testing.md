---
title: Testing
---

[← Development](development.md) · [← Contributing](contributing.md) · [README](../README.md)

# FastMCP Server — Testing Guide

## Quick Start

```bash
uv run pytest tests/ -v
```

With coverage report:

```bash
uv run pytest tests/ -v --cov=provider/ --cov-report=term-missing
```

## CI Pipeline

Every push and pull request triggers two parallel jobs via `test.yml`:

| Job | What it does |
|-----|-------------|
| `test-*` | Runs pytest with coverage, uploads report to Codecov |
| `lint-*` | Runs ruff, mypy, codespell, pre-commit |


Tests run against `trudenboy/ma-server@dev` (plugin-enabled fork — full CI with ruff + mypy).


## Tools

| Tool | Purpose |
|------|---------|
| `uv` | Virtual environment and dependency management |
| `Python 3.14` | Target Python version |
| `pytest` | Test framework |
| `pytest-cov` | Coverage collection |
| `Codecov` | Coverage report upload (automatic in CI) |
| `ruff` | Python linter and formatter |
| `mypy` | Static type checker |
| `codespell` | Spell-checking for source code |
| `pre-commit` | Pre-commit hook runner |

## Running Linters Locally

Run all pre-commit hooks (recommended before opening a PR):

```bash
uv run pre-commit run --all-files
```

Type checking only:

```bash
uv run mypy provider/
```

Linting only:

```bash
uv run ruff check provider/
uv run ruff format --check provider/
```

## Coverage

Coverage reports are automatically uploaded to Codecov on every CI push.
To view coverage locally:

```bash
uv run pytest tests/ --cov=provider/ --cov-report=html
open htmlcov/index.html
```

## When CI Fails

When tests or linters fail in CI, a GitHub issue is automatically created with the `incident:ci` label.
See [Incident Management](incident-management.md) for how the incident workflow operates.
