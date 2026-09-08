"""責務分離で明示した状態・探索・出力契約のテスト。"""
from __future__ import annotations

import csv
import os
import sqlite3
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
    InspectionResult,
    OptimizationMode,
    ProcessResult,
    ProcessStatus,
    SourceSnapshot,
)
from pdf_shrink.utils import sha256_file


def _snapshot(path: Path) -> SourceSnapshot:
    return discovery.snapshot(path, path.parent)


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


def test_snapshot_rejects_same_stat_source_replacement_during_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"A" * 32)
    real_sha256_file = discovery.sha256_file

    def replace_after_hash(path: Path) -> str:
        digest = real_sha256_file(path)
        _replace_source_with_same_size_and_mtime(path, b"B" * 32)
        return digest

    monkeypatch.setattr(discovery, "sha256_file", replace_after_hash)

    with pytest.raises(discovery.SourceChangedError, match="changed while hashing"):
        discovery.snapshot(source, tmp_path)


def test_config_hash_includes_execution_mode_and_tool_versions(tmp_path: Path) -> None:
    cfg = config.default_config(input_dir=tmp_path, output_dir=tmp_path / "out")

    assert config.config_hash(cfg) != config.config_hash(replace(cfg, dry_run=True))
    assert config.config_hash(cfg) != config.config_hash(
        replace(cfg, output_dir=tmp_path / "other-out")
    )
    assert config.config_hash(cfg) != config.config_hash(
        cfg.with_tool_versions(pymupdf="different", qpdf="different")
    )


def _replace_source_with_same_size_and_mtime(path: Path, data: bytes) -> None:
    original = path.stat()
    assert len(data) == original.st_size
    replacement = path.with_name(f".{path.name}.replacement")
    replacement.write_bytes(data)
    os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
    os.replace(replacement, path)
    os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))


def test_standard_config_hash_is_stable_after_axis_safe_fix() -> None:
    cfg = config.RunConfig(
        input_dir=Path("input"),
        output_dir=Path("output"),
    )

    current_hash = config.config_hash(cfg)

    assert current_hash == (
        "4ee17a418155fedd520dc8bb8ac98e7000a22bec6de665869076497a9bd5339f"
    )
    assert current_hash != (
        # 軸別DPI修正前のhash。非等方配置を再処理するため再利用しない。
        "883dcae25cf657fb4c2cdccc34bfa61cb6242b5a359880752839b12273369c5c"
    )


def test_pdf_presets_keep_300_dpi_and_change_config_hash(tmp_path: Path) -> None:
    standard = config.default_config(input_dir=tmp_path, output_dir=tmp_path / "out")
    compact = config.default_config(
        input_dir=tmp_path,
        output_dir=tmp_path / "out",
        preset=config.CompressionPreset.COMPACT,
    )

    assert standard.preset is config.CompressionPreset.STANDARD
    assert standard.lossy.dpi_target == config.PDF_IMAGE_DPI_TARGET == 300
    assert standard.lossy.quality == 92
    assert not standard.lossy.recompress_existing_jpeg
    assert compact.preset is config.CompressionPreset.COMPACT
    assert compact.lossy.dpi_target == 300
    assert compact.lossy.quality == 80
    assert compact.lossy.recompress_existing_jpeg
    assert compact.lossy.jpeg_recompress_min_percent == 0.05
    assert config.config_hash(standard) != config.config_hash(compact)


def test_switching_from_standard_state_to_compact_requires_reprocessing(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"source")
    snapshot = _snapshot(source_path)
    standard = config.default_config(
        input_dir=tmp_path,
        output_dir=tmp_path / "out",
    )
    compact = config.default_config(
        input_dir=tmp_path,
        output_dir=tmp_path / "out",
        preset=config.CompressionPreset.COMPACT,
    )
    conn = state.init_db(tmp_path / "state.sqlite3")
    try:
        output_path = tmp_path / "out" / "source.pdf"
        output_path.parent.mkdir()
        output_path.write_bytes(b"source")
        state.save_result(
            conn,
            snapshot,
            _result(
                output_path,
                ProcessStatus.UNCHANGED,
                6,
            ),
            config.config_hash(standard),
            input_dir=tmp_path,
            pymupdf_version="",
            qpdf_version="",
        )
        record = state.get_record(conn, str(source_path.resolve()))
    finally:
        conn.close()

    assert record is not None
    assert not state.should_process(
        record,
        snapshot.sha256,
        config.config_hash(standard),
        False,
        True,
    )
    assert state.should_process(
        record,
        snapshot.sha256,
        config.config_hash(compact),
        False,
        True,
    )


