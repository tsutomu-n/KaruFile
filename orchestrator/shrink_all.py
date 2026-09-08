# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""KaruFile の PDF・画像・動画オーケストレータ。

サードパーティ依存を持たない単一ファイルスクリプト（PEP 723）。`pdf-shrink` と
`media-shrink-tool` と `video-shrink` を `uv run --project` 経由でサブプロセス実行し、
混在するPDF・画像・動画フォルダーをまとめて軽量化する。動画はcompact presetだけで
対象にする。実行環境には uv と各プロジェクトの
`.venv` が必要。

使用例:
    uv run --script karufile.py -i "C:\\...\\input" [-o "C:\\...\\output"] -n
"""
from __future__ import annotations

import argparse
from collections import deque
import codecs
import csv
from fnmatch import fnmatchcase
import hashlib
import json
import logging
import math
import os
import queue
import re
import signal
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path, PureWindowsPath
from typing import Any

# KaruFile/orchestrator/shrink_all.py から見て parent.parent が KaruFile リポジトリのルート。
REPO_ROOT = Path(__file__).resolve().parent.parent

# 呼び出し対象プロジェクト。環境変数で上書き可能。
PDF_SHRINK_DIR = Path(os.environ.get("PDF_SHRINK_ROOT", REPO_ROOT / "pdf-shrink"))
MEDIA_SHRINK_DIR = Path(os.environ.get("MEDIA_SHRINK_ROOT", REPO_ROOT / "media-shrink-tool"))
VIDEO_SHRINK_DIR = Path(os.environ.get("VIDEO_SHRINK_ROOT", REPO_ROOT / "video-shrink"))

PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".gif", ".webp", ".heic", ".heif"
}
JPEG_EXTENSIONS = {".jpg", ".jpeg"}
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mkv", ".webm"}

IMAGE_SUMMARY_RE = re.compile(r"Resized\s+(\d+)\s+images\s+\((\d+)\s+errors\)")
IMAGE_SIZE_RE = re.compile(
    r"([\d.]+)\s*(B|KB|MB|GB|TB)\s*->\s+([\d.]+)\s*(B|KB|MB|GB|TB)",
    re.IGNORECASE,
)
IMAGE_MANIFEST_REQUIRED_COLUMNS = frozenset(
    {
        "source_path",
        "source_size",
        "source_sha256",
        "output_path",
        "output_size",
        "output_sha256",
        "action",
        "error",
        "preset",
        "recipe_hash",
        "orig_width",
        "orig_height",
        "new_width",
        "new_height",
    }
)
IMAGE_RECIPE_HASHES = {
    "standard": "2f60924f29b4cedccd15bd92d6dab4da72b22c1358c23e2edf1174fa3b70f420",
    "compact": "c5233dcedea2119fbfa723eb7020ba4f295d0fbcb0881ec8340f389614a26ddd",
}
IMAGE_NORMAL_ACTIONS = frozenset(
    {
        "CONVERTED",
        "SKIPPED_GENERATED",
        "SKIPPED_COMPLETE",
        "SKIPPED_COPY",
        "COPIED_ORIGINAL",
        "COPIED_ENCODE_FAILED",
    }
)
IMAGE_DRY_RUN_ACTIONS = frozenset({"DRY_RUN", "DRY_RUN_SKIPPED_GENERATED"})
IMAGE_EXACT_COPY_ACTIONS = frozenset(
    {"SKIPPED_GENERATED", "SKIPPED_COPY", "COPIED_ORIGINAL", "COPIED_ENCODE_FAILED"}
)
PDF_REPORT_REQUIRED_COLUMNS = frozenset(
    {
        "lossless_jpeg_requested",
        "photo_dpi",
        "source_path",
        "source_size",
        "source_sha256",
        "output_path",
        "output_size",
        "output_sha256",
        "saved_bytes",
        "saved_percent",
        "status",
        "preset",
        "profile",
    }
)
PDF_REPORT_STATUSES = frozenset(
    {
        "ADOPTED_LOSSLESS",
        "ADOPTED_LOSSY",
        "UNCHANGED",
        "SKIPPED_SMALL",
        "SKIPPED_ENCRYPTED",
        "SKIPPED_SIGNED",
        "SKIPPED_COMPLEX",
        "DRY_RUN_LOSSLESS",
        "DRY_RUN_LOSSY",
        "ERROR",
    }
)
PDF_COPY_STATUSES = frozenset(
    {
        "UNCHANGED",
        "SKIPPED_SMALL",
        "SKIPPED_ENCRYPTED",
        "SKIPPED_SIGNED",
        "SKIPPED_COMPLEX",
    }
)
VIDEO_REPORT_REQUIRED_COLUMNS = frozenset(
    {
        "source_path",
        "source_size",
        "output_size",
        "saved_bytes",
        "status",
        "error_message",
        "preset",
        "output_path",
        "source_sha256",
        "output_sha256",
        "saved_percent",
        "reason",
        "video_codec",
        "audio_codec",
        "width",
        "height",
        "fps",
        "duration",
        "vmaf_mean",
        "vmaf_p5",
        "ffmpeg_version",
    }
)
VIDEO_REPORT_STATUSES = frozenset(
    {
        "ADOPTED",
        "UNCHANGED",
        "SKIPPED_STANDARD",
        "SKIPPED_COMPLEX",
        "SKIPPED_UNSUPPORTED",
        "SKIPPED_COMPLETE",
        "DRY_RUN",
        "ERROR",
    }
)
VIDEO_MIN_SAVED_BYTES = 1024 * 1024
VIDEO_MIN_SAVED_PERCENT = 10.0
PROCESSOR_TIMEOUT_SECONDS = 24 * 60 * 60.0
PROCESSOR_TERMINATE_GRACE_SECONDS = 5.0
PROCESSOR_OUTPUT_TAIL_LINES = 256
PROCESSOR_OUTPUT_CHUNK_BYTES = 64 * 1024
PROCESSOR_OUTPUT_QUEUE_CHUNKS = 8
PROCESSOR_MAX_RETURNED_LINE_CHARS = 16 * 1024
VIDEO_MAX_WIDTH = 1280
VIDEO_MAX_HEIGHT = 720
VIDEO_MAX_FPS = 30.0
VIDEO_MIN_VMAF_MEAN = 85.0
VIDEO_MIN_VMAF_P5 = 70.0


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def _configure_console_output() -> None:
    """Keep the terminal encoding while making unrepresentable log text printable."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")


def human_size(num: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:.2f} {unit}"
        num /= 1024.0
    return f"{num:.2f} TB"


def _to_bytes(value: float, unit: str) -> int:
    unit = unit.upper()
    multipliers = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    return int(value * multipliers.get(unit, 1))


