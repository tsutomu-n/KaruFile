"""責務分離で明示した状態・探索・出力契約のテスト。"""
from __future__ import annotations

import csv
import os
import stat
import subprocess
import zipfile
from dataclasses import replace
from pathlib import Path

import pymupdf as fitz
import pytest

from pdf_shrink import (
    cli,
    config,
    discovery,
    inspect_pdf,
    output,
    qpdf,
    report,
    runner,
    state,
    worker,
)
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


def _make_directory_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            pytest.skip(f"could not create test junction: {completed.stderr}")
    else:
        link.symlink_to(target, target_is_directory=True)


def _rendered_page_pixmap(width: float, height: float, dpi: int) -> fitz.Pixmap:
    document = fitz.open()
    page = document.new_page(width=width, height=height)
    page.draw_rect(page.rect, color=(0, 0, 0), fill=(0, 0, 0))
    pixmap = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB)
    document.close()
    return pixmap


def _write_full_page_image_pdf(
    path: Path,
    *,
    dpi: int,
    text: str | None = None,
    text_render_mode: int = 0,
    text_color: tuple[float, float, float] = (0, 0, 0),
) -> None:
    width = height = 144
    pixmap = _rendered_page_pixmap(width, height, dpi)
    document = fitz.open()
    page = document.new_page(width=width, height=height)
    page.insert_image(page.rect, pixmap=pixmap)
    if text is not None:
        page.insert_text(
            (5, 12),
            text,
            fontsize=4,
            color=text_color,
            render_mode=text_render_mode,
        )
    document.save(path)
    document.close()


def _inspect_mode(path: Path) -> OptimizationMode:
    cfg = config.default_config(input_dir=path.parent, output_dir=path.parent / "out")
    result = inspect_pdf.inspect_file(path, cfg.scan, safe=False)
    assert result.ok
    assert result.mode is not None
    return result.mode


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
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    source = input_dir / "source.pdf"
    destination = tmp_path / "out" / "result.pdf"
    source.write_bytes(b"new")
    destination.parent.mkdir()
    destination.write_bytes(b"existing")

    def fail_copy(*_args: object, **_kwargs: object) -> None:
        raise OSError("copy failed")

    monkeypatch.setattr(output.shutil, "copy2", fail_copy)
    with pytest.raises(OSError, match="copy failed"):
        output.copy_original(
            source,
            destination,
            input_root=input_dir,
            output_root=destination.parent,
        )

    assert destination.read_bytes() == b"existing"
    assert list(destination.parent.glob(f".{destination.name}.*.tmp")) == []


