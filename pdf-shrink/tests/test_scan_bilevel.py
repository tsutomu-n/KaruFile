"""Scanner-produced indirect lengths and opt-in document bilevel compression."""
from dataclasses import replace
import hashlib
from pathlib import Path
import time

import pymupdf as fitz
import pytest

from pdf_shrink import cli, config, discovery, policy, qpdf, state, text_optimize, worker
from pdf_shrink.lossless_jpeg import CandidateRejected
from pdf_shrink.models import ProcessStatus
from test_protection_text import make_pdf


def indirect_scan(path):
    # Build a valid PDF with an indirect /Length, like real scanner output.
    with fitz.open() as doc:
        page = doc.new_page(width=144, height=144)
        page.insert_text((8, 30), "Invoice 1,234.50", fontsize=12)
        pix = page.get_pixmap(dpi=200, colorspace=fitz.csGRAY)
        jpeg = pix.tobytes("jpeg", jpg_quality=95)
    content = b"q 144 0 0 144 0 0 cm /Im0 Do Q"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 144 144] /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>",
        (f"<< /Type /XObject /Subtype /Image /Width {pix.width} /Height {pix.height} /BitsPerComponent 8 /ColorSpace /DeviceGray /Filter /DCTDecode /Length 6 0 R >>\nstream\n".encode() + jpeg + b"\nendstream"),
        f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream",
        str(len(jpeg)).encode(),
    ]
    data = bytearray(b"%PDF-1.7\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    start = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode())
    path.write_bytes(data)
    return len(jpeg)


@pytest.mark.parametrize("dry", [False, True])
def test_indirect_length_scanner_pdf_processes_without_error(tmp_path, dry):
    inputs = tmp_path / "in"
    inputs.mkdir()
    source = inputs / "scan.pdf"
    length = indirect_scan(source)
    before = hashlib.sha256(source.read_bytes()).digest()
    with fitz.open(source) as doc:
        assert not doc.is_repaired
        assert doc.xref_get_key(4, "Length") == ("xref", "6 0 R")
        assert policy._stream_length(doc, 4) == length
    cfg = replace(config.default_config(input_dir=inputs, output_dir=tmp_path / "out",
                                       text_scan_bilevel_patterns=("*.pdf",)), dry_run=dry)
    result = worker.process_one_file(discovery.snapshot(source, inputs), cfg, tmp_path / "temp",
                                     None if dry else qpdf.ensure_qpdf())
    assert hashlib.sha256(source.read_bytes()).digest() == before
    assert result.profile == "text_scan_bilevel"
    assert result.permission_basis == "explicit_text_scan_bilevel"
    if dry:
        assert result.status == ProcessStatus.DRY_RUN_LOSSY
        assert not result.output_path.exists()
        assert not result.candidate_details
    else:
        assert result.status == ProcessStatus.ADOPTED_LOSSY, result
        assert result.output_size < source.stat().st_size / 2
        assert next(c.kind for c in result.candidate_details if c.selected) == "text_scan_bilevel"
        with fitz.open(source) as src, fitz.open(result.output_path) as dst:
            assert dst[0].get_images()[0][2:4] == src[0].get_images()[0][2:4]
            assert dst[0].get_images()[0][4] == 1
            assert set(fitz.Pixmap(dst, dst[0].get_images()[0][0]).samples) == {0, 255}
        conn = state.init_db(tmp_path / "state.sqlite3")
        try:
            snapshot = discovery.snapshot(source, inputs)
            state.save_result(conn, snapshot, result, config.config_hash(cfg), input_dir=inputs,
                              pymupdf_version="", qpdf_version="")
            record = state.get_record(conn, str(source.resolve()))
            assert record.profile == "text_scan_bilevel"
            assert next(c.kind for c in record.candidate_details if c.selected) == "text_scan_bilevel"
        finally:
            conn.close()


def test_indirect_stream_limit_checked_before_decode(tmp_path, monkeypatch):
    source = tmp_path / "scan.pdf"
    length = indirect_scan(source)
    monkeypatch.setattr(policy, "MAX_STREAM_BYTES", length - 1)
    monkeypatch.setattr(fitz, "Pixmap", lambda *a: pytest.fail("decoded an over-limit stream"))
    assert policy.classify(source, "text_scan_bilevel").preservation_reason == "image_stream_limit"


@pytest.mark.parametrize("value", ["-1", "null", "/bad", "[42]", "true", "<< /Length 4 0 R >>"])
def test_invalid_indirect_length_is_error_before_decode(tmp_path, monkeypatch, value):
    source = tmp_path / "scan.pdf"
    indirect_scan(source)
    with fitz.open(source) as doc:
        doc.update_object(6, value)
        monkeypatch.setattr(fitz, "Pixmap", lambda *a: pytest.fail("decoded invalid stream length"))
        with pytest.raises(ValueError, match="stream length"):
            policy.scan_images(doc)


def test_bilevel_white_padding_threshold_and_rows():
    # Nine pixels per row deliberately exercises PDF's byte-aligned row padding.
    pix = fitz.Pixmap(fitz.csGRAY, 9, 2, bytes([219, 220, 255, 0, 255, 255, 0, 255, 0] + [255] * 9), False)
    budget = text_optimize.Budget(time.monotonic() + 10)
    assert text_optimize._bilevel_samples(pix, budget) == bytes([0x6D, 0x7F, 0xFF, 0xFF])
    with pytest.raises(CandidateRejected, match="time_limit"):
        text_optimize._bilevel_samples(pix, text_optimize.Budget(0))


def test_bilevel_permissions_hash_safe_and_preserve(tmp_path):
    parser = cli.build_parser()
    args = parser.parse_args(["run", "--input", str(tmp_path), "--text-scan-bilevel-pattern", r".\Scans\*.PDF"])
    cfg = config.build_config(args)
    assert cfg.text_scan_bilevel_patterns == ("scans/*.pdf",)
    assert config.profile_for_path(cfg, Path("Scans/a.pdf")) == "text_scan_bilevel"
    assert config.config_hash(cfg) != config.config_hash(replace(cfg, text_scan_bilevel_patterns=()))
    with pytest.raises(ValueError, match="safe"):
        replace(cfg, safe=True)
    conflict = replace(cfg, text_scan_patterns=("*",))
    with pytest.raises(ValueError, match="conflicting"):
        config.profile_for_path(conflict, Path("Scans/a.pdf"))
    assert config.profile_for_path(replace(conflict, preserve_patterns=("*",)), Path("Scans/a.pdf")) == "preserve"


def test_bilevel_rejects_large_tonal_change_and_keeps_jpeg_fallback(tmp_path):
    inputs = tmp_path / "in"
    inputs.mkdir()
    source = inputs / "gray.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=72, height=72)
        pix = fitz.Pixmap(fitz.csGRAY, 200, 200, bytes([180]) * 40000, False)
        xref = page.insert_image(page.rect, stream=pix.tobytes("jpeg", jpg_quality=95))
        doc.xref_set_key(xref, "ColorSpace", "/DeviceGray")
        doc.save(source)
    cfg = config.default_config(input_dir=inputs, output_dir=tmp_path / "out", text_scan_bilevel_patterns=("*",))
    result = worker.process_one_file(discovery.snapshot(source, inputs), cfg, tmp_path / "temp", qpdf.ensure_qpdf())
    binary = next(c for c in result.candidate_details if c.kind == "text_scan_bilevel")
    assert binary.reason == "quality_rejected"
    assert not binary.selected
    assert result.status != ProcessStatus.ERROR
    assert any(c.kind == "lossless" for c in result.candidate_details)


def test_bilevel_permission_does_not_bypass_complex_image_protection(tmp_path, monkeypatch):
    source = tmp_path / "mask.pdf"
    make_pdf(source, "mask")
    cfg = config.default_config(input_dir=tmp_path, output_dir=tmp_path.parent / (tmp_path.name + "-out"),
                                text_scan_bilevel_patterns=("*",))
    monkeypatch.setattr(text_optimize, "generate", lambda *a: pytest.fail("protected candidate"))
    result = worker.process_one_file(discovery.snapshot(source, tmp_path), cfg, tmp_path / "temp", None)
    assert result.status == ProcessStatus.PRESERVED_ORIGINAL
    assert result.output_path.read_bytes() == source.read_bytes()
