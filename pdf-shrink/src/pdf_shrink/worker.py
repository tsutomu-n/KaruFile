"""単一PDFの検査、候補生成、検証、採否判断。"""
from __future__ import annotations

import os
import tempfile
import traceback
from pathlib import Path

from . import discovery, output, transform, validate
from .config import ReductionOptions, RunConfig
from .inspect_pdf import inspect_file
from .models import (
    InspectionResult,
    OptimizationMode,
    ProcessResult,
    ProcessStatus,
    SourceSnapshot,
)
from .utils import ensure_dir, logger, sha256_file

SKIP_REASON_TO_STATUS = {
    "encrypted": ProcessStatus.SKIPPED_ENCRYPTED,
    "signed": ProcessStatus.SKIPPED_SIGNED,
    "form": ProcessStatus.SKIPPED_COMPLEX,
    "attachments": ProcessStatus.SKIPPED_COMPLEX,
    "repaired": ProcessStatus.SKIPPED_COMPLEX,
    "no_pages": ProcessStatus.SKIPPED_COMPLEX,
    "open_failed": ProcessStatus.SKIPPED_COMPLEX,
    "page_load_failed": ProcessStatus.SKIPPED_COMPLEX,
    "inspect_error": ProcessStatus.SKIPPED_COMPLEX,
}


def _map_skip_reason(reason: str) -> ProcessStatus:
    for key, status in SKIP_REASON_TO_STATUS.items():
        if key in reason:
            return status
    return ProcessStatus.SKIPPED_COMPLEX


def _meets_reduction(
    original_size: int,
    candidate_size: int,
    mode: OptimizationMode,
    options: ReductionOptions,
) -> bool:
    saved = original_size - candidate_size
    if saved <= 0:
        return False
    if mode is OptimizationMode.LOSSY:
        minimum_bytes = options.lossy_min_bytes
        minimum_percent = options.lossy_min_percent
    else:
        minimum_bytes = options.lossless_min_bytes
        minimum_percent = options.lossless_min_percent
    return saved >= minimum_bytes and saved / original_size >= minimum_percent


def _result(
    output_path: Path,
    status: ProcessStatus,
    *,
    inspection: InspectionResult | None = None,
    output_size: int | None,
    saved_bytes: int = 0,
    saved_percent: float = 0.0,
    error_message: str | None = None,
) -> ProcessResult:
    return ProcessResult(
        output_path=output_path,
        status=status,
        mode=inspection.mode if inspection else None,
        page_count=inspection.page_count if inspection else 0,
        scan_page_ratio=inspection.scan_page_ratio if inspection else 0.0,
        output_size=output_size,
        saved_bytes=saved_bytes,
        saved_percent=saved_percent,
        error_message=error_message,
    )


def process_one_file(
    source: SourceSnapshot,
    cfg: RunConfig,
    temp_root: Path,
    qpdf_exe: Path | None,
) -> ProcessResult:
    output_path = source.output_path(cfg.output_dir)
    inspection: InspectionResult | None = None
    temp_path: Path | None = None
    recovery_needed = True

    try:
        discovery.assert_source_unchanged(source, cfg.input_dir)
        if source.size < cfg.reduction.skip_below_bytes:
            if not cfg.dry_run:
                recovery_needed = False
                output.copy_original(
                    source,
                    output_path,
                    input_root=cfg.input_dir,
                    output_root=cfg.output_dir,
                )
            else:
                discovery.assert_source_unchanged(source, cfg.input_dir)
            return _result(
                output_path,
                ProcessStatus.SKIPPED_SMALL,
                output_size=None if cfg.dry_run else output_path.stat().st_size,
            )

        inspection = inspect_file(
            source.path,
            cfg.scan,
            safe=cfg.safe,
            lossy_options=cfg.lossy,
        )
        discovery.assert_source_unchanged(source, cfg.input_dir)
        if not inspection.ok:
            reason = inspection.skip_reason or "unknown"
            if not cfg.dry_run:
                recovery_needed = False
                output.copy_original(
                    source,
                    output_path,
                    input_root=cfg.input_dir,
                    output_root=cfg.output_dir,
                )
            error = reason if "inspect_error" in reason or "open_failed" in reason else None
            return _result(
                output_path,
                _map_skip_reason(reason),
                inspection=inspection,
                output_size=None if cfg.dry_run else output_path.stat().st_size,
                error_message=error,
            )

        if cfg.dry_run:
            status = (
                ProcessStatus.DRY_RUN_LOSSY
                if inspection.mode is OptimizationMode.LOSSY
                else ProcessStatus.DRY_RUN_LOSSLESS
            )
            return _result(
                output_path,
                status,
                inspection=inspection,
                output_size=None,
            )

        temp_dir = ensure_dir(temp_root / source.relative_path.parent)
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f"{source.path.stem}_",
            suffix=".pdf",
            dir=temp_dir,
        )
        os.close(descriptor)
        temp_path = Path(temp_name)

        if inspection.mode is OptimizationMode.LOSSY:
            transform.optimize_lossy(source.path, temp_path, cfg.lossy)
        else:
            if qpdf_exe is None:
                raise RuntimeError("qpdf is required for lossless optimization")
            transform.optimize_lossless(source.path, temp_path, qpdf_exe, cfg.qpdf)

        if qpdf_exe is None:
            raise RuntimeError("qpdf is required for candidate validation")
        valid, reason = validate.validate(
            source.path,
            temp_path,
            qpdf_exe,
            enhanced=cfg.lossy.recompress_existing_jpeg,
        )
        if not valid:
            raise RuntimeError(f"validation_failed: {reason}")

        candidate_size = temp_path.stat().st_size
        candidate_sha256 = sha256_file(temp_path)
        if _meets_reduction(source.size, candidate_size, inspection.mode, cfg.reduction):
            output.adopt_candidate(
                source,
                temp_path,
                output_path,
                candidate_sha256,
                input_root=cfg.input_dir,
                output_root=cfg.output_dir,
            )
            status = (
                ProcessStatus.ADOPTED_LOSSY
                if inspection.mode is OptimizationMode.LOSSY
                else ProcessStatus.ADOPTED_LOSSLESS
            )
            saved_bytes = source.size - candidate_size
            return _result(
                output_path,
                status,
                inspection=inspection,
                output_size=candidate_size,
                saved_bytes=saved_bytes,
                saved_percent=saved_bytes / source.size,
            )

        recovery_needed = False
        output.copy_original(
            source,
            output_path,
            input_root=cfg.input_dir,
            output_root=cfg.output_dir,
        )
        return _result(
            output_path,
            ProcessStatus.UNCHANGED,
            inspection=inspection,
            output_size=output_path.stat().st_size,
        )

    except Exception as exc:
        error_message = f"{exc}\n{traceback.format_exc()}"
        logger.error("Failed to process %s: %s", source.path, exc)
        recovered_size: int | None = None
        if (
            recovery_needed
            and not cfg.dry_run
            and discovery.source_is_unchanged(source, cfg.input_dir)
        ):
            try:
                output.copy_original(
                    source,
                    output_path,
                    input_root=cfg.input_dir,
                    output_root=cfg.output_dir,
                )
                recovered_size = output_path.stat().st_size
            except Exception as copy_error:
                error_message += f"\nrecovery_copy_failed: {copy_error}"
                logger.error(
                    "Failed to copy original after processing error %s: %s",
                    source.path,
                    copy_error,
                )
        return _result(
            output_path,
            ProcessStatus.ERROR,
            inspection=inspection,
            output_size=recovered_size,
            error_message=error_message,
        )
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
