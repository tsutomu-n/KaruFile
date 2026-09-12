"""Bounded, content-free image diagnostics for processing and publication."""
from dataclasses import dataclass, field
import json

RECIPE_VERSION = "grid2-pixel-jpeg-v2"
MAX_DIAGNOSTICS = 1000
MAX_FIELD = 2 * 1024 * 1024


@dataclass
class Analysis:
    images_total: int | None = None
    complete: bool = False
    records: list[dict] = field(default_factory=list)

    def report_fields(self) -> dict:
        records = []
        size = 2
        for record in self.records[:MAX_DIAGNOSTICS]:
            encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            size += len(encoded.encode("utf-8")) + bool(records)
            if size > MAX_FIELD:
                break
            records.append(record)
        return dict(images_total=self.images_total, analysis_complete=self.complete,
                    diagnostics_complete=self.complete and len(records) == self.images_total,
                    image_diagnostics=tuple(records))
