"""Root reconciliation for protection policy schema 5."""
import hashlib
from pathlib import Path

import pytest

import shrink_all
from test_shrink_all import _write_pdf_report


def test_patterns_normalize_conflict_and_preserve_priority():
    args = shrink_all.build_parser().parse_args([
        "-i", "input", "--pdf-text-pattern", r".\Reports\*.PDF",
        "--pdf-photo-pattern", "reports/*", "--pdf-preserve-pattern", "*keep*",
    ])
    options = ("standard", args.pdf_photo_pattern, args.pdf_preserve_pattern, args.pdf_text_pattern, [])
    assert shrink_all._pdf_profile(Path("Reports/KEEP.pdf"), *options) == "preserve"
    with pytest.raises(ValueError, match="conflicting"):
        shrink_all._pdf_profile(Path("reports/a.pdf"), *options)
    assert shrink_all._pdf_profile(Path("other.pdf"), *options) == "standard"


@pytest.mark.parametrize("mutation", [None, "bytes", "classification", "basis", "schema", "reason", "status", "policy"])
def test_preserved_report_requires_exact_bytes_and_current_policy(tmp_path, mutation):
    inputs, outputs = tmp_path / "in", tmp_path / "out"
    inputs.mkdir()
    outputs.mkdir()
    source, target = inputs / "a.pdf", outputs / "a.pdf"
    source.write_bytes(b"%PDF-1.7\nprotected original")
    target.write_bytes(source.read_bytes())
    if mutation == "bytes":
        target.write_bytes(b"%PDF-1.7\naltered!! original")
    row = {"source_path": str(source), "source_size": source.stat().st_size,
           "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
           "output_path": str(target), "output_size": target.stat().st_size,
           "output_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
           "saved_bytes": source.stat().st_size - target.stat().st_size,
           "saved_percent": (source.stat().st_size - target.stat().st_size) / source.stat().st_size,
           "status": "PRESERVED_ORIGINAL", "preset": "standard", "profile": "preserve",
           "requested_policy": "preserve", "classification": "protected",
           "permission_basis": "explicit_preserve", "preservation_reason": "explicit_preserve", "processing_schema": 5}
    changes = {"classification": ("classification", "text"), "basis": ("permission_basis", "explicit_text"),
               "schema": ("processing_schema", 4), "reason": ("preservation_reason", ""),
               "status": ("status", "UNCHANGED"), "policy": ("requested_policy", "photo")}
    if mutation in changes:
        key, value = changes[mutation]
        row[key] = value
    report = tmp_path / "report.csv"
    _write_pdf_report(report, [row])
    parsed = shrink_all.parse_pdf_report(report)
    assert shrink_all.pdf_report_matches_inputs(parsed, [source], input_dir=inputs, output_dir=outputs,
                                                preset="standard", dry_run=False, preserve_patterns=["*"]) == (mutation is None)


@pytest.mark.parametrize("missing", ["requested_policy", "classification", "permission_basis", "preservation_reason", "processing_schema"])
def test_old_or_incomplete_policy_csv_rejected(tmp_path, missing):
    report = tmp_path / "report.csv"
    report.write_text(",".join(sorted(shrink_all.PDF_REPORT_REQUIRED_COLUMNS - {missing})) + "\n", encoding="utf-8")
    assert shrink_all.parse_pdf_report(report) == {}


def test_preview_no_longer_requires_photo_permission():
    args = shrink_all.build_parser().parse_args(["-i", "input", "--pdf-preview"])
    assert args.pdf_preview and args.pdf_photo_pattern == []
