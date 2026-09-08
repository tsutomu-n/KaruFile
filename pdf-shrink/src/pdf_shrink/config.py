"""型付き設定と処理条件ハッシュ。"""
from __future__ import annotations

import hashlib
import json
from fnmatch import fnmatchcase
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path, PureWindowsPath
from typing import Any


PDF_IMAGE_DPI_TARGET = 300
PHOTO_IMAGE_DPI_TARGET = 200
PHOTO_DPI_MIN = 150
PHOTO_DPI_MAX = 300
PREVIEW_MAX_DPIS = 5


def validate_photo_dpi(value: Any, *, option: str = "--photo-dpi") -> int:
    if (
        isinstance(value, bool) or not isinstance(value, int)
        or not PHOTO_DPI_MIN <= value <= PHOTO_DPI_MAX
    ):
        raise ValueError(
            f"{option} must be an integer between {PHOTO_DPI_MIN} and {PHOTO_DPI_MAX}"
        )
    return value


def normalize_preview_dpis(values: Any) -> tuple[int, ...]:
    try:
        values = tuple(values)
    except TypeError as exc:
        raise ValueError("--preview-dpi must contain integer DPI values") from exc
    normalized = tuple(sorted(
        {validate_photo_dpi(value, option="--preview-dpi") for value in values},
        reverse=True,
    ))
    if len(normalized) > PREVIEW_MAX_DPIS:
        raise ValueError(f"--preview-dpi supports at most {PREVIEW_MAX_DPIS} distinct DPI values")
    return normalized


class CompressionPreset(StrEnum):
    STANDARD = "standard"
    COMPACT = "compact"


@dataclass(frozen=True)
class ScanOptions:
    page_image_ratio: float = 0.8
    max_visible_text: int = 20
    scan_page_ratio: float = 0.8


@dataclass(frozen=True)
class LossyOptions:
    dpi_threshold: int = 450
    dpi_target: int = PDF_IMAGE_DPI_TARGET
    quality: int = 92
    lossy: bool = True
    lossless: bool = True
    bitonal: bool = False
    color: bool = True
    gray: bool = True
    set_to_gray: bool = False
    recompress_existing_jpeg: bool = False
    jpeg_recompress_min_percent: float = 0.05
    photo_mode: bool = False
    # rewrite_images ではなく配置実効DPIで差し替える実装の識別子。
    # 値を変えると再開用 config_hash が変わり、旧UNCHANGED結果を再処理する。
    algorithm: str = "placed-effective-dpi-v4-axis-safe-decode-fixed"

    def __post_init__(self) -> None:
        if self.photo_mode:
            validate_photo_dpi(self.dpi_target)
        elif (
            isinstance(self.dpi_target, bool) or not isinstance(self.dpi_target, int)
            or self.dpi_target != PDF_IMAGE_DPI_TARGET
        ):
            raise ValueError(
                f"PDF image DPI target is fixed at {PDF_IMAGE_DPI_TARGET} for this profile"
            )
        if not 0 <= self.jpeg_recompress_min_percent < 1:
            raise ValueError("JPEG recompression minimum must be between 0 and 1")


def lossy_options_for_preset(
    preset: CompressionPreset | str,
) -> LossyOptions:
    if CompressionPreset(preset) is CompressionPreset.COMPACT:
        return LossyOptions(
            quality=80,
            recompress_existing_jpeg=True,
            algorithm="placed-effective-dpi-v5-axis-safe-compact-jpeg",
        )
    return LossyOptions()


def photo_lossy_options(dpi: int = PHOTO_IMAGE_DPI_TARGET) -> LossyOptions:
    """Explicitly selected viewing copies; never infer OCR need from DPI."""
    return LossyOptions(
        dpi_target=dpi,
        quality=80,
        photo_mode=True,
        lossless=False,
        algorithm="photo-jpeg-selectable-dpi-min-placement-v2",
    )


