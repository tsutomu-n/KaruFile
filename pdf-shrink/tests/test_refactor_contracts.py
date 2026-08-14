"""責務分離で明示した状態・探索・出力契約のテスト。"""
from __future__ import annotations

import csv
import zipfile
from dataclasses import replace
from pathlib import Path

import pymupdf as fitz
import pytest

from pdf_shrink import cli, config, discovery, inspect_pdf, output, qpdf, runner, state, worker
from pdf_shrink.models import (
    OptimizationMode,
    ProcessResult,
    ProcessStatus,
    SourceSnapshot,
)


def _snapshot(path: Path, sha256: str = "hash") -> SourceSnapshot:
    stat = path.stat()
    return SourceSnapshot(
        path=path.resolve(),
        relative_path=Path(path.name),
        sha256=sha256,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )


def _result(path: Path, status: ProcessStatus, output_size: int | None) -> ProcessResult:
    return ProcessResult(
        output_path=path,
        status=status,
        mode=None,
        page_count=0,
        scan_page_ratio=0.0,
        output_size=output_size,
        saved_bytes=0,
        saved_percent=0.0,
        error_message=None,
    )


def test_collect_pdfs_is_case_insensitive(tmp_path: Path) -> None:
    lower = tmp_path / "a.pdf"
    upper = tmp_path / "b.PDF"
    ignored = tmp_path / "c.txt"
    for path in (lower, upper, ignored):
        path.write_bytes(b"x")

    assert discovery.collect_pdfs(tmp_path) == [lower, upper]


def test_config_hash_includes_execution_mode_and_tool_versions(tmp_path: Path) -> None:
    cfg = config.default_config(input_dir=tmp_path, output_dir=tmp_path / "out")

    assert config.config_hash(cfg) != config.config_hash(replace(cfg, dry_run=True))
    assert config.config_hash(cfg) != config.config_hash(
        replace(cfg, output_dir=tmp_path / "other-out")
    )
    assert config.config_hash(cfg) != config.config_hash(
        cfg.with_tool_versions(pymupdf="different", qpdf="different")
    )


