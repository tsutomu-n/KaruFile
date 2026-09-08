"""Selected photo DPI is a processing contract; preview choices are separate."""
from __future__ import annotations

import csv
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from pdf_shrink import cli, config, discovery, report, state
from pdf_shrink.models import ProcessResult, ProcessStatus


def parse(tmp_path: Path, *options: str):
    return cli.build_parser().parse_args(["run", "--input", str(tmp_path), *options])


@pytest.mark.parametrize("dpi", [150, 151, 180, 200, 299, 300])
def test_photo_dpi_bounds_and_nonmatching_files(tmp_path: Path, dpi: int) -> None:
    cfg = config.build_config(parse(tmp_path, "--photo-pattern", "photos/*.pdf", "--photo-dpi", str(dpi)))
    selected = config.config_for_path(cfg, Path("photos/a.pdf"))
    untouched = config.config_for_path(cfg, Path("report.pdf"))
    assert cfg.photo_dpi == selected.lossy.dpi_target == dpi
    assert selected.lossy.photo_mode and selected.lossy.quality == 80
    assert selected.reduction.lossy_min_bytes == 64 * 1024
    assert untouched.lossy.dpi_target == 300 and not untouched.lossy.photo_mode


@pytest.mark.parametrize("value", [149, 301, 0, True, False, 150.0, "180", None])
def test_programmatic_photo_dpi_rejects_invalid_values(tmp_path: Path, value) -> None:
    with pytest.raises(ValueError, match="integer between"):
        config.photo_lossy_options(value)
    with pytest.raises(ValueError, match="integer between"):
        config.default_config(input_dir=tmp_path, photo_patterns=("*.pdf",), photo_dpi=value)


@pytest.mark.parametrize("options", [
    ("--photo-dpi", "200"),
    ("--photo-dpi", "150"),
    ("--preview",),
    ("--photo-pattern", "*.pdf", "--preview-dpi", "180"),
    ("--photo-pattern", "*.pdf", "--photo-dpi", "149"),
    ("--photo-pattern", "*.pdf", "--photo-dpi", "301"),
    ("--photo-pattern", "*.pdf", "--preview", "--preview-dpi", "149"),
    ("--photo-pattern", "*.pdf", "--preview", "--safe"),
])
def test_invalid_cli_combinations_fail_before_running(tmp_path: Path, monkeypatch, options) -> None:
    monkeypatch.setattr(cli.runner, "run", lambda cfg: pytest.fail("runner must not start"))
    assert cli.cmd_run(parse(tmp_path, *options)) == 2


@pytest.mark.parametrize("option", ["--photo-dpi", "--preview-dpi"])
def test_cli_requires_integer_dpi_tokens(tmp_path: Path, option: str) -> None:
    with pytest.raises(SystemExit) as exc:
        parse(tmp_path, "--photo-pattern", "*.pdf", "--preview", option, "180.5")
    assert exc.value.code == 2


def test_preview_defaults_and_deduplicated_limit(tmp_path: Path) -> None:
    normal = config.build_config(parse(tmp_path))
    assert normal.photo_dpi == 200 and not normal.preview and normal.preview_dpis == ()
    cfg = config.build_config(parse(tmp_path, "--photo-pattern", "*.pdf", "--preview"))
    assert cfg.preview_dpis == ()  # No extra DPI candidate without explicit selection.
    options = ["--photo-pattern", "*.pdf", "--preview"]
    for dpi in (180, 150, 300, 200, 299, 150):
        options.extend(("--preview-dpi", str(dpi)))
    selected = config.build_config(parse(tmp_path, *options))
    assert selected.preview_dpis == (300, 299, 200, 180, 150)
    with pytest.raises(ValueError, match="at most 5 distinct"):
        config.build_config(parse(tmp_path, *options, "--preview-dpi", "175"))


@pytest.mark.parametrize("changes", [
    {"photo_dpi": 150}, {"preview": True},
    {"preview_dpis": (150,)}, {"preview": "true"},
])
def test_programmatic_config_enforces_option_dependencies(tmp_path: Path, changes) -> None:
    cfg = config.default_config(input_dir=tmp_path)
    with pytest.raises(ValueError):
        replace(cfg, **changes)


