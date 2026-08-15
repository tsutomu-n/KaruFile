"""CSVレポートとコンソールサマリー。"""
from __future__ import annotations

import csv
import os
import stat
import tempfile
from collections.abc import Iterable
from pathlib import Path

from .state import Record
from .utils import human_size


REPORT_COLUMNS = [
    "source_path",
    "source_size",
    "output_size",
    "saved_bytes",
    "saved_percent",
    "mode",
    "status",
    "page_count",
    "scan_page_ratio",
    "error_message",
]


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


def write_csv(
    records: list[Record],
    output_path: Path,
    *,
    input_root: Path,
    work_root: Path,
    protected_sources: Iterable[Path],
) -> None:
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
                writer.writerow({
                    "source_path": r.source_path,
                    "source_size": r.source_size,
                    "output_size": r.output_size,
                    "saved_bytes": r.saved_bytes,
                    "saved_percent": r.saved_percent,
                    "mode": r.mode,
                    "status": r.status,
                    "page_count": r.page_count,
                    "scan_page_ratio": r.scan_page_ratio,
                    "error_message": r.error_message,
                })
        _validate_report_destination(
            output_path,
            input_root=input_root,
            work_root=work_root,
            protected_sources=protected_sources,
        )
        _make_writable(output_path)
        os.replace(temp_path, output_path)
    finally:
        _make_writable(temp_path)
        temp_path.unlink(missing_ok=True)


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

    for r in records:
        size = r.source_size or 0
        out_size = r.output_size or size
        saved = r.saved_bytes or 0
        total_in += size
        total_out += out_size
        total_saved += saved
        status_counts[r.status] = status_counts.get(r.status, 0) + 1

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
    print("=" * 50)
