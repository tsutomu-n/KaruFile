"""候補の判定履歴は原本採用時もSQLiteとCSVへ残す。"""
from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from pdf_shrink import discovery, report, state
from pdf_shrink.models import CandidateResult, OptimizationMode, ProcessResult, ProcessStatus


def test_diagnostics_migration_preserves_legacy_rows_and_is_repeatable(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    # Keep the old schema explicit: deriving it from the new one would fail to
    # exercise newly added columns when the current schema changes.
    with sqlite3.connect(database) as conn:
        conn.executescript("""
            CREATE TABLE files (
                source_path TEXT PRIMARY KEY, source_sha256 TEXT NOT NULL,
                source_size INTEGER NOT NULL, source_mtime_ns INTEGER NOT NULL,
                config_hash TEXT NOT NULL, mode TEXT, status TEXT NOT NULL,
                output_size INTEGER, output_sha256 TEXT, saved_bytes INTEGER,
                saved_percent REAL, page_count INTEGER, scan_page_ratio REAL,
                error_message TEXT, pymupdf_version TEXT, qpdf_version TEXT,
                processed_at TEXT
            );
            INSERT INTO files (
                source_path, source_sha256, source_size, source_mtime_ns,
                config_hash, mode, status, output_size, output_sha256,
                saved_bytes, saved_percent
            ) VALUES (
                'legacy.pdf', 'original-digest', 100, 1, 'old-config',
                'lossless', 'UNCHANGED', 100, 'output-digest', 0, 0.0
            );
        """)

    for _ in range(2):
        conn = state.init_db(database)
        try:
            record = state.get_record(conn, "legacy.pdf")
            assert record is not None
            assert record.source_sha256 == "original-digest"
            assert record.output_sha256 == "output-digest"
            assert record.config_hash == "old-config"
            assert record.status == "UNCHANGED"
            assert record.profile == record.decision_reason == ""
            assert record.candidate_size is None
            assert record.candidate_saved_bytes is None
            assert record.candidate_saved_percent is None
            assert record.images_changed == 0
            assert record.candidate_details == ()
            assert record.lossless_jpeg_requested is False
            assert record.photo_dpi is None
        finally:
            conn.close()


@pytest.mark.parametrize("candidate_size", [None, 100, 120])
@pytest.mark.parametrize("requested", [False, True])
def test_candidate_diagnostics_survive_state_and_csv_without_replacing_output_metrics(
    tmp_path: Path,
    candidate_size: int | None,
    requested: bool,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    original = input_dir / "写真.pdf"
    original.write_bytes(b"a" * 100)
    source = discovery.snapshot(original, input_dir)
    destination = output_dir / original.name
    destination.write_bytes(original.read_bytes())
    candidate_saved = 100 - candidate_size if candidate_size is not None else None
    details = (
        CandidateResult(
            "lossy", candidate_size, 2, "quality_rejected", "黒板文字の差分"
        ),
        CandidateResult("lossless", 100, reason="candidate_not_smaller"),
    )
    result = ProcessResult(
        output_path=destination,
        status=ProcessStatus.UNCHANGED,
        mode=OptimizationMode.LOSSY,
        page_count=1,
        scan_page_ratio=0.0,
        output_size=100,
        saved_bytes=0,
        saved_percent=0.0,
        error_message=None,
        profile="photo",
        decision_reason="quality_rejected",
        candidate_size=candidate_size,
        candidate_saved_bytes=candidate_saved,
        candidate_saved_percent=float(candidate_saved) if candidate_saved is not None else None,
        images_changed=2,
        candidate_details=details,
        lossless_jpeg_requested=requested,
        photo_dpi=180,
    )
    database = tmp_path / "state.sqlite3"
    conn = state.init_db(database)
    try:
        state.save_result(
            conn, source, result, "config", input_dir=input_dir,
            pymupdf_version="test", qpdf_version="test",
        )
    finally:
        conn.close()

    conn = state.init_db(database)
    try:
        record = state.get_record(conn, str(source.path))
        assert record is not None
        assert record.profile == "photo"
        assert record.lossless_jpeg_requested is requested
        assert record.photo_dpi == 180
        assert record.decision_reason == "quality_rejected"
        assert record.candidate_size == candidate_size
        assert record.candidate_saved_bytes == candidate_saved
        assert record.candidate_saved_percent == candidate_saved
        assert record.images_changed == 2
        assert record.candidate_details == details
        assert record.output_size == 100
        assert record.saved_bytes == 0
        assert record.saved_percent == 0.0
        report_path = tmp_path / "report.csv"
        report.write_csv(
            [record], report_path, input_root=input_dir, work_root=tmp_path,
            protected_sources=[original], output_root=output_dir, preset="standard",
        )
        with report_path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 1
        row = rows[0]
        assert row["preset"] == "standard"
        assert row["status"] == "UNCHANGED"
        assert row["profile"] == "photo"
        assert row["lossless_jpeg_requested"] == ("true" if requested else "false")
        assert row["photo_dpi"] == "180"
        assert row["decision_reason"] == "quality_rejected"
        assert row["candidate_size"] == (str(candidate_size) if candidate_size is not None else "")
        assert row["candidate_saved_bytes"] == (str(candidate_saved) if candidate_saved is not None else "")
        assert row["output_size"] == "100"
        assert row["saved_bytes"] == "0"
        assert row["images_changed"] == "2"
        assert tuple(CandidateResult(**item) for item in json.loads(row["candidate_details"])) == details

        # An updated result must replace the old candidate history, including
        # when the new result has no candidate size or details.
        cleared = replace(
            result, profile="standard", decision_reason="no_eligible_images",
            candidate_size=None, candidate_saved_bytes=None, candidate_saved_percent=None,
            images_changed=0, candidate_details=(),
        )
        state.save_result(
            conn, source, cleared, "next-config", input_dir=input_dir,
            pymupdf_version="test", qpdf_version="test",
        )
        refreshed = state.get_record(conn, str(source.path))
        assert refreshed is not None
        assert refreshed.profile == "standard"
        assert refreshed.decision_reason == "no_eligible_images"
        assert refreshed.candidate_size is None
        assert refreshed.candidate_saved_bytes is None
        assert refreshed.candidate_saved_percent is None
        assert refreshed.images_changed == 0
        assert refreshed.candidate_details == ()
    finally:
        conn.close()


def test_summary_explains_unchanged_reasons_including_legacy_records(
    capsys: pytest.CaptureFixture[str],
) -> None:
    legacy = state.Record(
        "legacy.pdf", "digest", 100, 1, "config", "lossless", "UNCHANGED",
        100, "digest", 0, 0.0, 1, 0.0, None, "test", "test", "then",
    )
    report.print_summary([
        legacy,
        replace(legacy, source_path="first.pdf", decision_reason="reduction_below_threshold"),
        replace(legacy, source_path="second.pdf", decision_reason="reduction_below_threshold"),
        replace(legacy, source_path="adopted.pdf", status="ADOPTED_LOSSLESS"),
    ])
    output = capsys.readouterr().out
    assert "reduction_below_threshold (候補の削減量が採用基準未満) : 2" in output
    assert "not_recorded (過去の処理で理由を記録していない) : 1" in output
