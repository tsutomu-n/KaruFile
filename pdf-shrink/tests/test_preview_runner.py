"""Preview failures are independent of committed normal PDF results."""
from __future__ import annotations

import csv
import os
import sqlite3
import subprocess
import sys
import types
from dataclasses import replace
from pathlib import Path

import pytest

import pdf_shrink
from pdf_shrink import config, discovery, runner, worker
from pdf_shrink.models import ProcessStatus


def _preview_stub(monkeypatch, generate):
    module = types.ModuleType("pdf_shrink.preview")
    module.generate = generate
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(pdf_shrink, "preview", module, raising=False)


def _case(tmp_path: Path, monkeypatch, *, dry_run=False, empty=False):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    source = input_dir / "photo.pdf"
    if not empty:
        from conftest import _make_text_pdf
        _make_text_pdf(source)
    cfg = config.default_config(
        input_dir=input_dir, output_dir=tmp_path / "output",
        photo_patterns=("*.pdf",), photo_dpi=180, preview=True,
    )
    cfg = replace(cfg, dry_run=dry_run)
    prepared = []
    processed = []

    def prepare(current):
        prepared.append(current)
        return current.with_tool_versions(pymupdf="test", qpdf="" if dry_run else "test"), None if dry_run else Path("qpdf-stub")

    def execute(sources, current, paths, qpdf_exe):
        processed.extend(source.path for source in sources)
        for source in sources:
            yield source, worker.process_one_file(source, current, paths.temp_root, qpdf_exe)

    monkeypatch.setattr(runner, "_prepare_tools", prepare)
    monkeypatch.setattr(runner, "_execute", execute)
    return cfg, source, prepared, processed


