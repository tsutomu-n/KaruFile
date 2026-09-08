"""Safety checks and atomic publication."""
from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

from .models import FileIdentity
from .utils import (
    PathValidationError,
    has_link_component,
    is_link_like,
    is_within,
    make_writable,
    stable_sha256_file,
    stat_file_identity,
)


def _same_as_protected(path: Path, protected_sources: Sequence[Path]) -> bool:
    for source in protected_sources:
        try:
            if os.path.samefile(path, source):
                return True
        except OSError:
            continue
    return False


def validate_destination(
    destination: Path,
    *,
    input_root: Path,
    output_root: Path,
    protected_sources: Sequence[Path],
) -> None:
    input_resolved = input_root.resolve(strict=True)
    output_resolved = output_root.resolve(strict=False)
    output_lexical = Path(os.path.abspath(output_root))
    destination_lexical = Path(os.path.abspath(destination))
    if not is_within(destination_lexical, output_lexical):
        raise PathValidationError(f"destination is outside output root: {destination}")
    if has_link_component(output_lexical, destination_lexical):
        raise PathValidationError(f"destination contains a link or junction: {destination}")
    resolved = destination.resolve(strict=False)
    if not is_within(resolved, output_resolved):
        raise PathValidationError(f"destination resolves outside output root: {destination}")
    if is_within(resolved, input_resolved):
        raise PathValidationError(f"destination resolves into input root: {destination}")
    if destination.exists():
        if destination.is_dir():
            raise PathValidationError(f"destination is a directory: {destination}")
        if is_link_like(destination):
            raise PathValidationError(f"destination is linked: {destination}")
        info = destination.stat()
        if info.st_nlink > 1:
            raise PathValidationError(f"destination is a hardlink: {destination}")
        if _same_as_protected(destination, protected_sources):
            raise PathValidationError(f"destination aliases an input source: {destination}")


def validate_auxiliary_path(
    candidate: Path,
    *,
    input_root: Path,
    output_root: Path,
    protected_sources: Sequence[Path],
) -> None:
    work_root = Path(os.path.abspath(output_root.parent))
    candidate_lexical = Path(os.path.abspath(candidate))
    if not is_within(candidate_lexical, work_root):
        raise PathValidationError(f"auxiliary path is outside work root: {candidate}")
    if has_link_component(work_root, candidate_lexical):
        raise PathValidationError(f"auxiliary path contains a link or junction: {candidate}")
    resolved = candidate.resolve(strict=False)
    input_resolved = input_root.resolve(strict=True)
    output_resolved = output_root.resolve(strict=False)
    if is_within(resolved, input_resolved) or is_within(input_resolved, resolved):
        raise PathValidationError(f"auxiliary path overlaps input: {candidate}")
    if is_within(resolved, output_resolved) or is_within(output_resolved, resolved):
        raise PathValidationError(f"auxiliary path overlaps output mirror: {candidate}")
    if candidate.exists():
        if is_link_like(candidate):
            raise PathValidationError(f"auxiliary path is linked: {candidate}")
        if not candidate.is_dir() and candidate.stat().st_nlink > 1:
            raise PathValidationError(f"auxiliary path is a hardlink: {candidate}")
        if not candidate.is_dir() and _same_as_protected(candidate, protected_sources):
            raise PathValidationError(f"auxiliary path aliases an input source: {candidate}")


@contextmanager
def staged_destination(
    destination: Path,
    *,
    input_root: Path,
    output_root: Path,
    protected_sources: Sequence[Path],
) -> Iterator[Path]:
    validate_destination(
        destination,
        input_root=input_root,
        output_root=output_root,
        protected_sources=protected_sources,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    validate_destination(
        destination,
        input_root=input_root,
        output_root=output_root,
        protected_sources=protected_sources,
    )
    descriptor, raw_path = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.stem}.",
        suffix=f".tmp{destination.suffix}",
    )
    os.close(descriptor)
    temporary = Path(raw_path)
    try:
        validate_destination(
            temporary,
            input_root=input_root,
            output_root=output_root,
            protected_sources=protected_sources,
        )
        yield temporary
    finally:
        make_writable(temporary)
        temporary.unlink(missing_ok=True)


def publish_staged(
    temporary: Path,
    destination: Path,
    *,
    input_root: Path,
    output_root: Path,
    protected_sources: Sequence[Path],
) -> None:
    validate_destination(
        destination,
        input_root=input_root,
        output_root=output_root,
        protected_sources=protected_sources,
    )
    # Never chmod the formal destination: it may have been swapped for an input
    # hardlink after validation. Read-only destinations intentionally fail closed.
    validate_destination(
        destination,
        input_root=input_root,
        output_root=output_root,
        protected_sources=protected_sources,
    )
    make_writable(temporary)
    os.replace(temporary, destination)


def atomic_copy(
    source: Path,
    destination: Path,
    *,
    input_root: Path,
    output_root: Path,
    protected_sources: Sequence[Path],
    expected_sha256: str | None = None,
    expected_identity: FileIdentity | None = None,
) -> tuple[int, str]:
    source_identity = stat_file_identity(source)
    if expected_identity is not None and source_identity != expected_identity:
        raise OSError(f"source identity changed before copy: {source}")
    with staged_destination(
        destination,
        input_root=input_root,
        output_root=output_root,
        protected_sources=protected_sources,
    ) as temporary:
        shutil.copy2(source, temporary)
        make_writable(temporary)
        copied_hash, copied_identity = stable_sha256_file(temporary)
        source_hash, _final_source_identity = stable_sha256_file(
            source,
            expected_identity=source_identity,
        )
        if expected_sha256 is not None and source_hash != expected_sha256:
            raise OSError(f"source changed before copy publication: {source}")
        if copied_hash != source_hash:
            raise OSError(f"copied source verification failed: {source}")
        size = copied_identity.size
        publish_staged(
            temporary,
            destination,
            input_root=input_root,
            output_root=output_root,
            protected_sources=protected_sources,
        )
    return size, copied_hash


@contextmanager
def staged_auxiliary(
    destination: Path,
    *,
    input_root: Path,
    output_root: Path,
    protected_sources: Sequence[Path],
) -> Iterator[Path]:
    validate_auxiliary_path(
        destination,
        input_root=input_root,
        output_root=output_root,
        protected_sources=protected_sources,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary = Path(raw_path)
    try:
        yield temporary
    finally:
        make_writable(temporary)
        temporary.unlink(missing_ok=True)


def publish_auxiliary(
    temporary: Path,
    destination: Path,
    *,
    input_root: Path,
    output_root: Path,
    protected_sources: Sequence[Path],
) -> None:
    validate_auxiliary_path(
        destination,
        input_root=input_root,
        output_root=output_root,
        protected_sources=protected_sources,
    )
    # Never chmod the formal auxiliary path for the same hardlink-race reason as
    # media destinations. Only our staged file may be made writable.
    validate_auxiliary_path(
        destination,
        input_root=input_root,
        output_root=output_root,
        protected_sources=protected_sources,
    )
    make_writable(temporary)
    os.replace(temporary, destination)
