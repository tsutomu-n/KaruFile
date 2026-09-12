"""Opt-in, failure recovery, font identity and persistence integration contracts."""
from dataclasses import replace
from pathlib import Path
import csv
import sqlite3

import pymupdf as fitz
import pytest

from pdf_shrink import config, discovery, font_pipeline, font_replace, report, runner, state, worker
from pdf_shrink.models import CandidateResult, ProcessStatus


def setup_case(tmp_path):
    inputs = tmp_path / "input"
    inputs.mkdir()
    path = inputs / "document.pdf"
    with fitz.open() as document:
        document.new_page(width=144, height=144).insert_text((10, 30), "Original text")
        document.save(path)
    cfg = replace(config.default_config(input_dir=inputs, output_dir=tmp_path / "output",
                                       font_replace_patterns=("*.PDF",)),
                  font_replace_path=tmp_path / "font.ttc", font_replace_sha256="a" * 64)
    return discovery.snapshot(path, inputs), cfg


@pytest.mark.parametrize("winner,changed,status", [
    ("font_replace", True, ProcessStatus.ADOPTED_LOSSY),
    ("lossless", False, ProcessStatus.ADOPTED_LOSSLESS),
    ("tie", False, ProcessStatus.ADOPTED_LOSSLESS),
    ("rejected", False, ProcessStatus.ADOPTED_LOSSLESS),
    ("none", False, ProcessStatus.UNCHANGED),
    ("error", False, ProcessStatus.ERROR),
])
def test_candidate_selection_and_failed_candidate_never_claims_font_adoption(tmp_path, monkeypatch, winner, changed, status):
    source, cfg = setup_case(tmp_path)
    monkeypatch.setattr(font_replace, "preflight", lambda *args: "")
    calls = []
    def evaluate(src, target, kind, *args):
        assert src == source
        calls.append(kind)
        size = source.size - (2 if kind == winner else 1)
        reason = "eligible"
        if winner == "none":
            size, reason = source.size, "candidate_not_smaller"
        if kind == "font_replace" and winner in {"rejected", "error"}:
            reason = "quality_rejected" if winner == "rejected" else "processing_error"
        target.write_bytes(b"x" * size)
        return CandidateResult(kind, size, reason=reason, text_extraction_changed=kind == "font_replace")
    monkeypatch.setattr(font_pipeline, "evaluate", evaluate)
    result = worker.process_one_file(source, cfg, tmp_path / "temp", Path("qpdf"))
    assert result.status == status
    assert result.text_extraction_changed is changed
    assert result.font_replacement_requested
    assert result.replacement_font == "Meiryo Regular"
    assert result.replacement_font_sha256 == "a" * 64
    assert result.processing_schema == 6
    assert calls == ["lossless", "font_replace"]
    if status in {ProcessStatus.ERROR, ProcessStatus.UNCHANGED}:
        assert result.output_path.read_bytes() == source.path.read_bytes()
        assert not any(c.selected for c in result.candidate_details)
    else:
        assert result.output_size < source.size < 256 * 1024
    conn = state.init_db(tmp_path / "selection.sqlite3")
    try:
        state.save_result(conn, source, result, config.config_hash(cfg), input_dir=cfg.input_dir,
                          pymupdf_version="test", qpdf_version="test")
        record = state.get_record(conn, str(source.path))
        assert record.text_extraction_changed is changed
        assert record.candidate_details == result.candidate_details
    finally:
        conn.close()


@pytest.mark.parametrize("dry", [False, True])
def test_unsupported_is_whole_document_protection_without_candidates(tmp_path, monkeypatch, dry):
    source, cfg = setup_case(tmp_path)
    cfg = replace(cfg, dry_run=dry)
    monkeypatch.setattr(font_replace, "preflight", lambda *args: "unsupported_font_encoding")
    monkeypatch.setattr(font_pipeline, "evaluate", lambda *a: pytest.fail("protected candidate"))
    result = worker.process_one_file(source, cfg, tmp_path / "temp", None)
    assert result.status == (ProcessStatus.DRY_RUN_PRESERVED if dry else ProcessStatus.PRESERVED_ORIGINAL)
    assert result.preservation_reason == "unsupported_font_encoding"
    assert result.font_replacement_requested and not result.text_extraction_changed
    if dry:
        assert not result.output_path.exists()
    else:
        assert result.output_path.read_bytes() == source.path.read_bytes()


def test_supported_dry_run_does_not_generate_or_run_external_tools(tmp_path, monkeypatch):
    source, cfg = setup_case(tmp_path)
    monkeypatch.setattr(font_replace, "preflight", lambda *args: "")
    monkeypatch.setattr(font_replace, "generate", lambda *a: pytest.fail("dry-run generation"))
    monkeypatch.setattr(font_pipeline, "evaluate", lambda *a: pytest.fail("dry-run candidate"))
    result = worker.process_one_file(source, replace(cfg, dry_run=True), tmp_path / "temp", None)
    assert result.status == ProcessStatus.DRY_RUN_LOSSY
    assert not result.output_path.exists() and not (tmp_path / "temp").exists()


