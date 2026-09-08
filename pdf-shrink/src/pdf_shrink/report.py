"""CSVレポートとコンソールサマリー。"""
from __future__ import annotations

import csv
import os
import shutil
import stat
import tempfile
from contextlib import contextmanager
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Iterator

from .models import ProcessStatus
from .state import Record, candidate_details_json
from .utils import human_size, sha256_file


REPORT_COLUMNS = [
    "source_path",
    "source_size",
    "source_sha256",
    "output_path",
    "output_size",
    "output_sha256",
    "saved_bytes",
    "saved_percent",
    "preset",
    "mode",
    "status",
    "page_count",
    "scan_page_ratio",
    "error_message",
    "profile",
    "decision_reason",
    "candidate_size",
    "candidate_saved_bytes",
    "candidate_saved_percent",
    "images_changed",
    "candidate_details",
]

UNCHANGED_REASON_LABELS = {
    "no_eligible_images": "再圧縮・縮小の対象画像なし",
    "no_image_savings": "画像候補が採用されず、画像の書き換えなし",
    "candidate_not_smaller": "候補が原本より小さくならなかった",
    "reduction_below_threshold": "候補の削減量が採用基準未満",
    "quality_rejected": "候補が画質・内容の検証に不合格",
    "not_recorded": "過去の処理で理由を記録していない",
}


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


def _validate_report_destination(
    output_path: Path,
    *,
    input_root: Path,
    work_root: Path,
    protected_sources: Iterable[Path],
) -> None:
    work_lexical = Path(os.path.abspath(work_root))
    output_lexical = Path(os.path.abspath(output_path))
    if not _is_within(output_lexical, work_lexical):
        raise ValueError(f"Report destination is outside the PDF work root: {output_path}")
    if _is_link_or_junction(work_lexical) or _is_link_or_junction(output_lexical):
        raise ValueError(f"Report destination contains a symlink or junction: {output_path}")
    work_resolved = work_root.resolve(strict=False)
    input_resolved = input_root.resolve(strict=True)
    output_resolved = output_path.resolve(strict=False)
    if not _is_within(output_resolved, work_resolved):
        raise ValueError(
            "Report destination escapes the PDF work root after resolving links: "
            f"{output_path} -> {output_resolved}"
        )
    if _is_within(output_resolved, input_resolved) or _is_within(
        input_resolved, output_resolved
    ):
        raise ValueError(
            "Report destination overlaps the input after resolving filesystem links: "
            f"{output_path} -> {output_resolved}"
        )
    if output_path.exists():
        output_stat = output_path.stat()
        if output_path.is_dir():
            raise ValueError(f"Report destination is a directory: {output_path}")
        if not output_stat.st_mode & stat.S_IWRITE:
            raise ValueError(f"Read-only PDF report is not replaced: {output_path}")
        if output_stat.st_nlink > 1:
            raise ValueError(f"Report destination is hard-linked: {output_path}")
        for source in protected_sources:
            if source.exists() and os.path.samefile(output_path, source):
                raise ValueError(
                    "Report destination is a hard link to an input source: "
                    f"{output_path} == {source}"
                )


def _make_writable(path: Path) -> None:
    try:
        mode = path.stat().st_mode
    except FileNotFoundError:
        return
    os.chmod(path, mode | stat.S_IWRITE)


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _stable_sha256(
    path: Path,
    *,
    expected_identity: tuple[int, int, int, int, int] | None = None,
) -> tuple[str, tuple[int, int, int, int, int]]:
    before = path.stat()
    identity = _stat_identity(before)
    if expected_identity is not None and identity != expected_identity:
        raise OSError(f"PDF report identity changed: {path}")
    if not path.is_file() or _is_link_or_junction(path):
        raise OSError(f"PDF report is not a regular file: {path}")
    digest = sha256_file(path)
    after = path.stat()
    if identity != _stat_identity(after):
        raise OSError(f"PDF report changed while hashing: {path}")
    return digest, identity