def test_preview_rejects_noninteger_values_and_normalizes_direct_config(tmp_path: Path) -> None:
    cfg = config.default_config(input_dir=tmp_path, photo_patterns=("*.pdf",), preview=True)
    assert replace(cfg, preview_dpis=(150, 200, 150)).preview_dpis == (200, 150)
    for value in (True, 150.0, 301, "180"):
        with pytest.raises(ValueError, match="integer between"):
            replace(cfg, preview_dpis=(value,))


def test_photo_dpi_changes_processing_hash_but_preview_does_not(tmp_path: Path) -> None:
    cfg = config.default_config(input_dir=tmp_path, photo_patterns=("*.pdf",))
    assert config.config_hash(cfg) != config.config_hash(replace(cfg, photo_dpi=180))
    assert config.config_hash(cfg) == config.config_hash(replace(cfg, preview=True))
    assert config.config_hash(cfg) == config.config_hash(replace(cfg, preview=True, preview_dpis=(300, 180, 150)))


def test_schema_four_invalidates_previous_successful_records() -> None:
    cfg = config.RunConfig(input_dir=Path("input"), output_dir=Path("output"))
    # Captured from the actual schema-3 implementation before this change.
    previous_hash = "752e2f137d1665227b37db04f7602a5a51b281a7c27eb4713614e3cbcb1ae50c"
    assert config.config_hash(cfg) != previous_hash


def test_photo_dpi_migration_preserves_legacy_photo_record(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as conn:
        conn.executescript("""
            CREATE TABLE files (
                source_path TEXT PRIMARY KEY, source_sha256 TEXT NOT NULL,
                source_size INTEGER NOT NULL, source_mtime_ns INTEGER NOT NULL,
                config_hash TEXT NOT NULL, mode TEXT, status TEXT NOT NULL,
                output_size INTEGER, output_sha256 TEXT, saved_bytes INTEGER,
                saved_percent REAL, page_count INTEGER, scan_page_ratio REAL,
                error_message TEXT, pymupdf_version TEXT, qpdf_version TEXT,
                processed_at TEXT, profile TEXT NOT NULL DEFAULT ''
            );
            INSERT INTO files (source_path, source_sha256, source_size,
                source_mtime_ns, config_hash, mode, status, output_size,
                output_sha256, profile) VALUES ('photo.pdf', 'source-hash',
                100, 1, 'schema-3', 'lossy', 'ADOPTED_LOSSY', 90,
                'output-hash', 'photo');
        """)
    for _ in range(2):
        conn = state.init_db(database)
        try:
            record = state.get_record(conn, "photo.pdf")
            assert record is not None and record.photo_dpi is None
            assert record.profile == "photo" and record.output_sha256 == "output-hash"
            assert record.config_hash == "schema-3"
            assert state.should_process(record, "source-hash", "schema-4", False, True)
        finally:
            conn.close()


@pytest.mark.parametrize("profile,dpi", [("photo", 150), ("photo", 300), ("standard", None), ("compact", None)])
@pytest.mark.parametrize("status", [ProcessStatus.DRY_RUN_LOSSY, ProcessStatus.SKIPPED_SMALL, ProcessStatus.ERROR])
def test_photo_dpi_survives_state_and_csv_for_nonadoption_results(tmp_path: Path, profile, dpi, status) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    original = input_dir / "photo.pdf"
    original.write_bytes(b"source")
    source = discovery.snapshot(original, input_dir)
    result = ProcessResult(
        output_path=tmp_path / "output" / original.name, status=status,
        mode=None, page_count=0, scan_page_ratio=0, output_size=None,
        saved_bytes=0, saved_percent=0, error_message=None, profile=profile,
        photo_dpi=dpi,
    )
    conn = state.init_db(tmp_path / "state.sqlite3")
    try:
        state.save_result(conn, source, result, "cfg", input_dir=input_dir, pymupdf_version="test", qpdf_version="test")
        record = state.get_record(conn, str(original))
        assert record is not None and record.photo_dpi == dpi
        target = tmp_path / "report.csv"
        report.write_csv([record], target, input_root=input_dir, work_root=tmp_path, protected_sources=[original])
        with target.open(encoding="utf-8-sig", newline="") as stream:
            row = next(csv.DictReader(stream))
        assert row["photo_dpi"] == (str(dpi) if dpi is not None else "")
    finally:
        conn.close()