def test_font_discovery_failure_precedes_workspace_or_tool_mutation(tmp_path, monkeypatch):
    source, cfg = setup_case(tmp_path)
    def missing():
        raise FileNotFoundError("YuGothR.ttc")
    monkeypatch.setattr(font_replace, "prepare_font", missing)
    monkeypatch.setattr(runner, "_prepare_tools", lambda *a: pytest.fail("tools before font discovery"))
    assert runner.run(cfg) == 1
    assert not cfg.output_dir.exists()
    assert not (tmp_path / ".pdf-shrink").exists()


def test_preserve_override_and_no_matches_do_not_discover_font(tmp_path, monkeypatch):
    source, cfg = setup_case(tmp_path)
    monkeypatch.setattr(font_replace, "prepare_font", lambda: pytest.fail("unused Windows font discovery"))
    for patterns, preserve in [(('*.pdf',), ('*',)), (('absent.pdf',), ('*',))]:
        assert runner.run(replace(cfg, font_replace_patterns=patterns, preserve_patterns=preserve,
                                  dry_run=True, workers=1)) == 0


def test_font_identity_controls_resume_but_inactive_font_does_not(tmp_path):
    source, cfg = setup_case(tmp_path)
    assert config.config_hash(cfg) != config.config_hash(replace(cfg, font_replace_sha256="b" * 64))
    inactive = replace(cfg, font_replace_patterns=())
    assert config.config_hash(inactive) == config.config_hash(replace(inactive, font_replace_sha256="b" * 64))
    with pytest.raises(ValueError, match="safe"):
        replace(cfg, safe=True)
    with pytest.raises(ValueError, match="conflicting"):
        config.profile_for_path(replace(cfg, text_patterns=("*",)), Path("document.pdf"))
    assert config.profile_for_path(replace(cfg, text_patterns=("*",), preserve_patterns=("*",)), Path("document.pdf")) == "preserve"


@pytest.mark.parametrize("kind", ["lossless", "font_replace"])
def test_expired_document_budget_does_not_start_candidate_tools(tmp_path, monkeypatch, kind):
    source, cfg = setup_case(tmp_path)
    monkeypatch.setattr(font_pipeline, "qpdf_optimize", lambda *a, **k: pytest.fail("expired qpdf"))
    monkeypatch.setattr(font_replace, "generate", lambda *a, **k: pytest.fail("expired generation"))
    target = tmp_path / "candidate.pdf"
    result = font_pipeline.evaluate(source, target, kind, cfg, Path("qpdf"), 0)
    assert result.reason == "quality_rejected" and "time_limit" in result.validation_reason
    assert not target.exists()


def test_schema_migration_and_font_fields_roundtrip(tmp_path, monkeypatch):
    source, cfg = setup_case(tmp_path)
    monkeypatch.setattr(font_replace, "preflight", lambda *a: "unsupported_font_encoding")
    result = worker.process_one_file(source, cfg, tmp_path / "temp", None)
    database = tmp_path / "state.sqlite3"
    # Existing schema lacks all four font fields; migration must retain its row.
    with sqlite3.connect(database) as conn:
        conn.executescript(state.SCHEMA)
        conn.execute("INSERT INTO files(source_path,source_sha256,source_size,source_mtime_ns,config_hash,status) VALUES (?,?,?,?,?,?)",
                     ("legacy.pdf", "old", 1, 1, "old", "UNCHANGED"))
    conn = state.init_db(database)
    try:
        legacy = state.get_record(conn, "legacy.pdf")
        assert legacy.source_sha256 == "old" and not legacy.font_replacement_requested
        assert legacy.replacement_font == legacy.replacement_font_sha256 == ""
        state.save_result(conn, source, result, config.config_hash(cfg), input_dir=cfg.input_dir,
                          pymupdf_version="test", qpdf_version="test")
        record = state.get_record(conn, str(source.path))
        assert record.processing_schema == 6 and record.font_replacement_requested
        assert record.replacement_font_sha256 == "a" * 64
        assert record.replacement_font == "Meiryo Regular" and not record.text_extraction_changed
        assert not state.should_process(record, source.sha256, config.config_hash(cfg), False, True)
        changed_font = replace(cfg, font_replace_sha256="b" * 64)
        assert state.should_process(record, source.sha256, config.config_hash(changed_font), False, True)
        target = tmp_path / "report.csv"
        report.write_csv([record], target, input_root=cfg.input_dir, work_root=tmp_path,
                         protected_sources=[source.path], output_root=cfg.output_dir, preset="standard")
        with target.open(encoding="utf-8-sig", newline="") as stream:
            row = next(csv.DictReader(stream))
        assert row["font_replacement_requested"] == "true"
        assert row["text_extraction_changed"] == "false"
        assert row["replacement_font_sha256"] == "a" * 64
        assert row["processing_schema"] == "6"
    finally:
        conn.close()
