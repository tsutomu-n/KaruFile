"""一括処理ユースケースのオーケストレーション。"""
from __future__ import annotations

import os
import stat
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pymupdf as fitz

from . import discovery, lossless_jpeg, output, qpdf, report, state, worker
from .config import RunConfig, config_hash, profile_for_path
from .models import ProcessResult, ProcessStatus, SourceSnapshot
from .utils import ensure_dir, human_size, logger, sha256_file


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

    if cfg.lossless_jpeg:
        path, version, digest = lossless_jpeg.prepare_tool(cfg.jpegtran_path)
        cfg = replace(cfg, jpegtran_path=path, jpegtran_version=version, jpegtran_sha256=digest)

    executable = qpdf.ensure_qpdf(cfg.qpdf_path)
    version = qpdf.qpdf_version(executable)
    return cfg.with_tool_versions(pymupdf=_pymupdf_version(), qpdf=version), executable


def _output_matches_record(record: state.Record | None, destination: Path) -> bool:
    """Verify a completed output by identity, size, and content digest."""
    if (
        record is None
        or record.output_size is None
        or not record.output_sha256
    ):
        return False
    try:
        before = destination.stat()
        if not destination.is_file() or before.st_size != record.output_size:
            return False
        digest = sha256_file(destination)
        after = destination.stat()
    except OSError:
        return False
    before_signature = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    after_signature = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    return before_signature == after_signature and digest == record.output_sha256


def _validate_report_snapshot(
    sources: list[SourceSnapshot],
    records: list[state.Record],
    cfg: RunConfig,
    processing_hash: str,
    protected_sources: tuple[Path, ...],
) -> None:
    """Revalidate every input and completed output at report publication."""
    records_by_source = {record.source_path: record for record in records}
    for source in sources:
        discovery.assert_source_unchanged(source, cfg.input_dir)
        record = records_by_source.get(str(source.path))
        if (
            record is None
            or record.source_sha256 != source.sha256
            or record.config_hash != processing_hash
        ):
            raise RuntimeError(f"PDF state is incomplete for report: {source.path}")
        if not cfg.dry_run and record.output_size is not None:
            destination = source.output_path(cfg.output_dir)
            output.validate_destination(
                destination,
                input_root=cfg.input_dir,
                output_root=cfg.output_dir,
                protected_sources=protected_sources,
            )
            if not _output_matches_record(
                record,
                destination,
            ):
                raise RuntimeError(
                    f"PDF output changed before report publication: {source.path}"
                )
            # The digest may take long enough for a link to be injected after
            # the first topology check.  Make topology the final output check.
            output.validate_destination(
                destination,
                input_root=cfg.input_dir,
                output_root=cfg.output_dir,
                protected_sources=protected_sources,
            )
        elif not cfg.dry_run and record.status != ProcessStatus.ERROR:
            raise RuntimeError(f"PDF output is missing before report: {source.path}")
        # Output hashing above can itself be long-running.
        discovery.assert_source_unchanged(source, cfg.input_dir)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _overlaps(first: Path, second: Path) -> bool:
    return _is_within(first, second) or _is_within(second, first)


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, FileNotFoundError):
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _has_link_component(root: Path, candidate: Path) -> bool:
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return True
    current = root
    if _is_link_or_junction(current):
        return True
    for part in relative.parts:
        current = current / part
        if _is_link_or_junction(current):
            return True
    return False


