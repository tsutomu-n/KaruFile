import hashlib

import pytest

import shrink_all
from test_shrink_all import _write_pdf_report


@pytest.mark.parametrize(("original", "saved", "accepted"), [(300000, 16383, False), (300000, 16384, True), (300000, 16385, True), (1000000, 19999, False), (1000000, 20000, True), (1000000, 20001, True)])
@pytest.mark.parametrize("requested", [False, True])
def test_lossless_report_reduction_boundary_and_request_match(tmp_path, original, saved, accepted, requested):
    inputs, outputs = tmp_path / "input", tmp_path / "output"
    inputs.mkdir()
    outputs.mkdir()
    source, output = inputs / "file.pdf", outputs / "file.pdf"
    source.write_bytes(b"%PDF-1.7\n" + b"a" * (original - 9))
    output.write_bytes(source.read_bytes()[:-saved])
    row = {
        "source_path": str(source), "source_size": original,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "output_path": str(output), "output_size": original - saved,
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "saved_bytes": saved, "saved_percent": saved / original,
        "status": "ADOPTED_LOSSLESS", "preset": "standard", "profile": "standard",
        "lossless_jpeg_requested": "true" if requested else "false",
    }
    report = tmp_path / "report.csv"
    _write_pdf_report(report, [row])
    parsed = shrink_all.parse_pdf_report(report)
    options = dict(input_dir=inputs, output_dir=outputs, preset="standard", dry_run=False)
    assert shrink_all.pdf_report_matches_inputs(parsed, [source], lossless_jpeg_requested=requested, **options) is accepted
    assert not shrink_all.pdf_report_matches_inputs(parsed, [source], lossless_jpeg_requested=not requested, **options)