def normalize_photo_patterns(values: Any) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw in values:
        value = str(raw).replace("\\", "/")
        if (
            not value.strip()
            or value.startswith("/")
            or PureWindowsPath(value).drive
            or ".." in value.split("/")
        ):
            raise ValueError("--photo-pattern must be a nonempty relative glob without '..'")
        value = "/".join(part for part in value.split("/") if part not in {"", "."})
        if not value:
            raise ValueError("--photo-pattern must be a nonempty relative glob")
        normalized.append(value.casefold())
    return tuple(sorted(set(normalized)))


@dataclass(frozen=True)
class ReductionOptions:
    skip_below_bytes: int = 256 * 1024
    lossless_min_bytes: int = 16 * 1024
    lossless_min_percent: float = 0.02
    lossy_min_bytes: int = 256 * 1024
    lossy_min_percent: float = 0.05


@dataclass(frozen=True)
class QpdfOptions:
    compress_streams: str = "y"
    decode_level: str = "generalized"
    recompress_flate: bool = True
    compression_level: int = 9
    object_streams: str = "generate"


@dataclass(frozen=True)
class RunConfig:
    input_dir: Path
    output_dir: Path
    workers: int = 2
    preset: CompressionPreset = CompressionPreset.STANDARD
    safe: bool = False
    dry_run: bool = False
    limit: int | None = None
    retry_errors: bool = False
    qpdf_path: Path | None = None
    scan: ScanOptions = ScanOptions()
    lossy: LossyOptions = LossyOptions()
    reduction: ReductionOptions = ReductionOptions()
    qpdf: QpdfOptions = QpdfOptions()
    pymupdf_version: str = ""
    qpdf_version: str = ""
    photo_patterns: tuple[str, ...] = ()
    photo_dpi: int = PHOTO_IMAGE_DPI_TARGET
    preview: bool = False
    preview_dpis: tuple[int, ...] = ()
    lossless_jpeg: bool = False
    jpegtran_path: Path | None = None
    jpegtran_version: str = ""
    jpegtran_sha256: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "photo_patterns", normalize_photo_patterns(self.photo_patterns))
        validate_photo_dpi(self.photo_dpi)
        object.__setattr__(self, "preview_dpis", normalize_preview_dpis(self.preview_dpis))
        if not isinstance(self.preview, bool):
            raise ValueError("--preview must be a boolean")
        if self.photo_dpi != PHOTO_IMAGE_DPI_TARGET and not self.photo_patterns:
            raise ValueError("--photo-dpi requires --photo-pattern")
        if self.preview and not self.photo_patterns:
            raise ValueError("--preview requires --photo-pattern")
        if self.preview_dpis and not self.preview:
            raise ValueError("--preview-dpi requires --preview")
        if self.safe and self.photo_patterns:
            raise ValueError("--safe cannot be combined with --photo-pattern")

    def with_tool_versions(self, *, pymupdf: str, qpdf: str) -> RunConfig:
        return replace(self, pymupdf_version=pymupdf, qpdf_version=qpdf)


def default_config(
    *,
    input_dir: Path | str = ".",
    output_dir: Path | str | None = None,
    preset: CompressionPreset | str = CompressionPreset.STANDARD,
    photo_patterns: tuple[str, ...] = (),
    photo_dpi: int = PHOTO_IMAGE_DPI_TARGET,
    preview: bool = False,
    preview_dpis: tuple[int, ...] = (),
) -> RunConfig:
    selected_preset = CompressionPreset(preset)
    input_path = Path(input_dir).resolve()
    output_path = (
        Path(output_dir).resolve()
        if output_dir is not None
        else (input_path.parent / f"{input_path.name}_軽量化").resolve()
    )
    return RunConfig(
        input_dir=input_path,
        output_dir=output_path,
        preset=selected_preset,
        lossy=lossy_options_for_preset(selected_preset),
        photo_patterns=photo_patterns,
        photo_dpi=photo_dpi,
        preview=preview,
        preview_dpis=preview_dpis,
    )


