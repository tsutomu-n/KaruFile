from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pytest

from excel_shrink import report, runner
from excel_shrink.cli import main
from excel_shrink.config import ExcelConfig
from excel_shrink.core import CoreResult
from excel_shrink.report import FIELDNAMES


def setup(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    output = tmp_path / "out"
    config = ExcelConfig(source, output, ("*.xlsx",))
    return source, output, config


def rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        assert tuple(reader.fieldnames) == FIELDNAMES
        return list(reader)


def protected(source, candidate, *, dpi, dry_run, analysis, max_side=None, jpeg_quality=85):
    analysis.images_total = 1
    return CoreResult(
        status="DRY_RUN_PRESERVED" if dry_run else "PRESERVED_ORIGINAL",
        reason="unsupported structure", images_total=1, images_changed=0, changed_parts=(),
    )


def adopted(source, candidate, *, dpi, dry_run, analysis, max_side=None, jpeg_quality=85):
    analysis.images_total = 1
    analysis.complete = True
    if dry_run:
        assert candidate is None
        return CoreResult(status="DRY_RUN", reason="eligible", images_total=1, images_changed=0, changed_parts=())
    candidate.write_bytes(b"smaller workbook")
    return CoreResult(status="ADOPTED_LOSSY", reason="resized", images_total=1, images_changed=1, changed_parts=("xl/media/image1.jpeg",))


def test_preservation_copies_exact_input_and_keeps_directories(tmp_path, monkeypatch):
    source, output, config = setup(tmp_path)
    nested = source / "sub"
    nested.mkdir()
    workbook = nested / "book.XLSX"
    workbook.write_bytes(b"protected original")
    (source / "other.xlsm").write_bytes(b"not selected")
    (source / "~$book.xlsx").write_bytes(b"lock")
    monkeypatch.setattr(runner, "process_workbook", protected)
    outcome = runner.run(config)
    assert outcome.exit_code == 0
    assert (output / "sub/book.XLSX").read_bytes() == workbook.read_bytes()
    assert not (output / "other.xlsm").exists()
    assert not (output / "~$book.xlsx").exists()
    record, = rows(config.report_path)
    assert record["relative_path"] == "sub/book.XLSX"
    assert record["source_sha256"] == record["output_sha256"]
    assert record["schema_version"] == "3"
    assert record["changed_parts"] == "[]"


def test_adoption_smaller_and_report_hashes(tmp_path, monkeypatch):
    source, output, config = setup(tmp_path)
    workbook = source / "book.xlsx"
    original = b"original" * 100
    workbook.write_bytes(original)
    monkeypatch.setattr(runner, "process_workbook", adopted)
    assert runner.run(config).exit_code == 0
    record, = rows(config.report_path)
    assert record["status"] == "ADOPTED_LOSSY"
    assert int(record["output_size"]) < int(record["source_size"])
    assert json.loads(record["changed_parts"]) == ["xl/media/image1.jpeg"]
    assert record["source_sha256"] != record["output_sha256"]
    assert workbook.read_bytes() == original
    assert (output / "book.xlsx").read_bytes() == b"smaller workbook"


def test_dry_run_does_not_create_or_replace_workbooks(tmp_path, monkeypatch):
    source, output, normal = setup(tmp_path)
    workbook = source / "book.xlsx"
    workbook.write_bytes(b"source")
    output.mkdir()
    completed = output / "book.xlsx"
    completed.write_bytes(b"prior result")
    normal.report_path.write_bytes(b"prior report")
    config = ExcelConfig(source, output, ("*.xlsx",), dry_run=True)
    monkeypatch.setattr(runner, "process_workbook", adopted)
    assert runner.run(config).exit_code == 0
    assert completed.read_bytes() == b"prior result"
    assert normal.report_path.read_bytes() == b"prior report"
    record, = rows(config.report_path)
    assert record["status"] == "DRY_RUN"
    assert record["output_sha256"] == record["output_size"] == ""
    assert record["images_changed"] == "0"
    assert record["changed_parts"] == "[]"
    assert not list(config.work_dir.glob("*.xlsx"))


def test_errors_continue_without_overwriting_prior_output(tmp_path, monkeypatch):
    source, output, config = setup(tmp_path)
    (source / "a.xlsx").write_bytes(b"corrupt")
    (source / "b.xlsx").write_bytes(b"valid original")
    output.mkdir()
    (output / "a.xlsx").write_bytes(b"existing result")

    def process(path, candidate, **options):
        if path.name == "a.xlsx":
            candidate.write_bytes(b"partial")
            raise OSError("image decode failed")
        return protected(path, candidate, **options)

    monkeypatch.setattr(runner, "process_workbook", process)
    outcome = runner.run(config)
    assert outcome.exit_code == 1
    assert (output / "a.xlsx").read_bytes() == b"existing result"
    assert (output / "b.xlsx").read_bytes() == b"valid original"
    first, second = rows(config.report_path)
    assert first["status"] == "ERROR"
    assert first["output_size"] == first["output_sha256"] == ""
    assert second["status"] == "PRESERVED_ORIGINAL"
    assert not list(config.work_dir.iterdir())


def test_source_mutation_before_publish_is_error(tmp_path, monkeypatch):
    source, output, config = setup(tmp_path)
    workbook = source / "book.xlsx"
    workbook.write_bytes(b"original" * 100)
    output.mkdir()
    prior = output / "book.xlsx"
    prior.write_bytes(b"prior")

    def mutate(path, candidate, **options):
        result = adopted(path, candidate, **options)
        path.write_bytes(b"changed concurrently")
        return result

    monkeypatch.setattr(runner, "process_workbook", mutate)
    assert runner.run(config).exit_code == 1
    assert prior.read_bytes() == b"prior"
    assert rows(config.report_path)[0]["status"] == "ERROR"


def test_reexecution_recomputes_without_cache(tmp_path, monkeypatch):
    source, _, config = setup(tmp_path)
    (source / "book.xlsx").write_bytes(b"original")
    called = []

    def counting(*args, **kwargs):
        called.append(args[0])
        return protected(*args, **kwargs)

    monkeypatch.setattr(runner, "process_workbook", counting)
    assert runner.run(config).exit_code == runner.run(config).exit_code == 0
    assert len(called) == 2


def test_report_publication_failure_keeps_old_report_and_completed_book(tmp_path, monkeypatch):
    source, output, config = setup(tmp_path)
    (source / "book.xlsx").write_bytes(b"original")
    config.report_path.write_bytes(b"old report")
    monkeypatch.setattr(runner, "process_workbook", protected)

    def fail(*args, **kwargs):
        raise PermissionError("report is locked")

    monkeypatch.setattr(report, "publish", fail)
    outcome = runner.run(config)
    assert outcome.exit_code == 1
    assert outcome.report_path is None
    assert config.report_path.read_bytes() == b"old report"
    assert (output / "book.xlsx").read_bytes() == b"original"


def test_output_changed_before_report_prevents_stale_success_report(tmp_path, monkeypatch):
    source, output, config = setup(tmp_path)
    (source / "book.xlsx").write_bytes(b"original")
    config.report_path.write_bytes(b"prior report")
    monkeypatch.setattr(runner, "process_workbook", protected)
    real_write_report = runner.write_report

    def tamper(path, results, guard, **kwargs):
        (output / "book.xlsx").write_bytes(b"modified output")
        return real_write_report(path, results, guard, **kwargs)

    monkeypatch.setattr(runner, "write_report", tamper)
    assert runner.run(config).exit_code == 1
    assert config.report_path.read_bytes() == b"prior report"


def test_report_hardlink_to_nonselected_file_aborts_before_core(tmp_path, monkeypatch):
    source, output, config = setup(tmp_path)
    (source / "book.xlsx").write_bytes(b"book")
    unrelated = source / "keep.bin"
    unrelated.write_bytes(b"keep")
    os.link(unrelated, config.report_path)
    monkeypatch.setattr(runner, "process_workbook", lambda *a, **k: pytest.fail("must preflight"))
    assert runner.run(config).exit_code == 1
    assert unrelated.read_bytes() == b"keep"
    assert not output.exists()


@pytest.mark.parametrize("options", [[], ["--pattern", "*.xlsx", "--dpi", "301"], ["--pattern", "../*.xlsx"]])
def test_cli_invalid_arguments_exit_two(tmp_path, options):
    with pytest.raises(SystemExit) as exc:
        main(["run", "--input", str(tmp_path), "--output", str(tmp_path / "out"), *options])
    assert exc.value.code == 2


@pytest.mark.parametrize("exception", [TimeoutError("processing budget exceeded"), PermissionError("output locked")])
def test_timeout_or_publication_failure_keeps_prior_output_and_continues(tmp_path, monkeypatch, exception):
    source, output, config = setup(tmp_path)
    (source / "a.xlsx").write_bytes(b"original first")
    (source / "b.xlsx").write_bytes(b"original second")
    output.mkdir()
    (output / "a.xlsx").write_bytes(b"previous successful output")
    real_publish = runner.publish
    def process(path, candidate, **options):
        if path.name == "a.xlsx" and isinstance(exception, TimeoutError):
            candidate.write_bytes(b"partial candidate")
            raise exception
        return protected(path, candidate, **options)
    def publish(stage, destination, *args):
        if destination.name == "a.xlsx":
            raise exception
        return real_publish(stage, destination, *args)
    monkeypatch.setattr(runner, "process_workbook", process)
    monkeypatch.setattr(runner, "publish", publish)
    assert runner.run(config).exit_code == 1
    assert (output / "a.xlsx").read_bytes() == b"previous successful output"
    assert (output / "b.xlsx").read_bytes() == b"original second"
    assert [row["status"] for row in rows(config.report_path)] == ["ERROR", "PRESERVED_ORIGINAL"]


@pytest.mark.parametrize("part", ["xl/workbook.xml", "xl/media/not-image.xml", "xl/media//image.png", "xl/media/./image.png"])
def test_invalid_core_changed_parts_do_not_publish(tmp_path, monkeypatch, part):
    source, output, config = setup(tmp_path)
    (source / "book.xlsx").write_bytes(b"original" * 50)
    output.mkdir()
    prior = output / "book.xlsx"
    prior.write_bytes(b"prior completed")
    def invalid(path, candidate, **options):
        candidate.write_bytes(b"smaller")
        return CoreResult("ADOPTED_LOSSY", "claimed success", 1, 1, (part,))
    monkeypatch.setattr(runner, "process_workbook", invalid)
    assert runner.run(config).exit_code == 1
    assert prior.read_bytes() == b"prior completed"
