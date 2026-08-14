"""処理パイプラインを流れる型付きデータ。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class OptimizationMode(StrEnum):
    LOSSLESS = "lossless"
    LOSSY = "lossy"


class ProcessStatus(StrEnum):
    ADOPTED_LOSSLESS = "ADOPTED_LOSSLESS"
    ADOPTED_LOSSY = "ADOPTED_LOSSY"
    UNCHANGED = "UNCHANGED"
    SKIPPED_SMALL = "SKIPPED_SMALL"
    SKIPPED_ENCRYPTED = "SKIPPED_ENCRYPTED"
    SKIPPED_SIGNED = "SKIPPED_SIGNED"
    SKIPPED_COMPLEX = "SKIPPED_COMPLEX"
    DRY_RUN_LOSSLESS = "DRY_RUN_LOSSLESS"
    DRY_RUN_LOSSY = "DRY_RUN_LOSSY"
    ERROR = "ERROR"


@dataclass(frozen=True)
class SourceSnapshot:
    """処理対象を選定した時点の入力ファイル情報。"""

    path: Path
    relative_path: Path
    sha256: str
    size: int
    mtime_ns: int

    def output_path(self, output_dir: Path) -> Path:
        return (output_dir / self.relative_path).resolve()


@dataclass(frozen=True)
class InspectionResult:
    ok: bool
    skip_reason: str | None
    page_count: int
    scan_page_ratio: float
    mode: OptimizationMode | None


@dataclass(frozen=True)
class ProcessResult:
    output_path: Path
    status: ProcessStatus
    mode: OptimizationMode | None
    page_count: int
    scan_page_ratio: float
    output_size: int | None
    saved_bytes: int
    saved_percent: float
    error_message: str | None