def build_config(args: Any) -> RunConfig:
    input_dir = Path(args.input).resolve()
    output_arg = getattr(args, "output", None)
    output_dir = (
        Path(output_arg).resolve()
        if output_arg
        else (input_dir.parent / f"{input_dir.name}_軽量化").resolve()
    )
    workers = int(getattr(args, "workers", 2))
    if workers < 1:
        raise ValueError("--workers must be at least 1")

    limit = getattr(args, "limit", None)
    if limit is not None and limit < 1:
        raise ValueError("--limit must be at least 1")

    qpdf_arg = getattr(args, "qpdf_path", None)
    try:
        preset = CompressionPreset(
            getattr(args, "preset", CompressionPreset.STANDARD.value)
        )
    except ValueError as exc:
        raise ValueError("--preset must be standard or compact") from exc
    safe = bool(getattr(args, "safe", False))
    if safe and preset is CompressionPreset.COMPACT:
        raise ValueError("--safe cannot be combined with --preset compact")
    photo_patterns = tuple(getattr(args, "photo_pattern", None) or ())
    photo_dpi = getattr(args, "photo_dpi", None)
    if photo_dpi is not None and not photo_patterns:
        raise ValueError("--photo-dpi requires --photo-pattern")

    return RunConfig(
        input_dir=input_dir,
        output_dir=output_dir,
        workers=workers,
        preset=preset,
        safe=safe,
        dry_run=bool(getattr(args, "dry_run", False)),
        limit=limit,
        retry_errors=bool(getattr(args, "retry_errors", False)),
        qpdf_path=Path(qpdf_arg).expanduser().resolve() if qpdf_arg else None,
        lossy=lossy_options_for_preset(preset),
        photo_patterns=photo_patterns,
        photo_dpi=PHOTO_IMAGE_DPI_TARGET if photo_dpi is None else photo_dpi,
        preview=bool(getattr(args, "preview", False)),
        preview_dpis=tuple(getattr(args, "preview_dpi", None) or ()),
        lossless_jpeg=bool(getattr(args, "lossless_jpeg", False)),
        jpegtran_path=Path(args.jpegtran_path).expanduser().resolve() if getattr(args, "jpegtran_path", None) else None,
    )


def profile_for_path(cfg: RunConfig, relative_path: Path) -> str:
    path = relative_path.as_posix().casefold()
    return "photo" if any(fnmatchcase(path, p) for p in cfg.photo_patterns) else str(cfg.preset)


def config_for_path(cfg: RunConfig, relative_path: Path) -> RunConfig:
    if profile_for_path(cfg, relative_path) != "photo":
        return cfg
    return replace(
        cfg,
        lossy=photo_lossy_options(cfg.photo_dpi),
        reduction=replace(cfg.reduction, lossy_min_bytes=64 * 1024),
    )


def config_hash(cfg: RunConfig) -> str:
    """処理結果または記録される判定結果に影響する条件をハッシュ化する。"""
    from .lossless_jpeg import RECIPE

    lossy = asdict(cfg.lossy)
    if not cfg.lossy.recompress_existing_jpeg:
        # standardで無効な追加項目は、既存stateとのhash互換性を保つ。
        lossy.pop("recompress_existing_jpeg")
        lossy.pop("jpeg_recompress_min_percent")
    relevant = {
        # Legacy rows lack the requested photo DPI and must run once again.
        "processing_schema": 4,
        "lossless_jpeg": cfg.lossless_jpeg,
        "jpeg_recipe": RECIPE,
        "jpegtran_version": cfg.jpegtran_version if cfg.lossless_jpeg else "",
        "jpegtran_sha256": cfg.jpegtran_sha256 if cfg.lossless_jpeg else "",
        "photo_patterns": cfg.photo_patterns,
        "photo_dpi": cfg.photo_dpi,
        "photo_recipe": asdict(photo_lossy_options(cfg.photo_dpi)) if cfg.photo_patterns else None,
        # DBの主キーは入力パスだけなので、出力先も再開条件へ含める。
        "output_dir": str(cfg.output_dir),
        "safe": cfg.safe,
        "dry_run": cfg.dry_run,
        "scan": asdict(cfg.scan),
        "lossy": lossy,
        "reduction": asdict(cfg.reduction),
        "qpdf": asdict(cfg.qpdf),
        "pymupdf_version": cfg.pymupdf_version,
        "qpdf_version": cfg.qpdf_version,
    }
    # Preview is a separate artifact: requesting it must reuse valid PDF output.
    # Neither preview nor preview_dpis participates in the processing hash.
    data = json.dumps(relevant, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
