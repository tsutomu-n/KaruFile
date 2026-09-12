"""Values at the filesystem and CSV boundaries."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from .diagnostics import RECIPE_VERSION


@dataclass(frozen=True, slots=True)
class FileIdentity:
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True, slots=True)
class Fingerprint:
    sha256: str
    identity: FileIdentity


@dataclass(frozen=True, slots=True)
class ProcessResult:
    source_path: str
    relative_path: str
    output_path: str
    source_size: int
    source_sha256: str
    status: str
    dpi: int | None
    max_side: int | None = None
    jpeg_quality: int = 85
    output_size: int | None = None
    output_sha256: str = ""
    images_total: int | None = None
    images_changed: int = 0
    changed_parts: tuple[str, ...] = ()
    reason: str = ""
    recipe_version: str = RECIPE_VERSION
    analysis_complete: bool = False
    diagnostics_complete: bool = False
    image_diagnostics: tuple[dict, ...] = ()


@dataclass(frozen=True, slots=True)
class RunOutcome:
    results: tuple[ProcessResult, ...]
    exit_code: int
    report_path: Path | None = None
    error: str = ""
