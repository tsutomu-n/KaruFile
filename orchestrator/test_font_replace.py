"""Explicit font replacement stays bound to selection, current bytes and report schema."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import shrink_all
from test_shrink_all import PDF_REPORT_FIELDS, _write_image_manifest, _write_pdf_report


def _font_row(source: Path, target: Path, status: str = "ADOPTED_LOSSY") -> dict:
    dry_run = status.startswith("DRY_RUN_")
    protected = status in {"PRESERVED_ORIGINAL", "DRY_RUN_PRESERVED"}
    original = source.read_bytes()
    completed = None if dry_run else target.read_bytes()
    saved = 0 if completed is None else len(original) - len(completed)
    return {
        "source_path": str(source), "source_size": len(original),
        "source_sha256": hashlib.sha256(original).hexdigest(),
        "output_path": str(target), "output_size": "" if dry_run else len(completed),
        "output_sha256": "" if dry_run else hashlib.sha256(completed).hexdigest(),
        "saved_bytes": saved, "saved_percent": saved / len(original),
        "status": status, "preset": "standard", "profile": "font_replace",
        "classification": "protected" if protected else "font_replace",
        "preservation_reason": "unsupported_font_structure" if protected else "",
        "font_replacement_requested": "true", "replacement_font": "Meiryo Regular",
        "replacement_font_sha256": "a" * 64, "text_extraction_changed": "false",
    }


@pytest.fixture
def font_case(tmp_path):
    inputs, outputs = tmp_path / "input", tmp_path / "output"
    inputs.mkdir()
    outputs.mkdir()
    source, target = inputs / "report.pdf", outputs / "report.pdf"
    source.write_bytes(b"%PDF-1.7\n" + b"original" * 16)
    target.write_bytes(source.read_bytes()[:-1])
    row = _font_row(source, target)
    options = dict(input_dir=inputs, output_dir=outputs, preset="standard", dry_run=False,
                   font_replace_patterns=["*.PDF"])
    return tmp_path / "report.csv", source, target, row, options


@pytest.mark.parametrize("other", ["photo", "text", "text_scan", "text_scan_bilevel"])
def test_font_patterns_normalize_conflict_and_preserve(other):
    args = shrink_all.build_parser().parse_args([
        "-i", "input", "--pdf-font-replace-pattern", r".\Reports\*.PDF",
        "--pdf-font-replace-pattern=-extra.pdf",
    ])
    assert args.pdf_font_replace_pattern == ["Reports/*.PDF", "-extra.pdf"]
    options = dict(photo_patterns=[], font_replace_patterns=args.pdf_font_replace_pattern)
    path = Path("reports/nested/a.pdf")
    assert shrink_all._pdf_profile(path, "compact", **options) == "font_replace"
    assert shrink_all._pdf_profile(Path("elsewhere.pdf"), "compact", **options) == "compact"
    options[f"{other}_patterns"] = ["*"]
    with pytest.raises(ValueError, match="conflicting PDF permissions"):
        shrink_all._pdf_profile(path, "standard", **options)
    assert shrink_all._pdf_profile(path, "standard", preserve_patterns=["*"], **options) == "preserve"


@pytest.mark.parametrize("pattern", ["", " ", "../*.pdf", "a/../*.pdf", "/a.pdf", r"C:\a.pdf"])
def test_font_patterns_reject_unsafe_globs(pattern):
    with pytest.raises(SystemExit) as caught:
        shrink_all.build_parser().parse_args(["-i", "input", "--pdf-font-replace-pattern", pattern])
    assert caught.value.code == 2


@pytest.mark.parametrize("missing", [
    "font_replacement_requested", "replacement_font", "replacement_font_sha256", "text_extraction_changed",
])
def test_missing_font_report_columns_rejected(font_case, missing):
    report, _source, _target, _row, _options = font_case
    report.write_text(",".join(name for name in PDF_REPORT_FIELDS if name != missing) + "\n", encoding="utf-8")
    assert shrink_all.parse_pdf_report(report) == {}


def test_meiryo_report_must_match_requested_family(font_case):
    report, source, target, row, options = font_case
    row['replacement_font'] = 'Yu Gothic Regular'
    _write_pdf_report(report, [row])
    parsed = shrink_all.parse_pdf_report(report)
    assert parsed
    assert not shrink_all.pdf_report_matches_inputs(parsed, [source], **options)
    assert shrink_all.pdf_report_matches_inputs(parsed, [source], **options, font_family='yu-gothic')
    parsed['rows'][0]['replacement_font'] = 'Meiryo Regular'
    assert not shrink_all.pdf_report_matches_inputs(parsed, [source], **options, font_family='yu-gothic')


def test_family_without_selection_rejected_before_work(tmp_path, monkeypatch):
    monkeypatch.setattr(shrink_all, 'run_command', lambda *a: pytest.fail('unexpected processor'))
    with pytest.raises(SystemExit) as exc:
        shrink_all.main(['-i', str(tmp_path), '--pdf-font-family', 'meiryo'])
    assert exc.value.code == 2


@pytest.mark.parametrize(("field", "value"), [
    ("font_replacement_requested", "false"), ("font_replacement_requested", "True"),
    ("font_replacement_requested", ""), ("replacement_font", "Yu Mincho"),
    ("replacement_font", ""), ("replacement_font_sha256", ""),
    ("replacement_font_sha256", "A" * 64), ("replacement_font_sha256", "a" * 63),
    ("replacement_font_sha256", "g" * 64), ("text_extraction_changed", "True"),
    ("text_extraction_changed", ""), ("processing_schema", 5),
])
def test_parser_rejects_invalid_font_metadata(font_case, field, value):
    report, _source, _target, row, _options = font_case
    row[field] = value
    _write_pdf_report(report, [row])
    assert shrink_all.parse_pdf_report(report) == {}


@pytest.mark.parametrize(("field", "value"), [
    ("font_replacement_requested", False), ("font_replacement_requested", 1),
    ("replacement_font", "Yu Mincho"), ("replacement_font_sha256", "A" * 64),
    ("replacement_font_sha256", None), ("text_extraction_changed", 1),
    ("text_extraction_changed", "false"), ("classification", "text"),
    ("permission_basis", "explicit_text"), ("requested_policy", "text"),
    ("processing_schema", 5), ("source_sha256", "b" * 64), ("output_sha256", "b" * 64),
])
def test_matcher_independently_rejects_forged_font_row(font_case, field, value):
    report, source, _target, row, options = font_case
    _write_pdf_report(report, [row])
    parsed = shrink_all.parse_pdf_report(report)
    assert shrink_all.pdf_report_matches_inputs(parsed, [source], **options)
    parsed["rows"][0][field] = value
    assert not shrink_all.pdf_report_matches_inputs(parsed, [source], **options)


@pytest.mark.parametrize("status", [
    "ADOPTED_LOSSY", "ADOPTED_LOSSLESS", "UNCHANGED", "PRESERVED_ORIGINAL",
    "DRY_RUN_LOSSY", "DRY_RUN_PRESERVED", "ERROR",
])
def test_font_report_tracks_request_for_adopted_protected_and_dry_run(font_case, status):
    report, source, target, _row, options = font_case
    if status in {"UNCHANGED", "PRESERVED_ORIGINAL", "ERROR"}:
        target.write_bytes(source.read_bytes())
    row = _font_row(source, target, status)
    options["dry_run"] = status.startswith("DRY_RUN_")
    _write_pdf_report(report, [row])
    parsed = shrink_all.parse_pdf_report(report)
    assert shrink_all.pdf_report_matches_inputs(parsed, [source], **options)
    # A request is not proof that the font candidate was adopted. Lossless wins are valid.
    assert parsed["rows"][0]["font_replacement_requested"] is True
    assert parsed["rows"][0]["text_extraction_changed"] is False
    assert not shrink_all.pdf_report_matches_inputs(parsed, [source], **dict(options, font_replace_patterns=[]))


@pytest.mark.parametrize("status", ["ADOPTED_LOSSY", "ADOPTED_LOSSLESS", "UNCHANGED", "PRESERVED_ORIGINAL", "DRY_RUN_LOSSY", "ERROR"])
def test_extraction_change_only_belongs_to_adopted_font_candidate(font_case, status):
    report, source, target, _row, options = font_case
    if status in {"UNCHANGED", "PRESERVED_ORIGINAL", "ERROR"}:
        target.write_bytes(source.read_bytes())
    row = _font_row(source, target, status)
    row["text_extraction_changed"] = "true"
    options["dry_run"] = status.startswith("DRY_RUN_")
    _write_pdf_report(report, [row])
    parsed = shrink_all.parse_pdf_report(report)
    assert shrink_all.pdf_report_matches_inputs(parsed, [source], **options) is (status == "ADOPTED_LOSSY")


@pytest.mark.parametrize(("field", "value"), [
    ("font_replacement_requested", "true"), ("replacement_font", "Meiryo Regular"),
    ("replacement_font_sha256", "a" * 64), ("text_extraction_changed", "true"),
])
def test_other_profiles_reject_font_metadata(font_case, field, value):
    report, _source, _target, row, _options = font_case
    row.update(profile="standard", classification="text", font_replacement_requested="false",
               replacement_font="", replacement_font_sha256="", text_extraction_changed="false")
    row[field] = value
    _write_pdf_report(report, [row])
    assert shrink_all.parse_pdf_report(report) == {}


def test_font_report_rejects_different_font_file_hashes_in_one_run(font_case):
    report, source, target, row, options = font_case
    source2, target2 = source.with_name("second.pdf"), target.with_name("second.pdf")
    source2.write_bytes(source.read_bytes())
    target2.write_bytes(target.read_bytes())
    second = _font_row(source2, target2)
    _write_pdf_report(report, [row, second])
    assert shrink_all.pdf_report_matches_inputs(shrink_all.parse_pdf_report(report), [source, source2], **options)
    second["replacement_font_sha256"] = "b" * 64
    _write_pdf_report(report, [row, second])
    assert not shrink_all.pdf_report_matches_inputs(shrink_all.parse_pdf_report(report), [source, source2], **options)


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("family", [None, "yu-gothic"])
def test_root_forwards_font_permission_only_to_pdf_and_verifies_report(tmp_path, monkeypatch, dry_run, family):
    inputs, outputs = tmp_path / "input", tmp_path / "output"
    inputs.mkdir()
    source = inputs / "report.pdf"
    source.write_bytes(b"%PDF-1.7\noriginal")
    calls = []

    def fake_run(name, _project, args):
        calls.append(name)
        if name == "pdf-shrink":
            assert [arg for arg in args if arg.startswith("--font-replace-pattern=")] == [
                "--font-replace-pattern=*.PDF", "--font-replace-pattern=-extra.pdf",
            ]
            if family:
                assert args[args.index("--font-family")+1] == family
            else:
                assert "--font-family" not in args
            assert "--lossless-jpeg" in args
            assert ("--dry-run" in args) is dry_run
            target = outputs / source.name
            if not dry_run:
                target.write_bytes(source.read_bytes())
            row = _font_row(source, target, "DRY_RUN_LOSSY" if dry_run else "UNCHANGED")
            if family:
                row["replacement_font"] = "Yu Gothic Regular"
            row["lossless_jpeg_requested"] = "true"
            _write_pdf_report(tmp_path / ("report.dry-run.csv" if dry_run else "report.csv"), [row])
        else:
            assert name == "media-shrink"
            assert not any("font-replace" in arg for arg in args)
            assert "--lossless-jpeg" not in args
            Path(f"{outputs}.image-errors.csv").write_text("source,planned_output,error\n", encoding="utf-8")
            suffix = ".dry-run" if dry_run else ""
            _write_image_manifest(Path(f"{outputs}.image-manifest{suffix}.csv"))
        return 0, [], 0.01

    monkeypatch.setattr(shrink_all, "run_command", fake_run)
    args = ["-i", str(inputs), "-o", str(outputs), "--pdf-font-replace-pattern", "*.PDF",
            "--pdf-font-replace-pattern=-extra.pdf", "--pdf-lossless-jpeg"]
    if family:
        args.extend(["--pdf-font-family", family])
    if dry_run:
        args.append("--dry-run")
    assert shrink_all.main(args) == 0
    assert calls == ["pdf-shrink", "media-shrink"]
    assert source.read_bytes() == b"%PDF-1.7\noriginal"
    if dry_run:
        assert not outputs.exists()


def test_overlapping_font_permissions_fail_before_processor_or_output(tmp_path, monkeypatch):
    inputs, outputs = tmp_path / "input", tmp_path / "output"
    inputs.mkdir()
    (inputs / "report.pdf").write_bytes(b"%PDF-1.7\noriginal")
    monkeypatch.setattr(shrink_all, "run_command", lambda *args: pytest.fail("processor ran before conflict rejection"))
    assert shrink_all.main(["-i", str(inputs), "-o", str(outputs),
                            "--pdf-font-replace-pattern", "*", "--pdf-text-pattern", "*"]) == 1
    assert not outputs.exists()