@contextmanager
def staged_csv(
    records: list[Record],
    output_path: Path,
    *,
    input_root: Path,
    work_root: Path,
    protected_sources: Iterable[Path],
    output_root: Path | None = None,
    preset: str = "",
) -> Iterator[Path]:
    protected_sources = tuple(protected_sources)
    _validate_report_destination(
        output_path,
        input_root=input_root,
        work_root=work_root,
        protected_sources=protected_sources,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _validate_report_destination(
        output_path,
        input_root=input_root,
        work_root=work_root,
        protected_sources=protected_sources,
    )
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        dir=output_path.parent,
    )
    os.close(descriptor)
    temp_path = Path(temp_name)
    try:
        with temp_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=REPORT_COLUMNS)
            writer.writeheader()
            for r in records:
                report_output_path = ""
                if output_root is not None:
                    source_path = Path(r.source_path)
                    relative_path = source_path.relative_to(input_root.resolve(strict=True))
                    report_output_path = str(output_root / relative_path)
                writer.writerow({
                    "source_path": r.source_path,
                    "source_size": r.source_size,
                    "source_sha256": r.source_sha256,
                    "output_path": report_output_path,
                    "output_size": r.output_size,
                    "output_sha256": r.output_sha256 or "",
                    "saved_bytes": r.saved_bytes,
                    "saved_percent": r.saved_percent,
                    "preset": preset,
                    "mode": r.mode,
                    "status": r.status,
                    "page_count": r.page_count,
                    "scan_page_ratio": r.scan_page_ratio,
                    "error_message": r.error_message,
                    "profile": r.profile,
                    "decision_reason": r.decision_reason,
                    "candidate_size": r.candidate_size,
                    "candidate_saved_bytes": r.candidate_saved_bytes,
                    "candidate_saved_percent": r.candidate_saved_percent,
                    "images_changed": r.images_changed,
                    "candidate_details": candidate_details_json(r.candidate_details),
                })
        yield temp_path
    finally:
        _make_writable(temp_path)
        temp_path.unlink(missing_ok=True)


@contextmanager
def published_staged_csv(
    temporary: Path,
    output_path: Path,
    *,
    input_root: Path,
    work_root: Path,
    protected_sources: Iterable[Path],
    before_publish: Callable[[], None] | None = None,
) -> Iterator[None]:
    """Publish a staged report and restore the prior report on peer failure."""

    protected_sources = tuple(protected_sources)
    _validate_report_destination(
        output_path,
        input_root=input_root,
        work_root=work_root,
        protected_sources=protected_sources,
    )
    new_sha256, new_identity = _stable_sha256(temporary)
    had_previous = output_path.is_file()
    descriptor, backup_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.",
        suffix=".backup",
        dir=output_path.parent,
    )
    os.close(descriptor)
    backup_path = Path(backup_name)
    previous_sha256 = ""
    previous_identity: tuple[int, int, int, int, int] | None = None
    backup_identity: tuple[int, int, int, int, int] | None = None
    try:
        if had_previous:
            previous_sha256, previous_identity = _stable_sha256(output_path)
            shutil.copy2(output_path, backup_path)
            backup_sha256, backup_identity = _stable_sha256(backup_path)
            current_sha256, _ = _stable_sha256(
                output_path,
                expected_identity=previous_identity,
            )
            if backup_sha256 != previous_sha256 or current_sha256 != previous_sha256:
                raise OSError(
                    f"existing PDF report changed while backing it up: {output_path}"
                )

        published = False
        published_identity: tuple[int, int, int, int, int] | None = None
        try:
            if before_publish is not None:
                before_publish()
            # before_publish may hash many source/output files.  Revalidate the
            # formal path and staged bytes immediately before replace.
            _validate_report_destination(
                output_path,
                input_root=input_root,
                work_root=work_root,
                protected_sources=protected_sources,
            )
            if had_previous:
                current_sha256, _ = _stable_sha256(
                    output_path,
                    expected_identity=previous_identity,
                )
                if current_sha256 != previous_sha256:
                    raise OSError(f"existing PDF report changed before publish: {output_path}")
            elif output_path.exists():
                raise OSError(f"PDF report appeared before publish: {output_path}")
            staged_sha256, _ = _stable_sha256(
                temporary,
                expected_identity=new_identity,
            )
            if staged_sha256 != new_sha256:
                raise OSError(f"staged PDF report changed before publish: {temporary}")
            os.replace(temporary, output_path)
            published = True
            published_sha256, published_identity = _stable_sha256(output_path)
            if published_sha256 != new_sha256:
                raise OSError(f"published PDF report verification failed: {output_path}")
            yield
        except BaseException as exc:
            if published:
                try:
                    current_sha256, _ = _stable_sha256(
                        output_path,
                        expected_identity=published_identity,
                    )
                    if current_sha256 != new_sha256:
                        raise OSError("published PDF report changed before rollback")
                    _validate_report_destination(
                        output_path,
                        input_root=input_root,
                        work_root=work_root,
                        protected_sources=protected_sources,
                    )
                    if had_previous:
                        backup_sha256, _ = _stable_sha256(
                            backup_path,
                            expected_identity=backup_identity,
                        )
                        if backup_sha256 != previous_sha256:
                            raise OSError("PDF report rollback backup changed")
                        os.replace(backup_path, output_path)
                        restored_sha256, _ = _stable_sha256(output_path)
                        if restored_sha256 != previous_sha256:
                            raise OSError("PDF report rollback verification failed")
                    else:
                        output_path.unlink()
                        if output_path.exists():
                            raise OSError("new PDF report could not be removed after failure")
                except BaseException as rollback_exc:
                    raise RuntimeError(
                        f"PDF report rollback failed after {type(exc).__name__}: {exc}"
                    ) from rollback_exc
            raise
    finally:
        _make_writable(backup_path)
        backup_path.unlink(missing_ok=True)