def _rows(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _state_rows(path: Path):
    with sqlite3.connect(path) as conn:
        return conn.execute(
            "SELECT source_path, status, photo_dpi, config_hash, processed_at FROM files ORDER BY source_path"
        ).fetchall()


@pytest.mark.parametrize("failure", [False, True, "exception"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_preview_runs_after_committed_report_and_cannot_undo_results(
    tmp_path: Path, monkeypatch, failure, dry_run: bool,
) -> None:
    cfg, source, prepared, processed = _case(tmp_path, monkeypatch, dry_run=dry_run)
    paths = runner.WorkspacePaths.from_config(cfg)
    captured = []

    def generate(current, sources, records, qpdf_exe, protected_sources):
        assert current.preview and current.photo_dpi == 180
        assert [s.path for s in sources] == [source]
        assert protected_sources == (source,)
        assert len(records) == 1 and records[0].photo_dpi == 180
        assert qpdf_exe == (None if dry_run else Path("qpdf-stub"))
        # A separate connection observes committed state before preview begins.
        committed = _state_rows(paths.database)
        assert len(committed) == 1 and committed[0][2] == 180
        assert _rows(paths.report)[0]["photo_dpi"] == "180"
        captured.append((paths.report.read_bytes(), committed))
        if failure == "exception":
            raise OSError("comparison assets could not be written")
        return not failure

    _preview_stub(monkeypatch, generate)
    assert runner.run(cfg) == (1 if failure else 0)
    assert len(prepared) == 1 and processed == [source]
    assert len(captured) == 1
    assert (paths.report.read_bytes(), _state_rows(paths.database)) == captured[0]
    assert source.read_bytes().startswith(b"%PDF-")
    destination = cfg.output_dir / source.name
    if dry_run:
        assert not destination.exists()
    else:
        assert destination.read_bytes() == source.read_bytes()


def test_preview_toggle_and_dpi_choices_reuse_completed_pdf(tmp_path: Path, monkeypatch) -> None:
    cfg, source, prepared, processed = _case(tmp_path, monkeypatch)
    paths = runner.WorkspacePaths.from_config(cfg)
    calls = []
    _preview_stub(monkeypatch, lambda *args: calls.append(args) or True)
    assert runner.run(replace(cfg, preview=False)) == 0
    original_records = _state_rows(paths.database)
    assert calls == [] and processed == [source]
    assert runner.run(replace(cfg, preview_dpis=(150, 300, 150))) == 0
    assert processed == [source]  # No second transformation for preview changes.
    assert _state_rows(paths.database) == original_records
    assert len(calls) == 1 and calls[0][0].preview_dpis == (300, 150)
    assert len(calls[0][1]) == len(calls[0][2]) == 1


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("preview_enabled", [False, True])
def test_zero_pdfs_publish_empty_report_without_preparing_any_tools(
    tmp_path: Path, monkeypatch, dry_run: bool, preview_enabled: bool,
) -> None:
    cfg, source, prepared, processed = _case(tmp_path, monkeypatch, dry_run=dry_run, empty=True)
    cfg = replace(
        cfg, preview=preview_enabled, lossless_jpeg=True,
        jpegtran_path=tmp_path / "absent-jpegtran.exe",
        pymupdf_version="stale", qpdf_version="stale",
        jpegtran_version="stale", jpegtran_sha256="stale",
    )
    seen = []

    def generate(current, sources, records, qpdf_exe, protected_sources):
        assert sources == records == [] and protected_sources == ()
        assert qpdf_exe is None
        assert current.pymupdf_version == current.qpdf_version == ""
        assert current.jpegtran_version == current.jpegtran_sha256 == ""
        seen.append(current)
        return True

    _preview_stub(monkeypatch, generate)
    assert runner.run(cfg) == 0
    assert prepared == processed == []
    assert len(seen) == int(preview_enabled)
    paths = runner.WorkspacePaths.from_config(cfg)
    assert _rows(paths.report) == [] and _state_rows(paths.database) == []


def test_report_failure_does_not_start_preview(tmp_path: Path, monkeypatch) -> None:
    cfg, source, _, _ = _case(tmp_path, monkeypatch)
    called = []
    _preview_stub(monkeypatch, lambda *args: called.append(args) or True)

    def fail_report(*args, **kwargs):
        raise OSError("report publication failed")

    monkeypatch.setattr(runner.report, "write_csv", fail_report)
    assert runner.run(cfg) == 1 and called == []
    assert _state_rows(runner.WorkspacePaths.from_config(cfg).database) == []


def test_successful_preview_does_not_hide_normal_pdf_error(tmp_path: Path, monkeypatch) -> None:
    cfg, source, _, _ = _case(tmp_path, monkeypatch)

    def execute(sources, current, paths, qpdf_exe):
        for snapshot in sources:
            yield snapshot, runner._worker_crash_result(snapshot, current, OSError("worker failed"))

    monkeypatch.setattr(runner, "_execute", execute)
    called = []
    _preview_stub(monkeypatch, lambda *args: called.append(args) or True)
    assert runner.run(cfg) == 1
    assert len(called) == 1 and called[0][2][0].status == ProcessStatus.ERROR
    assert called[0][2][0].photo_dpi == 180
    assert (cfg.output_dir / source.name).read_bytes() == source.read_bytes()


@pytest.mark.parametrize("matched", [False, True])
@pytest.mark.parametrize("dry_run", [False, True])
def test_worker_crash_result_retains_only_selected_photo_dpi(tmp_path: Path, monkeypatch, matched, dry_run) -> None:
    cfg, path, _, _ = _case(tmp_path, monkeypatch, dry_run=dry_run)
    cfg = replace(cfg, photo_patterns=("*.pdf",) if matched else ("unmatched.pdf",))
    snapshot = discovery.snapshot(path, cfg.input_dir)
    result = runner._worker_crash_result(snapshot, cfg, OSError("crashed"))
    assert result.status is ProcessStatus.ERROR
    assert result.photo_dpi == (180 if matched else None)
    assert result.profile == ("photo" if matched else "standard")


@pytest.mark.parametrize("name", ["pdf-preview", "pdf-preview.json", "pdf-preview.dry-run.json"])
@pytest.mark.parametrize("side", ["input", "output"])
def test_preview_workspace_collisions_are_rejected_only_when_enabled(tmp_path: Path, name, side) -> None:
    input_dir = tmp_path / (name if side == "input" else "input")
    input_dir.mkdir()
    output_dir = tmp_path / (name if side == "output" else "output")
    cfg = config.default_config(input_dir=input_dir, output_dir=output_dir, photo_patterns=("*.pdf",))
    paths = runner.WorkspacePaths.from_config(cfg)
    runner._validate_workspace_paths(cfg, paths, [], ())
    with pytest.raises(ValueError, match="preview.*overlaps"):
        runner._validate_workspace_paths(replace(cfg, preview=True), paths, [], ())


@pytest.mark.parametrize("name", ["pdf-preview.json", "pdf-preview.dry-run.json"])
def test_preview_hardlink_is_rejected_before_tools_and_state(tmp_path: Path, monkeypatch, name) -> None:
    cfg, source, prepared, _ = _case(tmp_path, monkeypatch)
    other = cfg.input_dir / "other.pdf"
    other.write_bytes(b"other protected source")
    cfg = replace(cfg, limit=1)
    selected = discovery.select_pilot([source, other], 1)[0]
    unselected = other if selected == source else source
    os.link(unselected, tmp_path / name)
    assert runner.run(cfg) == 1 and prepared == []
    assert not runner.WorkspacePaths.from_config(cfg).database.exists()
    assert source.read_bytes().startswith(b"%PDF-")
    assert other.read_bytes() == b"other protected source"


def test_preview_directory_link_is_rejected_before_tools(tmp_path: Path, monkeypatch) -> None:
    cfg, source, prepared, _ = _case(tmp_path, monkeypatch)
    link = tmp_path / "pdf-preview"
    if os.name == "nt":
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(cfg.input_dir)],
            capture_output=True, text=True, check=False,
        )
        if completed.returncode != 0:
            pytest.skip(f"could not create test junction: {completed.stderr}")
    else:
        link.symlink_to(cfg.input_dir, target_is_directory=True)
    assert runner.run(cfg) == 1 and prepared == []
    assert source.read_bytes().startswith(b"%PDF-")
