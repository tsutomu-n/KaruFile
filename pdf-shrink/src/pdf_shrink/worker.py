"""単一PDFの検査、候補生成、検証、採否判断。"""
from __future__ import annotations

import os
import tempfile
import time
import traceback
from dataclasses import replace
from pathlib import Path

from . import discovery, lossless_jpeg, output, transform, validate
from .config import ReductionOptions, RunConfig, config_for_path, profile_for_path
from .inspect_pdf import inspect_file
from .models import (
    CandidateResult,
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


def _evaluate_candidate(
    source: SourceSnapshot,
    cfg: RunConfig,
    path: Path,
    mode: OptimizationMode,
    profile: str,
    qpdf_exe: Path,
    *,
    jpeg_kind: str | None = None,
    deadline: float = float("inf"),
) -> CandidateResult:
    """Keep rejection evidence separate from failures of tools or structure."""
    kind = jpeg_kind or (profile if mode is OptimizationMode.LOSSY else "lossless")
    detail = CandidateResult(kind=kind)
    try:
        changed = 0
        if jpeg_kind:
            changed = lossless_jpeg.optimize(
                source.path, path, cfg, qpdf_exe,
                progressive=jpeg_kind == "jpeg_lossless_progressive", deadline=deadline,
            )
            if not changed:
                return replace(detail, reason="no_image_savings")
        elif mode is OptimizationMode.LOSSY:
            changed = transform.optimize_lossy(source.path, path, cfg.lossy)
        else:
            transform.optimize_lossless(source.path, path, qpdf_exe, cfg.qpdf)
        detail = replace(detail, size=path.stat().st_size, images_changed=changed or 0)
        if mode is OptimizationMode.LOSSY and changed == 0:
            return replace(detail, reason="no_image_savings")
        kwargs = {"enhanced": cfg.lossy.recompress_existing_jpeg or cfg.lossy.photo_mode}
        if cfg.lossy.photo_mode:
            kwargs["detail"] = True
        if jpeg_kind:
            rc = validate.qpdf_check(qpdf_exe, path)
            if rc:
                raise RuntimeError(f"qpdf check failed (rc={rc})")
            lossless_jpeg.validate_exact(source.path, path, deadline)
            valid, reason = True, ""
        else:
            valid, reason = validate.validate(source.path, path, qpdf_exe, **kwargs)
        if not valid:
            quality_rejection = reason.startswith((
                "render_diff_too_large", "render_local_diff_too_large",
                "render_detail_diff_too_large", "render_detail_local_diff_too_large",
                "render_detail_pixel_limit", "render_detail_time_limit",
                "render_detail_region_limit",
            ))
            return replace(
                detail,
                reason="quality_rejected" if quality_rejection else "processing_error",
                validation_reason=reason,
            )
        if _meets_reduction(source.size, detail.size, mode, cfg.reduction):
            return replace(detail, reason="eligible")
        return replace(
            detail,
            reason="candidate_not_smaller" if detail.size >= source.size else "reduction_below_threshold",
        )
    except lossless_jpeg.CandidateRejected as exc:
        return replace(detail, reason="quality_rejected", validation_reason=str(exc))
    except Exception as exc:
        return replace(detail, reason="processing_error", validation_reason=str(exc))


def process_one_file(
    source: SourceSnapshot,
    cfg: RunConfig,
    temp_root: Path,
    qpdf_exe: Path | None,
) -> ProcessResult:
    profile = profile_for_path(cfg, source.relative_path)
    cfg = config_for_path(cfg, source.relative_path)
    output_path = source.output_path(cfg.output_dir)
    inspection: InspectionResult | None = None
    temp_paths: list[Path] = []
    candidates: list[CandidateResult] = []
    recovery_needed = True

    def finish(
        status: ProcessStatus,
        *,
        output_size: int | None,
        reason: str,
        saved_bytes: int = 0,
        error_message: str | None = None,
        selected_mode: OptimizationMode | None = None,
    ) -> ProcessResult:
        primary = candidates[0] if candidates else None
        size = primary.size if primary else None
        saved = source.size - size if size is not None else None
        result = _result(
            output_path, status, inspection=inspection, output_size=output_size,
            saved_bytes=saved_bytes,
            saved_percent=saved_bytes / source.size if source.size else 0,
            error_message=error_message,
        )
        return replace(
            result, mode=selected_mode or result.mode, profile=profile,
            decision_reason=reason, candidate_size=size, candidate_saved_bytes=saved,
            candidate_saved_percent=saved / source.size if saved is not None and source.size else None,
            images_changed=primary.images_changed if primary else 0,
            candidate_details=tuple(candidates),
            lossless_jpeg_requested=cfg.lossless_jpeg,
        )

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
            return finish(
                ProcessStatus.SKIPPED_SMALL,
                output_size=None if cfg.dry_run else output_path.stat().st_size,
                reason="source_too_small",
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
            inspection_failed = profile == "photo" and reason.startswith("inspect_error:")
            return finish(
                ProcessStatus.ERROR if inspection_failed else _map_skip_reason(reason),
                output_size=None if cfg.dry_run else output_path.stat().st_size,
                error_message=error,
                reason="processing_error" if inspection_failed else reason,
            )

        if cfg.dry_run:
            status = (
                ProcessStatus.DRY_RUN_LOSSY
                if inspection.mode is OptimizationMode.LOSSY
                else ProcessStatus.DRY_RUN_LOSSLESS
            )
            return finish(
                status,
                output_size=None,
                reason=str(status).lower(),
            )

        temp_dir = ensure_dir(temp_root / source.relative_path.parent)
        if qpdf_exe is None:
            raise RuntimeError("qpdf is required for candidate validation")
        modes = [inspection.mode or OptimizationMode.LOSSLESS]
        if inspection.mode is OptimizationMode.LOSSY:
            modes.append(OptimizationMode.LOSSLESS)
        kinds: list[str | None] = [None] * len(modes)
        if cfg.lossless_jpeg:
            modes.extend([OptimizationMode.LOSSLESS] * 2)
            kinds.extend(["jpeg_lossless_baseline", "jpeg_lossless_progressive"])
        jpeg_deadline = None
        for mode, jpeg_kind in zip(modes, kinds):
            descriptor, temp_name = tempfile.mkstemp(
                prefix=f"{source.path.stem}_", suffix=".pdf", dir=temp_dir,
            )
            os.close(descriptor)
            path = Path(temp_name)
            temp_paths.append(path)
            if jpeg_kind:
                if jpeg_deadline is None:
                    jpeg_deadline = time.monotonic() + lossless_jpeg.RECIPE["document_seconds"]
                candidate = _evaluate_candidate(
                    source, cfg, path, mode, profile, qpdf_exe,
                    jpeg_kind=jpeg_kind, deadline=jpeg_deadline,
                )
            else:
                candidate = _evaluate_candidate(source, cfg, path, mode, profile, qpdf_exe)
            candidates.append(candidate)
            discovery.assert_source_unchanged(source, cfg.input_dir)
            if candidate.reason == "processing_error":
                raise RuntimeError(f"{candidate.kind} candidate failed: {candidate.validation_reason}")

        eligible = [index for index, c in enumerate(candidates) if c.reason == "eligible"]
        if eligible:
            priorities = {"lossless": 0, "jpeg_lossless_baseline": 1, "jpeg_lossless_progressive": 2}
            chosen = min(eligible, key=lambda i: (candidates[i].size, priorities.get(candidates[i].kind, 3)))
            candidate = candidates[chosen]
            candidate_size = candidate.size
            assert candidate_size is not None
            candidate_sha256 = sha256_file(temp_paths[chosen])
            output.adopt_candidate(
                source,
                temp_paths[chosen],
                output_path,
                candidate_sha256,
                input_root=cfg.input_dir,
                output_root=cfg.output_dir,
            )
            status = (
                ProcessStatus.ADOPTED_LOSSY
                if modes[chosen] is OptimizationMode.LOSSY
                else ProcessStatus.ADOPTED_LOSSLESS
            )
            candidates[chosen] = replace(candidate, selected=True)
            saved_bytes = source.size - candidate_size
            return finish(
                status,
                output_size=candidate_size,
                saved_bytes=saved_bytes,
                reason=(
                    f"adopted_{candidate.kind}" if candidate.kind.startswith("jpeg_lossless_")
                    else "fallback_lossless" if chosen else str(status).lower()
                ),
                selected_mode=modes[chosen],
            )

        recovery_needed = False
        output.copy_original(
            source,
            output_path,
            input_root=cfg.input_dir,
            output_root=cfg.output_dir,
        )
        return finish(
            ProcessStatus.UNCHANGED,
            output_size=output_path.stat().st_size,
            reason=candidates[0].reason,
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
        return finish(
            ProcessStatus.ERROR,
            output_size=recovered_size,
            error_message=error_message,
            reason="processing_error",
        )
    finally:
        for path in temp_paths:
            path.unlink(missing_ok=True)