def test_legacy_state_schema_is_migrated_and_reprocessed_once(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy-state.sqlite3"
    legacy_schema = state.SCHEMA.replace("    output_sha256     TEXT,\n", "")
    conn = sqlite3.connect(database)
    conn.executescript(legacy_schema)
    conn.execute(
        """
        INSERT INTO files (
            source_path, source_sha256, source_size, source_mtime_ns, config_hash,
            mode, status, output_size
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("legacy.pdf", "source-hash", 100, 1, "config", "lossless", "UNCHANGED", 80),
    )
    conn.commit()
    conn.close()

    conn = state.init_db(database)
    try:
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(files)").fetchall()
        }
        record = state.get_record(conn, "legacy.pdf")
    finally:
        conn.close()

    assert "output_sha256" in columns
    assert record is not None
    assert record.output_sha256 is None
    # Even if a size-only caller reports a match, a legacy row has no content
    # proof and therefore must be regenerated once.
    assert state.should_process(
        record,
        "source-hash",
        "config",
        False,
        True,
    )


def test_completed_state_rejects_same_size_output_corruption(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "out" / "source.pdf"
    source.write_bytes(b"source")
    destination.parent.mkdir()
    destination.write_bytes(b"A" * 32)
    snapshot = _snapshot(source)

    conn = state.init_db(tmp_path / "state.sqlite3")
    try:
        state.save_result(
            conn,
            snapshot,
            _result(destination, ProcessStatus.UNCHANGED, 32),
            "config",
            input_dir=tmp_path,
            pymupdf_version="pymupdf",
            qpdf_version="qpdf",
        )
        record = state.get_record(conn, str(source.resolve()))
    finally:
        conn.close()

    assert record is not None
    assert record.output_sha256
    assert runner._output_matches_record(record, destination)

    destination.write_bytes(b"B" * 32)

    assert destination.stat().st_size == record.output_size
    assert not runner._output_matches_record(record, destination)
    assert state.should_process(
        record,
        snapshot.sha256,
        "config",
        False,
        False,
    )


def test_state_does_not_publish_success_after_source_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "source.pdf"
    destination = tmp_path / "out" / "source.pdf"
    source_path.write_bytes(b"A" * 32)
    destination.parent.mkdir()
    destination.write_bytes(b"healthy-output")
    source = discovery.snapshot(source_path, tmp_path)
    conn = state.init_db(tmp_path / "state.sqlite3")

    def hash_output_then_replace(_result_value: ProcessResult) -> str:
        digest = sha256_file(destination)
        _replace_source_with_same_size_and_mtime(source_path, b"B" * 32)
        return digest

    monkeypatch.setattr(state, "_stable_output_sha256", hash_output_then_replace)
    try:
        with pytest.raises(discovery.SourceChangedError, match="changed"):
            state.save_result(
                conn,
                source,
                _result(
                    destination,
                    ProcessStatus.UNCHANGED,
                    destination.stat().st_size,
                ),
                "config",
                input_dir=tmp_path,
                pymupdf_version="pymupdf",
                qpdf_version="qpdf",
            )
        record = state.get_record(conn, str(source.path))
    finally:
        conn.close()

    assert record is None


def test_state_rejects_completed_output_without_stable_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "source.pdf"
    destination = tmp_path / "output.pdf"
    source_path.write_bytes(b"source")
    destination.write_bytes(b"output")
    source = discovery.snapshot(source_path, tmp_path)
    conn = state.init_db(tmp_path / "state.sqlite3")
    monkeypatch.setattr(state, "_stable_output_sha256", lambda _result_value: None)
    try:
        with pytest.raises(OSError, match="stable PDF output digest"):
            state.save_result(
                conn,
                source,
                _result(destination, ProcessStatus.UNCHANGED, destination.stat().st_size),
                "config",
                input_dir=tmp_path,
                pymupdf_version="pymupdf",
                qpdf_version="qpdf",
            )
        record = state.get_record(conn, str(source.path))
    finally:
        conn.close()

    assert record is None


def test_reuse_race_keeps_existing_state_report_and_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source_path = input_dir / "source.pdf"
    destination = output_dir / "source.pdf"
    source_path.write_bytes(b"A" * 32)
    destination.write_bytes(b"healthy-output")
    cfg = config.default_config(input_dir=input_dir, output_dir=output_dir)
    prepared = cfg.with_tool_versions(pymupdf="test-pymupdf", qpdf="test-qpdf")
    source = discovery.snapshot(source_path, input_dir)
    paths = runner.WorkspacePaths.from_config(cfg)
    paths.state_dir.mkdir()
    conn = state.init_db(paths.database)
    try:
        state.save_result(
            conn,
            source,
            _result(destination, ProcessStatus.UNCHANGED, destination.stat().st_size),
            config.config_hash(prepared),
            input_dir=input_dir,
            pymupdf_version=prepared.pymupdf_version,
            qpdf_version=prepared.qpdf_version,
        )
        before_record = state.get_record(conn, str(source.path))
    finally:
        conn.close()
    paths.report.write_bytes(b"healthy-report")

    monkeypatch.setattr(
        runner,
        "_prepare_tools",
        lambda _cfg: (prepared, tmp_path / "qpdf.exe"),
    )

    def replace_during_output_check(
        _record: state.Record | None,
        _destination: Path,
    ) -> bool:
        _replace_source_with_same_size_and_mtime(source_path, b"B" * 32)
        return True

    monkeypatch.setattr(runner, "_output_matches_record", replace_during_output_check)

    assert runner.run(cfg) == 1

    conn = state.init_db(paths.database)
    try:
        after_record = state.get_record(conn, str(source.path))
    finally:
        conn.close()
    assert after_record == before_record
    assert destination.read_bytes() == b"healthy-output"
    assert paths.report.read_bytes() == b"healthy-report"


@pytest.mark.parametrize("changed_target", ["source", "output", "output_hardlink"])
def test_report_publication_revalidates_all_inputs_and_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed_target: str,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source_path = input_dir / "source.pdf"
    destination = output_dir / "source.pdf"
    external = tmp_path / "external.pdf"
    source_path.write_bytes(b"A" * 32)
    destination.write_bytes(b"C" * 32)
    external.write_bytes(b"C" * 32)
    cfg = config.default_config(input_dir=input_dir, output_dir=output_dir)
    prepared = cfg.with_tool_versions(pymupdf="test-pymupdf", qpdf="test-qpdf")
    source = discovery.snapshot(source_path, input_dir)
    paths = runner.WorkspacePaths.from_config(cfg)
    paths.state_dir.mkdir()
    conn = state.init_db(paths.database)
    try:
        state.save_result(
            conn,
            source,
            _result(destination, ProcessStatus.UNCHANGED, 32),
            config.config_hash(prepared),
            input_dir=input_dir,
            pymupdf_version=prepared.pymupdf_version,
            qpdf_version=prepared.qpdf_version,
        )
        before_record = state.get_record(conn, str(source.path))
    finally:
        conn.close()
    paths.report.write_bytes(b"healthy-report")
    monkeypatch.setattr(
        runner,
        "_prepare_tools",
        lambda _cfg: (prepared, tmp_path / "qpdf.exe"),
    )
    real_write_csv = runner.report.write_csv

    def mutate_before_report_validation(*args: object, **kwargs: object) -> None:
        if changed_target == "source":
            _replace_source_with_same_size_and_mtime(source_path, b"B" * 32)
        elif changed_target == "output_hardlink":
            destination.unlink()
            os.link(external, destination)
        else:
            _replace_source_with_same_size_and_mtime(destination, b"D" * 32)
        real_write_csv(*args, **kwargs)

    monkeypatch.setattr(
        runner.report,
        "write_csv",
        mutate_before_report_validation,
    )

    assert runner.run(cfg) == 1

    conn = state.init_db(paths.database)
    try:
        after_record = state.get_record(conn, str(source.path))
    finally:
        conn.close()
    assert after_record == before_record
    assert paths.report.read_bytes() == b"healthy-report"


def test_commit_failure_rolls_back_state_and_restores_previous_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    source_path = input_dir / "source.pdf"
    source_path.write_bytes(b"old-content")
    cfg = replace(
        config.default_config(input_dir=input_dir, output_dir=output_dir),
        dry_run=True,
    )
    assert runner.run(cfg) == 0

    paths = runner.WorkspacePaths.from_config(cfg)
    old_report = paths.report.read_bytes()
    real_init_db = state.init_db
    conn = real_init_db(paths.database)
    try:
        old_record = state.get_record(conn, str(source_path.resolve()))
    finally:
        conn.close()
    assert old_record is not None
    source_path.write_bytes(b"new-content")

    class CommitFailingConnection:
        def __init__(self, connection: sqlite3.Connection) -> None:
            self._connection = connection

        def __getattr__(self, name: str):
            return getattr(self._connection, name)

        def commit(self) -> None:
            raise RuntimeError("commit failed")

    monkeypatch.setattr(
        state,
        "init_db",
        lambda path: CommitFailingConnection(real_init_db(path)),
    )

    assert runner.run(cfg) == 1
    assert paths.report.read_bytes() == old_report
    conn = real_init_db(paths.database)
    try:
        current_record = state.get_record(conn, str(source_path.resolve()))
    finally:
        conn.close()
    assert current_record == old_record


def test_cli_compact_preset_builds_compact_config(tmp_path: Path) -> None:
    args = cli.build_parser().parse_args([
        "run",
        "--input", str(tmp_path),
        "--preset", "compact",
    ])

    cfg = config.build_config(args)

    assert cfg.preset is config.CompressionPreset.COMPACT
    assert cfg.lossy.quality == 80
    assert cfg.lossy.dpi_target == 300
    assert cfg.lossy.recompress_existing_jpeg


def test_pdf_dpi_target_cannot_be_changed() -> None:
    with pytest.raises(ValueError, match="fixed at 300"):
        config.LossyOptions(dpi_target=299)


def test_cli_rejects_safe_compact_before_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("runner must not receive contradictory options")
        ),
    )

    assert cli.main([
        "run",
        "--input", str(tmp_path),
        "--preset", "compact",
        "--safe",
    ]) == 2


def test_state_lists_only_requested_sources(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    first_snapshot = _snapshot(first)
    second_snapshot = _snapshot(second)
    first_output = tmp_path / "out-first.pdf"
    second_output = tmp_path / "out-second.pdf"
    first_output.write_bytes(first.read_bytes())
    second_output.write_bytes(second.read_bytes())
    conn = state.init_db(tmp_path / "state.sqlite3")
    try:
        state.save_result(
            conn,
            first_snapshot,
            _result(first_output, ProcessStatus.UNCHANGED, first.stat().st_size),
            "config",
            input_dir=tmp_path,
            pymupdf_version="pymupdf",
            qpdf_version="qpdf",
        )
        state.save_result(
            conn,
            second_snapshot,
            _result(second_output, ProcessStatus.UNCHANGED, second.stat().st_size),
            "config",
            input_dir=tmp_path,
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
            input_dir=tmp_path,
            pymupdf_version="pymupdf",
            qpdf_version="qpdf",
        )
        record = state.get_record(conn, str(source.resolve()))
    finally:
        conn.close()

    assert state.should_process(record, snapshot.sha256, "config", False, False)


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
            discovery.snapshot(source, input_dir),
            destination,
            input_root=input_dir,
            output_root=destination.parent,
        )

    assert destination.read_bytes() == b"existing"
    assert list(destination.parent.glob(f".{destination.name}.*.tmp")) == []


def test_original_copy_rejects_source_replacement_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source_path = input_dir / "source.pdf"
    destination = output_dir / "source.pdf"
    source_path.write_bytes(b"A" * 32)
    destination.write_bytes(b"healthy-output")
    source = discovery.snapshot(source_path, input_dir)
    real_copy2 = output.shutil.copy2

    def replace_source_after_copy(copy_source: Path, temporary: Path) -> None:
        real_copy2(copy_source, temporary)
        _replace_source_with_same_size_and_mtime(source_path, b"B" * 32)

    monkeypatch.setattr(output.shutil, "copy2", replace_source_after_copy)

    with pytest.raises(discovery.SourceChangedError, match="changed"):
        output.copy_original(
            source,
            destination,
            input_root=input_dir,
            output_root=output_dir,
        )

    assert destination.read_bytes() == b"healthy-output"
    assert list(output_dir.glob(f".{destination.name}.*.tmp")) == []


def test_candidate_copy_requires_its_verified_start_hash(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source_path = input_dir / "source.pdf"
    candidate = tmp_path / "candidate.pdf"
    destination = output_dir / "source.pdf"
    source_path.write_bytes(b"source")
    candidate.write_bytes(b"verified-candidate")
    destination.write_bytes(b"healthy-output")
    source = discovery.snapshot(source_path, input_dir)
    expected_candidate_sha256 = sha256_file(candidate)
    candidate.write_bytes(b"tampered-candidate")

    with pytest.raises(OSError, match="verified digest"):
        output.adopt_candidate(
            source,
            candidate,
            destination,
            expected_candidate_sha256,
            input_root=input_dir,
            output_root=output_dir,
        )

    assert destination.read_bytes() == b"healthy-output"


def test_candidate_publication_source_race_keeps_existing_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    temp_root = tmp_path / "temp"
    input_dir.mkdir()
    output_dir.mkdir()
    temp_root.mkdir()
    source_path = input_dir / "source.pdf"
    destination = output_dir / "source.pdf"
    source_path.write_bytes(b"A" * 32)
    destination.write_bytes(b"healthy-output")
    source = discovery.snapshot(source_path, input_dir)
    cfg = replace(
        config.default_config(input_dir=input_dir, output_dir=output_dir),
        reduction=replace(
            config.ReductionOptions(),
            skip_below_bytes=1,
            lossless_min_bytes=1,
            lossless_min_percent=0.0,
        ),
    )
    monkeypatch.setattr(
        worker,
        "inspect_file",
        lambda *_args, **_kwargs: InspectionResult(
            True, None, 1, 0.0, OptimizationMode.LOSSLESS
        ),
    )
    monkeypatch.setattr(
        worker.transform,
        "optimize_lossless",
        lambda _source, candidate, *_args: candidate.write_bytes(b"candidate"),
    )
    monkeypatch.setattr(worker.validate, "validate", lambda *_args, **_kwargs: (True, "ok"))
    real_copy2 = output.shutil.copy2

    def replace_source_after_candidate_copy(copy_source: Path, temporary: Path) -> None:
        real_copy2(copy_source, temporary)
        _replace_source_with_same_size_and_mtime(source_path, b"B" * 32)

    monkeypatch.setattr(output.shutil, "copy2", replace_source_after_candidate_copy)

    result = worker.process_one_file(
        source,
        cfg,
        temp_root,
        tmp_path / "qpdf.exe",
    )

    assert result.status is ProcessStatus.ERROR
    assert result.output_size is None
    assert destination.read_bytes() == b"healthy-output"
    assert list(temp_root.rglob("*.pdf")) == []


def test_destination_is_rechecked_after_final_source_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source_path = input_dir / "source.pdf"
    destination = output_dir / "source.pdf"
    source_path.write_bytes(b"source")
    source = discovery.snapshot(source_path, input_dir)
    real_assert = output.discovery.assert_source_unchanged
    calls = 0

    def inject_hardlink_after_source_hash(
        snapshot: SourceSnapshot,
        root: Path,
    ) -> None:
        nonlocal calls
        real_assert(snapshot, root)
        calls += 1
        if calls == 2:
            os.link(source_path, destination)

    monkeypatch.setattr(
        output.discovery,
        "assert_source_unchanged",
        inject_hardlink_after_source_hash,
    )

    with pytest.raises(ValueError, match="hard link"):
        output.copy_original(
            source,
            destination,
            input_root=input_dir,
            output_root=output_dir,
        )

    assert source_path.read_bytes() == b"source"
    assert calls == 2


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
            discovery.snapshot(source, input_dir),
            destination,
            input_root=input_dir,
            output_root=output_dir,
        )

    assert source.read_bytes() == b"original"


def test_copy_original_rejects_read_only_output_and_cleans_temp(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    source = input_dir / "source.pdf"
    destination = output_dir / "source.pdf"
    source.write_bytes(b"first")
    os.chmod(source, stat.S_IREAD)
    try:
        output.copy_original(
            discovery.snapshot(source, input_dir),
            destination,
            input_root=input_dir,
            output_root=output_dir,
        )
        original_output = destination.read_bytes()
        os.chmod(source, stat.S_IWRITE | stat.S_IREAD)
        source.write_bytes(b"second")
        os.chmod(source, stat.S_IREAD)
        os.chmod(destination, stat.S_IREAD)

        with pytest.raises(ValueError, match="Read-only output"):
            output.copy_original(
                discovery.snapshot(source, input_dir),
                destination,
                input_root=input_dir,
                output_root=output_dir,
            )

        assert destination.read_bytes() == original_output
        assert source.read_bytes() == b"second"
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
            discovery.snapshot(source, input_dir),
            destination,
            input_root=input_dir,
            output_root=output_dir,
        )

    assert source.read_bytes() == b"source"


def test_copy_publication_never_chmods_destination_after_hardlink_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source = input_dir / "source.pdf"
    destination = output_dir / "source.pdf"
    source.write_bytes(b"protected source")
    destination.write_bytes(b"old output")
    source_mode = stat.S_IREAD
    os.chmod(source, source_mode)
    original_validate = output.validate_destination
    original_chmod = output.os.chmod
    calls = 0
    chmod_paths: list[Path] = []

    def inject_after_final_validation(*args: object, **kwargs: object) -> None:
        nonlocal calls
        original_validate(*args, **kwargs)
        calls += 1
        if calls == 3:
            destination.unlink()
            os.link(source, destination)

    def record_chmod(path: os.PathLike[str] | str, mode: int) -> None:
        chmod_paths.append(Path(path))
        original_chmod(path, mode)

    monkeypatch.setattr(output, "validate_destination", inject_after_final_validation)
    monkeypatch.setattr(output.os, "chmod", record_chmod)
    try:
        try:
            output.copy_original(
                discovery.snapshot(source, input_dir),
                destination,
                input_root=input_dir,
                output_root=output_dir,
            )
        except OSError:
            pass  # Windows may refuse replacing a read-only raced-in hardlink.

        assert source.read_bytes() == b"protected source"
        assert stat.S_IMODE(source.stat().st_mode) & stat.S_IWRITE == 0
        assert source not in chmod_paths
        assert destination not in chmod_paths
    finally:
        original_chmod(source, stat.S_IWRITE | stat.S_IREAD)


def test_report_rejects_read_only_output_and_cleans_temp(tmp_path: Path) -> None:
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
    original_report = report_path.read_bytes()
    os.chmod(report_path, stat.S_IREAD)
    try:
        with pytest.raises(ValueError, match="Read-only PDF report"):
            report.write_csv(
                [],
                report_path,
                input_root=input_dir,
                work_root=tmp_path,
                protected_sources=(),
            )
        assert report_path.read_bytes() == original_report
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


def test_report_publication_never_chmods_destination_after_hardlink_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    source = input_dir / "source.pdf"
    report_path = tmp_path / "report.csv"
    source.write_bytes(b"protected source")
    report_path.write_bytes(b"old report")
    os.chmod(source, stat.S_IREAD)
    original_validate = report._validate_report_destination
    original_chmod = report.os.chmod
    calls = 0
    chmod_paths: list[Path] = []

    def inject_after_final_validation(*args: object, **kwargs: object) -> None:
        nonlocal calls
        original_validate(*args, **kwargs)
        calls += 1
        if calls == 3:
            report_path.unlink()
            os.link(source, report_path)

    def record_chmod(path: os.PathLike[str] | str, mode: int) -> None:
        chmod_paths.append(Path(path))
        original_chmod(path, mode)

    monkeypatch.setattr(report, "_validate_report_destination", inject_after_final_validation)
    monkeypatch.setattr(report.os, "chmod", record_chmod)
    try:
        try:
            report.write_csv(
                [],
                report_path,
                input_root=input_dir,
                work_root=tmp_path,
                protected_sources=(source,),
            )
        except (OSError, ValueError):
            pass

        assert source.read_bytes() == b"protected source"
        assert stat.S_IMODE(source.stat().st_mode) & stat.S_IWRITE == 0
        assert source not in chmod_paths
        assert report_path not in chmod_paths
    finally:
        original_chmod(source, stat.S_IWRITE | stat.S_IREAD)


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

    result = inspect_pdf.inspect_file(
        path,
        config.default_config().scan,
        safe=False,
    )
    assert result.ok
    assert result.scan_page_ratio == 0
    assert result.mode is OptimizationMode.LOSSY


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

    result = inspect_pdf.inspect_file(
        path,
        config.default_config().scan,
        safe=False,
    )
    assert result.ok
    assert result.scan_page_ratio == 0
    assert result.mode is OptimizationMode.LOSSY


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


def test_oversampled_inline_image_is_complex_unless_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    source_path = input_dir / "inline.pdf"
    document = fitz.open()
    document.new_page(width=72, height=72)
    document.save(source_path)
    document.close()
    inline_info = {
        "xref": 0,
        "bbox": (0, 0, 72, 72),
        "transform": (72, 0, 0, 72, 0, 0),
        "width": 601,
        "height": 300,
    }
    monkeypatch.setattr(
        inspect_pdf,
        "_page_image_infos",
        lambda _page: [inline_info],
    )
    cfg = replace(
        config.default_config(input_dir=input_dir, output_dir=output_dir),
        reduction=replace(config.ReductionOptions(), skip_below_bytes=1),
    )

    unsafe = inspect_pdf.inspect_file(
        source_path,
        cfg.scan,
        safe=False,
        lossy_options=cfg.lossy,
    )
    safe = inspect_pdf.inspect_file(
        source_path,
        cfg.scan,
        safe=True,
        lossy_options=cfg.lossy,
    )

    assert not unsafe.ok
    assert unsafe.skip_reason == "unsupported_oversampled_inline_image"
    assert safe.ok
    assert safe.mode is OptimizationMode.LOSSLESS

    result = worker.process_one_file(
        discovery.snapshot(source_path, input_dir),
        cfg,
        tmp_path / "temp",
        None,
    )
    assert result.status is ProcessStatus.SKIPPED_COMPLEX
    assert result.output_path.read_bytes() == source_path.read_bytes()


@pytest.mark.parametrize(
    ("failed_check", "expected_reason"),
    [
        ("attachment", "attachment_check_failed: metadata unavailable"),
        ("signature", "signature_check_failed: metadata unavailable"),
    ],
)
def test_metadata_safety_check_failure_is_complex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_check: str,
    expected_reason: str,
) -> None:
    class MetadataDocument:
        is_encrypted = False
        needs_pass = False
        is_repaired = False
        page_count = 1
        is_form_pdf = False

        def embfile_names(self) -> list[str]:
            if failed_check == "attachment":
                raise RuntimeError("metadata unavailable")
            return []

        def get_sigflags(self) -> int:
            if failed_check == "signature":
                raise RuntimeError("metadata unavailable")
            return -1

        def close(self) -> None:
            pass

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    source_path = input_dir / "metadata.pdf"
    source_path.write_bytes(b"not parsed because fitz.open is mocked")
    monkeypatch.setattr(inspect_pdf.fitz, "open", lambda _path: MetadataDocument())
    cfg = replace(
        config.default_config(input_dir=input_dir, output_dir=output_dir),
        reduction=replace(config.ReductionOptions(), skip_below_bytes=1),
    )

    inspection = inspect_pdf.inspect_file(source_path, cfg.scan, safe=False)
    assert not inspection.ok
    assert inspection.skip_reason == expected_reason

    result = worker.process_one_file(
        discovery.snapshot(source_path, input_dir),
        cfg,
        tmp_path / "temp",
        None,
    )
    assert result.status is ProcessStatus.SKIPPED_COMPLEX
    assert result.output_path.read_bytes() == source_path.read_bytes()


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


def test_dry_run_source_race_returns_error_without_publishing_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    source_path = input_dir / "source.pdf"
    source_path.write_bytes(b"A" * 32)
    source = discovery.snapshot(source_path, input_dir)
    cfg = replace(
        config.default_config(input_dir=input_dir, output_dir=output_dir),
        dry_run=True,
        reduction=replace(config.ReductionOptions(), skip_below_bytes=1),
    )

    def inspect_then_replace(*_args: object, **_kwargs: object) -> InspectionResult:
        _replace_source_with_same_size_and_mtime(source_path, b"B" * 32)
        return InspectionResult(True, None, 1, 0.0, OptimizationMode.LOSSLESS)

    monkeypatch.setattr(worker, "inspect_file", inspect_then_replace)

    result = worker.process_one_file(source, cfg, tmp_path / "temp", None)

    assert result.status is ProcessStatus.ERROR
    assert result.output_size is None
    assert "changed" in (result.error_message or "").lower()
    assert not source.output_path(output_dir).exists()


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
    assert rows[0]["source_sha256"] == sha256_file(second_pdf)
    assert rows[0]["output_path"] == str(tmp_path / "second-out" / "second.pdf")
    assert rows[0]["output_sha256"] == ""
    assert rows[0]["preset"] == "standard"


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
