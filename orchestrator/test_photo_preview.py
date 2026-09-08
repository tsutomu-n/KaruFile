from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

import shrink_all
from test_shrink_all import _make_directory_link, _write_image_manifest, _write_pdf_report


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pdf_row(source: Path, output: Path, *, dry_run: bool = False, photo_dpi: int = 150):
    return {
        "source_path": str(source), "source_size": source.stat().st_size,
        "source_sha256": _digest(source), "output_path": str(output),
        "output_size": "" if dry_run else output.stat().st_size,
        "output_sha256": "" if dry_run else _digest(output),
        "saved_bytes": 0, "saved_percent": 0,
        "status": "DRY_RUN_LOSSY" if dry_run else "UNCHANGED",
        "preset": "standard", "profile": "photo", "photo_dpi": photo_dpi,
    }


def _preview_payload(input_dir: Path, output_dir: Path, rows, *, dry_run=False, failed=False):
    run_dir = output_dir.parent / "pdf-preview" / "unique-run"
    index = run_dir / "index.html"
    if not dry_run and not failed:
        run_dir.mkdir(parents=True)
        index.write_text("<!doctype html><title>Comparison</title>", encoding="utf-8")
    return {
        "schema": 1, "requested": True, "dry_run": dry_run,
        "photo_dpi": 150, "preview_dpis": [200, 180, 150],
        "input_root": str(input_dir), "output_root": str(output_dir),
        "status": "ERROR" if failed else "DRY_RUN" if dry_run else "COMPLETE",
        "run_dir": None if dry_run or failed else str(run_dir),
        "index_path": None if dry_run or failed else str(index),
        "index_sha256": None if dry_run or failed else _digest(index),
        "items": [
            {
                "source_path": row["source_path"],
                "relative_path": Path(row["source_path"]).relative_to(input_dir).as_posix(),
                "source_sha256": row["source_sha256"],
                "output_path": row["output_path"],
                "output_sha256": row["output_sha256"] or None,
                "pdf_status": row["status"],
                "status": "ERROR" if failed else "SKIPPED" if dry_run else "READY",
                "reason": "render failed" if failed else "dry run" if dry_run else "",
            } for row in rows
        ],
        "errors": ["render failed"] if failed else [],
    }


@pytest.fixture
def preview_case(tmp_path):
    inputs, outputs = tmp_path / "input", tmp_path / "output"
    inputs.mkdir()
    outputs.mkdir()
    source, output = inputs / "photo.pdf", outputs / "photo.pdf"
    source.write_bytes(b"%PDF-1.7\nphoto")
    output.write_bytes(source.read_bytes())
    report = tmp_path / "report.csv"
    _write_pdf_report(report, [_pdf_row(source, output)])
    parsed = shrink_all.parse_pdf_report(report)
    payload = _preview_payload(inputs, outputs, parsed["rows"])
    path = tmp_path / "pdf-preview.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    options = dict(
        previous=None, report_result=parsed, input_dir=inputs, output_dir=outputs,
        photo_dpi=150, preview_dpis=[200, 180, 150], dry_run=False,
    )
    return path, payload, options


def test_preview_parser_defaults_and_distinct_dpi_order():
    plain = shrink_all.build_parser().parse_args(["-i", "input"])
    assert plain.pdf_photo_dpi == 200
    assert plain.pdf_preview is False and plain.pdf_preview_dpi == []
    preview = shrink_all.build_parser().parse_args([
        "-i", "input", "--pdf-photo-pattern", "*.pdf", "--pdf-photo-dpi", "150",
        "--pdf-preview", "--pdf-preview-dpi", "150", "--pdf-preview-dpi", "300",
        "--pdf-preview-dpi", "180", "--pdf-preview-dpi", "150",
    ])
    assert preview.pdf_photo_dpi == 150
    assert preview.pdf_preview_dpi == [300, 180, 150]


@pytest.mark.parametrize("args", [
    ["--pdf-photo-dpi", "150"],
    ["--pdf-photo-pattern", "*.pdf", "--pdf-preview-dpi", "180"],
    ["--pdf-photo-pattern", "*.pdf", "--pdf-photo-dpi", "149"],
    ["--pdf-photo-pattern", "*.pdf", "--pdf-photo-dpi", "301"],
    ["--pdf-photo-pattern", "*.pdf", "--pdf-photo-dpi", "200.0"],
    ["--pdf-photo-pattern", "*.pdf", "--pdf-photo-dpi", "true"],
    ["--pdf-photo-pattern", "*.pdf", "--pdf-preview", "--pdf-preview-dpi", "149"],
    ["--pdf-photo-pattern", "*.pdf", "--pdf-preview", "--pdf-preview-dpi", "301"],
    ["--pdf-photo-pattern", "*.pdf", "--pdf-preview"]
    + [arg for dpi in range(150, 156) for arg in ("--pdf-preview-dpi", str(dpi))],
])
def test_preview_parser_rejects_invalid_combinations(args):
    with pytest.raises(SystemExit) as caught:
        shrink_all.build_parser().parse_args(["-i", "input", *args])
    assert caught.value.code == 2