def run_command(
    name: str,
    project_dir: Path,
    args: list[str],
) -> tuple[int, list[str], float]:
    """processor出力をstreamし、有限時間・固定長tailで実行する。"""
    cmd = ["uv", "run", "--project", str(project_dir)]
    cmd.extend(args)

    logging.info("[%s] Starting: %s", name, " ".join(cmd))
    start = time.perf_counter()
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    # The pipe reader below decodes UTF-8 even on Windows legacy code pages.
    env["PYTHONIOENCODING"] = "utf-8"
    popen_options: dict[str, Any] = {}
    if os.name == "nt":
        popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_options["start_new_session"] = True
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=project_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            **popen_options,
        )
    except OSError as exc:
        elapsed = time.perf_counter() - start
        logging.error("[%s] Failed to start: %s", name, exc)
        return 1, [], elapsed
    events: queue.Queue[tuple[str, bytes | BaseException | None]] = queue.Queue(
        maxsize=PROCESSOR_OUTPUT_QUEUE_CHUNKS
    )

    def read_output() -> None:
        try:
            if proc.stdout is not None:
                while True:
                    read = getattr(proc.stdout, "read1", proc.stdout.read)
                    chunk = read(PROCESSOR_OUTPUT_CHUNK_BYTES)
                    if not chunk:
                        break
                    events.put(("data", chunk))
        except BaseException as exc:  # surfaced as a failed processor run below
            events.put(("error", exc))
        finally:
            if proc.stdout is not None:
                proc.stdout.close()
            events.put(("eof", None))

    reader = threading.Thread(target=read_output, name=f"{name}-output", daemon=True)
    reader.start()
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    lines: deque[str] = deque(maxlen=PROCESSOR_OUTPUT_TAIL_LINES)
    pending_line = ""
    stream_done = False
    stream_error: BaseException | None = None
    deadline = time.monotonic() + PROCESSOR_TIMEOUT_SECONDS

    def consume_text(text: str, *, final: bool = False) -> None:
        nonlocal pending_line
        if text:
            print(text, end="", flush=True)
            pending_line += text
        while True:
            newline = pending_line.find("\n")
            if newline < 0:
                break
            line = pending_line[:newline].rstrip("\r")
            lines.append(line[-PROCESSOR_MAX_RETURNED_LINE_CHARS:])
            pending_line = pending_line[newline + 1 :]
        if len(pending_line) > PROCESSOR_MAX_RETURNED_LINE_CHARS:
            pending_line = pending_line[-PROCESSOR_MAX_RETURNED_LINE_CHARS:]
        if final and pending_line:
            lines.append(pending_line.rstrip("\r")[-PROCESSOR_MAX_RETURNED_LINE_CHARS:])
            pending_line = ""

    timed_out = False
    while not (stream_done and proc.poll() is not None):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            logging.error("[%s] Timed out after %.0f seconds", name, PROCESSOR_TIMEOUT_SECONDS)
            _terminate_process_tree(proc)
            break
        try:
            kind, payload = events.get(timeout=min(0.1, remaining))
        except queue.Empty:
            continue
        if kind == "data":
            assert isinstance(payload, bytes)
            consume_text(decoder.decode(payload))
        elif kind == "error":
            assert isinstance(payload, BaseException)
            stream_error = payload
            _terminate_process_tree(proc)
            break
        else:
            stream_done = True
            consume_text(decoder.decode(b"", final=True), final=True)

    if timed_out or stream_error is not None:
        drain_deadline = time.monotonic() + PROCESSOR_TERMINATE_GRACE_SECONDS
        while not stream_done and time.monotonic() < drain_deadline:
            try:
                kind, payload = events.get(timeout=0.1)
            except queue.Empty:
                continue
            if kind == "data":
                assert isinstance(payload, bytes)
                consume_text(decoder.decode(payload))
            elif kind == "error":
                assert isinstance(payload, BaseException)
                stream_error = payload
            else:
                stream_done = True
                consume_text(decoder.decode(b"", final=True), final=True)
    reader.join(timeout=PROCESSOR_TERMINATE_GRACE_SECONDS)
    if proc.poll() is None:
        _terminate_process_tree(proc, force=True)
    try:
        returncode = proc.wait(timeout=PROCESSOR_TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        returncode = 1
    if timed_out or stream_error is not None:
        if stream_error is not None:
            logging.error("[%s] Failed while reading output: %s", name, stream_error)
        returncode = returncode or 1
    elapsed = time.perf_counter() - start
    logging.info("[%s] Finished in %.2fs (exit code: %d)", name, elapsed, returncode)
    return returncode, list(lines), elapsed


def _terminate_process_tree(proc: subprocess.Popen[bytes], *, force: bool = False) -> None:
    """uv wrapperとそのprocessor子プロセスを同じtree/session単位で停止する。"""

    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            command = ["taskkill", "/PID", str(proc.pid), "/T"]
            if force:
                command.append("/F")
            subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=PROCESSOR_TERMINATE_GRACE_SECONDS,
                check=False,
            )
        else:
            os.killpg(proc.pid, signal.SIGKILL if force else signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        try:
            proc.kill() if force else proc.terminate()
        except OSError:
            pass
    if not force:
        try:
            proc.wait(timeout=PROCESSOR_TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            _terminate_process_tree(proc, force=True)


def _is_link_or_junction(path: Path) -> bool:
    """Return whether *path* is a filesystem link that traversal must not follow."""

    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, FileNotFoundError):
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def collect_files(input_dir: Path, extensions: set[str]) -> list[Path]:
    """Collect regular files without following symlinks or Windows junctions."""

    input_root = input_dir.resolve(strict=True)
    found: list[Path] = []
    pending = [input_root]
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise ValueError(f"入力ディレクトリを探索できません: {directory}: {exc}") from exc

        for entry in entries:
            path = Path(entry.path)
            if _is_link_or_junction(path):
                raise ValueError(f"入力内のシンボリックリンクまたはjunctionは処理できません: {path}")
            try:
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                resolved = path.resolve(strict=True)
            except OSError as exc:
                raise ValueError(f"入力ファイルを確認できません: {path}: {exc}") from exc

            if not _is_within(resolved, input_root):
                raise ValueError(f"入力root外へ解決されるファイルは処理できません: {path}")
            if resolved.suffix.lower() in extensions:
                found.append(resolved)

    return sorted(
        found,
        key=lambda path: (
            path.relative_to(input_root).as_posix().casefold(),
            path.relative_to(input_root).as_posix(),
        ),
    )


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _pdf_photo_pattern(value: str) -> str:
    """Normalize input-relative globs using the PDF CLI's portable path rules."""
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    if (
        not normalized.strip()
        or normalized.startswith("/")
        or PureWindowsPath(normalized).drive
        or ".." in parts
    ):
        raise argparse.ArgumentTypeError("must be a nonempty input-relative pattern without '..'")
    normalized = "/".join(part for part in parts if part not in {"", "."})
    if not normalized:
        raise argparse.ArgumentTypeError("must name an input-relative PDF pattern")
    return normalized


def _pdf_photo_dpi(value: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value):
        raise argparse.ArgumentTypeError("must be an integer between 150 and 300")
    parsed = int(value)
    if not 150 <= parsed <= 300:
        raise argparse.ArgumentTypeError("must be an integer between 150 and 300")
    return parsed


class _ArgumentParser(argparse.ArgumentParser):
    def parse_args(self, args=None, namespace=None):
        parsed = super().parse_args(args, namespace)
        if parsed.pdf_photo_dpi is not None and not parsed.pdf_photo_pattern:
            self.error("--pdf-photo-dpi requires --pdf-photo-pattern")
        if parsed.pdf_preview and not parsed.pdf_photo_pattern:
            self.error("--pdf-preview requires --pdf-photo-pattern")
        if parsed.pdf_preview_dpi and not parsed.pdf_preview:
            self.error("--pdf-preview-dpi requires --pdf-preview")
        parsed.pdf_preview_dpi = sorted(set(parsed.pdf_preview_dpi), reverse=True)
        if len(parsed.pdf_preview_dpi) > 5:
            self.error("--pdf-preview-dpi accepts at most 5 distinct DPI values")
        if parsed.pdf_photo_dpi is None:
            parsed.pdf_photo_dpi = 200
        return parsed


def _pdf_profile(relative: Path, preset: str, photo_patterns: list[str]) -> str:
    path = relative.as_posix().casefold()
    if any(fnmatchcase(path, pattern.casefold()) for pattern in photo_patterns):
        return "photo"
    return preset


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _has_link_component(root: Path, candidate: Path) -> bool:
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return True
    current = root
    if _is_link_or_junction(current):
        return True
    for part in relative.parts:
        current = current / part
        if _is_link_or_junction(current):
            return True
    return False


def validate_directories(input_dir: Path, output_dir: Path) -> None:
    """processor 起動前に危険な入出力関係を拒否する。"""
    if not input_dir.is_dir():
        raise ValueError(f"入力ディレクトリが存在しません: {input_dir}")
    if output_dir.exists() and not output_dir.is_dir():
        raise ValueError(f"出力先がディレクトリではありません: {output_dir}")
    if input_dir == output_dir:
        raise ValueError("入力と出力に同じディレクトリは指定できません")
    if _is_within(output_dir, input_dir):
        raise ValueError("出力ディレクトリを入力ディレクトリ配下には置けません")
    if _is_within(input_dir, output_dir):
        raise ValueError("入力ディレクトリを出力ディレクトリ配下には置けません")


def _plan_image_destinations(
    input_root: Path,
    output_dir: Path,
    image_files: list[Path],
) -> list[tuple[Path, Path]]:
    """media_shrink.image.plan_outputs と同じstable naming/collision規則を適用する。"""

    base: list[tuple[Path, Path, Path]] = []
    groups: dict[str, list[int]] = {}
    for source in image_files:
        relative_source = source.resolve(strict=True).relative_to(input_root)
        relative_output = relative_source
        if relative_output.suffix.lower() not in JPEG_EXTENSIONS:
            relative_output = relative_output.with_name(f"{relative_output.name}.jpg")
        index = len(base)
        base.append((source, relative_source, relative_output))
        groups.setdefault(relative_output.as_posix().casefold(), []).append(index)

    hashed_indexes = {
        index
        for indexes in groups.values()
        if len(indexes) > 1
        for index in indexes
    }
    while True:
        planned_relative: list[Path] = []
        for index, (_source, relative_source, relative_output) in enumerate(base):
            if index in hashed_indexes:
                digest = hashlib.sha256(
                    relative_source.as_posix().encode("utf-8")
                ).hexdigest()[:8]
                relative_output = relative_output.with_name(
                    f"{relative_output.stem}~{digest}{relative_output.suffix}"
                )
            planned_relative.append(relative_output)

        final_groups: dict[str, list[int]] = {}
        for index, relative_output in enumerate(planned_relative):
            final_groups.setdefault(relative_output.as_posix().casefold(), []).append(index)
        remaining = [indexes for indexes in final_groups.values() if len(indexes) > 1]

        path_parts = [
            tuple(part.casefold() for part in relative_output.parts)
            for relative_output in planned_relative
        ]
        prefix_indexes = {
            left_index
            for left_index, left in enumerate(path_parts)
            for right_index, right in enumerate(path_parts)
            if left_index != right_index
            and len(left) < len(right)
            and right[:len(left)] == left
        }
        if not remaining and not prefix_indexes:
            return [
                (base[index][0], output_dir / relative_output)
                for index, relative_output in enumerate(planned_relative)
            ]

        newly_hashed = {
            index
            for indexes in remaining
            for index in indexes
            if index not in hashed_indexes
        }
        newly_hashed.update(index for index in prefix_indexes if index not in hashed_indexes)
        if newly_hashed:
            hashed_indexes.update(newly_hashed)
            continue

        conflicting = sorted(
            {index for indexes in remaining for index in indexes} | prefix_indexes
        )
        sources_text = ", ".join(str(base[index][1]) for index in conflicting)
        raise ValueError(
            "8桁hashでも画像出力の同名・file/directory衝突を解消できません: "
            f"{sources_text}"
        )


def validate_planned_destinations(
    input_dir: Path,
    output_dir: Path,
    pdf_files: list[Path],
    image_files: list[Path],
    video_files: list[Path] | None = None,
) -> None:
    """全processorの予定出力が、link解決後も安全な出力root内か確認する。"""

    input_root = input_dir.resolve(strict=True)
    output_root = output_dir.resolve(strict=False)
    planned: list[tuple[str, Path, Path]] = []
    for source in pdf_files:
        relative = source.resolve(strict=True).relative_to(input_root)
        planned.append(("pdf", source, output_dir / relative))

    planned.extend(
        ("image", source, destination)
        for source, destination in _plan_image_destinations(
            input_root,
            output_dir,
            image_files,
        )
    )
    for source in video_files or []:
        relative = source.resolve(strict=True).relative_to(input_root)
        planned.append(("video", source, output_dir / relative))

    protected_sources = tuple([*pdf_files, *image_files, *(video_files or [])])

    for _processor, source, destination in planned:
        resolved_source = source.resolve(strict=True)
        if not _is_within(resolved_source, input_root):
            raise ValueError(f"入力root外へ解決されるファイルは処理できません: {source}")
        resolved_destination = destination.resolve(strict=False)
        if not _is_within(resolved_destination, output_root):
            raise ValueError(
                "予定出力が出力root外へ解決されます: "
                f"{destination} -> {resolved_destination}"
            )
        if _is_within(resolved_destination, input_root):
            raise ValueError(
                "予定出力が入力側へ解決されます: "
                f"{destination} -> {resolved_destination}"
            )
        destination_lexical = Path(os.path.abspath(destination))
        output_lexical = Path(os.path.abspath(output_dir))
        if _has_link_component(output_lexical, destination_lexical):
            raise ValueError(f"予定出力にlink/junction componentがあります: {destination}")
        if destination.exists():
            destination_stat = destination.stat()
            if destination_stat.st_nlink > 1:
                raise ValueError(f"予定出力がhardlinkです: {destination}")
            for protected_source in protected_sources:
                if os.path.samefile(destination, protected_source):
                    raise ValueError(
                        f"予定出力が入力sourceと同一fileです: "
                        f"{destination} == {protected_source}"
                    )

    relative_plans = [
        (
            processor,
            destination.relative_to(output_dir),
            tuple(part.casefold() for part in destination.relative_to(output_dir).parts),
        )
        for processor, _source, destination in planned
    ]
    resolved_plans = [
        (
            destination,
            tuple(
                part.casefold()
                for part in destination.resolve(strict=False).relative_to(output_root).parts
            ),
        )
        for _processor, _source, destination in planned
    ]
    for index, (destination, parts) in enumerate(resolved_plans):
        for other_destination, other_parts in resolved_plans[index + 1:]:
            common = min(len(parts), len(other_parts))
            if parts[:common] == other_parts[:common]:
                raise ValueError(
                    "予定出力の実体に同名・file/directory衝突があります: "
                    f"{destination} / {other_destination}"
                )
    for index, (processor, relative, parts) in enumerate(relative_plans):
        for other_processor, other_relative, other_parts in relative_plans[index + 1:]:
            common = min(len(parts), len(other_parts))
            has_prefix_conflict = parts[:common] == other_parts[:common] and (
                len(parts) != len(other_parts)
                or processor != other_processor
            )
            if has_prefix_conflict:
                raise ValueError(
                    "予定出力にfile/directory衝突があります: "
                    f"{relative} / {other_relative}"
                )


def validate_derived_write_paths(
    input_dir: Path,
    output_dir: Path,
    pdf_files: list[Path],
    image_files: list[Path],
    video_files: list[Path] | None = None,
    *,
    pdf_preview: bool = False,
) -> None:
    """processorが出力mirror外へ書く状態・reportパスの衝突を拒否する。"""

    input_root = input_dir.resolve(strict=True)
    output_root = output_dir.resolve(strict=False)
    work_root = Path(os.path.abspath(output_dir.parent))
    work_root_resolved = work_root.resolve(strict=False)
    derived: list[tuple[str, Path]] = [
        ("image error report", Path(f"{output_dir}.image-errors.csv")),
        ("image manifest", Path(f"{output_dir}.image-manifest.csv")),
        ("image dry-run manifest", Path(f"{output_dir}.image-manifest.dry-run.csv")),
    ]
    if pdf_files or pdf_preview:
        state_dir = work_root / ".pdf-shrink"
        temp_root = state_dir / "temp"
        derived.extend(
            [
                ("PDF state directory", state_dir),
                ("PDF temporary directory", temp_root),
                ("PDF state database", state_dir / "state.sqlite3"),
                ("PDF state journal", state_dir / "state.sqlite3-journal"),
                ("PDF state WAL", state_dir / "state.sqlite3-wal"),
                ("PDF state shared memory", state_dir / "state.sqlite3-shm"),
                ("PDF report", work_root / "report.csv"),
                ("PDF dry-run report", work_root / "report.dry-run.csv"),
            ]
        )
        derived.extend(
            (
                "PDF per-source temporary directory",
                temp_root / source.resolve(strict=True).relative_to(input_root).parent,
            )
            for source in pdf_files
        )
        if pdf_preview:
            derived.extend(
                [
                    ("PDF preview directory", work_root / "pdf-preview"),
                    ("PDF preview manifest", work_root / "pdf-preview.json"),
                    ("PDF preview dry-run manifest", work_root / "pdf-preview.dry-run.json"),
                ]
            )

    if video_files:
        video_state_dir = Path(f"{output_dir}.video-state")
        video_temp_root = video_state_dir / "temp"
        derived.extend(
            [
                ("Video state directory", video_state_dir),
                ("Video temporary directory", video_temp_root),
                ("Video state database", video_state_dir / "state.sqlite3"),
                ("Video state journal", video_state_dir / "state.sqlite3-journal"),
                ("Video state WAL", video_state_dir / "state.sqlite3-wal"),
                ("Video state shared memory", video_state_dir / "state.sqlite3-shm"),
                ("Video report", Path(f"{output_dir}.video-report.csv")),
                ("Video dry-run report", Path(f"{output_dir}.video-report.dry-run.csv")),
            ]
        )
        derived.extend(
            (
                "Video per-source temporary directory",
                video_temp_root / source.resolve(strict=True).relative_to(input_root).parent,
            )
            for source in video_files
        )

    protected_sources = tuple([*pdf_files, *image_files, *(video_files or [])])

    for label, candidate in derived:
        candidate_lexical = Path(os.path.abspath(candidate))
        if not _is_within(candidate_lexical, work_root):
            raise ValueError(f"{label}がwork root外です: {candidate}")
        if _has_link_component(work_root, candidate_lexical):
            raise ValueError(f"{label}にlink/junctionが含まれます: {candidate}")
        resolved = candidate.resolve(strict=False)
        if not _is_within(resolved, work_root_resolved):
            raise ValueError(
                f"{label}がwork root外へ解決されます: {candidate} -> {resolved}"
            )
        if _is_within(resolved, input_root) or _is_within(input_root, resolved):
            raise ValueError(
                f"{label}が入力と衝突します: {candidate} -> {resolved}"
            )
        if _is_within(resolved, output_root) or _is_within(output_root, resolved):
            raise ValueError(
                f"{label}が出力mirrorと衝突します: {candidate} -> {resolved}"
            )
        if candidate.exists():
            candidate_stat = candidate.stat()
            if not candidate.is_dir() and candidate_stat.st_nlink > 1:
                raise ValueError(f"{label}がhardlinkです: {candidate}")
            for protected_source in protected_sources:
                if os.path.samefile(candidate, protected_source):
                    raise ValueError(
                        f"{label}が入力sourceと同一fileです: "
                        f"{candidate} == {protected_source}"
                    )


def _empty_result() -> dict[str, Any]:
    return {
        "count": 0,
        "errors": 0,
        "orig_size": 0,
        "new_size": 0,
        "saved": 0,
    }


def _unavailable_result() -> dict[str, Any]:
    return {
        "count": None,
        "errors": None,
        "orig_size": None,
        "new_size": None,
        "saved": None,
    }


def _file_signature(path: Path) -> tuple[int, int, int, int, int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (
        stat.st_dev,
        stat.st_ino,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
        stat.st_size,
        stat.st_nlink,
    )


def _was_updated(path: Path, previous: tuple[int, int, int, int, int, int] | None) -> bool:
    current = _file_signature(path)
    return current is not None and current != previous


def _stable_file_size_and_sha256(path: Path) -> tuple[int, str]:
    before = _file_signature(path)
    if before is None or not path.is_file():
        raise OSError(f"file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    after = _file_signature(path)
    if before != after:
        raise OSError(f"file changed while hashing: {path}")
    return before[-2], digest.hexdigest()


SourceBaseline = dict[Path, tuple[tuple[int, int, int, int, int, int], str]]


def _capture_source_baseline(paths: list[Path]) -> SourceBaseline:
    """processor起動前の全対象をstable identityとSHA-256へ固定する。"""

    baseline: SourceBaseline = {}
    for path in paths:
        resolved = path.resolve(strict=True)
        signature = _file_signature(resolved)
        if signature is None:
            raise OSError(f"source is missing before processing: {resolved}")
        _size, digest = _stable_file_size_and_sha256(resolved)
        if _file_signature(resolved) != signature:
            raise OSError(f"source changed while capturing baseline: {resolved}")
        baseline[resolved] = (signature, digest)
    return baseline


def _source_baseline_matches(baseline: SourceBaseline) -> bool:
    """全processor終了後も開始時の入力identityと内容が同じか確認する。"""

    try:
        for path, (expected_signature, expected_digest) in baseline.items():
            if _file_signature(path) != expected_signature:
                return False
            _size, observed_digest = _stable_file_size_and_sha256(path)
            if (
                observed_digest != expected_digest
                or _file_signature(path) != expected_signature
            ):
                return False
        # 後続fileのhash中に先に検証したfileが差し替えられる競合窓を閉じる。
        # contentは上で検証済みなので、最後は全pathのidentityを一括再確認する。
        if any(
            _file_signature(path) != expected_signature
            for path, (expected_signature, _expected_digest) in baseline.items()
        ):
            return False
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _is_safe_result_file(path: Path, protected_sources: list[Path]) -> bool:
    """hash後にもresult pathが通常の独立fileであることを確認する。"""

    if not path.is_file() or _is_link_or_junction(path):
        return False
    try:
        if path.stat().st_nlink != 1:
            return False
        return not any(os.path.samefile(path, source) for source in protected_sources)
    except OSError:
        return False


def _has_stable_pdf_header(path: Path) -> bool:
    signature = _file_signature(path)
    if signature is None:
        return False
    try:
        with path.open("rb") as stream:
            header = stream.read(1024)
    except OSError:
        return False
    return b"%PDF-" in header and _file_signature(path) == signature


def validate_pdf_preview_manifest(
    path: Path,
    *,
    previous: tuple[int, int, int, int, int, int] | None,
    report_result: dict[str, Any],
    input_dir: Path,
    output_dir: Path,
    photo_dpi: int,
    preview_dpis: list[int],
    dry_run: bool,
) -> dict[str, Any] | None:
    """Accept only a fresh preview matching the already verified PDF report."""
    try:
        if not _was_updated(path, previous):
            return None
        rows = report_result.get("rows")
        if not isinstance(rows, list):
            return None
        protected = [Path(row["source_path"]) for row in rows]
        protected.extend(
            Path(row["output_path"]) for row in rows if row["output_sha256"]
        )
        work_root = Path(os.path.abspath(output_dir.parent))
        expected_manifest = work_root / (
            "pdf-preview.dry-run.json" if dry_run else "pdf-preview.json"
        )
        if path != expected_manifest or _has_link_component(work_root, path):
            return None
        if not _is_safe_result_file(path, protected):
            return None
        signature = _file_signature(path)
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
        if _file_signature(path) != signature or not isinstance(data, dict):
            return None
        if not {
            "schema", "requested", "dry_run", "photo_dpi", "preview_dpis",
            "input_root", "output_root", "status", "run_dir", "index_path",
            "index_sha256", "items", "errors",
        }.issubset(data):
            return None
        if (
            type(data.get("schema")) is not int or data["schema"] != 1
            or data.get("requested") is not True
            or data.get("dry_run") is not dry_run
            or type(data.get("photo_dpi")) is not int
            or data["photo_dpi"] != photo_dpi
            or data.get("preview_dpis") != preview_dpis
            or any(type(dpi) is not int for dpi in data["preview_dpis"])
        ):
            return None
        for field, expected in (("input_root", input_dir), ("output_root", output_dir)):
            reported_root = data.get(field)
            if not isinstance(reported_root, str) or not Path(reported_root).is_absolute():
                return None
            if Path(reported_root) != expected.resolve(strict=False):
                return None
        errors = data.get("errors")
        if not isinstance(errors, list) or any(not isinstance(error, str) or not error for error in errors):
            return None
        status = data.get("status")
        if status not in ({"DRY_RUN", "ERROR"} if dry_run else {"COMPLETE", "ERROR"}):
            return None
        if (status == "ERROR") != bool(errors):
            return None
        expected_rows = {
            str(Path(row["source_path"])).casefold(): row
            for row in rows if row["profile"] == "photo"
        }
        items = data.get("items")
        if not isinstance(items, list) or len(items) != len(expected_rows):
            return None
        seen: set[str] = set()
        item_has_error = False
        for item in items:
            if not isinstance(item, dict):
                return None
            if not {
                "source_path", "relative_path", "source_sha256", "output_path",
                "output_sha256", "pdf_status", "status", "reason",
            }.issubset(item):
                return None
            source_name = item.get("source_path")
            if not isinstance(source_name, str) or not Path(source_name).is_absolute():
                return None
            key = str(Path(source_name)).casefold()
            if key in seen or key not in expected_rows:
                return None
            seen.add(key)
            row = expected_rows[key]
            relative = Path(row["source_path"]).relative_to(input_dir).as_posix()
            if (
                item.get("relative_path") != relative
                or item.get("source_sha256") != row["source_sha256"]
                or item.get("output_path") != row["output_path"]
                or item.get("output_sha256") != (row["output_sha256"] or None)
                or item.get("pdf_status") != row["status"]
                or not isinstance(item.get("reason"), str)
            ):
                return None
            item_status = item.get("status")
            if item_status not in {"READY", "SKIPPED", "ERROR"}:
                return None
            if dry_run and item_status == "READY":
                return None
            if item_status == "READY" and (row["status"] == "ERROR" or not row["output_sha256"]):
                return None
            if item_status == "ERROR":
                item_has_error = True
                if not item["reason"]:
                    return None
        if item_has_error and status != "ERROR":
            return None
        run_dir, index_path, index_sha256 = (
            data.get("run_dir"), data.get("index_path"), data.get("index_sha256")
        )
        if dry_run or run_dir is None:
            if any(value is not None for value in (run_dir, index_path, index_sha256)):
                return None
            if not dry_run and status != "ERROR":
                return None
        else:
            if not isinstance(run_dir, str) or not Path(run_dir).is_absolute():
                return None
            run_path = Path(run_dir)
            preview_root = work_root / "pdf-preview"
            if run_path.parent != preview_root or _has_link_component(work_root, run_path):
                return None
            if not run_path.is_dir() or run_path.resolve(strict=True).parent != preview_root.resolve(strict=True):
                return None
            if index_path is None:
                if status != "ERROR" or index_sha256 is not None:
                    return None
            else:
                if not isinstance(index_path, str) or Path(index_path) != run_path / "index.html":
                    return None
                index = Path(index_path)
                if not _is_safe_result_file(index, protected) or _has_link_component(work_root, index):
                    return None
                size, digest = _stable_file_size_and_sha256(index)
                if size == 0 or digest != index_sha256:
                    return None
        if _file_signature(path) != signature or not _is_safe_result_file(path, protected):
            return None
        return data
    except (OSError, RuntimeError, TypeError, ValueError, KeyError):
        return None


def parse_pdf_report(report_path: Path) -> dict[str, Any]:
    total_in = 0
    total_out = 0
    saved = 0
    count = 0
    errors = 0
    output_sizes_complete = True
    status_counts: dict[str, int] = {}
    source_paths: list[str] = []
    rows: list[dict[str, Any]] = []

    if not report_path.exists():
        return {}

    try:
        with open(report_path, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or not PDF_REPORT_REQUIRED_COLUMNS.issubset(
                reader.fieldnames
            ):
                raise ValueError("required PDF report columns are missing")
            for row in reader:
                if None in row:
                    raise ValueError("PDF report row has unexpected extra columns")
                source_path = row.get("source_path")
                if not source_path:
                    raise ValueError("PDF report row has no source_path")
                output_path = row.get("output_path")
                if not output_path:
                    raise ValueError("PDF report row has no output_path")
                source_paths.append(source_path)
                count += 1
                raw_input = row.get("source_size")
                raw_output = row.get("output_size")
                if raw_input in (None, ""):
                    raise ValueError("PDF report row has no source_size")
                input_size = int(raw_input)
                if input_size < 0:
                    raise ValueError("PDF report source_size must not be negative")
                total_in += input_size
                if raw_output in (None, ""):
                    output_size = None
                    output_sizes_complete = False
                else:
                    output_size = int(raw_output)
                    if output_size < 0:
                        raise ValueError("PDF report output_size must not be negative")
                    total_out += output_size
                saved_bytes = int(row.get("saved_bytes") or 0)
                if saved_bytes < 0:
                    raise ValueError("PDF report saved_bytes must not be negative")
                saved += saved_bytes
                saved_percent = float(row.get("saved_percent") or 0)
                if not math.isfinite(saved_percent) or saved_percent < 0:
                    raise ValueError("PDF report saved_percent is invalid")
                status = row.get("status") or ""
                if status not in PDF_REPORT_STATUSES:
                    raise ValueError(f"unknown PDF report status: {status!r}")
                preset = row.get("preset") or ""
                if preset not in {"standard", "compact"}:
                    raise ValueError(f"unknown PDF report preset: {preset!r}")
                profile = row.get("profile") or ""
                lossless_jpeg_requested = row.get("lossless_jpeg_requested")
                if lossless_jpeg_requested not in {"true", "false"}:
                    raise ValueError("PDF report lossless_jpeg_requested must be true or false")
                if profile not in {"standard", "compact", "photo"}:
                    raise ValueError(f"unknown PDF report profile: {profile!r}")
                raw_photo_dpi = row.get("photo_dpi")
                if profile == "photo":
                    photo_dpi = _pdf_photo_dpi(raw_photo_dpi)
                else:
                    if raw_photo_dpi != "":
                        raise ValueError("non-photo PDF report photo_dpi must be empty")
                    photo_dpi = None
                source_sha256 = (row.get("source_sha256") or "").lower()
                output_sha256 = (row.get("output_sha256") or "").lower()
                if not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
                    raise ValueError("PDF report source_sha256 is invalid")
                if output_sha256 and not re.fullmatch(r"[0-9a-f]{64}", output_sha256):
                    raise ValueError("PDF report output_sha256 is invalid")
                status_counts[status] = status_counts.get(status, 0) + 1
                if status == "ERROR":
                    errors += 1
                rows.append(
                    {
                        "source_path": source_path,
                        "source_size": input_size,
                        "source_sha256": source_sha256,
                        "output_path": output_path,
                        "output_size": output_size,
                        "output_sha256": output_sha256,
                        "saved_bytes": saved_bytes,
                        "saved_percent": saved_percent,
                        "status": status,
                        "preset": preset,
                        "profile": profile,
                        "photo_dpi": photo_dpi,
                        "lossless_jpeg_requested": lossless_jpeg_requested == "true",
                    }
                )
    except Exception as exc:
        logging.warning("Failed to parse PDF report %s: %s", report_path, exc)
        return {}

    return {
        "count": count,
        "orig_size": total_in,
        "new_size": total_out if output_sizes_complete else None,
        "saved": saved if output_sizes_complete else None,
        "errors": errors,
        "status_counts": status_counts,
        "source_paths": source_paths,
        "rows": rows,
    }


def pdf_report_matches_inputs(
    report_result: dict[str, Any],
    pdf_files: list[Path],
    *,
    input_dir: Path,
    output_dir: Path,
    preset: str,
    dry_run: bool,
    photo_patterns: list[str] | None = None,
    lossless_jpeg_requested: bool = False,
    photo_dpi: int = 200,
) -> bool:
    """Verify PDF report rows against current source and output bytes."""

    if report_result.get("count") != len(pdf_files):
        return False
    rows = report_result.get("rows")
    if not isinstance(rows, list) or len(rows) != len(pdf_files):
        return False
    verified_outputs: list[tuple[Path, int, str]] = []
    try:
        input_root = input_dir.resolve(strict=True)
        expected_sources = {
            str(path.resolve(strict=True)).casefold(): path.resolve(strict=True)
            for path in pdf_files
        }
        reported = [
            str(Path(row["source_path"]).resolve(strict=False)).casefold()
            for row in rows
        ]
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    if len(set(reported)) != len(reported) or set(reported) != set(expected_sources):
        return False

    try:
        for row in rows:
            source = expected_sources[
                str(Path(row["source_path"]).resolve(strict=False)).casefold()
            ]
            relative = source.relative_to(input_root)
            expected_output = output_dir / relative
            if Path(row["output_path"]).resolve(strict=False) != expected_output.resolve(
                strict=False
            ):
                return False
            if row["preset"] != preset:
                return False
            if row.get("lossless_jpeg_requested") is not lossless_jpeg_requested:
                return False
            if row["profile"] != _pdf_profile(relative, preset, photo_patterns or []):
                return False
            expected_dpi = photo_dpi if row["profile"] == "photo" else None
            if row.get("photo_dpi") != expected_dpi or (
                expected_dpi is not None and type(row.get("photo_dpi")) is not int
            ):
                return False

            source_size, source_sha256 = _stable_file_size_and_sha256(source)
            if (
                row["source_size"] != source_size
                or row["source_sha256"] != source_sha256
            ):
                return False

            status = row["status"]
            output_size = row["output_size"]
            output_sha256 = row["output_sha256"]
            saved_bytes = row["saved_bytes"]
            saved_percent = row["saved_percent"]
            if dry_run:
                if status not in {"DRY_RUN_LOSSLESS", "DRY_RUN_LOSSY", "ERROR"}:
                    return False
                if (
                    output_size is not None
                    or output_sha256
                    or saved_bytes != 0
                    or saved_percent != 0
                ):
                    return False
                continue
            if status in {"DRY_RUN_LOSSLESS", "DRY_RUN_LOSSY"}:
                return False
            if output_size is None:
                if (
                    status != "ERROR"
                    or output_sha256
                    or saved_bytes != 0
                    or saved_percent != 0
                ):
                    return False
                continue
            if not output_sha256:
                return False
            if (
                not expected_output.is_file()
                or _is_link_or_junction(expected_output)
                or expected_output.stat().st_nlink > 1
            ):
                return False
            actual_output_size, actual_output_sha256 = _stable_file_size_and_sha256(
                expected_output
            )
            if (
                output_size != actual_output_size
                or output_sha256 != actual_output_sha256
            ):
                return False
            if not _is_safe_result_file(expected_output, pdf_files):
                return False
            if output_size <= 0 or not _has_stable_pdf_header(expected_output):
                return False
            verified_outputs.append((expected_output, output_size, output_sha256))
            expected_saved = source_size - output_size
            expected_percent = expected_saved / source_size if source_size else 0.0
            if saved_bytes != expected_saved or not math.isclose(
                saved_percent,
                expected_percent,
                rel_tol=1e-9,
                abs_tol=1e-12,
            ):
                return False
            if status in PDF_COPY_STATUSES | {"ERROR"}:
                if output_size != source_size or output_sha256 != source_sha256:
                    return False
            elif status == "ADOPTED_LOSSLESS":
                if output_size <= 0 or saved_bytes < 16 * 1024 or saved_percent < 0.02:
                    return False
            elif status == "ADOPTED_LOSSY":
                min_saved_bytes = (64 if row["profile"] == "photo" else 256) * 1024
                if output_size <= 0 or saved_bytes < min_saved_bytes or saved_percent < 0.05:
                    return False
            else:
                return False
        for output_path, output_size, output_sha256 in verified_outputs:
            if (
                not _is_safe_result_file(output_path, pdf_files)
                or not _has_stable_pdf_header(output_path)
                or _stable_file_size_and_sha256(output_path)
                != (output_size, output_sha256)
                or not _is_safe_result_file(output_path, pdf_files)
            ):
                return False
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        return False
    return True


def _parse_optional_video_int(row: dict[str, str | None], field: str) -> int | None:
    raw_value = row.get(field)
    if raw_value in (None, ""):
        return None
    value = int(raw_value)
    if value <= 0:
        raise ValueError(f"video report {field} must be positive when present")
    return value


def _parse_optional_video_float(
    row: dict[str, str | None],
    field: str,
    *,
    minimum: float,
    maximum: float | None = None,
    minimum_inclusive: bool = False,
) -> float | None:
    raw_value = row.get(field)
    if raw_value in (None, ""):
        return None
    value = float(raw_value)
    if not math.isfinite(value):
        raise ValueError(f"video report {field} must be finite")
    below_minimum = value < minimum if minimum_inclusive else value <= minimum
    if below_minimum or (maximum is not None and value > maximum):
        raise ValueError(f"video report {field} is outside its valid range")
    return value


def parse_video_report(report_path: Path) -> dict[str, Any]:
    """Parse the atomic video report without trusting child stdout summaries."""

    total_in = 0
    total_out = 0
    count = 0
    errors = 0
    output_sizes_complete = True
    status_counts: dict[str, int] = {}
    source_paths: list[str] = []
    presets: list[str] = []
    rows: list[dict[str, Any]] = []

    if not report_path.exists():
        return {}

    try:
        with open(report_path, "r", newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or not VIDEO_REPORT_REQUIRED_COLUMNS.issubset(
                reader.fieldnames
            ):
                raise ValueError("required video report columns are missing")
            for row in reader:
                if None in row:
                    raise ValueError("video report row has unexpected extra columns")
                source_path = row.get("source_path")
                if not source_path:
                    raise ValueError("video report row has no source_path")
                source_paths.append(source_path)
                preset = row.get("preset") or ""
                if preset not in {"standard", "compact"}:
                    raise ValueError(f"unknown video report preset: {preset!r}")
                presets.append(preset)
                raw_input = row.get("source_size")
                if raw_input in (None, ""):
                    raise ValueError("video report row has no source_size")
                input_size = int(raw_input)
                if input_size < 0:
                    raise ValueError("video report source_size must not be negative")
                total_in += input_size
                raw_output = row.get("output_size")
                if raw_output in (None, ""):
                    output_size = None
                    output_sizes_complete = False
                else:
                    output_size = int(raw_output)
                    if output_size < 0:
                        raise ValueError("video report output_size must not be negative")
                    total_out += output_size
                raw_saved = row.get("saved_bytes")
                if raw_saved in (None, ""):
                    raise ValueError("video report row has no saved_bytes")
                saved_bytes = int(raw_saved)
                raw_saved_percent = row.get("saved_percent")
                if raw_saved_percent in (None, ""):
                    raise ValueError("video report row has no saved_percent")
                saved_percent = float(raw_saved_percent)
                if not math.isfinite(saved_percent):
                    raise ValueError("video report saved_percent must be finite")
                status = row.get("status") or ""
                if status not in VIDEO_REPORT_STATUSES:
                    raise ValueError(f"unknown video report status: {status!r}")
                status_counts[status] = status_counts.get(status, 0) + 1
                if status == "ERROR":
                    errors += 1
                output_path = row.get("output_path") or ""
                source_sha256 = (row.get("source_sha256") or "").lower()
                output_sha256 = (row.get("output_sha256") or "").lower()
                if not output_path:
                    raise ValueError("video report row has no output_path")
                if not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
                    raise ValueError("video report source_sha256 is invalid")
                if output_sha256 and not re.fullmatch(r"[0-9a-f]{64}", output_sha256):
                    raise ValueError("video report output_sha256 is invalid")
                reason = row.get("reason") or ""
                if not reason.strip():
                    raise ValueError("video report reason must not be empty")
                video_codec = (row.get("video_codec") or "").casefold()
                audio_codec = (row.get("audio_codec") or "").casefold()
                width = _parse_optional_video_int(row, "width")
                height = _parse_optional_video_int(row, "height")
                fps = _parse_optional_video_float(row, "fps", minimum=0.0)
                duration = _parse_optional_video_float(row, "duration", minimum=0.0)
                vmaf_mean = _parse_optional_video_float(
                    row,
                    "vmaf_mean",
                    minimum=0.0,
                    maximum=100.0,
                    minimum_inclusive=True,
                )
                vmaf_p5 = _parse_optional_video_float(
                    row,
                    "vmaf_p5",
                    minimum=0.0,
                    maximum=100.0,
                    minimum_inclusive=True,
                )
                ffmpeg_version = row.get("ffmpeg_version") or ""
                rows.append(
                    {
                        "source_path": source_path,
                        "source_size": input_size,
                        "output_path": output_path,
                        "output_size": output_size,
                        "saved_bytes": saved_bytes,
                        "saved_percent": saved_percent,
                        "status": status,
                        "error_message": row.get("error_message") or "",
                        "preset": preset,
                        "source_sha256": source_sha256,
                        "output_sha256": output_sha256,
                        "reason": reason,
                        "video_codec": video_codec,
                        "audio_codec": audio_codec,
                        "width": width,
                        "height": height,
                        "fps": fps,
                        "duration": duration,
                        "vmaf_mean": vmaf_mean,
                        "vmaf_p5": vmaf_p5,
                        "ffmpeg_version": ffmpeg_version,
                    }
                )
                count += 1
    except Exception as exc:
        logging.warning("Failed to parse video report %s: %s", report_path, exc)
        return {}

    return {
        "count": count,
        "orig_size": total_in,
        "new_size": total_out if output_sizes_complete else None,
        "saved": total_in - total_out if output_sizes_complete else None,
        "errors": errors,
        "status_counts": status_counts,
        "source_paths": source_paths,
        "presets": presets,
        "rows": rows,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _video_metadata_ranges_are_valid(row: dict[str, Any]) -> bool:
    if not isinstance(row.get("reason"), str) or not row["reason"].strip():
        return False
    if any(
        not isinstance(row.get(field), str)
        for field in ("video_codec", "audio_codec", "ffmpeg_version")
    ):
        return False
    for field in ("width", "height"):
        value = row.get(field)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
        ):
            return False
    for field in ("fps", "duration"):
        value = row.get(field)
        if value is not None and (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value <= 0
        ):
            return False
    for field in ("vmaf_mean", "vmaf_p5"):
        value = row.get(field)
        if value is not None and (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or not 0 <= value <= 100
        ):
            return False
    return True


def _video_adopted_metadata_matches(row: dict[str, Any], output_path: Path) -> bool:
    width = row.get("width")
    height = row.get("height")
    fps = row.get("fps")
    duration = row.get("duration")
    vmaf_mean = row.get("vmaf_mean")
    vmaf_p5 = row.get("vmaf_p5")
    if any(value is None for value in (width, height, fps, duration, vmaf_mean, vmaf_p5)):
        return False
    suffix = output_path.suffix.casefold()
    expected_audio_codec = "aac" if suffix in {".mp4", ".m4v"} else "opus"
    if suffix not in VIDEO_EXTENSIONS:
        return False
    return (
        row["video_codec"].casefold() == "av1"
        and row["audio_codec"].casefold() in {"", expected_audio_codec}
        and width <= VIDEO_MAX_WIDTH
        and height <= VIDEO_MAX_HEIGHT
        and width % 2 == 0
        and height % 2 == 0
        and fps <= VIDEO_MAX_FPS
        and vmaf_mean >= VIDEO_MIN_VMAF_MEAN
        and vmaf_p5 >= VIDEO_MIN_VMAF_P5
        and bool(row["ffmpeg_version"].strip())
    )


def video_report_matches_inputs(
    report_result: dict[str, Any],
    video_files: list[Path],
    *,
    input_dir: Path,
    output_dir: Path,
    preset: str,
    dry_run: bool,
) -> bool:
    """Validate every reported source, planned output, size, and content identity."""

    if report_result.get("count") != len(video_files):
        return False
    raw_paths = report_result.get("source_paths")
    raw_presets = report_result.get("presets")
    rows = report_result.get("rows")
    if not isinstance(raw_paths, list) or len(raw_paths) != len(video_files):
        return False
    if not isinstance(raw_presets, list) or raw_presets != [preset] * len(video_files):
        return False
    if not isinstance(rows, list) or len(rows) != len(video_files):
        return False
    verified_outputs: list[tuple[Path, int, str]] = []
    try:
        input_root = input_dir.resolve(strict=True)
        output_root = output_dir.resolve(strict=False)
        expected_by_key = {
            str(path.resolve(strict=True)).casefold(): path.resolve(strict=True)
            for path in video_files
        }
        reported = [str(Path(path).resolve(strict=False)).casefold() for path in raw_paths]
        if len(set(reported)) != len(reported) or set(reported) != set(expected_by_key):
            return False
        for row in rows:
            if not isinstance(row, dict):
                return False
            if not _video_metadata_ranges_are_valid(row):
                return False
            source_key = str(Path(row["source_path"]).resolve(strict=False)).casefold()
            source = expected_by_key.get(source_key)
            if source is None:
                return False
            source_stat_before = source.stat()
            if row["source_size"] != source_stat_before.st_size:
                return False
            if row["source_sha256"] != _sha256_file(source):
                return False
            source_stat_after = source.stat()
            if (
                source_stat_after.st_dev != source_stat_before.st_dev
                or source_stat_after.st_ino != source_stat_before.st_ino
                or source_stat_after.st_size != source_stat_before.st_size
                or source_stat_after.st_mtime_ns != source_stat_before.st_mtime_ns
                or source_stat_after.st_ctime_ns != source_stat_before.st_ctime_ns
            ):
                return False
            expected_output = output_root / source.relative_to(input_root)
            reported_output = Path(row["output_path"]).resolve(strict=False)
            if str(reported_output).casefold() != str(expected_output.resolve(strict=False)).casefold():
                return False
            output_size = row["output_size"]
            saved_bytes = row["saved_bytes"]
            expected_saved = (
                source_stat_before.st_size - output_size if output_size is not None else 0
            )
            if saved_bytes != expected_saved:
                return False
            expected_percent = (
                expected_saved / source_stat_before.st_size * 100
                if output_size is not None and source_stat_before.st_size
                else 0.0
            )
            if not math.isclose(
                row["saved_percent"], expected_percent, rel_tol=0.0, abs_tol=0.000001
            ):
                return False
            if row["preset"] != preset:
                return False
            if dry_run:
                if (
                    row["status"] != "DRY_RUN"
                    or output_size is not None
                    or row["output_sha256"]
                    or row["error_message"]
                ):
                    return False
                continue
            if row["status"] == "DRY_RUN":
                return False
            if preset == "compact" and row["status"] == "SKIPPED_STANDARD":
                return False
            if output_size is None:
                if (
                    row["status"] != "ERROR"
                    or not row["error_message"]
                    or row["output_sha256"]
                ):
                    return False
                continue
            if not expected_output.is_file() or _is_link_or_junction(expected_output):
                return False
            output_stat = expected_output.stat()
            if output_stat.st_nlink > 1 or output_stat.st_size != output_size:
                return False
            if not row["output_sha256"] or row["output_sha256"] != _sha256_file(expected_output):
                return False
            output_stat_after = expected_output.stat()
            if (
                output_stat_after.st_dev != output_stat.st_dev
                or output_stat_after.st_ino != output_stat.st_ino
                or output_stat_after.st_size != output_stat.st_size
                or output_stat_after.st_mtime_ns != output_stat.st_mtime_ns
                or output_stat_after.st_ctime_ns != output_stat.st_ctime_ns
            ):
                return False
            if not _is_safe_result_file(expected_output, video_files):
                return False
            verified_outputs.append(
                (expected_output, output_size, row["output_sha256"])
            )
            is_exact_copy = (
                output_size == source_stat_before.st_size
                and saved_bytes == 0
                and row["saved_percent"] == 0.0
                and row["output_sha256"] == row["source_sha256"]
            )
            if row["status"] in {
                "UNCHANGED",
                "SKIPPED_STANDARD",
                "SKIPPED_COMPLEX",
                "SKIPPED_UNSUPPORTED",
            }:
                if row["error_message"] or not is_exact_copy:
                    return False
            elif row["status"] == "ERROR":
                if not row["error_message"] or not is_exact_copy:
                    return False
            elif row["status"] in {"ADOPTED", "SKIPPED_COMPLETE"}:
                if row["error_message"]:
                    return False
                is_adopted_shape = (
                    output_size > 0
                    and saved_bytes >= VIDEO_MIN_SAVED_BYTES
                    and row["saved_percent"] >= VIDEO_MIN_SAVED_PERCENT
                    and preset == "compact"
                    and _video_adopted_metadata_matches(row, expected_output)
                )
                if row["status"] == "ADOPTED" and not is_adopted_shape:
                    return False
                if row["status"] == "SKIPPED_COMPLETE" and not (
                    is_exact_copy or is_adopted_shape
                ):
                    return False
            else:
                return False
        for output_path, output_size, output_sha256 in verified_outputs:
            if (
                not _is_safe_result_file(output_path, video_files)
                or _stable_file_size_and_sha256(output_path)
                != (output_size, output_sha256)
                or not _is_safe_result_file(output_path, video_files)
            ):
                return False
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        return False
    return True


def _parse_optional_image_int(
    row: dict[str, str | None],
    field: str,
    *,
    positive: bool,
) -> int | None:
    raw_value = row.get(field)
    if raw_value in (None, ""):
        return None
    value = int(raw_value)
    if value < (1 if positive else 0):
        raise ValueError(f"image manifest {field} is outside its valid range")
    return value


def parse_image_manifest(report_path: Path) -> dict[str, Any]:
    """Parse the atomic all-result image manifest without trusting stdout."""

    try:
        report_is_unsafe = (
            not report_path.is_file()
            or _is_link_or_junction(report_path)
            or report_path.stat().st_nlink > 1
        )
    except OSError:
        return {}
    if report_is_unsafe:
        return {}
    before = _file_signature(report_path)
    rows: list[dict[str, Any]] = []
    total_in = 0
    total_out = 0
    output_sizes_complete = True
    errors = 0
    try:
        with report_path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or not IMAGE_MANIFEST_REQUIRED_COLUMNS.issubset(
                reader.fieldnames
            ):
                raise ValueError("required image manifest columns are missing")
            for raw_row in reader:
                if None in raw_row:
                    raise ValueError("image manifest row has unexpected extra columns")
                source_path = raw_row.get("source_path") or ""
                output_path = raw_row.get("output_path") or ""
                if not source_path or not output_path:
                    raise ValueError("image manifest paths must not be empty")
                source_size = _parse_optional_image_int(
                    raw_row, "source_size", positive=False
                )
                if source_size is None:
                    raise ValueError("image manifest source_size is required")
                output_size = _parse_optional_image_int(
                    raw_row, "output_size", positive=True
                )
                source_sha256 = (raw_row.get("source_sha256") or "").lower()
                output_sha256 = (raw_row.get("output_sha256") or "").lower()
                recipe_hash = (raw_row.get("recipe_hash") or "").lower()
                if not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
                    raise ValueError("image manifest source_sha256 is invalid")
                if output_sha256 and not re.fullmatch(r"[0-9a-f]{64}", output_sha256):
                    raise ValueError("image manifest output_sha256 is invalid")
                if not re.fullmatch(r"[0-9a-f]{64}", recipe_hash):
                    raise ValueError("image manifest recipe_hash is invalid")
                preset = raw_row.get("preset") or ""
                if preset not in IMAGE_RECIPE_HASHES:
                    raise ValueError(f"unknown image manifest preset: {preset!r}")
                action = raw_row.get("action") or ""
                if action not in IMAGE_NORMAL_ACTIONS | IMAGE_DRY_RUN_ACTIONS | {"ERROR"}:
                    raise ValueError(f"unknown image manifest action: {action!r}")
                row = {
                    "source_path": source_path,
                    "source_size": source_size,
                    "source_sha256": source_sha256,
                    "output_path": output_path,
                    "output_size": output_size,
                    "output_sha256": output_sha256,
                    "action": action,
                    "error": raw_row.get("error") or "",
                    "preset": preset,
                    "recipe_hash": recipe_hash,
                    "orig_width": _parse_optional_image_int(
                        raw_row, "orig_width", positive=True
                    ),
                    "orig_height": _parse_optional_image_int(
                        raw_row, "orig_height", positive=True
                    ),
                    "new_width": _parse_optional_image_int(
                        raw_row, "new_width", positive=True
                    ),
                    "new_height": _parse_optional_image_int(
                        raw_row, "new_height", positive=True
                    ),
                }
                rows.append(row)
                total_in += source_size
                if output_size is None:
                    output_sizes_complete = False
                else:
                    total_out += output_size
                if row["error"]:
                    errors += 1
        if before is None or _file_signature(report_path) != before:
            raise OSError("image manifest changed while reading")
    except Exception as exc:
        logging.warning("Failed to parse image manifest %s: %s", report_path, exc)
        return {}

    return {
        "count": len(rows) - errors,
        "row_count": len(rows),
        "errors": errors,
        "orig_size": total_in,
        "new_size": total_out if output_sizes_complete else None,
        "saved": total_in - total_out if output_sizes_complete else None,
        "rows": rows,
        "source_paths": [row["source_path"] for row in rows],
    }


def _image_dimensions_are_valid(row: dict[str, Any], preset: str) -> bool:
    original = (row.get("orig_width"), row.get("orig_height"))
    resized = (row.get("new_width"), row.get("new_height"))
    if any(value is None for value in original + resized):
        return False
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0
        for value in original + resized
    ):
        return False
    max_long, max_short = (1024, 768) if preset == "compact" else (1280, 960)
    return max(resized) <= max_long and min(resized) <= max_short


def image_manifest_matches_inputs(
    manifest: dict[str, Any],
    image_files: list[Path],
    *,
    input_dir: Path,
    output_dir: Path,
    preset: str,
    dry_run: bool,
) -> bool:
    """Validate 1:1 paths, recipes, shapes, and current source/output bytes."""

    rows = manifest.get("rows")
    if (
        manifest.get("row_count") != len(image_files)
        or not isinstance(rows, list)
        or len(rows) != len(image_files)
    ):
        return False
    try:
        input_root = input_dir.resolve(strict=True)
        output_root = output_dir.resolve(strict=False)
        expected_plans = _plan_image_destinations(input_root, output_dir, image_files)
        expected_by_source = {
            str(source.resolve(strict=True)).casefold(): (
                source.resolve(strict=True),
                output.resolve(strict=False),
            )
            for source, output in expected_plans
        }
        reported_sources = [
            str(Path(row["source_path"]).resolve(strict=False)).casefold()
            for row in rows
        ]
        if (
            len(set(reported_sources)) != len(reported_sources)
            or set(reported_sources) != set(expected_by_source)
        ):
            return False

        verified: list[tuple[Path, int, str, Path | None, int | None, str]] = []
        for row in rows:
            source_key = str(Path(row["source_path"]).resolve(strict=False)).casefold()
            source, expected_output = expected_by_source[source_key]
            if (
                str(Path(row["output_path"]).resolve(strict=False)).casefold()
                != str(expected_output).casefold()
                or row["preset"] != preset
                or row["recipe_hash"] != IMAGE_RECIPE_HASHES[preset]
            ):
                return False
            source_size, source_sha256 = _stable_file_size_and_sha256(source)
            if (
                row["source_size"] != source_size
                or row["source_sha256"] != source_sha256
            ):
                return False

            action = row["action"]
            error = row["error"]
            output_size = row["output_size"]
            output_sha256 = row["output_sha256"]
            if action == "ERROR":
                if (
                    not error
                    or output_size is not None
                    or output_sha256
                    or any(
                        row[field] is not None
                        for field in ("orig_width", "orig_height", "new_width", "new_height")
                    )
                ):
                    return False
                verified.append((source, source_size, source_sha256, None, None, ""))
                continue
            if not _image_dimensions_are_valid(row, preset):
                return False
            if dry_run:
                if (
                    action not in IMAGE_DRY_RUN_ACTIONS
                    or error
                    or output_size is not None
                    or output_sha256
                ):
                    return False
                verified.append((source, source_size, source_sha256, None, None, ""))
                continue
            if action not in IMAGE_NORMAL_ACTIONS:
                return False
            if error and action != "COPIED_ENCODE_FAILED":
                return False
            if output_size is None or not output_sha256:
                return False
            output_lexical = Path(os.path.abspath(expected_output))
            if (
                not expected_output.is_file()
                or _has_link_component(Path(os.path.abspath(output_dir)), output_lexical)
                or expected_output.stat().st_nlink > 1
            ):
                return False
            actual_size, actual_sha256 = _stable_file_size_and_sha256(expected_output)
            if output_size != actual_size or output_sha256 != actual_sha256:
                return False
            if action in IMAGE_EXACT_COPY_ACTIONS and (
                output_size != source_size or output_sha256 != source_sha256
            ):
                return False
            verified.append(
                (
                    source,
                    source_size,
                    source_sha256,
                    expected_output,
                    output_size,
                    output_sha256,
                )
            )

        # 前段のoutput検証中にsource/outputが変化していないことを再確認する。
        for source, source_size, source_sha256, output, output_size, output_sha256 in verified:
            if _stable_file_size_and_sha256(source) != (source_size, source_sha256):
                return False
            if output is not None and _stable_file_size_and_sha256(output) != (
                output_size,
                output_sha256,
            ):
                return False
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        return False
    return True


def image_errors_match_manifest(
    error_report: Path,
    manifest: dict[str, Any],
) -> bool:
    """互換error-only CSVがmanifestのerror行と完全一致することを確認する。"""

    before = _file_signature(error_report)
    try:
        report_is_unsafe = (
            before is None
            or not error_report.is_file()
            or _is_link_or_junction(error_report)
            or error_report.stat().st_nlink > 1
        )
    except OSError:
        return False
    if report_is_unsafe:
        return False
    try:
        with error_report.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or not {"source", "planned_output", "error"}.issubset(
                reader.fieldnames
            ):
                return False
            actual = []
            for row in reader:
                if None in row or not row.get("source") or not row.get("planned_output") or not row.get("error"):
                    return False
                actual.append(
                    (
                        str(Path(row["source"]).resolve(strict=False)).casefold(),
                        str(Path(row["planned_output"]).resolve(strict=False)).casefold(),
                        row["error"],
                    )
                )
        if _file_signature(error_report) != before:
            return False
        expected = [
            (
                str(Path(row["source_path"]).resolve(strict=False)).casefold(),
                str(Path(row["output_path"]).resolve(strict=False)).casefold(),
                row["error"],
            )
            for row in manifest.get("rows", [])
            if row.get("error")
        ]
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        return False
    return actual == expected


def parse_image_summary(lines: list[str]) -> dict[str, Any] | None:
    count: int | None = None
    errors = 0
    orig_size: int | None = None
    new_size: int | None = None

    for line in lines:
        m = IMAGE_SUMMARY_RE.search(line)
        if m:
            count = int(m.group(1))
            errors = int(m.group(2))
            continue
        m = IMAGE_SIZE_RE.search(line)
        if m:
            orig_size = _to_bytes(float(m.group(1)), m.group(2))
            new_size = _to_bytes(float(m.group(3)), m.group(4))

    if count is None:
        return None

    return {
        "count": count,
        "errors": errors,
        "orig_size": orig_size,
        "new_size": new_size,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="karufile",
        description="PDF・画像・対応動画を、原本を変更せず別フォルダーへ軽量化する",
    )
    parser.add_argument("-i", "--input", required=True, help="入力ディレクトリ")
    parser.add_argument(
        "-o", "--output",
        help="出力ディレクトリ（未指定時は <input>_軽量化）",
    )
    parser.add_argument(
        "--pdf-workers", type=_positive_int, default=2,
        help="pdf-shrink の並列数（デフォルト 2）",
    )
    parser.add_argument(
        "--image-workers", type=_positive_int, default=4,
        help="media-shrink-tool の並列数（デフォルト 4）",
    )
    parser.add_argument(
        "--video-workers", type=_positive_int, default=1,
        help="video-shrink の並列数（デフォルト 1、compactのみ）",
    )
    parser.add_argument(
        "--preset",
        choices=("standard", "compact"),
        default="standard",
        help="圧縮プリセット（デフォルト standard）",
    )
    parser.add_argument(
        "--pdf-photo-pattern",
        action="append",
        type=_pdf_photo_pattern,
        default=[],
        metavar="PATTERN",
        help=(
            "指定した写真中心PDFに閲覧用DPI縮小・JPEG品質80候補を許可（画質劣化あり）。"
            "入力相対パスのglob、大小文字を区別せず、*は/も含む。反復可"
        ),
    )
    parser.add_argument(
        "--pdf-photo-dpi", type=_pdf_photo_dpi, metavar="DPI",
        help="写真PDFの目標DPI（150〜300の整数、既定200、--pdf-photo-pattern必須）",
    )
    parser.add_argument(
        "--pdf-preview", action="store_true",
        help="写真PDFの原本と完成出力を比較する静的HTMLを追加（--pdf-photo-pattern必須）",
    )
    parser.add_argument(
        "--pdf-preview-dpi", type=_pdf_photo_dpi, action="append", default=[], metavar="DPI",
        help="目視比較用の追加DPI候補（150〜300、反復可、最大5種類、--pdf-preview必須）",
    )
    parser.add_argument("--pdf-lossless-jpeg", action="store_true", help="jpegtran 3.2.0のJPEG可逆候補を追加（既定OFF、手動準備）")
    parser.add_argument("--pdf-jpegtran-path", help="PDFで使うjpegtran実行ファイル。指定だけでは有効化しない")
    parser.add_argument(
        "--ffmpeg-path",
        help="compact動画で使うffmpeg実行ファイル（未指定時はPATH）",
    )
    parser.add_argument(
        "--ffprobe-path",
        help="compact動画で使うffprobe実行ファイル（未指定時はPATH）",
    )
    parser.add_argument(
        "-n", "--dry-run", action="store_true",
        help="完成PDF・画像・動画を作らず判定を確認（状態・レポートは更新される場合あり）",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="詳細ログ")
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_console_output()
    args = build_parser().parse_args(argv)

    setup_logging(args.verbose)

    try:
        input_dir = Path(args.input).resolve()
        if args.output:
            output_dir = Path(args.output).resolve()
        else:
            output_dir = (input_dir.parent / f"{input_dir.name}_軽量化").resolve()
        validate_directories(input_dir, output_dir)
        pdf_files = collect_files(input_dir, PDF_EXTENSIONS)
        image_files = collect_files(input_dir, IMAGE_EXTENSIONS)
        video_files = (
            collect_files(input_dir, VIDEO_EXTENSIONS)
            if args.preset == "compact"
            else []
        )
        validate_planned_destinations(
            input_dir, output_dir, pdf_files, image_files, video_files
        )
        validate_derived_write_paths(
            input_dir, output_dir, pdf_files, image_files, video_files,
            pdf_preview=args.pdf_preview,
        )
        source_baseline = _capture_source_baseline(
            [*pdf_files, *image_files, *video_files]
        )
    except (OSError, RuntimeError, ValueError) as exc:
        logging.error("%s", exc)
        return 1

    if not args.dry_run:
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            validate_planned_destinations(
                input_dir, output_dir, pdf_files, image_files, video_files
            )
            validate_derived_write_paths(
                input_dir, output_dir, pdf_files, image_files, video_files,
                pdf_preview=args.pdf_preview,
            )
        except OSError as exc:
            logging.error("出力ディレクトリを作成できません: %s", exc)
            return 1
        except (RuntimeError, ValueError) as exc:
            logging.error("出力作成後の安全性検証に失敗しました: %s", exc)
            return 1

    print("KaruFile")
    print()
    print(f"Input  : {input_dir}")
    print(f"Output : {output_dir}")
    print(f"Preset : {args.preset}")
    print()
    print(f"PDF    : {len(pdf_files)}")
    print(f"Images : {len(image_files)}")
    print(f"Videos : {len(video_files)}")
    print()
    print("Source files : keep")
    print("Files deleted: 0")
    print()
    print("Starting...")
    sys.stdout.flush()

    start = time.perf_counter()
    report_name = "report.dry-run.csv" if args.dry_run else "report.csv"
    pdf_report_path = output_dir.parent / report_name
    pdf_report_before = _file_signature(pdf_report_path)
    pdf_preview_path = output_dir.parent / (
        "pdf-preview.dry-run.json" if args.dry_run else "pdf-preview.json"
    )
    pdf_preview_before = _file_signature(pdf_preview_path) if args.pdf_preview else None
    pdf_preview_index: str | None = None
    image_error_report = Path(f"{output_dir}.image-errors.csv")
    image_report_before = _file_signature(image_error_report)
    image_manifest_path = Path(
        f"{output_dir}.image-manifest.dry-run.csv"
        if args.dry_run
        else f"{output_dir}.image-manifest.csv"
    )
    image_manifest_before = _file_signature(image_manifest_path)
    video_report_path = Path(
        f"{output_dir}.video-report.dry-run.csv"
        if args.dry_run
        else f"{output_dir}.video-report.csv"
    )
    video_report_before = _file_signature(video_report_path)

    # 1. PDF 軽量化
    pdf_exit = 0
    pdf_result = _empty_result()
    if pdf_files or args.pdf_preview:
        pdf_args = [
            "python", "-m", "pdf_shrink", "run",
            "--input", str(input_dir),
            "--output", str(output_dir),
            "--workers", str(args.pdf_workers),
            "--preset", args.preset,
        ]
        pdf_args.extend(f"--photo-pattern={pattern}" for pattern in args.pdf_photo_pattern)
        if args.pdf_photo_pattern:
            pdf_args.extend(["--photo-dpi", str(args.pdf_photo_dpi)])
        if args.pdf_preview:
            pdf_args.append("--preview")
            for dpi in args.pdf_preview_dpi:
                pdf_args.extend(["--preview-dpi", str(dpi)])
        if args.pdf_lossless_jpeg:
            pdf_args.append("--lossless-jpeg")
        if args.pdf_jpegtran_path:
            pdf_args.extend(["--jpegtran-path", args.pdf_jpegtran_path])
        if args.dry_run:
            pdf_args.append("--dry-run")
        if args.verbose:
            pdf_args.append("-v")

        pdf_exit, _pdf_lines, _pdf_elapsed = run_command("pdf-shrink", PDF_SHRINK_DIR, pdf_args)

        if _was_updated(pdf_report_path, pdf_report_before):
            parsed_pdf = parse_pdf_report(pdf_report_path)
            if parsed_pdf and pdf_report_matches_inputs(
                parsed_pdf,
                pdf_files,
                input_dir=input_dir,
                output_dir=output_dir,
                preset=args.preset,
                dry_run=args.dry_run,
                photo_patterns=args.pdf_photo_pattern,
                lossless_jpeg_requested=args.pdf_lossless_jpeg,
                photo_dpi=args.pdf_photo_dpi,
            ):
                pdf_result = parsed_pdf
                if parsed_pdf.get("errors", 0) > 0:
                    pdf_exit = pdf_exit or 1
            else:
                logging.error(
                    "PDF report does not match the current input set: %s",
                    pdf_report_path,
                )
                pdf_result = _unavailable_result()
                pdf_exit = pdf_exit or 1
        else:
            logging.error("PDF report was not updated by this run: %s", pdf_report_path)
            pdf_result = _unavailable_result()
            pdf_exit = pdf_exit or 1

        if args.pdf_preview:
            preview = validate_pdf_preview_manifest(
                pdf_preview_path,
                previous=pdf_preview_before,
                report_result=pdf_result,
                input_dir=input_dir,
                output_dir=output_dir,
                photo_dpi=args.pdf_photo_dpi,
                preview_dpis=args.pdf_preview_dpi,
                dry_run=args.dry_run,
            )
            if preview is None:
                logging.error("PDF preview manifest is missing, stale, unsafe, or inconsistent: %s", pdf_preview_path)
                pdf_exit = pdf_exit or 1
            elif preview["status"] == "ERROR":
                logging.error("PDF preview generation failed: %s", "; ".join(preview["errors"]))
                pdf_exit = pdf_exit or 1
            else:
                pdf_preview_index = preview["index_path"]

    # 2. 画像リサイズ
    image_args = [
        "python", "-m", "media_shrink", "resize",
        "-i", str(input_dir),
        "-o", str(output_dir),
        "-j", str(args.image_workers),
        "--preset", args.preset,
    ]
    if args.dry_run:
        image_args.append("-n")
    if args.verbose:
        image_args.append("-v")

    image_exit, _image_lines, _image_elapsed = run_command(
        "media-shrink", MEDIA_SHRINK_DIR, image_args
    )
    image_report_updated = _was_updated(image_error_report, image_report_before)
    if not image_report_updated:
        logging.error("Image error report was not updated by this run: %s", image_error_report)
        image_exit = image_exit or 1
    image_result = _unavailable_result()
    if _was_updated(image_manifest_path, image_manifest_before):
        parsed_image = parse_image_manifest(image_manifest_path)
        if (
            parsed_image
            and image_manifest_matches_inputs(
                parsed_image,
                image_files,
                input_dir=input_dir,
                output_dir=output_dir,
                preset=args.preset,
                dry_run=args.dry_run,
            )
            and image_report_updated
            and image_errors_match_manifest(image_error_report, parsed_image)
        ):
            image_result = parsed_image
            if parsed_image.get("errors", 0) > 0:
                image_exit = image_exit or 1
        else:
            logging.error(
                "Image manifest does not match current inputs/outputs/errors: %s",
                image_manifest_path,
            )
            image_exit = image_exit or 1
    else:
        logging.error("Image manifest was not updated by this run: %s", image_manifest_path)
        image_exit = image_exit or 1

    # 3. compact動画軽量化。standardでは既存v1互換のため動画を探索・起動しない。
    video_exit = 0
    video_result = _empty_result()
    video_report_updated = False
    if video_files:
        video_args = [
            "python", "-m", "video_shrink", "run",
            "--input", str(input_dir),
            "--output", str(output_dir),
            "--workers", str(args.video_workers),
            "--preset", args.preset,
        ]
        if args.dry_run:
            video_args.append("--dry-run")
        if args.ffmpeg_path:
            video_args.extend(["--ffmpeg-path", args.ffmpeg_path])
        if args.ffprobe_path:
            video_args.extend(["--ffprobe-path", args.ffprobe_path])
        if args.verbose:
            video_args.append("-v")

        video_exit, _video_lines, _video_elapsed = run_command(
            "video-shrink", VIDEO_SHRINK_DIR, video_args
        )
        video_report_updated = _was_updated(video_report_path, video_report_before)
        if video_report_updated:
            parsed_video = parse_video_report(video_report_path)
            if parsed_video and video_report_matches_inputs(
                parsed_video,
                video_files,
                input_dir=input_dir,
                output_dir=output_dir,
                preset=args.preset,
                dry_run=args.dry_run,
            ):
                video_result = parsed_video
                if parsed_video.get("errors", 0) > 0:
                    video_exit = video_exit or 1
            else:
                logging.error(
                    "Video report does not match the current input set: %s",
                    video_report_path,
                )
                video_result = _unavailable_result()
                video_exit = video_exit or 1
        else:
            logging.error("Video report was not updated by this run: %s", video_report_path)
            video_result = _unavailable_result()
            video_exit = video_exit or 1

    # 4. 結果集計。画像はstdoutではなく検証済みmanifestのexact totalsを使う。
    source_integrity_ok = _source_baseline_matches(source_baseline)
    source_exit = 0
    if not source_integrity_ok:
        logging.error("Input source files changed or could not be verified during this run")
        source_exit = 1
        pdf_result = _unavailable_result()
        image_result = _unavailable_result()
        video_result = _unavailable_result()
    elapsed = time.perf_counter() - start

    # 5. 統合サマリー
    pdf_orig = pdf_result.get("orig_size", 0)
    pdf_new = pdf_result.get("new_size", 0)
    pdf_errors = pdf_result.get("errors", 0)

    img_orig = image_result.get("orig_size", 0)
    img_new = image_result.get("new_size", 0)
    img_errors = image_result.get("errors", 0)

    video_orig = video_result.get("orig_size", 0)
    video_new = video_result.get("new_size", 0)
    video_errors = video_result.get("errors", 0)

    original_known = all(isinstance(value, int) for value in (pdf_orig, img_orig, video_orig))
    output_known = all(isinstance(value, int) for value in (pdf_new, img_new, video_new))
    total_orig = pdf_orig + img_orig + video_orig if original_known else None
    total_new = pdf_new + img_new + video_new if output_known else None
    totals_known = total_orig is not None and total_new is not None
    total_saved = total_orig - total_new if totals_known else None
    reduction = (
        total_saved / total_orig * 100
        if totals_known and total_orig
        else 0.0 if totals_known else None
    )

    print()
    print("KaruFile completed")
    print()
    print(f"PDF errors   : {pdf_errors if pdf_errors is not None else 'unknown'}")
    print(f"Image errors : {img_errors if img_errors is not None else 'unknown'}")
    print(f"Video errors : {video_errors if video_errors is not None else 'unknown'}")
    print()
    if args.dry_run:
        print(f"Original size : {human_size(total_orig) if total_orig is not None else 'unknown'}")
        print("Output size   : not written (dry-run)")
        print("Saved         : not calculated (dry-run)")
        print("Reduction     : not calculated (dry-run)")
    else:
        print(f"Original size : {human_size(total_orig) if total_orig is not None else 'unknown'}")
        print(f"Output size   : {human_size(total_new) if total_new is not None else 'unknown'}")
        print(f"Saved         : {human_size(total_saved) if total_saved is not None else 'unknown'}")
        print(f"Reduction     : {f'{reduction:.2f}%' if reduction is not None else 'unknown'}")
    print()
    print(
        "Source files changed: "
        + ("NO" if source_integrity_ok else "YES OR COULD NOT VERIFY")
    )
    print("Files deleted       : 0")
    print()
    print("Image error report:")
    if image_report_updated:
        print(image_error_report)
    else:
        print(f"{image_error_report} (not updated this run)")
    if video_files:
        print("Video report:")
        if video_report_updated:
            print(video_report_path)
        else:
            print(f"{video_report_path} (not updated this run)")
    print(f"Elapsed: {elapsed:.2f}s")
    if pdf_preview_index:
        print(f"PDF preview: {pdf_preview_index}")

    if args.dry_run:
        print("\n[DRY-RUN] PDF・画像・動画出力は作成しません。状態とレポートは更新される場合があります。")

    return 0 if (
        pdf_exit == 0
        and image_exit == 0
        and video_exit == 0
        and source_exit == 0
    ) else 1


if __name__ == "__main__":
    sys.exit(main())
