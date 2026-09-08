"""入力ディレクトリの検証、PDF探索、処理前スナップショット。"""
from __future__ import annotations

import os
import random
from pathlib import Path

from .models import SourceSnapshot
from .utils import sha256_file


class SourceChangedError(OSError):
    """The input no longer matches its immutable discovery snapshot."""


def _is_nested(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_directories(input_dir: Path, output_dir: Path) -> None:
    if not input_dir.exists():
        raise ValueError(f"Input directory does not exist: {input_dir}")
    if not input_dir.is_dir():
        raise ValueError(f"Input path is not a directory: {input_dir}")
    input_root = input_dir.resolve(strict=True)
    output_root = output_dir.resolve(strict=False)
    if input_root == output_root:
        raise ValueError("Output directory must differ from input directory")
    if _is_nested(input_root, output_root) or _is_nested(output_root, input_root):
        raise ValueError("Input and output directories must not be nested")


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def _stat_signature(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _capture_stable_hash(path: Path) -> tuple[os.stat_result, str]:
    before = path.stat()
    digest = sha256_file(path)
    after = path.stat()
    if _stat_signature(before) != _stat_signature(after):
        raise SourceChangedError(f"Input changed while hashing: {path}")
    return after, digest


def _has_link_component(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
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


def collect_pdfs(input_dir: Path) -> list[Path]:
    """PDFを探索する。symlink/junctionは追跡せず、fail closedにする。"""

    input_root = input_dir.resolve(strict=True)
    found: list[Path] = []
    pending = [input_root]
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise ValueError(f"Could not scan input directory {directory}: {exc}") from exc

        for entry in entries:
            path = Path(entry.path)
            if _is_link_or_junction(path):
                raise ValueError(f"Input symlinks and junctions are not supported: {path}")
            try:
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                resolved = path.resolve(strict=True)
            except OSError as exc:
                raise ValueError(f"Could not inspect input path {path}: {exc}") from exc

            if not _is_nested(input_root, resolved):
                raise ValueError(f"Input file resolves outside the input root: {path}")
            if resolved.suffix.casefold() == ".pdf":
                found.append(resolved)

    return sorted(
        found,
        key=lambda path: (
            path.relative_to(input_root).as_posix().casefold(),
            path.relative_to(input_root).as_posix(),
        ),
    )


def select_pilot(files: list[Path], limit: int | None) -> list[Path]:
    if limit is None or limit >= len(files):
        return list(files)

    largest_count = limit // 2
    by_size = sorted(files, key=lambda path: path.stat().st_size, reverse=True)
    largest = set(by_size[:largest_count])
    remaining = [path for path in files if path not in largest]
    random_sample = random.Random(0).sample(remaining, limit - largest_count)
    return sorted(largest | set(random_sample))


def snapshot(path: Path, input_dir: Path) -> SourceSnapshot:
    input_root = input_dir.resolve(strict=True)
    resolved = path.resolve(strict=True)
    if not _is_nested(input_root, resolved):
        raise ValueError(f"Input file resolves outside the input root: {path}")
    if _has_link_component(input_root, resolved):
        raise ValueError(f"Input path contains a symlink or junction: {path}")
    stat, file_hash = _capture_stable_hash(resolved)
    return SourceSnapshot(
        path=resolved,
        relative_path=resolved.relative_to(input_root),
        sha256=file_hash,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        device=stat.st_dev,
        inode=stat.st_ino,
        ctime_ns=stat.st_ctime_ns,
    )


def assert_source_unchanged(source: SourceSnapshot, input_dir: Path) -> None:
    """Re-hash an input and require its full filesystem identity to be stable."""
    try:
        input_root = input_dir.resolve(strict=True)
        if not _is_nested(input_root, source.path):
            raise SourceChangedError(f"Input escaped its root: {source.path}")
        if _has_link_component(input_root, source.path):
            raise SourceChangedError(
                f"Input path became a symlink or junction: {source.path}"
            )
        resolved = source.path.resolve(strict=True)
        if resolved != source.path:
            raise SourceChangedError(f"Input path identity changed: {source.path}")
        observed, digest = _capture_stable_hash(source.path)
    except SourceChangedError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise SourceChangedError(f"Input changed during processing: {source.path}") from exc
    if _stat_signature(observed) != source.stat_signature or digest != source.sha256:
        raise SourceChangedError(f"Input changed during processing: {source.path}")


def source_is_unchanged(source: SourceSnapshot, input_dir: Path) -> bool:
    try:
        assert_source_unchanged(source, input_dir)
    except SourceChangedError:
        return False
    return True