def test_photo_report_matches_exact_target(preview_case):
    _path, _payload, options = preview_case
    report = options["report_result"]
    sources = [Path(row["source_path"]) for row in report["rows"]]
    arguments = dict(
        input_dir=options["input_dir"], output_dir=options["output_dir"],
        preset="standard", dry_run=False, photo_patterns=["*.pdf"],
    )
    assert shrink_all.pdf_report_matches_inputs(report, sources, photo_dpi=150, **arguments)
    assert not shrink_all.pdf_report_matches_inputs(report, sources, photo_dpi=180, **arguments)
    report["rows"][0]["photo_dpi"] = 150.0
    assert not shrink_all.pdf_report_matches_inputs(report, sources, photo_dpi=150, **arguments)


@pytest.mark.parametrize(("profile", "value"), [
    ("photo", ""), ("photo", "150.0"), ("photo", "true"), ("photo", "149"),
    ("photo", "301"), ("standard", "200"), ("compact", "200"),
])
def test_photo_report_rejects_invalid_dpi_cells(preview_case, profile, value):
    path, _payload, options = preview_case
    row = dict(options["report_result"]["rows"][0], profile=profile, photo_dpi=value)
    row["lossless_jpeg_requested"] = "false"
    _write_pdf_report(path.with_suffix(".csv"), [row])
    assert shrink_all.parse_pdf_report(path.with_suffix(".csv")) == {}


def test_preview_manifest_valid_and_stale(preview_case):
    path, payload, options = preview_case
    assert shrink_all.validate_pdf_preview_manifest(path, **options) == payload
    options["previous"] = shrink_all._file_signature(path)
    assert shrink_all.validate_pdf_preview_manifest(path, **options) is None


@pytest.mark.parametrize("field", [
    "schema", "requested", "dry_run", "photo_dpi", "preview_dpis", "input_root",
    "output_root", "status", "run_dir", "index_path", "index_sha256", "items", "errors",
])
def test_preview_manifest_rejects_missing_fields(preview_case, field):
    path, payload, options = preview_case
    del payload[field]
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert shrink_all.validate_pdf_preview_manifest(path, **options) is None


