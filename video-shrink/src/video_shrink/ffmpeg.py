"""Bounded subprocess boundary for external FFmpeg tools."""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Sequence

from .config import CompactRecipe
from .models import ToolInfo


class ToolError(RuntimeError):
    pass


_READ_CHUNK_BYTES = 64 * 1024
_WAIT_SLICE_SECONDS = 0.1
_KILL_GRACE_SECONDS = 5.0
_READER_JOIN_GRACE_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False


class _TailBuffer:
    """Keep only the most recent bytes while tracking whether data was discarded."""

    __slots__ = ("limit", "parts", "retained", "total")

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.parts: deque[bytes] = deque()
        self.retained = 0
        self.total = 0

    def append(self, chunk: bytes) -> None:
        self.total += len(chunk)
        if len(chunk) >= self.limit:
            self.parts.clear()
            self.parts.append(chunk[-self.limit :])
            self.retained = self.limit
            return
        self.parts.append(chunk)
        self.retained += len(chunk)
        while self.retained > self.limit:
            excess = self.retained - self.limit
            head = self.parts[0]
            if len(head) <= excess:
                self.parts.popleft()
                self.retained -= len(head)
            else:
                self.parts[0] = head[excess:]
                self.retained -= excess

    @property
    def truncated(self) -> bool:
        return self.total > self.limit

    def text(self) -> str:
        return b"".join(self.parts).decode("utf-8", errors="replace")


@dataclass(slots=True)
class _ReaderState:
    buffer: _TailBuffer
    error: BaseException | None = None


def _drain_pipe(stream: BinaryIO, state: _ReaderState) -> None:
    try:
        while chunk := stream.read(_READ_CHUNK_BYTES):
            state.buffer.append(chunk)
    except BaseException as exc:
        state.error = exc
    finally:
        try:
            stream.close()
        except BaseException as exc:
            if state.error is None:
                state.error = exc


def _wait_for_exit(
    process: subprocess.Popen[bytes],
    timeout: float,
    reader_states: Sequence[_ReaderState],
) -> int:
    deadline = time.monotonic() + timeout
    while True:
        reader_error = next((state.error for state in reader_states if state.error), None)
        if reader_error is not None:
            raise ToolError(f"subprocess output reader failed: {reader_error}")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, timeout)
        try:
            return process.wait(timeout=min(_WAIT_SLICE_SECONDS, remaining))
        except subprocess.TimeoutExpired:
            continue