def test_collect_pdfs_rejects_linked_directory(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    external = tmp_path / "external"
    input_dir.mkdir()
    external.mkdir()
    (external / "outside.pdf").write_bytes(b"outside")
    _make_directory_link(input_dir / "linked", external)

    with pytest.raises(ValueError, match="junction"):
        discovery.collect_pdfs(input_dir)


def test_source_output_path_does_not_resolve_through_junction(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    source_dir = input_dir / "nested"
    output_dir = tmp_path / "output"
    source_dir.mkdir(parents=True)
    output_dir.mkdir()
    source = source_dir / "source.pdf"
    source.write_bytes(b"source")
    _make_directory_link(output_dir / "nested", source_dir)
    snapshot = discovery.snapshot(source, input_dir)

    assert snapshot.output_path(output_dir) == output_dir / "nested" / "source.pdf"
    assert snapshot.output_path(output_dir).resolve() == source.resolve()


def test_copy_original_rejects_junction_escape_without_mutating_source(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    source_dir = input_dir / "nested"
    output_dir = tmp_path / "output"
    source_dir.mkdir(parents=True)
    output_dir.mkdir()
    source = source_dir / "source.pdf"
    source.write_bytes(b"original")
    _make_directory_link(output_dir / "nested", source_dir)
    destination = output_dir / "nested" / "source.pdf"

    with pytest.raises(ValueError, match="junction|input root"):
        output.copy_original(
            source,
            destination,
            input_root=input_dir,
            output_root=output_dir,
        )

    assert source.read_bytes() == b"original"


def test_copy_original_replaces_read_only_output_and_cleans_temp(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    source = input_dir / "source.pdf"
    destination = output_dir / "source.pdf"
    source.write_bytes(b"first")
    os.chmod(source, stat.S_IREAD)
    try:
        output.copy_original(
            source,
            destination,
            input_root=input_dir,
            output_root=output_dir,
        )
        os.chmod(source, stat.S_IWRITE | stat.S_IREAD)
        source.write_bytes(b"second")
        os.chmod(source, stat.S_IREAD)
        os.chmod(destination, stat.S_IREAD)

        output.copy_original(
            source,
            destination,
            input_root=input_dir,
            output_root=output_dir,
        )

        assert destination.read_bytes() == b"second"
        assert list(output_dir.glob(f".{destination.name}.*.tmp")) == []
    finally:
        os.chmod(source, stat.S_IWRITE | stat.S_IREAD)
        if destination.exists():
            os.chmod(destination, stat.S_IWRITE | stat.S_IREAD)


def test_copy_original_rejects_hard_link_to_current_source(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source = input_dir / "source.pdf"
    destination = output_dir / "source.pdf"
    source.write_bytes(b"source")
    os.link(source, destination)

    with pytest.raises(ValueError, match="hard link"):
        output.copy_original(
            source,
            destination,
            input_root=input_dir,
            output_root=output_dir,
        )

    assert source.read_bytes() == b"source"


def test_report_atomically_replaces_read_only_output(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    report_path = tmp_path / "report.csv"
    report.write_csv(
        [],
        report_path,
        input_root=input_dir,
        work_root=tmp_path,
        protected_sources=(),
    )
    os.chmod(report_path, stat.S_IREAD)
    try:
        report.write_csv(
            [],
            report_path,
            input_root=input_dir,
            work_root=tmp_path,
            protected_sources=(),
        )
        assert "source_path" in report_path.read_text(encoding="utf-8-sig")
        assert list(tmp_path.glob(f".{report_path.name}.*.tmp")) == []
    finally:
        os.chmod(report_path, stat.S_IWRITE | stat.S_IREAD)


def test_report_rejects_hardlink_before_chmod_or_replace(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    external = tmp_path / "external.csv"
    report_path = tmp_path / "report.csv"
    external.write_bytes(b"external")
    os.link(external, report_path)

    with pytest.raises(ValueError, match="hard-linked"):
        report.write_csv(
            [],
            report_path,
            input_root=input_dir,
            work_root=tmp_path,
            protected_sources=(),
        )

    assert external.read_bytes() == b"external"


def test_runner_rejects_output_junction_before_tool_preparation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    source_dir = input_dir / "nested"
    output_dir = tmp_path / "output"
    source_dir.mkdir(parents=True)
    output_dir.mkdir()
    source = source_dir / "source.pdf"
    source.write_bytes(b"source")
    _make_directory_link(output_dir / "nested", source_dir)
    cfg = replace(
        config.default_config(input_dir=input_dir, output_dir=output_dir),
        dry_run=True,
    )
    monkeypatch.setattr(
        runner,
        "_prepare_tools",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("tools must not be prepared before preflight")
        ),
    )

    assert runner.run(cfg) == 1
    assert source.read_bytes() == b"source"


def test_runner_rejects_output_hard_link_to_another_input_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    first = input_dir / "a.pdf"
    second = input_dir / "b.pdf"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    selected = discovery.select_pilot([first, second], 1)[0]
    unselected = second if selected == first else first
    os.link(unselected, output_dir / selected.name)
    cfg = replace(
        config.default_config(input_dir=input_dir, output_dir=output_dir),
        dry_run=True,
        limit=1,
    )
    monkeypatch.setattr(
        runner,
        "_prepare_tools",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("tools must not be prepared before preflight")
        ),
    )

    assert runner.run(cfg) == 1
    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"second"


@pytest.mark.parametrize("input_name", [".pdf-shrink", "report.csv", "report.dry-run.csv"])
def test_runner_rejects_workspace_collision_before_tool_preparation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    input_name: str,
) -> None:
    input_dir = tmp_path / input_name
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "source.pdf").write_bytes(b"source")
    cfg = replace(
        config.default_config(input_dir=input_dir, output_dir=output_dir),
        dry_run=True,
    )
    monkeypatch.setattr(
        runner,
        "_prepare_tools",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("tools must not be prepared before preflight")
        ),
    )

    assert runner.run(cfg) == 1


def test_runner_rejects_state_junction_into_input_before_tool_preparation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "source.pdf").write_bytes(b"source")
    _make_directory_link(tmp_path / ".pdf-shrink", input_dir)
    cfg = replace(
        config.default_config(input_dir=input_dir, output_dir=output_dir),
        dry_run=True,
    )
    monkeypatch.setattr(
        runner,
        "_prepare_tools",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("tools must not be prepared before preflight")
        ),
    )

    assert runner.run(cfg) == 1


def test_runner_rejects_state_junction_outside_work_root_before_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    external = tmp_path / "external"
    input_dir.mkdir()
    external.mkdir()
    (input_dir / "source.pdf").write_bytes(b"source")
    _make_directory_link(tmp_path / ".pdf-shrink", external)
    cfg = replace(
        config.default_config(input_dir=input_dir, output_dir=output_dir),
        dry_run=True,
    )
    monkeypatch.setattr(
        runner,
        "_prepare_tools",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("tools must not be prepared before preflight")
        ),
    )

    assert runner.run(cfg) == 1


