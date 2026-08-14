"""一括処理ユースケースのオーケストレーション。"""
from __future__ import annotations

import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf as fitz

from . import discovery, output, qpdf, report, state, worker
from .config import RunConfig, config_hash
from .models import ProcessResult, ProcessStatus, SourceSnapshot
from .utils import ensure_dir, human_size, logger


@dataclass(frozen=True)
class WorkspacePaths:
    state_dir: Path
    temp_root: Path
    database: Path
    report: Path

    @classmethod
    def from_config(cls, cfg: RunConfig) -> WorkspacePaths:
        work_root = cfg.output_dir.parent
        state_dir = work_root / ".pdf-shrink"
        report_name = "report.dry-run.csv" if cfg.dry_run else "report.csv"
        return cls(
            state_dir=state_dir,
            temp_root=state_dir / "temp",
            database=state_dir / "state.sqlite3",
            report=work_root / report_name,
        )


def _pymupdf_version() -> str:
    try:
        return fitz.version[0]
    except Exception:
        return "unknown"


def _prepare_tools(cfg: RunConfig) -> tuple[RunConfig, Path | None]:
    if cfg.dry_run:
        return cfg.with_tool_versions(pymupdf=_pymupdf_version(), qpdf=""), None

    executable = qpdf.ensure_qpdf(cfg.qpdf_path)
    version = qpdf.qpdf_version(executable)
    return cfg.with_tool_versions(pymupdf=_pymupdf_version(), qpdf=version), executable


def _worker_crash_result(
    source: SourceSnapshot,
    cfg: RunConfig,
    exc: BaseException,
) -> ProcessResult:
    destination = source.output_path(cfg.output_dir)
    error_message = f"{exc}\n{traceback.format_exc()}"
    recovered_size: int | None = None
    if not cfg.dry_run:
        try:
            output.copy_original(source.path, destination)
            recovered_size = destination.stat().st_size
        except Exception as copy_error:
            error_message += f"\nrecovery_copy_failed: {copy_error}"
            logger.error(
                "Failed to copy original after worker crash %s: %s",
                source.path,
                copy_error,
            )
    return ProcessResult(
        output_path=destination,
        status=ProcessStatus.ERROR,
        mode=None,
        page_count=0,
        scan_page_ratio=0.0,
        output_size=recovered_size,
        saved_bytes=0,
        saved_percent=0.0,
        error_message=error_message,
    )


def _execute(
    sources: list[SourceSnapshot],
    cfg: RunConfig,
    paths: WorkspacePaths,
    qpdf_exe: Path | None,
):
    if not sources:
        return
    max_workers = min(cfg.workers, len(sources))
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures: dict[Any, SourceSnapshot] = {}
        task_starts: dict[Any, float] = {}
        for source in sources:
            future = executor.submit(
                worker.process_one_file,
                source,
                cfg,
                paths.temp_root,
                qpdf_exe,
            )
            task_starts[future] = time.perf_counter()
            futures[future] = source
        for future in as_completed(futures):
            source = futures[future]
            task_elapsed = time.perf_counter() - task_starts.pop(future)
            try:
                result = future.result()
            except Exception as exc:
                logger.error("Worker crashed for %s: %s", source.path, exc)
                result = _worker_crash_result(source, cfg, exc)
            logger.info(
                "Finished %s in %.2fs (status=%s, saved=%s, mode=%s)",
                source.path,
                task_elapsed,
                result.status,
                human_size(result.saved_bytes),
                result.mode or "-",
            )
            yield source, result


def run(cfg: RunConfig) -> int:
    try:
        discovery.validate_directories(cfg.input_dir, cfg.output_dir)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    paths = WorkspacePaths.from_config(cfg)
    ensure_dir(paths.state_dir)
    if not cfg.dry_run:
        ensure_dir(cfg.output_dir)
        ensure_dir(paths.temp_root)

    try:
        cfg, qpdf_exe = _prepare_tools(cfg)
    except Exception as exc:
        logger.error("Failed to locate qpdf: %s", exc)
        return 1

    processing_hash = config_hash(cfg)
    logger.info("Config hash: %s", processing_hash[:16])

    files = discovery.collect_pdfs(cfg.input_dir)
    logger.info("Found %d PDF files", len(files))
    selected = discovery.select_pilot(files, cfg.limit)
    if cfg.limit is not None:
        logger.info("Limited to %d files for pilot run", len(selected))
    try:
        sources = [discovery.snapshot(path, cfg.input_dir) for path in selected]
    except (OSError, ValueError) as exc:
        logger.error("Failed to read an input PDF: %s", exc)
        return 1

    conn = state.init_db(paths.database)
    try:
        to_process: list[SourceSnapshot] = []
        for source in sources:
            destination = source.output_path(cfg.output_dir)
            record = state.get_record(conn, str(source.path))
            output_matches_record = (
                record is not None
                and record.output_size is not None
                and destination.is_file()
                and destination.stat().st_size == record.output_size
            )
            if state.should_process(
                record,
                source.sha256,
                processing_hash,
                cfg.retry_errors,
                output_matches_record,
                output_required=not cfg.dry_run,
            ):
                to_process.append(source)
            else:
                logger.debug("Skipping unchanged file: %s", source.path)

        logger.info(
            "Files to process: %d, skipped: %d",
            len(to_process),
            len(sources) - len(to_process),
        )

        process_start = time.perf_counter()
        for source, result in _execute(to_process, cfg, paths, qpdf_exe):
            state.save_result(
                conn,
                source,
                result,
                processing_hash,
                pymupdf_version=cfg.pymupdf_version,
                qpdf_version=cfg.qpdf_version,
            )
        elapsed = time.perf_counter() - process_start

        records = state.list_records_for_paths(
            conn,
            (str(source.path) for source in sources),
        )
    finally:
        conn.close()

    report.write_csv(records, paths.report)
    report.print_summary(records, elapsed_seconds=elapsed)
    logger.info("Report saved to %s", paths.report)
    return 1 if any(record.status == ProcessStatus.ERROR for record in records) else 0