def _validate_workspace_paths(
    cfg: RunConfig,
    paths: WorkspacePaths,
    sources: list[SourceSnapshot],
    protected_sources: tuple[Path, ...],
) -> None:
    """状態・一時・reportの派生writeが入力やPDF出力と衝突しないか検証する。"""

    input_root = cfg.input_dir.resolve(strict=True)
    output_root = cfg.output_dir.resolve(strict=False)
    work_root = Path(os.path.abspath(cfg.output_dir.parent))
    work_root_resolved = work_root.resolve(strict=False)
    derived: list[tuple[str, Path]] = [
        ("state directory", paths.state_dir),
        ("temporary directory", paths.temp_root),
        ("state database", paths.database),
        ("state database journal", Path(f"{paths.database}-journal")),
        ("state database WAL", Path(f"{paths.database}-wal")),
        ("state database shared memory", Path(f"{paths.database}-shm")),
        ("report", work_root / "report.csv"),
        ("dry-run report", work_root / "report.dry-run.csv"),
    ]
    if cfg.preview:
        derived.extend([
            ("preview directory", work_root / "pdf-preview"),
            ("preview report", work_root / "pdf-preview.json"),
            ("dry-run preview report", work_root / "pdf-preview.dry-run.json"),
        ])
    derived.extend(
        (
            "per-source temporary directory",
            paths.temp_root / source.relative_path.parent,
        )
        for source in sources
    )
    for label, candidate in derived:
        candidate_lexical = Path(os.path.abspath(candidate))
        if not _is_within(candidate_lexical, work_root):
            raise ValueError(f"{label} is outside the PDF work root: {candidate}")
        if _has_link_component(work_root, candidate_lexical):
            raise ValueError(f"{label} contains a symlink or junction: {candidate}")
        resolved = candidate.resolve(strict=False)
        if not _is_within(resolved, work_root_resolved):
            raise ValueError(
                f"{label} escapes the PDF work root after resolving links: "
                f"{candidate} -> {resolved}"
            )
        if _overlaps(resolved, input_root):
            raise ValueError(
                f"{label} overlaps the input after resolving filesystem links: "
                f"{candidate} -> {resolved}"
            )
        if _overlaps(resolved, output_root):
            raise ValueError(
                f"{label} overlaps the PDF output root: {candidate} -> {resolved}"
            )
        if candidate.exists():
            candidate_stat = candidate.stat()
            if not candidate.is_dir() and candidate_stat.st_nlink > 1:
                raise ValueError(f"{label} is hard-linked: {candidate}")
            for source_path in protected_sources:
                try:
                    same_file = os.path.samefile(candidate, source_path)
                except OSError as exc:
                    raise ValueError(
                        f"Could not verify {label} identity for {candidate}: {exc}"
                    ) from exc
                if same_file:
                    raise ValueError(
                        f"{label} is a hard link to an input source: "
                        f"{candidate} == {source_path}"
                    )


def _worker_crash_result(
    source: SourceSnapshot,
    cfg: RunConfig,
    exc: BaseException,
) -> ProcessResult:
    destination = source.output_path(cfg.output_dir)
    profile = profile_for_path(cfg, source.relative_path)
    error_message = f"{exc}\n{traceback.format_exc()}"
    recovered_size: int | None = None
    if (
        not cfg.dry_run
        and discovery.source_is_unchanged(source, cfg.input_dir)
    ):
        try:
            output.copy_original(
                source,
                destination,
                input_root=cfg.input_dir,
                output_root=cfg.output_dir,
            )
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
        profile=profile,
        requested_policy=profile,
        classification="unclassified",
        decision_reason="processing_error",
        lossless_jpeg_requested=cfg.lossless_jpeg,
        photo_dpi=cfg.photo_dpi if profile == "photo" else None,
        font_replacement_requested=profile == "font_replace",
        replacement_font=cfg.replacement_font if profile == "font_replace" else "",
        replacement_font_sha256=cfg.font_replace_sha256 if profile == "font_replace" else "",
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
                "Finished %s in %.2fs (status=%s, saved=%s, mode=%s, "
                "profile=%s, reason=%s, candidate_size=%s, images_changed=%d)",
                source.path,
                task_elapsed,
                result.status,
                human_size(result.saved_bytes),
                result.mode or "-",
                result.profile or "-",
                result.decision_reason or "-",
                human_size(result.candidate_size) if result.candidate_size is not None else "-",
                result.images_changed,
            )
            yield source, result


