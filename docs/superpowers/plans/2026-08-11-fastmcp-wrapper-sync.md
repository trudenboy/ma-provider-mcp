# FastMCP Wrapper Synchronization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ma-provider-tools` durably render FastMCP's complete runtime dependencies and checked-out Music Assistant source-overlay Docker environment without changing other providers.

**Architecture:** Add one opt-in registry capability, `ma_source_overlay`, and thread it through both renderer contexts. Jinja templates branch on that capability: FastMCP uses its source-overlay contract, while every existing provider keeps generic site-packages symlink mode.

**Tech Stack:** Python 3, PyYAML, JSON Schema 2020-12, Jinja2, pytest, Docker Compose YAML, POSIX shell templates.

## Global Constraints

- Work in `trudenboy/ma-provider-tools`, never in generated provider files.
- Use feature branch `fix/fastmcp-wrapper-sync` from current `main`.
- FastMCP runtime dependencies are exactly `fastmcp==3.4.6` and `prefab-ui==0.20.2`.
- `ma_source_overlay` defaults to `false`; only `fastmcp_server` opts in.
- Generic providers retain the current `/tmp/provider` symlink behavior.
- Rendered FastMCP Compose uses `${MA_SERVER_ROOT:-../ma-server}` and read-only source mounts.
- Tests assert rendered behavior from controlled inputs rather than inspecting Jinja source.
- Do not merge or distribute until the tools PR is green and the user selects integration.

---

### Task 1: Restore the complete FastMCP runtime dependency contract

**Files:**
- Modify: `providers.yml:411-424`
- Modify: `tests/test_render_for_provider.py`

**Interfaces:**
- Consumes: `scripts/render_for_provider.py --domain fastmcp_server ... pyproject.toml.j2`.
- Produces: a rendered `[project].dependencies` list containing exactly the two FastMCP manifest requirements.

- [ ] **Step 1: Add a failing rendered-output test**

Extend the test helper so callers select templates, then parse the rendered TOML:

```python
import tomllib


def _run(domain: str, out_dir: Path, *templates: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--domain",
            domain,
            "--out-dir",
            str(out_dir),
            *templates,
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def test_fastmcp_runtime_dependencies_match_its_manifest(tmp_path: Path) -> None:
    """A clean FastMCP environment installs every provider runtime dependency."""
    result = _run("fastmcp_server", tmp_path, "pyproject.toml.j2")
    assert result.returncode == 0, result.stderr
    project = tomllib.loads((tmp_path / "pyproject.toml").read_text())

    assert project["project"]["dependencies"] == [
        "fastmcp==3.4.6",
        "prefab-ui==0.20.2",
    ]
```

Update the two existing helper calls to pass
`"scripts/check_method_order.py.j2"` explicitly.

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
python3 -m pytest tests/test_render_for_provider.py::test_fastmcp_runtime_dependencies_match_its_manifest -q
```

Expected: FAIL because the rendered list is only `fastmcp>=3.2,<4.0`.

- [ ] **Step 3: Correct the registry entry**

Replace the FastMCP dependency list in `providers.yml` with:

```yaml
    runtime_dependencies:
      - "fastmcp==3.4.6"
      - "prefab-ui==0.20.2"
```

- [ ] **Step 4: Verify GREEN and registry validity**

Run:

```bash
python3 -m pytest tests/test_render_for_provider.py -q
python3 scripts/validate_providers_yml.py
```

Expected: all tests pass and the registry validator exits 0.

- [ ] **Step 5: Commit the dependency correction**

```bash
git add providers.yml tests/test_render_for_provider.py
git commit -m "fix: restore FastMCP runtime dependencies"
```

---

### Task 2: Add an opt-in checked-out MA source overlay

**Files:**
- Modify: `schemas/providers.schema.json:78-110`
- Modify: `providers.yml:411-425`
- Modify: `scripts/render_for_provider.py:35-60`
- Modify: `scripts/distribute.py:270-295`
- Modify: `wrappers/docker-compose.dev.yml.j2`
- Modify: `wrappers/scripts/docker-init.sh.j2`
- Modify: `tests/test_render_for_provider.py`

**Interfaces:**
- Consumes: optional registry boolean `ma_source_overlay`.
- Produces: renderer context key `ma_source_overlay: bool`; FastMCP Compose/source-init output; unchanged generic output for providers without the flag.

- [ ] **Step 1: Add failing behavior tests for both rendering branches**

Add YAML parsing plus these tests:

```python
import yaml


