"""Development Compose runtime contract tests."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_compose_defaults_to_a_neighboring_ma_checkout() -> None:
    """The effective MA bind mount is portable across developer home directories."""
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker CLI is unavailable")
    completed = subprocess.run(  # noqa: S603 - resolved Docker executable, fixed arguments
        [docker, "compose", "-f", "docker-compose.dev.yml", "config", "--format", "json"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    config: dict[str, Any] = json.loads(completed.stdout)
    assert config["services"]["ma"]["environment"]["PYTHONPATH"] == "/ma-server"
    ma_mount = next(
        mount for mount in config["services"]["ma"]["volumes"] if mount["target"] == "/ma-server"
    )

    assert ma_mount["type"] == "bind"
    assert ma_mount["source"] == str((REPO_ROOT.parent / "ma-server").resolve())
    assert ma_mount["target"] == "/ma-server"
    assert ma_mount["read_only"] is True