def run(cfg: RunConfig) -> int:
    try:
        discovery.validate_directories(cfg.input_dir, cfg.output_dir)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.error("%s", exc)
        return 1

    paths = WorkspacePaths.from_config(cfg)
    try:
        files = discovery.collect_pdfs(cfg.input_dir)
        logger.info("Found %d PDF files", len(files))
        selected = discovery.select_pilot(files, cfg.limit)
        if cfg.limit is not None:
            logger.info("Limited to %d files for pilot run", len(selected))
        sources = [discovery.snapshot(path, cfg.input_dir) for path in selected]
        # Validate all permissions before tool execution or output publication.
        for path in files:
            profile_for_path(cfg, path.relative_to(cfg.input_dir))
        # --limit の未選択PDFもhardlink保護対象。未選択原本へのchmod/置換も禁止する。
        protected_sources = tuple(files)
        for source in sources:
            output.validate_destination(
                source.output_path(cfg.output_dir),
                input_root=cfg.input_dir,
                output_root=cfg.output_dir,
                protected_sources=protected_sources,
            )
        _validate_workspace_paths(cfg, paths, sources, protected_sources)
        if any(profile_for_path(cfg, source.relative_path) == "font_replace" for source in sources):
            from .font_replace import prepare_font
            font_path, font_sha256 = prepare_font() if cfg.font_family == "meiryo" else prepare_font(cfg.font_family)
            cfg = replace(cfg, font_replace_path=font_path, font_replace_sha256=font_sha256)
            logger.warning(
                "Font replacement requested: %s. Typeface and search/copy whitespace may change.", cfg.replacement_font
            )
    except (OSError, RuntimeError, ValueError) as exc:
        logger.error("PDF preflight failed: %s", exc)
        return 1

    try:
        ensure_dir(paths.state_dir)
        if not cfg.dry_run:
            ensure_dir(cfg.output_dir)
            ensure_dir(paths.temp_root)
    except OSError as exc:
        logger.error("Failed to create PDF workspace directories: %s", exc)
        return 1

    try:
        if sources:
            cfg, qpdf_exe = _prepare_tools(cfg)
        else:
            # Empty runs still publish current empty reports, without resolving,
            # executing, or downloading optional external tools.
            cfg = replace(
                cfg, pymupdf_version="", qpdf_version="",
                jpegtran_version="", jpegtran_sha256="",
            )
            qpdf_exe = None
    except Exception as exc:
        logger.error("Failed to prepare PDF tools: %s", exc)
        return 1

    processing_hash = config_hash(cfg)
    logger.info("Config hash: %s", processing_hash[:16])

    try:
        for source in sources:
            output.validate_destination(
                source.output_path(cfg.output_dir),
                input_root=cfg.input_dir,
                output_root=cfg.output_dir,
                protected_sources=protected_sources,
            )
        _validate_workspace_paths(cfg, paths, sources, protected_sources)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.error("PDF preflight changed before state initialization: %s", exc)
        return 1

    try:
        conn = state.init_db(paths.database)
    except Exception as exc:
        logger.error("Failed to initialize PDF state database: %s", exc)
        return 1
    try:
        to_process: list[SourceSnapshot] = []
        for source in sources:
            try:
                discovery.assert_source_unchanged(source, cfg.input_dir)
            except discovery.SourceChangedError as exc:
                logger.error("PDF input changed before reuse decision: %s", exc)
                return 1
            destination = source.output_path(cfg.output_dir)
            record = state.get_record(conn, str(source.path))
            output_matches_record = _output_matches_record(record, destination)
            try:
                discovery.assert_source_unchanged(source, cfg.input_dir)
            except discovery.SourceChangedError as exc:
                logger.error("PDF input changed during reuse decision: %s", exc)
                return 1
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
            try:
                state.save_result(
                    conn,
                    source,
                    result,
                    processing_hash,
                    input_dir=cfg.input_dir,
                    pymupdf_version=cfg.pymupdf_version,
                    qpdf_version=cfg.qpdf_version,
                    commit=False,
                )
            except discovery.SourceChangedError as exc:
                logger.error("PDF input changed before state publication: %s", exc)
                conn.rollback()
                return 1
        elapsed = time.perf_counter() - process_start

        records = state.list_records_for_paths(
            conn,
            (str(source.path) for source in sources),
        )
        report.write_csv(
            records,
            paths.report,
            input_root=cfg.input_dir,
            work_root=cfg.output_dir.parent,
            protected_sources=files,
            output_root=cfg.output_dir,
            preset=str(cfg.preset),
            before_publish=lambda: _validate_report_snapshot(
                sources,
                records,
                cfg,
                processing_hash,
                protected_sources,
            ),
            after_publish=conn.commit,
        )
    except Exception as exc:
        conn.rollback()
        logger.error("Failed to write PDF report: %s", exc)
        return 1
    finally:
        conn.close()
    report.print_summary(records, elapsed_seconds=elapsed)
    logger.info("Report saved to %s", paths.report)
    if cfg.preview:
        # Preview is a separate publication after PDF state/report commit. Its
        # failure must never roll back already verified normal PDF results.
        try:
            from . import preview

            if not preview.generate(cfg, sources, records, qpdf_exe, protected_sources):
                logger.error("PDF preview failed; completed PDF report/state are retained")
                return 1
        except Exception as exc:
            logger.error(
                "PDF preview failed; completed PDF report/state are retained: %s", exc,
            )
            return 1
    return 1 if any(record.status == ProcessStatus.ERROR for record in records) else 0