def _kill_and_wait(process: subprocess.Popen[bytes]) -> int:
    try:
        running = process.poll() is None
    except BaseException:
        running = True
    if running:
        with suppress(OSError):
            process.kill()
    try:
        return process.wait(timeout=_KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise ToolError("subprocess did not exit after termination") from exc


def _finish_readers(
    threads: Sequence[threading.Thread],
    streams: Sequence[BinaryIO],
    states: Sequence[_ReaderState],
) -> ToolError | None:
    deadline = time.monotonic() + _READER_JOIN_GRACE_SECONDS
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    if any(thread.is_alive() for thread in threads):
        for stream in streams:
            with suppress(OSError, ValueError):
                stream.close()
        deadline = time.monotonic() + _READER_JOIN_GRACE_SECONDS
        for thread in threads:
            thread.join(max(0.0, deadline - time.monotonic()))
    if any(thread.is_alive() for thread in threads):
        return ToolError("subprocess output readers did not finish")
    reader_error = next((state.error for state in states if state.error), None)
    if reader_error is not None:
        return ToolError(f"subprocess output reader failed: {reader_error}")
    return None


def run_command(
    argv: Sequence[str | os.PathLike[str]],
    *,
    timeout: float,
    max_output_bytes: int,
    cwd: Path | None = None,
    require_complete_stdout: bool = False,
) -> CommandResult:
    """Run without a shell while keeping captured output bounded in memory."""

    command = tuple(os.fspath(value) for value in argv)
    if not command:
        raise ValueError("subprocess argv must not be empty")
    if timeout <= 0 or max_output_bytes <= 0:
        raise ValueError("subprocess timeout and output bound must be positive")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        process = subprocess.Popen(
            command,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            creationflags=creationflags,
            bufsize=0,
        )
    except OSError as exc:
        raise ToolError(f"could not start {Path(command[0]).name}: {exc}") from exc
    if process.stdout is None or process.stderr is None:
        _kill_and_wait(process)
        raise ToolError("subprocess pipes were not created")

    streams = (process.stdout, process.stderr)
    states = (
        _ReaderState(_TailBuffer(max_output_bytes)),
        _ReaderState(_TailBuffer(max_output_bytes)),
    )
    threads = tuple(
        threading.Thread(
            target=_drain_pipe,
            args=(stream, state),
            daemon=True,
            name=f"video-shrink-{name}-reader",
        )
        for name, stream, state in zip(("stdout", "stderr"), streams, states)
    )
    started: list[threading.Thread] = []
    try:
        for thread in threads:
            thread.start()
            started.append(thread)
    except BaseException as exc:
        with suppress(BaseException):
            _kill_and_wait(process)
        _finish_readers(started, streams[: len(started)], states[: len(started)])
        for stream in streams[len(started) :]:
            with suppress(OSError, ValueError):
                stream.close()
        raise ToolError(f"could not start subprocess output readers: {exc}") from exc

    timed_out = False
    pending_error: BaseException | None = None
    try:
        returncode = _wait_for_exit(process, timeout, states)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            returncode = _kill_and_wait(process)
        except BaseException as exc:
            returncode = -1
            pending_error = exc
    except BaseException as exc:
        pending_error = exc
        try:
            returncode = _kill_and_wait(process)
        except BaseException as cleanup_exc:
            returncode = -1
            if hasattr(exc, "add_note"):
                exc.add_note(f"subprocess cleanup also failed: {cleanup_exc}")

    reader_error = _finish_readers(threads, streams, states)
    if pending_error is not None:
        if reader_error is not None and hasattr(pending_error, "add_note"):
            pending_error.add_note(str(reader_error))
        raise pending_error
    if reader_error is not None:
        raise reader_error
    stdout_state, stderr_state = states
    if require_complete_stdout and stdout_state.buffer.truncated:
        raise ToolError(f"subprocess stdout exceeded {max_output_bytes} bytes")
    return CommandResult(
        argv=command,
        returncode=returncode,
        stdout=stdout_state.buffer.text(),
        stderr=stderr_state.buffer.text(),
        timed_out=timed_out,
        stdout_truncated=stdout_state.buffer.truncated,
        stderr_truncated=stderr_state.buffer.truncated,
    )


def _resolve_tool(explicit: Path | None, name: str) -> Path:
    if explicit is not None:
        try:
            resolved = explicit.expanduser().resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ToolError(f"{name} path cannot be resolved: {explicit}") from exc
        if not resolved.is_file():
            raise ToolError(f"{name} path is not a file: {resolved}")
        return resolved
    located = shutil.which(name)
    if not located:
        raise ToolError(f"{name} was not found on PATH")
    return Path(located).resolve(strict=True)


def _version(executable: Path, recipe: CompactRecipe) -> str:
    result = run_command(
        [executable, "-version"],
        timeout=recipe.tool_timeout_seconds,
        max_output_bytes=recipe.max_subprocess_output_bytes,
        require_complete_stdout=True,
    )
    if result.timed_out or result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ToolError(f"{executable.name} version check failed: {detail}")
    first_line = result.stdout.splitlines()[0].strip() if result.stdout.splitlines() else ""
    if not first_line:
        raise ToolError(f"{executable.name} returned no version")
    return first_line


def _require_capability(ffmpeg: Path, kind: str, name: str, recipe: CompactRecipe) -> None:
    result = run_command(
        [ffmpeg, "-hide_banner", "-h", f"{kind}={name}"],
        timeout=recipe.tool_timeout_seconds,
        max_output_bytes=recipe.max_subprocess_output_bytes,
    )
    lines = [
        line.strip().casefold()
        for line in (result.stdout + "\n" + result.stderr).splitlines()
        if line.strip()
    ]
    expected_heading = f"{kind.casefold()} {name.casefold()}"
    if (
        result.timed_out
        or result.returncode != 0
        or not lines
        or not lines[0].startswith(expected_heading)
    ):
        raise ToolError(f"FFmpeg does not provide required {kind} {name}")


def prepare_tools(
    ffmpeg_path: Path | None,
    ffprobe_path: Path | None,
    recipe: CompactRecipe,
) -> ToolInfo:
    ffmpeg = _resolve_tool(ffmpeg_path, "ffmpeg")
    ffprobe = _resolve_tool(ffprobe_path, "ffprobe")
    ffmpeg_version = _version(ffmpeg, recipe)
    ffprobe_version = _version(ffprobe, recipe)
    for kind, name in (
        ("encoder", "libsvtav1"),
        ("encoder", "aac"),
        ("encoder", "libopus"),
        ("filter", "scale"),
        ("filter", "fps"),
        ("filter", "libvmaf"),
        ("muxer", "mp4"),
        ("muxer", "matroska"),
        ("muxer", "webm"),
    ):
        _require_capability(ffmpeg, kind, name, recipe)
    return ToolInfo(
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        ffmpeg_version=ffmpeg_version,
        ffprobe_version=ffprobe_version,
    )


def prepare_probe_tool(ffprobe_path: Path | None, recipe: CompactRecipe) -> ToolInfo:
    """Locate only ffprobe for dry-run; no encoder or VMAF capability is touched."""

    ffprobe = _resolve_tool(ffprobe_path, "ffprobe")
    return ToolInfo(
        ffmpeg=Path("ffmpeg"),
        ffprobe=ffprobe,
        ffmpeg_version="",
        ffprobe_version=_version(ffprobe, recipe),
    )


def command_detail(result: CommandResult) -> str:
    if result.timed_out:
        return "timed out"
    detail = result.stderr.strip() or result.stdout.strip()
    if result.stderr_truncated or result.stdout_truncated:
        detail = f"[tail only] {detail}"
    return detail[-4096:]