def test_state_lists_only_requested_sources(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    first_snapshot = _snapshot(first, "first-hash")
    second_snapshot = _snapshot(second, "second-hash")
    conn = state.init_db(tmp_path / "state.sqlite3")
    try:
        state.save_result(
            conn,
            first_snapshot,
            _result(tmp_path / "out-first.pdf", ProcessStatus.UNCHANGED, first.stat().st_size),
            "config",
            pymupdf_version="pymupdf",
            qpdf_version="qpdf",
        )
        state.save_result(
            conn,
            second_snapshot,
            _result(tmp_path / "out-second.pdf", ProcessStatus.UNCHANGED, second.stat().st_size),
            "config",
            pymupdf_version="pymupdf",
            qpdf_version="qpdf",
        )

        records = state.list_records_for_paths(conn, [str(second.resolve())])
    finally:
        conn.close()

    assert [record.source_path for record in records] == [str(second.resolve())]


def test_unrecovered_error_is_retried_without_retry_flag(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source")
    snapshot = _snapshot(source)
    conn = state.init_db(tmp_path / "state.sqlite3")
    try:
        state.save_result(
            conn,
            snapshot,
            _result(tmp_path / "missing.pdf", ProcessStatus.ERROR, None),
            "config",
            pymupdf_version="pymupdf",
            qpdf_version="qpdf",
        )
        record = state.get_record(conn, str(source.resolve()))
    finally:
        conn.close()

    assert state.should_process(record, "hash", "config", False, False)


def test_atomic_copy_preserves_existing_output_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "out" / "result.pdf"
    source.write_bytes(b"new")
    destination.parent.mkdir()
    destination.write_bytes(b"existing")

    def fail_copy(*_args: object, **_kwargs: object) -> None:
        raise OSError("copy failed")

    monkeypatch.setattr(output.shutil, "copy2", fail_copy)
    with pytest.raises(OSError, match="copy failed"):
        output.copy_original(source, destination)

    assert destination.read_bytes() == b"existing"
    assert list(destination.parent.glob(f".{destination.name}.*.tmp")) == []


def test_white_integer_srgb_text_does_not_block_scan_detection(tmp_path: Path) -> None:
    image_source = fitz.open()
    image_page = image_source.new_page(width=144, height=144)
    image_page.draw_rect(image_page.rect, color=(0, 0, 0), fill=(0, 0, 0))
    pixmap = image_page.get_pixmap(dpi=72, colorspace=fitz.csRGB)

    path = tmp_path / "white-text-scan.pdf"
    document = fitz.open()
    page = document.new_page(width=144, height=144)
    page.insert_image(page.rect, pixmap=pixmap)
    page.insert_text((5, 12), "invisible text " * 10, fontsize=4, color=(1, 1, 1))
    document.save(path)
    document.close()
    image_source.close()

    cfg = config.default_config(input_dir=tmp_path, output_dir=tmp_path.parent / "out")
    result = inspect_pdf.inspect_file(path, cfg.scan, safe=False)

    assert result.ok
    assert result.mode is OptimizationMode.LOSSY


def test_dry_run_reports_plan_without_creating_pdf(
    tmp_path: Path,
    sample_pdfs: dict[str, Path],
) -> None:
    source = discovery.snapshot(sample_pdfs["scan"], tmp_path / "PDF")
    cfg = replace(
        config.default_config(input_dir=tmp_path / "PDF", output_dir=tmp_path / "out"),
        dry_run=True,
    )

    result = worker.process_one_file(source, cfg, tmp_path / "temp", None)

    assert result.status is ProcessStatus.DRY_RUN_LOSSY
    assert result.output_size is None
    assert not result.output_path.exists()


def test_dry_run_does_not_require_qpdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "small.pdf").write_bytes(b"small")
    cfg = replace(
        config.default_config(input_dir=input_dir, output_dir=tmp_path / "output"),
        dry_run=True,
    )

    def unexpected_qpdf_lookup(*_args: object, **_kwargs: object) -> Path:
        raise AssertionError("dry-run must not prepare qpdf")

    monkeypatch.setattr(qpdf, "ensure_qpdf", unexpected_qpdf_lookup)

    assert runner.run(cfg) == 0


def test_runner_returns_failure_when_current_result_has_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "source.pdf").write_bytes(b"source")
    cfg = replace(
        config.default_config(input_dir=input_dir, output_dir=tmp_path / "output"),
        dry_run=True,
    )

    def error_result(sources, *_args, **_kwargs):
        for source in sources:
            yield source, _result(
                source.output_path(cfg.output_dir),
                ProcessStatus.ERROR,
                None,
            )

    monkeypatch.setattr(runner, "_execute", error_result)

    assert runner.run(cfg) == 1


def test_cli_report_excludes_other_input_records(tmp_path: Path) -> None:
    first_input = tmp_path / "first"
    second_input = tmp_path / "second"
    first_input.mkdir()
    second_input.mkdir()
    first_pdf = first_input / "first.pdf"
    second_pdf = second_input / "second.pdf"
    first_pdf.write_bytes(b"small first")
    second_pdf.write_bytes(b"small second")

    assert cli.main([
        "run", "--input", str(first_input), "--output", str(tmp_path / "first-out"), "--dry-run",
    ]) == 0
    assert cli.main([
        "run", "--input", str(second_input), "--output", str(tmp_path / "second-out"), "--dry-run",
    ]) == 0

    with open(tmp_path / "report.dry-run.csv", newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["source_path"] for row in rows] == [str(second_pdf.resolve())]


def test_qpdf_archive_rejects_parent_traversal(tmp_path: Path) -> None:
    archive_path = tmp_path / "qpdf.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../escaped.txt", "unsafe")

    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(RuntimeError, match="Unsafe path"):
            qpdf._safe_extract(archive, tmp_path / "extract")

    assert not (tmp_path / "escaped.txt").exists()


def test_cli_rejects_input_file(tmp_path: Path) -> None:
    input_file = tmp_path / "not-a-directory"
    input_file.write_text("x", encoding="utf-8")

    assert cli.main(["run", "--input", str(input_file), "--dry-run"]) == 1
