"""型付き設定と処理条件ハッシュ。"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ScanOptions:
    page_image_ratio: float = 0.8
    max_visible_text: int = 20
    scan_page_ratio: float = 0.8


@dataclass(frozen=True)
class LossyOptions:
    dpi_threshold: int = 450
    dpi_target: int = 300
    quality: int = 92
    lossy: bool = True
    lossless: bool = True
    bitonal: bool = False
    color: bool = True
    gray: bool = True
    set_to_gray: bool = False
    # rewrite_images ではなく配置実効DPIで差し替える実装の識別子。
    # 値を変えると再開用 config_hash が変わり、旧UNCHANGED結果を再処理する。
    algorithm: str = "placed-effective-dpi-v2"


@dataclass(frozen=True)
class ReductionOptions:
    skip_below_bytes: int = 256 * 1024
    lossless_min_bytes: int = 64 * 1024
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

    def with_tool_versions(self, *, pymupdf: str, qpdf: str) -> RunConfig:
        return replace(self, pymupdf_version=pymupdf, qpdf_version=qpdf)


def default_config(
    *,
    input_dir: Path | str = ".",
    output_dir: Path | str | None = None,
) -> RunConfig:
    input_path = Path(input_dir).resolve()
    output_path = (
        Path(output_dir).resolve()
        if output_dir is not None
        else (input_path.parent / f"{input_path.name}_軽量化").resolve()
    )
    return RunConfig(input_dir=input_path, output_dir=output_path)


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
    return RunConfig(
        input_dir=input_dir,
        output_dir=output_dir,
        workers=workers,
        safe=bool(getattr(args, "safe", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        limit=limit,
        retry_errors=bool(getattr(args, "retry_errors", False)),
        qpdf_path=Path(qpdf_arg).expanduser().resolve() if qpdf_arg else None,
    )


def config_hash(cfg: RunConfig) -> str:
    """処理結果または記録される判定結果に影響する条件をハッシュ化する。"""
    relevant = {
        # DBの主キーは入力パスだけなので、出力先も再開条件へ含める。
        "output_dir": str(cfg.output_dir),
        "safe": cfg.safe,
        "dry_run": cfg.dry_run,
        "scan": asdict(cfg.scan),
        "lossy": asdict(cfg.lossy),
        "reduction": asdict(cfg.reduction),
        "qpdf": asdict(cfg.qpdf),
        "pymupdf_version": cfg.pymupdf_version,
        "qpdf_version": cfg.qpdf_version,
    }
    data = json.dumps(relevant, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
