"""Bounded path ownership, stable reads and atomic publication.

Link checks are repeated at publication. As with the other local processors,
this is not an OS sandbox against hostile concurrent filesystem modification.
"""
from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .models import FileIdentity, Fingerprint


def identity(value: os.stat_result) -> FileIdentity:
    return FileIdentity(value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def is_link_like(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def check_components(path: Path) -> None:
    path = Path(os.path.abspath(path))
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if is_link_like(current):
            raise ValueError(f"path contains a link or junction: {current}")


def fingerprint(path: Path, expected: Fingerprint | None = None) -> Fingerprint:
    check_components(path)
    before = identity(path.stat())
    if expected is not None and before != expected.identity:
        raise OSError(f"source identity changed: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        opened = identity(os.fstat(stream.fileno()))
        # Windows Python 3.13 stat/fstat can expose different ctime semantics
        # (creation time versus change time). Compare each ctime within its own
        # API and use inode, size and mtime to link the path to the open handle.
        path_key = (before.device, before.inode, before.size, before.mtime_ns)
        opened_key = (opened.device, opened.inode, opened.size, opened.mtime_ns)
        if opened_key != path_key:
            raise OSError(f"file changed while opening: {path}")
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
        if identity(os.fstat(stream.fileno())) != opened:
            raise OSError(f"file changed while reading: {path}")
    check_components(path)
    if identity(path.stat()) != before:
        raise OSError(f"file changed after reading: {path}")
    result = Fingerprint(digest.hexdigest(), before)
    if expected is not None and result != expected:
        raise OSError(f"source contents changed: {path}")
    return result


def _overlaps(left: Path, right: Path) -> bool:
    return left.is_relative_to(right) or right.is_relative_to(left)


def validate_roots(input_dir: Path, output_dir: Path) -> tuple[Path, Path]:
    source = Path(os.path.abspath(input_dir))
    output = Path(os.path.abspath(output_dir))
    check_components(source)
    check_components(output)
    source = source.resolve(strict=True)
    output = output.resolve(strict=False)
    if not source.is_dir():
        raise ValueError(f"input must be a directory: {source}")
    if output.exists() and not output.is_dir():
        raise ValueError(f"output must be a directory: {output}")
    if _overlaps(source, output):
        raise ValueError("input and output must be separate, non-nested directories")
    return source, output


def discover_files(root: Path) -> tuple[Path, ...]:
    files = []
    pending = [root]
    while pending:
        directory = pending.pop()
        check_components(directory)
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                if is_link_like(path):
                    raise ValueError(f"linked inputs are unsupported: {path}")
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    files.append(path)
                else:
                    raise ValueError(f"input is not a regular file or directory: {path}")
    return tuple(sorted(files, key=lambda item: (item.as_posix().casefold(), item.as_posix())))


@dataclass(frozen=True)
class PathGuard:
    input_root: Path
    output_root: Path
    report_path: Path
    work_dir: Path
    sources: tuple[Path, ...]

    def validate(self, path: Path, *, directory: bool = False) -> None:
        lexical = Path(os.path.abspath(path))
        check_components(lexical)
        resolved = lexical.resolve(strict=False)
        allowed = (
            resolved.is_relative_to(self.output_root)
            or resolved == self.report_path
            or resolved.is_relative_to(self.work_dir)
        )
        if not allowed or _overlaps(resolved, self.input_root):
            raise ValueError(f"unsafe output or auxiliary path: {path}")
        if path.exists():
            info = path.stat()
            if directory:
                if not stat.S_ISDIR(info.st_mode):
                    raise ValueError(f"expected directory: {path}")
            else:
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError(f"expected regular file: {path}")
                if info.st_nlink != 1:
                    raise ValueError(f"hard-linked output is unsupported: {path}")
                for source in self.sources:
                    if source.exists() and os.path.samefile(path, source):
                        raise ValueError(f"output aliases an input: {path}")

    def preflight(self, destinations: tuple[Path, ...]) -> None:
        if _overlaps(self.work_dir, self.output_root) or _overlaps(self.report_path, self.output_root):
            raise ValueError("derived Excel paths overlap the output tree")
        self.validate(self.output_root, directory=True)
        self.validate(self.work_dir, directory=True)
        self.validate(self.report_path)
        planned: list[tuple[Path, tuple[str, ...]]] = []
        for destination in destinations:
            self.validate(destination)
            parts = tuple(part.casefold() for part in destination.relative_to(self.output_root).parts)
            for other, other_parts in planned:
                common = min(len(parts), len(other_parts))
                if parts[:common] == other_parts[:common]:
                    raise ValueError(f"planned Excel outputs collide: {destination} / {other}")
            planned.append((destination, parts))

    def make_work_dir(self) -> None:
        self.validate(self.work_dir, directory=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.validate(self.work_dir, directory=True)


@contextmanager
def staged_file(guard: PathGuard, suffix: str) -> Iterator[Path]:
    guard.make_work_dir()
    descriptor, raw = tempfile.mkstemp(prefix="stage-", suffix=suffix, dir=guard.work_dir)
    stage = Path(raw)
    owner = identity(os.fstat(descriptor))
    os.close(descriptor)
    try:
        guard.validate(stage)
        yield stage
    finally:
        # Only unlink the exact inode created here; never recurse or chmod.
        # The core may replace its candidate atomically; leave such files for inspection.
        try:
            guard.validate(stage)
            current = identity(stage.stat())
            if (current.device, current.inode) == (owner.device, owner.inode):
                stage.unlink()
        except (FileNotFoundError, OSError, ValueError):
            pass


def publish(stage: Path, destination: Path, guard: PathGuard, expected: Fingerprint) -> None:
    guard.validate(stage)
    guard.validate(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    guard.validate(destination)
    fingerprint(stage, expected)
    guard.validate(stage)
    guard.validate(destination)
    os.replace(stage, destination)
