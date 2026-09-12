"""Explicit workbook selection and bounded resolution settings."""
from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PureWindowsPath
from .recipe import resolve_recipe


def normalize_patterns(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized = []
    for raw in values:
        value = str(raw).replace("\\", "/")
        if (
            not value.strip()
            or value.startswith("/")
            or PureWindowsPath(value).drive
            or ".." in value.split("/")
        ):
            raise ValueError("--pattern must be a nonempty relative glob without '..'")
        value = "/".join(part for part in value.split("/") if part not in {"", "."})
        if not value:
            raise ValueError("--pattern must be a nonempty relative glob")
        normalized.append(value.casefold())
    if not normalized:
        raise ValueError("at least one --pattern is required")
    return tuple(sorted(set(normalized)))


@dataclass(frozen=True)
class ExcelConfig:
    input_dir: Path
    output_dir: Path
    patterns: tuple[str, ...]
    dpi: int | None = None
    dry_run: bool = False
    max_side: int | None = None
    jpeg_quality: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "patterns", normalize_patterns(self.patterns))
        dpi, max_side, quality = resolve_recipe(self.dpi, self.max_side, self.jpeg_quality)
        object.__setattr__(self, "dpi", dpi)
        object.__setattr__(self, "max_side", max_side)
        object.__setattr__(self, "jpeg_quality", quality)

    def selected(self, relative: Path) -> bool:
        return (
            relative.suffix.casefold() == ".xlsx"
            and not relative.name.startswith("~$")
            and any(fnmatchcase(relative.as_posix().casefold(), pattern) for pattern in self.patterns)
        )

    @property
    def report_path(self) -> Path:
        suffix = ".excel-report.dry-run.csv" if self.dry_run else ".excel-report.csv"
        return Path(str(self.output_dir) + suffix)

    @property
    def work_dir(self) -> Path:
        return Path(str(self.output_dir) + ".excel-work")
