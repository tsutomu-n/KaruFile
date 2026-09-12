"""Schema 3 reports, checked before atomic publication."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Callable, Sequence

from .models import ProcessResult
from .diagnostics import MAX_FIELD
from .output import PathGuard, fingerprint, publish, staged_file

FIELDNAMES = (
    "schema_version", "source_path", "relative_path", "output_path", "source_size",
    "output_size", "source_sha256", "output_sha256", "status", "dpi", "images_total",
    "images_changed", "changed_parts", "reason", "max_side", "jpeg_quality",
    "recipe_version", "analysis_complete", "diagnostics_complete", "image_diagnostics",
)


def as_row(result: ProcessResult) -> dict[str, str]:
    row = {name: str(getattr(result, name)) for name in FIELDNAMES if name != "schema_version"}
    row["schema_version"] = "3"
    for name in ("dpi", "max_side"):
        row[name] = "" if getattr(result, name) is None else str(getattr(result, name))
    row["images_total"] = "" if result.images_total is None else str(result.images_total)
    for name in ("analysis_complete", "diagnostics_complete"):
        row[name] = str(getattr(result, name)).lower()
    row["image_diagnostics"] = json.dumps(result.image_diagnostics, ensure_ascii=False, separators=(",", ":"))
    if any(len(value.encode("utf-8")) > MAX_FIELD for value in row.values()):
        raise ValueError("Excel report field exceeds limit")
    row["output_size"] = "" if result.output_size is None else str(result.output_size)
    row["changed_parts"] = json.dumps(result.changed_parts, ensure_ascii=False, separators=(",", ":"))
    return row


def write_report(
    path: Path,
    results: Sequence[ProcessResult],
    guard: PathGuard,
    *,
    before_publish: Callable[[], None],
) -> None:
    expected_rows = [as_row(result) for result in results]
    with staged_file(guard, ".csv") as stage:
        with stage.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(expected_rows)
            stream.flush()
        if stage.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("Excel report exceeds limit")
        previous_limit = csv.field_size_limit(MAX_FIELD)
        try:
            with stage.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                if tuple(reader.fieldnames or ()) != FIELDNAMES or list(reader) != expected_rows:
                    raise OSError("staged Excel report verification failed")
        finally:
            csv.field_size_limit(previous_limit)
        stage_fingerprint = fingerprint(stage)
        before_publish()
        publish(stage, path, guard, stage_fingerprint)