@pytest.mark.parametrize(("field", "value"), [
    ("schema", True), ("schema", 2), ("requested", False), ("dry_run", True),
    ("photo_dpi", 150.0), ("photo_dpi", 180), ("preview_dpis", [200, 180]),
    ("preview_dpis", [200.0, 180, 150]), ("input_root", "input"),
    ("output_root", "output"), ("items", []), ("status", "DRY_RUN"),
    ("status", "ERROR"), ("errors", ["unreported failure"]),
    ("index_sha256", "f" * 64), ("run_dir", None), ("index_path", None),
])
def test_preview_manifest_rejects_forged_fields(preview_case, field, value):
    path, payload, options = preview_case
    payload[field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert shrink_all.validate_pdf_preview_manifest(path, **options) is None


@pytest.mark.parametrize(("field", "value"), [
    ("source_sha256", "f" * 64), ("output_sha256", "f" * 64),
    ("source_path", "photo.pdf"), ("output_path", "photo.pdf"),
    ("relative_path", "../photo.pdf"), ("pdf_status", "ADOPTED_LOSSY"),
    ("status", "COMPLETE"), ("reason", None),
])
def test_preview_manifest_rejects_forged_item(preview_case, field, value):
    path, payload, options = preview_case
    payload["items"][0][field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert shrink_all.validate_pdf_preview_manifest(path, **options) is None


def test_preview_manifest_rejects_duplicate_inputs(preview_case):
    path, payload, options = preview_case
    payload["items"].append(dict(payload["items"][0]))
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert shrink_all.validate_pdf_preview_manifest(path, **options) is None


def test_preview_manifest_rejects_index_outside_run(preview_case):
    path, payload, options = preview_case
    outside = path.parent / "outside.html"
    outside.write_bytes(Path(payload["index_path"]).read_bytes())
    payload["index_path"] = str(outside)
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert shrink_all.validate_pdf_preview_manifest(path, **options) is None


@pytest.mark.parametrize("target", ["manifest", "index"])
def test_preview_manifest_rejects_hardlinks(preview_case, target):
    path, payload, options = preview_case
    original = path if target == "manifest" else Path(payload["index_path"])
    os.link(original, original.with_suffix(".link"))
    assert shrink_all.validate_pdf_preview_manifest(path, **options) is None


def test_preview_manifest_rejects_run_junction(preview_case):
    path, payload, options = preview_case
    original_run = Path(payload["run_dir"])
    link = original_run.with_name("linked-run")
    _make_directory_link(link, original_run)
    payload["run_dir"] = str(link)
    payload["index_path"] = str(link / "index.html")
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert shrink_all.validate_pdf_preview_manifest(path, **options) is None


@pytest.mark.parametrize("mode", ["normal", "dry", "failure", "missing", "disabled", "empty"])
def test_root_preview_runs_independent_image_stage_and_keeps_pdf_results(tmp_path, monkeypatch, capsys, mode):
    inputs, outputs = tmp_path / "input", tmp_path / "output"
    inputs.mkdir()
    source = inputs / "photo.pdf"
    if mode != "empty":
        source.write_bytes(b"%PDF-1.7\nphoto")
    dry_run = mode == "dry"
    preview = mode != "disabled"
    calls = []

    def fake_run(name, _project, args):
        calls.append(name)
        if name == "pdf-shrink":
            assert args[args.index("--photo-dpi") + 1] == "150"
            assert ("--preview" in args) is preview
            if preview:
                assert [args[i + 1] for i, arg in enumerate(args) if arg == "--preview-dpi"] == ["200", "180", "150"]
            output = outputs / source.name
            if not dry_run and mode != "empty":
                output.write_bytes(source.read_bytes())
            rows = [] if mode == "empty" else [_pdf_row(source, output, dry_run=dry_run)]
            _write_pdf_report(tmp_path / ("report.dry-run.csv" if dry_run else "report.csv"), rows)
            if preview and mode != "missing":
                payload = _preview_payload(inputs, outputs, rows, dry_run=dry_run, failed=mode == "failure")
                path = tmp_path / ("pdf-preview.dry-run.json" if dry_run else "pdf-preview.json")
                path.write_text(json.dumps(payload), encoding="utf-8")
        else:
            assert name == "media-shrink"
            assert not any(arg.startswith("--photo") or arg.startswith("--preview") for arg in args)
            Path(f"{outputs}.image-errors.csv").write_text("source,planned_output,error\n", encoding="utf-8")
            _write_image_manifest(Path(f"{outputs}.image-manifest{'.dry-run' if dry_run else ''}.csv"))
        return 0, [], 0.01

    if mode == "disabled":
        (tmp_path / "pdf-preview.json").write_text("invalid old manifest", encoding="utf-8")
    monkeypatch.setattr(shrink_all, "run_command", fake_run)
    args = ["-i", str(inputs), "-o", str(outputs), "--pdf-photo-pattern", "*.pdf", "--pdf-photo-dpi", "150"]
    if preview:
        args += ["--pdf-preview", "--pdf-preview-dpi", "150", "--pdf-preview-dpi", "180", "--pdf-preview-dpi", "200", "--pdf-preview-dpi", "150"]
    if dry_run:
        args.append("--dry-run")
    assert shrink_all.main(args) == (1 if mode in {"failure", "missing"} else 0)
    assert calls == ["pdf-shrink", "media-shrink"]
    printed = capsys.readouterr().out
    assert "PDF errors   : 0" in printed
    if dry_run:
        assert not outputs.exists()
        assert not (tmp_path / "pdf-preview").exists()
    elif mode in {"normal", "empty"}:
        assert "PDF preview:" in printed


@pytest.mark.parametrize("target", ["pdf-preview", "pdf-preview.json", "pdf-preview.dry-run.json"])
def test_preview_preflight_rejects_reserved_output_collision(tmp_path, monkeypatch, target):
    inputs = tmp_path / "input"
    inputs.mkdir()
    (inputs / "photo.pdf").write_bytes(b"%PDF-1.7\nphoto")
    calls = []
    monkeypatch.setattr(shrink_all, "run_command", lambda *args: calls.append(args))
    assert shrink_all.main([
        "-i", str(inputs), "-o", str(tmp_path / target),
        "--pdf-photo-pattern", "*.pdf", "--pdf-preview",
    ]) == 1
    assert calls == []