def write_csv(
    records: list[Record],
    output_path: Path,
    *,
    input_root: Path,
    work_root: Path,
    protected_sources: Iterable[Path],
    output_root: Path | None = None,
    preset: str = "",
    before_publish: Callable[[], None] | None = None,
    after_publish: Callable[[], None] | None = None,
) -> None:
    with staged_csv(
        records,
        output_path,
        input_root=input_root,
        work_root=work_root,
        protected_sources=protected_sources,
        output_root=output_root,
        preset=preset,
    ) as temporary:
        with published_staged_csv(
            temporary,
            output_path,
            input_root=input_root,
            work_root=work_root,
            protected_sources=protected_sources,
            before_publish=before_publish,
        ):
            if after_publish is not None:
                after_publish()


def _format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes, sec = divmod(int(seconds), 60)
    return f"{minutes}m {sec}s"


def print_summary(records: list[Record], elapsed_seconds: float = 0.0) -> None:
    total_in = 0
    total_out = 0
    total_saved = 0
    status_counts: dict[str, int] = {}
    unchanged_reasons: dict[str, int] = {}

    for r in records:
        size = r.source_size or 0
        out_size = r.output_size or size
        saved = r.saved_bytes or 0
        total_in += size
        total_out += out_size
        total_saved += saved
        status_counts[r.status] = status_counts.get(r.status, 0) + 1
        if r.status == ProcessStatus.UNCHANGED:
            reason = r.decision_reason or "not_recorded"
            unchanged_reasons[reason] = unchanged_reasons.get(reason, 0) + 1

    throughput = (total_in / elapsed_seconds / (1024 * 1024)) if elapsed_seconds > 0 else 0.0
    files_per_sec = (len(records) / elapsed_seconds) if elapsed_seconds > 0 else 0.0

    print("\n" + "=" * 50)
    print("PDF Shrink Summary")
    print("=" * 50)
    print(f"Files            : {len(records)}")
    print(f"Total input      : {human_size(total_in)}")
    print(f"Total output     : {human_size(total_out)}")
    print(f"Saved            : {human_size(total_saved)} "
          f"({(total_saved / total_in * 100) if total_in else 0:.2f}%)")
    print(f"Elapsed          : {_format_elapsed(elapsed_seconds)}")
    print(f"Throughput       : {throughput:.2f} MiB/s")
    print(f"Files/sec        : {files_per_sec:.2f}")
    print("-" * 50)
    print("Status counts:")
    for status, count in sorted(status_counts.items()):
        print(f"  {status:<24} : {count:>4}")
    if unchanged_reasons:
        print("UNCHANGED reasons:")
        for reason, count in sorted(unchanged_reasons.items()):
            label = UNCHANGED_REASON_LABELS.get(reason, reason)
            print(f"  {reason} ({label}) : {count}")
    print("=" * 50)