def _rendered_compose(domain: str, tmp_path: Path) -> dict:
    result = _run(domain, tmp_path, "docker-compose.dev.yml.j2")
    assert result.returncode == 0, result.stderr
    return yaml.safe_load((tmp_path / "docker-compose.dev.yml").read_text())


def test_fastmcp_compose_mounts_neighboring_ma_source(tmp_path: Path) -> None:
    """FastMCP integration tests execute the checked-out MA source and provider."""
    service = _rendered_compose("fastmcp_server", tmp_path)["services"]["ma"]

    assert service["environment"] == {"PYTHONPATH": "/ma-server"}
    assert "${MA_SERVER_ROOT:-../ma-server}:/ma-server:ro" in service["volumes"]
    assert (
        "./provider/:/ma-server/music_assistant/providers/fastmcp_server:ro"
        in service["volumes"]
    )
    assert "./tests/:/tmp/provider-tests:ro" in service["volumes"]
    assert "./provider/:/tmp/provider:ro" not in service["volumes"]


def test_ordinary_provider_compose_keeps_generic_overlay(tmp_path: Path) -> None:
    """The FastMCP source checkout does not become a global wrapper requirement."""
    service = _rendered_compose("yandex_music", tmp_path)["services"]["ma"]

    assert "environment" not in service
    assert "./provider/:/tmp/provider:ro" in service["volumes"]
    assert all("/ma-server" not in mount for mount in service["volumes"])


def test_fastmcp_init_validates_source_imports(tmp_path: Path) -> None:
    """FastMCP startup rejects fallback to the image's installed provider."""
    result = _run("fastmcp_server", tmp_path, "scripts/docker-init.sh.j2")
    assert result.returncode == 0, result.stderr
    script = (tmp_path / "scripts" / "docker-init.sh").read_text()

    assert "export PYTHONPATH=\"/ma-server${PYTHONPATH:+:$PYTHONPATH}\"" in script
    assert "/ma-server/music_assistant/providers/fastmcp_server/*" in script
    assert "ln -s /tmp/provider" not in script


def test_ordinary_provider_init_keeps_symlink_mode(tmp_path: Path) -> None:
    """Providers without source-overlay metadata still link into site-packages."""
    result = _run("yandex_music", tmp_path, "scripts/docker-init.sh.j2")
    assert result.returncode == 0, result.stderr
    script = (tmp_path / "scripts" / "docker-init.sh").read_text()

    assert "ln -s /tmp/provider" in script
    assert "export PYTHONPATH=\"/ma-server" not in script
```

- [ ] **Step 2: Run the four tests and verify RED**

Run:

```bash
python3 -m pytest tests/test_render_for_provider.py -k "compose or init" -q
```

Expected: FastMCP assertions fail because it still renders generic mode; the
ordinary-provider assertions pass.

- [ ] **Step 3: Define and thread the registry capability**

Add this optional property to `schemas/providers.schema.json`:

```json
"ma_source_overlay": {
  "type": "boolean",
  "description": "Mount a neighbouring MA checkout and provider tests in the Docker dev environment."
}
```

Add `ma_source_overlay: true` to the FastMCP entry. Add this exact context item
to both `build_context` in `scripts/render_for_provider.py` and the context in
`scripts/distribute.py::render_wrappers`:

```python
"ma_source_overlay": provider.get("ma_source_overlay", False),
```

- [ ] **Step 4: Implement conditional Compose rendering**

In `wrappers/docker-compose.dev.yml.j2`, preserve the common service settings
and branch only the environment and provider mounts:

```jinja2
{% if ma_source_overlay %}
    environment:
      PYTHONPATH: /ma-server
    volumes:
      - ${MA_DATA_DIR:-./.ma-data}:/data
      - ${MA_SERVER_ROOT:-../ma-server}:/ma-server:ro
      - ./{{ provider_path }}:/ma-server/music_assistant/providers/{{ domain }}:ro
      - ./tests/:/tmp/provider-tests:ro
{% else %}
    volumes:
      - ./.ma-data:/data
      - ./{{ provider_path }}:/tmp/provider:ro
{% endif %}
      - ./pyproject.toml:/tmp/pyproject.toml:ro
      - ./scripts/docker-init.sh:/init.sh:ro
