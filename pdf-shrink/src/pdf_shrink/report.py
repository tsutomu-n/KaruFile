"""CSVレポートとコンソールサマリー。"""
from __future__ import annotations

import csv
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


def write_csv(records: list[Record], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
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
