"""検証済み候補または原本を出力先へ安全に公開する。"""
from __future__ import annotations

import os
import shutil
import stat
import tempfile
from collections.abc import Iterable
from pathlib import Path

from . import discovery
from .models import SourceSnapshot
from .utils import ensure_dir, sha256_file


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _is_link_or_junction(path: Path) -> bool:
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


def _has_link_component(root: Path, destination: Path) -> bool:
    try:
        relative = destination.relative_to(root)
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


def validate_destination(
    destination: Path,
    *,
    input_root: Path,
    output_root: Path,
    protected_sources: Iterable[Path] = (),
) -> None:
    """公開先が字句上もlink解決後も専用出力root内に留まることを確認する。"""

    input_resolved = input_root.resolve(strict=True)
    output_lexical = Path(os.path.abspath(output_root))
    destination_lexical = Path(os.path.abspath(destination))
    if not _is_within(destination_lexical, output_lexical):
        raise ValueError(f"Output destination is outside the output root: {destination}")
    if _has_link_component(output_lexical, destination_lexical):
        raise ValueError(f"Output destination contains a symlink or junction: {destination}")

    output_resolved = output_root.resolve(strict=False)
    destination_resolved = destination.resolve(strict=False)
    if (
        _is_within(output_resolved, input_resolved)
        or _is_within(input_resolved, output_resolved)
    ):
        raise ValueError("Input and output roots overlap after resolving filesystem links")
    if _is_within(destination_resolved, input_resolved):
        raise ValueError(
            "Output destination resolves into the input root: "
            f"{destination} -> {destination_resolved}"
        )
    if not _is_within(destination_resolved, output_resolved):
        raise ValueError(
            "Output destination escapes the output root after resolving filesystem links: "
            f"{destination} -> {destination_resolved}"
        )
    if destination.exists():
        destination_stat = destination.stat()
        if not destination_stat.st_mode & stat.S_IWRITE:
            raise ValueError(f"Read-only output destination is not replaced: {destination}")
        if destination_stat.st_nlink > 1:
            raise ValueError(f"Output destination is a hard link: {destination}")
        for protected in protected_sources:
            try:
                same_file = protected.exists() and os.path.samefile(destination, protected)
            except OSError as exc:
                raise ValueError(
                    f"Could not verify output identity for {destination}: {exc}"
                ) from exc
            if same_file:
                raise ValueError(
                    "Output destination is a hard link to an input source: "
                    f"{destination} == {protected}"
                )


def _make_writable(path: Path) -> None:
    try:
        mode = path.stat().st_mode
    except FileNotFoundError:
        return
    os.chmod(path, mode | stat.S_IWRITE)


def _stat_signature(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _stable_sha256(path: Path) -> str:
    before = path.stat()
    digest = sha256_file(path)
    after = path.stat()
    if _stat_signature(before) != _stat_signature(after):
        raise OSError(f"Copy source changed while hashing: {path}")
    return digest


def _publish_copy(
    copy_source: Path,
    destination: Path,
    protected_source: SourceSnapshot,
    expected_copy_sha256: str,
    *,
    input_root: Path,
    output_root: Path,
) -> None:
    """同一ディレクトリ内の一時ファイルを経由して出力を置換する。"""
    protected_sources = (protected_source.path,)
    validate_destination(
        destination,
        input_root=input_root,
        output_root=output_root,
        protected_sources=protected_sources,
    )
    ensure_dir(destination.parent)
    validate_destination(
        destination,
        input_root=input_root,
        output_root=output_root,
        protected_sources=protected_sources,
    )
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        # Copying may take long enough for either the input or a generated
        # candidate to be replaced.  Anchor both before starting the copy.
        discovery.assert_source_unchanged(protected_source, input_root)
        if _stable_sha256(copy_source) != expected_copy_sha256:
            raise OSError(f"Copy source does not match its verified digest: {copy_source}")
        shutil.copy2(copy_source, temp_path)
        # copy2 はWindowsのread-only属性も複製する。公開・cleanup前に解除する。
        _make_writable(temp_path)
        if _stable_sha256(temp_path) != expected_copy_sha256:
            raise OSError(f"Staged copy verification failed: {copy_source}")
        os.utime(
            temp_path,
            ns=(protected_source.mtime_ns, protected_source.mtime_ns),
        )
        # Re-hashing the input is comparatively slow, so destination topology
        # must be checked again afterwards.  The final sequence intentionally
        # mirrors the image pipeline: source -> destination -> replace.
        discovery.assert_source_unchanged(protected_source, input_root)
        validate_destination(
            destination,
            input_root=input_root,
            output_root=output_root,
            protected_sources=protected_sources,
        )
        os.replace(temp_path, destination)
    finally:
        _make_writable(temp_path)
        temp_path.unlink(missing_ok=True)


def copy_original(
    source: SourceSnapshot,
    destination: Path,
    *,
    input_root: Path,
    output_root: Path,
) -> None:
    _publish_copy(
        source.path,
        destination,
        source,
        source.sha256,
        input_root=input_root,
        output_root=output_root,
    )


def adopt_candidate(
    original: SourceSnapshot,
    candidate: Path,
    destination: Path,
    candidate_sha256: str,
    *,
    input_root: Path,
    output_root: Path,
) -> None:
    _publish_copy(
        candidate,
        destination,
        original,
        candidate_sha256,
        input_root=input_root,
        output_root=output_root,
    )
