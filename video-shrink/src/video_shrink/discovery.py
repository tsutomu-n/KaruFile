"""Safe video discovery and immutable source snapshots."""
from __future__ import annotations

import os
from pathlib import Path

from .config import SUPPORTED_EXTENSIONS
from .models import SourceSnapshot
from .utils import PathValidationError, is_link_like, is_within, stable_sha256_file


def collect_videos(input_dir: Path) -> list[Path]:
    root = input_dir.resolve(strict=True)
    found: list[Path] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise PathValidationError(f"cannot scan input directory {directory}: {exc}") from exc
        for entry in entries:
            path = Path(entry.path)
            if is_link_like(path):
                raise PathValidationError(f"linked input paths are not supported: {path}")
            try:
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                resolved = path.resolve(strict=True)
            except OSError as exc:
                raise PathValidationError(f"cannot inspect input path {path}: {exc}") from exc
            if not is_within(resolved, root):
                raise PathValidationError(f"input path resolves outside input root: {path}")
            if resolved.suffix.lower() in SUPPORTED_EXTENSIONS:
                found.append(resolved)
    return sorted(
        found,
        key=lambda path: (
            path.relative_to(root).as_posix().casefold(),
            path.relative_to(root).as_posix(),
        ),
    )


def snapshot(path: Path, input_dir: Path) -> SourceSnapshot:
    resolved = path.resolve(strict=True)
    root = input_dir.resolve(strict=True)
    if not is_within(resolved, root):
        raise PathValidationError(f"input file resolves outside input root: {path}")
    digest, identity = stable_sha256_file(resolved)
    return SourceSnapshot(
        path=resolved,
        relative_path=resolved.relative_to(root),
        sha256=digest,
        identity=identity,
    )


def source_is_unchanged(source: SourceSnapshot) -> bool:
    try:
        digest, _identity = stable_sha256_file(
            source.path,
            expected_identity=source.identity,
        )
        return digest == source.sha256
    except OSError:
        return False
