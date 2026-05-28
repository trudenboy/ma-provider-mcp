"""Unit tests for SafeLogTail (path allowlist, byte cap, redactor)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from provider.debug.log_reader import SafeLogTail


def test_tail_returns_last_n_lines(tmp_log_dir: Path) -> None:
    """SafeLogTail.tail returns exactly N requested lines."""
    tail = SafeLogTail()
    result = tail.tail(lines=5)
    assert len(result.lines) == 5
    assert result.bytes_scanned > 0
    assert result.truncated is False


def test_tail_redacts_bearer_token(tmp_log_dir: Path) -> None:
    """SafeLogTail redacts Authorization: Bearer tokens."""
    tail = SafeLogTail()
    result = tail.tail(lines=200)
    joined = "\n".join(line.message for line in result.lines)
    assert "abc.def.ghi" not in joined
    assert "<redacted>" in joined


def test_tail_redacts_query_string_secrets(tmp_log_dir: Path) -> None:
    """SafeLogTail redacts token= and password= query string values."""
    tail = SafeLogTail()
    result = tail.tail(lines=200)
    joined = "\n".join(line.message for line in result.lines)
    assert "secret_token_42" not in joined
    assert "hunter2" not in joined


def test_tail_filters_by_level(tmp_log_dir: Path) -> None:
    """SafeLogTail filters by log level."""
    tail = SafeLogTail()
    result = tail.tail(lines=200, level="ERROR")
    assert all(line.level == "ERROR" for line in result.lines)
    assert any("lookup failed" in line.message for line in result.lines)


def test_tail_filters_by_component_regex(tmp_log_dir: Path) -> None:
    """SafeLogTail filters by component regex."""
    tail = SafeLogTail()
    result = tail.tail(lines=200, component_regex=r"providers\.yandex.*")
    assert all(
        line.component and line.component.startswith("music_assistant.providers.yandex")
        for line in result.lines
    )


@pytest.mark.parametrize(
    "name",
    [
        "../etc/passwd",
        "/etc/passwd",
        "musicassistant.log\x00.txt",
        "..",
        ".",
        "",
        "musicassistant.log.99",
    ],
)
def test_path_traversal_rejected(tmp_log_dir: Path, name: str) -> None:
    """SafeLogTail rejects path traversal attempts."""
    tail = SafeLogTail()
    with pytest.raises(ToolError):
        tail.tail(lines=1, name=name)


def test_symlink_escape_rejected(tmp_log_dir: Path) -> None:
    """SafeLogTail rejects symlinks pointing outside ROOT."""
    outside = tmp_log_dir.parent / "outside.log"
    outside.write_text("LEAK\n")
    symlink = tmp_log_dir / "musicassistant.log.1"  # in allowlist by basename
    symlink.symlink_to(outside)

    tail = SafeLogTail()
    with pytest.raises(ToolError):
        tail.tail(lines=1, name="musicassistant.log.1")


def test_scan_bytes_cap_marks_truncated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SafeLogTail marks result truncated when 10MB cap is reached."""
    from provider.debug import log_reader

    monkeypatch.setattr(log_reader.SafeLogTail, "ROOT", tmp_path, raising=True)
    huge = tmp_path / "musicassistant.log"
    with huge.open("wb") as fh:
        # 20 MB of repeated, parseable lines.
        line = b"2026-05-28 09:00:00,001 INFO music_assistant.mass: filler\n"
        while fh.tell() < 20 * 1024 * 1024:
            fh.write(line)

    tail = log_reader.SafeLogTail()
    result = tail.tail(lines=10_000)
    assert result.truncated is True
    assert result.bytes_scanned <= 10 * 1024 * 1024 + len(line)


def test_scan_bytes_cap_drops_partial_first_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the byte cap fires mid-line, the partial leading fragment must be dropped.

    Without the fix, `_read_last_lines` would return a half-parsed entry with
    no timestamp / level / component (just a tail substring of a real line) —
    which slips past since_seconds filtering and confuses callers.
    """
    from provider.debug import log_reader

    monkeypatch.setattr(log_reader.SafeLogTail, "ROOT", tmp_path, raising=True)
    huge = tmp_path / "musicassistant.log"
    with huge.open("wb") as fh:
        line = b"2026-05-28 09:00:00,001 INFO music_assistant.mass: filler\n"
        # 11 MB of identical, parseable lines — enough to trigger the 10 MB cap.
        while fh.tell() < 11 * 1024 * 1024:
            fh.write(line)

    tail = log_reader.SafeLogTail()
    result = tail.tail(lines=2000)
    assert result.truncated is True
    # Every returned line must be fully parsed — no None timestamps.
    assert all(entry.timestamp is not None for entry in result.lines), (
        "partial leading fragment leaked: "
        + str([e for e in result.lines if e.timestamp is None][:3])
    )


# ---- E2E tests via MCP transport (debug_tail_log tool) ----


async def test_e2e_debug_tail_log(mounted_debug: Any, tmp_log_dir: Path) -> None:
    """debug_tail_log tool returns the last 5 lines via MCP."""
    async with Client(mounted_debug) as client:
        result = await client.call_tool("debug_tail_log", {"lines": 5})
    assert len(result.data.lines) == 5
    assert result.data.truncated is False


async def test_e2e_debug_tail_log_invalid_name(mounted_debug: Any, tmp_log_dir: Path) -> None:
    """debug_tail_log rejects path traversal attempts via MCP."""
    async with Client(mounted_debug) as client:
        with pytest.raises(ToolError):
            await client.call_tool("debug_tail_log", {"name": "../etc/passwd"})