@pytest.mark.parametrize(
    "sidecar",
    ["state.sqlite3", "state.sqlite3-journal", "state.sqlite3-wal", "state.sqlite3-shm"],
)
def test_runner_rejects_state_sidecar_hardlink_to_unselected_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sidecar: str,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    state_dir = tmp_path / ".pdf-shrink"
    input_dir.mkdir()
    state_dir.mkdir()
    first = input_dir / "a.pdf"
    second = input_dir / "b.pdf"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    selected = discovery.select_pilot([first, second], 1)[0]
    unselected = second if selected == first else first
    os.link(unselected, state_dir / sidecar)
    cfg = replace(
        config.default_config(input_dir=input_dir, output_dir=output_dir),
        dry_run=True,
        limit=1,
    )
    monkeypatch.setattr(
        runner,
        "_prepare_tools",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("tools must not be prepared before preflight")
        ),
    )

    assert runner.run(cfg) == 1
    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"second"


def test_runner_rejects_report_hard_link_to_input_before_tool_preparation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    first = input_dir / "a.pdf"
    second = input_dir / "b.pdf"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    selected = discovery.select_pilot([first, second], 1)[0]
    unselected = second if selected == first else first
    os.link(unselected, tmp_path / "report.dry-run.csv")
    cfg = replace(
        config.default_config(input_dir=input_dir, output_dir=output_dir),
        dry_run=True,
        limit=1,
    )
    monkeypatch.setattr(
        runner,
        "_prepare_tools",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("tools must not be prepared before preflight")
        ),
    )

    assert runner.run(cfg) == 1
    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"second"


def test_runner_returns_failure_when_state_initialization_fails(
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
    monkeypatch.setattr(
        state,
        "init_db",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("database unavailable")),
    )

    assert runner.run(cfg) == 1


def test_hidden_ocr_text_does_not_block_scan_detection(tmp_path: Path) -> None:
    path = tmp_path / "hidden-ocr-scan.pdf"
    _write_full_page_image_pdf(
        path,
        dpi=600,
        text="hidden OCR text " * 10,
        text_render_mode=3,
    )

    assert _inspect_mode(path) is OptimizationMode.LOSSY


def test_white_text_on_dark_background_counts_as_visible(tmp_path: Path) -> None:
    path = tmp_path / "white-text-scan.pdf"
    _write_full_page_image_pdf(
        path,
        dpi=600,
        text="visible white text " * 10,
        text_color=(1, 1, 1),
    )

    assert _inspect_mode(path) is OptimizationMode.LOSSLESS


def test_multiple_small_images_are_not_combined_for_scan_detection(tmp_path: Path) -> None:
    path = tmp_path / "small-images.pdf"
    pixmap = _rendered_page_pixmap(72, 72, 600)
    document = fitz.open()
    page = document.new_page(width=144, height=144)
    for rect in (
        fitz.Rect(0, 0, 72, 72),
        fitz.Rect(72, 0, 144, 72),
        fitz.Rect(0, 72, 72, 144),
        fitz.Rect(72, 72, 144, 144),
    ):
        page.insert_image(rect, pixmap=pixmap)
    document.save(path)
    document.close()

    assert _inspect_mode(path) is OptimizationMode.LOSSLESS


def test_full_page_300_dpi_image_is_not_lossy_candidate(tmp_path: Path) -> None:
    path = tmp_path / "scan-300-dpi.pdf"
    _write_full_page_image_pdf(path, dpi=300)

    assert _inspect_mode(path) is OptimizationMode.LOSSLESS


def test_full_page_600_dpi_image_is_lossy_candidate(tmp_path: Path) -> None:
    path = tmp_path / "scan-600-dpi.pdf"
    _write_full_page_image_pdf(path, dpi=600)

    assert _inspect_mode(path) is OptimizationMode.LOSSY


def test_effective_dpi_accounts_for_ninety_degree_rotation() -> None:
    info = {
        "bbox": (0, 0, 144, 72),
        "width": 1200,
        "height": 2400,
    }

    assert inspect_pdf._effective_image_dpi(info) == pytest.approx(1200)


def test_zero_opacity_texttrace_span_is_not_visible() -> None:
    class TracePage:
        def get_texttrace(self):
            return [
                {"type": 0, "opacity": 0, "chars": [1, 2, 3]},
                {"type": 0, "opacity": 1, "chars": [4, 5]},
            ]

    assert inspect_pdf._page_visible_text_len(TracePage()) == 2


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
