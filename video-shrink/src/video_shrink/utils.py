"""Filesystem and hashing helpers."""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import BinaryIO

from .models import FileIdentity


class PathValidationError(ValueError):
    pass


class UnstableFileError(OSError):
    pass


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, FileNotFoundError, OSError):
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def has_link_component(root: Path, candidate: Path) -> bool:
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return True
    current = root
    if is_link_like(current):
        return True
    for part in relative.parts:
        current = current / part
        if is_link_like(current):
            return True
    return False


def make_writable(path: Path) -> None:
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    try:
        path.chmod(mode | stat.S_IWRITE)
    except OSError:
        pass


def _sha256_stream(stream: BinaryIO, chunk_size: int) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(chunk_size):
        digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    with path.open("rb") as stream:
        return _sha256_stream(stream, chunk_size)


def identity_from_stat(value: os.stat_result) -> FileIdentity:
    return FileIdentity(
        device=value.st_dev,
        inode=value.st_ino,
        size=value.st_size,
        mtime_ns=value.st_mtime_ns,
        ctime_ns=value.st_ctime_ns,
    )


def stat_file_identity(path: Path) -> FileIdentity:
    return identity_from_stat(path.stat())


def stable_sha256_file(
    path: Path,
    *,
    expected_identity: FileIdentity | None = None,
    chunk_size: int = 1024 * 1024,
) -> tuple[str, FileIdentity]:
    """Hash a path whose identity stays unchanged for the whole read."""

    path_before = stat_file_identity(path)
    if expected_identity is not None and path_before != expected_identity:
        raise UnstableFileError(f"file identity changed before hashing: {path}")
    digest = sha256_file(path, chunk_size=chunk_size)
    path_after = stat_file_identity(path)
    if path_before != path_after or (
        expected_identity is not None and path_after != expected_identity
    ):
        raise UnstableFileError(f"file identity changed while hashing: {path}")
    return digest, path_after


def validate_input_output(input_dir: Path, output_dir: Path) -> tuple[Path, Path]:
    input_lexical = Path(os.path.abspath(input_dir))
    output_lexical = Path(os.path.abspath(output_dir))
    for label, candidate in (("input", input_lexical), ("output", output_lexical)):
        anchor = Path(candidate.anchor)
        if has_link_component(anchor, candidate):
            raise PathValidationError(f"{label} path contains a link or junction: {candidate}")
    try:
        source = input_dir.resolve(strict=True)
        destination = output_dir.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PathValidationError(f"input/output path cannot be resolved: {exc}") from exc
    if not source.is_dir():
        raise PathValidationError(f"input path is not a directory: {source}")
    if destination.exists() and not destination.is_dir():
        raise PathValidationError(f"output path is not a directory: {destination}")
    source_key = os.path.normcase(str(source))
    destination_key = os.path.normcase(str(destination))
    try:
        common = os.path.normcase(os.path.commonpath((source_key, destination_key)))
    except ValueError:
        common = ""
    if source_key == destination_key:
        raise PathValidationError("input and output directories must be different")
    if common == source_key:
        raise PathValidationError("output directory must not be inside input")
    if common == destination_key:
        raise PathValidationError("input directory must not be inside output")
    return source, destination


def file_identity(path: Path) -> tuple[int, int] | None:
    try:
        value = path.stat()
    except OSError:
        return None
    return value.st_dev, value.st_ino