```

- [ ] **Step 5: Implement conditional init rendering**

In `wrappers/scripts/docker-init.sh.j2`, put the current provider-directory
lookup/remove/symlink block under `{% if not ma_source_overlay %}`. Under the
true branch render the existing FastMCP source checks generically with
`{{ domain }}`:

```jinja2
{% if ma_source_overlay %}
export PYTHONPATH="/ma-server${PYTHONPATH:+:$PYTHONPATH}"
SOURCE_FILE=$(/app/venv/bin/python3 -c "import music_assistant; print(music_assistant.__file__)")
case "$SOURCE_FILE" in
  /ma-server/*) echo "==> MA source overlay: $SOURCE_FILE" ;;
  *) echo "ERROR: MA source overlay is inactive ($SOURCE_FILE)" >&2; exit 1 ;;
esac
{% else %}
PROVIDERS_DIR=$(/app/venv/bin/python3 -c \
    "import music_assistant.providers, os; print(os.path.dirname(music_assistant.providers.__file__))")
rm -rf "${PROVIDERS_DIR}/{{ domain }}"
ln -s /tmp/provider "${PROVIDERS_DIR}/{{ domain }}"
echo "==> Provider linked: ${PROVIDERS_DIR}/{{ domain }}"
{% endif %}
```

After dependency installation, add the provider import-origin check only in
the true branch, using
`music_assistant.providers.{{ domain }}` and expected path
`/ma-server/music_assistant/providers/{{ domain }}/*`.

- [ ] **Step 6: Verify GREEN, shell syntax, and schema**

Run:

```bash
python3 -m pytest tests/test_render_for_provider.py -q
python3 scripts/validate_providers_yml.py
tmp_dir=$(mktemp -d)
python3 scripts/render_for_provider.py --domain fastmcp_server --out-dir "$tmp_dir" scripts/docker-init.sh.j2
sh -n "$tmp_dir/scripts/docker-init.sh"
```

Expected: tests and validation pass; `sh -n` exits 0.

- [ ] **Step 7: Commit the source-overlay capability**

```bash
git add providers.yml schemas/providers.schema.json scripts/render_for_provider.py scripts/distribute.py wrappers/docker-compose.dev.yml.j2 wrappers/scripts/docker-init.sh.j2 tests/test_render_for_provider.py
git commit -m "fix: preserve FastMCP source-overlay wrappers"
```

---

### Task 3: Verify and publish the canonical tools correction

**Files:**
- Verification-only task: the worktree must remain clean after Tasks 1-2.

**Interfaces:**
- Consumes: Tasks 1-2 commits.
- Produces: a green draft PR against `trudenboy/ma-provider-tools:main` whose later distribution can safely update the provider repo.

- [ ] **Step 1: Run full tools verification**

```bash
python3 -m pytest -q
python3 scripts/validate_providers_yml.py
pre-commit run --all-files
git diff --check main...HEAD
```

Expected: every command exits 0.

- [ ] **Step 2: Inspect exact scope**

```bash
git status -sb
git diff --stat main...HEAD
git log --oneline main..HEAD
```

Expected: only registry/schema/renderer/template/tests files from Tasks 1-2.

- [ ] **Step 3: Push and create a draft PR**

Use the `github:yeet` workflow. Title:

```text
Preserve FastMCP source-overlay wrappers
```

The PR body must state the two observed regressions, RED/GREEN tests, generic
provider non-regression, and that generated provider files will arrive through
the normal distribution workflow after integration.
