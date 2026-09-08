from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from video_shrink.config import CompactRecipe
from video_shrink.ffmpeg import CommandResult, ToolError, _require_capability, run_command
from video_shrink import ffmpeg


def test_capability_check_uses_positive_heading_not_incidental_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = CommandResult(
        ("ffmpeg",),
        0,
        "Filter scale\n  unknown 0 ..FV....... valid option value\n",
        "",
    )
    monkeypatch.setattr(ffmpeg, "run_command", lambda *args, **kwargs: result)
    _require_capability(Path("ffmpeg"), "filter", "scale", CompactRecipe())


def test_capability_check_rejects_ffmpeg_zero_exit_unknown_component(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = CommandResult(("ffmpeg",), 0, "", "Unknown filter 'scale'.\n")
    monkeypatch.setattr(ffmpeg, "run_command", lambda *args, **kwargs: result)
    with pytest.raises(ToolError, match="required filter scale"):
        _require_capability(Path("ffmpeg"), "filter", "scale", CompactRecipe())


def test_run_command_never_uses_a_shell_and_bounds_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class FakeProcess:
        def __init__(self, argv, **kwargs):
            observed["argv"] = argv
            observed.update(kwargs)
            self.args = argv
            self.stdout = io.BytesIO(b"0123456789")
            self.stderr = io.BytesIO(b"abcdefghij")

        def wait(self, timeout=None):
            observed["timeout"] = timeout
            return 0

        def poll(self):
            return 0

        def kill(self):
            raise AssertionError("kill should not be called")

    monkeypatch.setattr(subprocess, "Popen", FakeProcess)
    result = run_command(
        ["ffmpeg", "-version"], timeout=3.0, max_output_bytes=4
    )
    assert observed["shell"] is False
    assert observed["stdin"] is subprocess.DEVNULL
    assert observed["stdout"] is subprocess.PIPE
    assert observed["stderr"] is subprocess.PIPE
    assert observed["bufsize"] == 0
    assert 0 < observed["timeout"] <= 0.1
    expected_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    assert observed["creationflags"] == expected_flags
    assert result.stdout == "6789"
    assert result.stderr == "ghij"
    assert result.stdout_truncated and result.stderr_truncated


def test_run_command_kills_timed_out_process(monkeypatch: pytest.MonkeyPatch) -> None:
    observed = {"killed": False}

    class FakeProcess:
        def __init__(self, argv, **kwargs):
            self.args = argv
            self.stdout = io.BytesIO()
            self.stderr = io.BytesIO()

        def wait(self, timeout=None):
            return -9

        def poll(self):
            return None if not observed["killed"] else -9

        def kill(self):
            observed["killed"] = True

    monkeypatch.setattr(subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(
        ffmpeg,
        "_wait_for_exit",
        lambda *args: (_ for _ in ()).throw(subprocess.TimeoutExpired("ffmpeg", 1.0)),
    )
    result = run_command(["ffmpeg"], timeout=1.0, max_output_bytes=100)
    assert result.timed_out
    assert observed["killed"]


def test_large_stdout_and_stderr_are_drained_without_pipe_deadlock() -> None:
    block_count = 96
    block_size = 32 * 1024
    code = (
        "import os\n"
        f"for _ in range({block_count}):\n"
        f" os.write(1, b'O' * {block_size})\n"
        f" os.write(2, b'E' * {block_size})\n"
    )
    result = run_command(
        [sys.executable, "-c", code], timeout=10.0, max_output_bytes=1024
    )
    assert result.returncode == 0
    assert not result.timed_out
    assert result.stdout == "O" * 1024
    assert result.stderr == "E" * 1024
    assert result.stdout_truncated and result.stderr_truncated


def test_complete_stdout_limit_is_enforced_after_both_pipes_are_drained() -> None:
    code = (
        "import os\n"
        "os.write(1, b'O' * 200000)\n"
        "os.write(2, b'E' * 200000)\n"
    )
    with pytest.raises(ToolError, match="stdout exceeded"):
        run_command(
            [sys.executable, "-c", code],
            timeout=10.0,
            max_output_bytes=1024,
            require_complete_stdout=True,
        )


def test_real_timeout_returns_bounded_result() -> None:
    result = run_command(
        [sys.executable, "-c", "import time; print('started'); time.sleep(10)"],
        timeout=0.1,
        max_output_bytes=1024,
    )
    assert result.timed_out
    assert result.returncode != 0
