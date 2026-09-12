"""Sequential workbook processing with independently validated publication."""
from __future__ import annotations

import logging
import shutil
from dataclasses import replace
from pathlib import Path, PurePosixPath

from .config import ExcelConfig
from .core import CoreResult, process_workbook
from .diagnostics import Analysis
from .models import Fingerprint, ProcessResult, RunOutcome
from .output import PathGuard, discover_files, fingerprint, publish, staged_file, validate_roots
from .report import write_report

LOGGER = logging.getLogger(__name__)


def _validate_core(result: CoreResult, dry_run: bool) -> None:
    valid = {"DRY_RUN", "DRY_RUN_PRESERVED"} if dry_run else {"ADOPTED_LOSSY", "PRESERVED_ORIGINAL"}
    if result.status not in valid or not isinstance(result.reason, str) or not result.reason.strip():
        raise ValueError("invalid Excel core status or reason")
    if (type(result.images_changed) is not int or result.images_changed < 0
            or (result.images_total is not None and (type(result.images_total) is not int or result.images_total < 0))):
        raise ValueError("invalid Excel core image counts")
    if (result.images_changed > (result.images_total or 0) or result.images_changed != len(result.changed_parts)):
        raise ValueError("Excel core changed-part count mismatch")
    if len(set(result.changed_parts)) != len(result.changed_parts):
        raise ValueError("duplicate changed Excel parts")
    for part in result.changed_parts:
        if (
            not isinstance(part, str) or not part or "\\" in part
            or PurePosixPath(part).is_absolute() or ".." in PurePosixPath(part).parts
            or not part.startswith("xl/media/") or ":" in part or "%" in part
            or any(segment in {"", ".", ".."} for segment in part.split("/"))
            or PurePosixPath(part).suffix.lower() not in {".jpg", ".jpeg", ".png"}
        ):
            raise ValueError("unsafe changed Excel part name")
    if result.status == "ADOPTED_LOSSY":
        if result.images_changed == 0:
            raise ValueError("adopted workbook has no changed images")
    elif result.images_changed or result.changed_parts:
        raise ValueError("preserved or dry-run workbook cannot have changed parts")


def _one(
    source: Path, config: ExcelConfig, guard: PathGuard,
) -> tuple[ProcessResult, Fingerprint | None, Fingerprint | None]:
    relative = source.relative_to(config.input_dir)
    destination = config.output_dir / relative
    result = ProcessResult(
        source_path=str(source), relative_path=relative.as_posix(), output_path=str(destination),
        source_size=0, source_sha256="", status="ERROR", dpi=config.dpi,
        max_side=config.max_side, jpeg_quality=config.jpeg_quality,
    )
    source_fp = None
    analysis = Analysis()
    try:
        guard.validate(destination)
        source_fp = fingerprint(source)
        result = replace(result, source_size=source_fp.identity.size, source_sha256=source_fp.sha256)
        if config.dry_run:
            core = process_workbook(source, None, dpi=config.dpi, dry_run=True, analysis=analysis,
                                    max_side=config.max_side, jpeg_quality=config.jpeg_quality)
            _validate_core(core, True)
            fingerprint(source, source_fp)
            return replace(result, status=core.status, reason=core.reason, **analysis.report_fields()), source_fp, None
        with staged_file(guard, ".xlsx") as stage:
            core = process_workbook(source, stage, dpi=config.dpi, dry_run=False, analysis=analysis,
                                    max_side=config.max_side, jpeg_quality=config.jpeg_quality)
            _validate_core(core, False)
            fingerprint(source, source_fp)
            if core.status == "PRESERVED_ORIGINAL":
                guard.validate(stage)
                shutil.copyfile(source, stage)
            output_fp = fingerprint(stage)
            fingerprint(source, source_fp)
            if core.status == "PRESERVED_ORIGINAL" and output_fp.sha256 != source_fp.sha256:
                raise OSError("preserved workbook differs from original")
            if core.status == "ADOPTED_LOSSY" and output_fp.identity.size >= source_fp.identity.size:
                raise ValueError("candidate workbook is not strictly smaller")
            publish(stage, destination, guard, output_fp)
            published_fp = fingerprint(destination)
            if published_fp.sha256 != output_fp.sha256 or published_fp.identity.size != output_fp.identity.size:
                raise OSError("published Excel workbook verification failed")
        return replace(
            result, status=core.status, reason=core.reason, **analysis.report_fields(),
            images_changed=core.images_changed, changed_parts=core.changed_parts,
            output_size=published_fp.identity.size, output_sha256=published_fp.sha256,
        ), source_fp, published_fp
    except Exception as exc:
        LOGGER.error("%s: %s", source, exc)
        return replace(result, reason=f"{type(exc).__name__}: {exc}", **analysis.report_fields()), source_fp, None


def run(config: ExcelConfig) -> RunOutcome:
    results: list[ProcessResult] = []
    source_fps: dict[str, Fingerprint] = {}
    output_fps: dict[str, Fingerprint] = {}
    try:
        source_root, output_root = validate_roots(config.input_dir, config.output_dir)
        config = replace(config, input_dir=source_root, output_dir=output_root)
        sources = discover_files(source_root)
        selected = tuple(source for source in sources if config.selected(source.relative_to(source_root)))
        guard = PathGuard(source_root, output_root, config.report_path, config.work_dir, sources)
        guard.preflight(tuple(output_root / source.relative_to(source_root) for source in selected))
        for source in selected:
            result, source_fp, output_fp = _one(source, config, guard)
            results.append(result)
            if source_fp is not None:
                source_fps[str(source)] = source_fp
            if output_fp is not None:
                output_fps[result.output_path] = output_fp

        def validate_results() -> None:
            for result in results:
                if result.status == "ERROR":
                    continue
                fingerprint(Path(result.source_path), source_fps[result.source_path])
                if result.output_size is not None:
                    guard.validate(Path(result.output_path))
                    fingerprint(Path(result.output_path), output_fps[result.output_path])

        write_report(config.report_path, results, guard, before_publish=validate_results)
        return RunOutcome(tuple(results), int(any(item.status == "ERROR" for item in results)), config.report_path)
    except Exception as exc:
        LOGGER.error("Excel processing failed: %s", exc)
        return RunOutcome(tuple(results), 1, error=f"{type(exc).__name__}: {exc}")
