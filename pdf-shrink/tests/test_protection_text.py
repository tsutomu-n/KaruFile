"""Public policy acceptance: actual PDFs, exact copy boundaries and text guards."""
from dataclasses import replace
from pathlib import Path
import time

import pymupdf as fitz
import pytest

from pdf_shrink import config, discovery, policy, qpdf, runner, text_optimize, worker
from pdf_shrink.lossless_jpeg import CandidateRejected
from pdf_shrink.models import ProcessStatus


def make_pdf(path, kind="text", dpi=600):
    with fitz.open() as doc:
        page = doc.new_page(width=144, height=144)
        page.insert_text((10, 25), "012345 Thin text", fontsize=9, color=(0.2, 0.1, 0.3))
        if kind == "rules":
            page.draw_rect(fitz.Rect(5, 5, 139, 139))
            page.draw_line((5, 40), (139, 40))
        elif kind == "curve":
            page.draw_circle((80, 80), 20)
        elif kind == "fill":
            page.draw_rect(fitz.Rect(50, 50, 90, 90), fill=(0, 0, 0))
        elif kind == "diagonal":
            page.draw_line((5, 40), (139, 50))
        if kind in {"scan", "shared", "mask"}:
            pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB)
            with fitz.open() as scan:
                sp = scan.new_page(width=144, height=144)
                xref = sp.insert_image(sp.rect, pixmap=pix)
                # Explicit simple RGB fixture, excluding MuPDF's default ICC profile.
                scan.xref_set_key(xref, "ColorSpace", "/DeviceRGB")
                scan.xref_set_key(xref, "DecodeParms", "null")
                if kind == "shared":
                    sp = scan.new_page(width=288, height=288)
                    sp.insert_image(sp.rect, xref=xref)
                if kind == "mask":
                    scan.xref_set_key(xref, "Decode", "[0 1 0 1 0 1]")
                scan.save(path)
            return
        doc.save(path)


@pytest.mark.parametrize("preset", ["standard", "compact"])
@pytest.mark.parametrize("kind", ["scan", "rules", "curve", "fill", "diagonal"])
def test_default_protection_never_generates_candidates(tmp_path, monkeypatch, preset, kind):
    inputs = tmp_path / "input"
    inputs.mkdir()
    path = inputs / "document.pdf"
    make_pdf(path, kind)
    cfg = config.default_config(input_dir=inputs, output_dir=tmp_path / "out", preset=preset)
    monkeypatch.setattr(worker, "_evaluate_candidate", lambda *a, **k: pytest.fail("protected candidate"))
    monkeypatch.setattr(text_optimize, "generate", lambda *a, **k: pytest.fail("protected text candidate"))
    result = worker.process_one_file(discovery.snapshot(path, inputs), cfg, tmp_path / "temp", None)
    assert result.status == ProcessStatus.PRESERVED_ORIGINAL
    assert result.candidate_details == ()
    assert result.output_path.read_bytes() == path.read_bytes()


def test_explicit_preserve_overrides_all_conflicts_even_corrupt_pdf(tmp_path, monkeypatch):
    inputs = tmp_path / "in"
    inputs.mkdir()
    path = inputs / "a.pdf"
    path.write_bytes(b"unreadable but explicitly preserved")
    cfg = replace(config.default_config(input_dir=inputs, output_dir=tmp_path / "out"),
                  preserve_patterns=("*.PDF",), text_patterns=("*",), text_scan_patterns=("*",), photo_patterns=("*",), lossless_jpeg=True)
    result = worker.process_one_file(discovery.snapshot(path, inputs), cfg, tmp_path / "temp", None)
    assert result.status == ProcessStatus.PRESERVED_ORIGINAL
    assert result.preservation_reason == "explicit_preserve"
    assert result.output_path.read_bytes() == path.read_bytes()
    assert not result.candidate_details


def test_conflict_preflight_has_no_outputs_or_tools(tmp_path, monkeypatch):
    inputs = tmp_path / "in"
    inputs.mkdir()
    make_pdf(inputs / "a.pdf")
    cfg = replace(config.default_config(input_dir=inputs, output_dir=tmp_path / "out"),
                  text_patterns=("*",), photo_patterns=("*",))
    monkeypatch.setattr(runner, "_prepare_tools", lambda *a: pytest.fail("tool preparation before conflict"))
    assert runner.run(cfg) == 1
    assert not cfg.output_dir.exists()


@pytest.mark.parametrize("kind,protected", [("text", False), ("rules", False), ("curve", True), ("fill", True), ("diagonal", True), ("scan", True)])
def test_explicit_table_requires_simple_rules(tmp_path, kind, protected):
    path = tmp_path / "a.pdf"
    make_pdf(path, kind)
    assert policy.classify(path, "text").protected == protected


def test_blank_pages_with_text_allowed_but_blank_document_protected(tmp_path):
    path = tmp_path / "a.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.new_page().insert_text((20, 20), "text")
        doc.save(path)
    assert not policy.classify(path, "standard").protected
    blank = tmp_path / "blank.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(blank)
    assert policy.classify(blank, "standard").preservation_reason == "no_confirmed_text"


@pytest.mark.parametrize("dry", [False, True])
def test_structure_failure_is_error_and_recovery_is_exact(tmp_path, dry):
    inputs = tmp_path / "in"
    inputs.mkdir()
    path = inputs / "broken.pdf"
    path.write_bytes(b"broken")
    cfg = replace(config.default_config(input_dir=inputs, output_dir=tmp_path / "out"), dry_run=dry)
    result = worker.process_one_file(discovery.snapshot(path, inputs), cfg, tmp_path / "temp", None)
    assert result.status == ProcessStatus.ERROR
    assert bool(result.error_message)
    assert not result.candidate_details
    if dry:
        assert not result.output_path.exists()
    else:
        assert result.output_path.read_bytes() == path.read_bytes()


@pytest.mark.parametrize("kind", ["text", "rules", "scan", "shared"])
def test_real_candidates_preserve_text_and_placements(tmp_path, kind):
    inputs = tmp_path / "in"
    inputs.mkdir()
    path = inputs / "a.pdf"
    make_pdf(path, kind)
    cfg = replace(config.default_config(input_dir=inputs, output_dir=tmp_path / "out"),
                  text_patterns=("*",) if kind == "rules" else (),
                  text_scan_patterns=("*",) if kind in {"scan", "shared"} else ())
    result = worker.process_one_file(discovery.snapshot(path, inputs), cfg, tmp_path / "temp", qpdf.ensure_qpdf())
    assert result.status in {ProcessStatus.UNCHANGED, ProcessStatus.ADOPTED_LOSSLESS, ProcessStatus.ADOPTED_LOSSY}, result
    assert len(result.candidate_details) == (4 if kind in {"scan", "shared"} else 3)
    assert result.output_size <= path.stat().st_size
    assert all(c.reason != "processing_error" for c in result.candidate_details)
    with fitz.open(path) as src, fitz.open(result.output_path) as dst:
        assert [p.get_text() for p in src] == [p.get_text() for p in dst]
        assert [text_optimize._placements(p) for p in src] == [text_optimize._placements(p) for p in dst]


@pytest.mark.parametrize("dpi", [150, 300, 600])
@pytest.mark.parametrize("candidate_kind", ["text_scan_jpeg_92", "text_scan_bilevel"])
def test_scan_dimensions_never_upscale_and_respect_shared_placement(tmp_path, dpi, candidate_kind):
    path, target = tmp_path / "scan.pdf", tmp_path / "candidate.pdf"
    make_pdf(path, "shared", dpi)
    cfg = config.default_config(input_dir=tmp_path, output_dir=tmp_path.parent / "unused")
    text_optimize.generate(path, target, candidate_kind, cfg, qpdf.ensure_qpdf(), text_optimize.Budget(time.monotonic() + 300))
    with fitz.open(path) as src, fitz.open(target) as dst:
        original = src[0].get_images()[0]
        actual = dst[0].get_images()[0]
        # Shared placement is twice as large: 600 effective -> 300 there.
        assert actual[2:4] == original[2:4]
        assert actual[5] == "DeviceGray"


def test_special_scan_protects_entire_document(tmp_path):
    path = tmp_path / "mask.pdf"
    make_pdf(path, "mask")
    assert policy.classify(path, "text_scan").protected


def test_budget_and_text_position_rejections(tmp_path):
    source, candidate = tmp_path / "a.pdf", tmp_path / "b.pdf"
    make_pdf(source)
    with fitz.open() as doc:
        page = doc.new_page(width=144, height=144)
        page.insert_text((11, 25), "012345 Thin text", fontsize=9, color=(0.2, 0.1, 0.3))
        doc.save(candidate)
    with pytest.raises(CandidateRejected, match="time_limit"):
        text_optimize.validate_candidate(source, candidate, "lossless", qpdf.ensure_qpdf(), text_optimize.Budget(0))
    with pytest.raises(CandidateRejected, match="position_mismatch"):
        text_optimize.validate_candidate(source, candidate, "lossless", qpdf.ensure_qpdf(), text_optimize.Budget(time.monotonic() + 300))
    with pytest.raises(CandidateRejected, match="pixel_limit"):
        text_optimize.validate_candidate(source, source, "lossless", qpdf.ensure_qpdf(), text_optimize.Budget(time.monotonic() + 300, maximum=1))


@pytest.mark.parametrize("failure,winner", [("none", "lossless"), ("gray_rejected", "lossless"), ("larger", None), ("tool", None), ("budget", None)])
def test_text_arbitration_small_ties_and_failure_paths(tmp_path, monkeypatch, failure, winner):
    inputs = tmp_path / "in"
    inputs.mkdir()
    path = inputs / "a.pdf"
    make_pdf(path)
    source = discovery.snapshot(path, inputs)
    calls = []
    def generate(src, dst, kind, cfg, tool, budget):
        assert src == path
        calls.append(kind)
        if failure == "tool":
            raise OSError("disk failure")
        if failure == "budget":
            raise CandidateRejected("text_document_time_limit")
        dst.write_bytes(b"x" * (source.size + 1 if failure == "larger" else source.size - 1))
        return 0
    def validate(src, dst, kind, *args):
        if failure == "gray_rejected" and kind == "text_gray":
            raise CandidateRejected("text_render_mismatch")
    monkeypatch.setattr(text_optimize, "generate", generate)
    monkeypatch.setattr(text_optimize, "validate_candidate", validate)
    cfg = config.default_config(input_dir=inputs, output_dir=tmp_path / "out")
    result = worker.process_one_file(source, cfg, tmp_path / "temp", Path("qpdf"))
    assert source.size < 256 * 1024
    assert next((d.kind for d in result.candidate_details if d.selected), None) == winner
    if winner:
        assert result.saved_bytes == 1 and result.status == ProcessStatus.ADOPTED_LOSSLESS
    else:
        assert result.output_path.read_bytes() == path.read_bytes()
        assert result.status == (ProcessStatus.ERROR if failure == "tool" else ProcessStatus.UNCHANGED)
    assert calls == (["lossless"] if failure == "tool" else ["lossless", "text_subset", "text_gray"])


def test_safe_disables_grayscale_and_rejects_scan_permission(tmp_path, monkeypatch):
    cfg = config.default_config(input_dir=tmp_path, output_dir=tmp_path.parent / "unused")
    with pytest.raises(ValueError, match="safe"):
        replace(cfg, safe=True, text_scan_patterns=("*",))
    path = tmp_path / "a.pdf"
    make_pdf(path)
    cfg = replace(cfg, safe=True, dry_run=True)
    monkeypatch.setattr(text_optimize, "generate", lambda *a: pytest.fail("dry run candidate"))
    result = worker.process_one_file(discovery.snapshot(path, tmp_path), cfg, tmp_path / "temp", None)
    assert result.status == ProcessStatus.DRY_RUN_LOSSLESS
    assert not result.output_path.exists()
    assert not (tmp_path / "temp").exists()


def test_policy_hash_covers_all_permissions_and_additive_schema(tmp_path):
    cfg = config.default_config(input_dir=tmp_path, output_dir=tmp_path.parent / "unused")
    for name in ("preserve_patterns", "text_patterns", "text_scan_patterns"):
        assert config.config_hash(replace(cfg, **{name: ("*",)})) != config.config_hash(cfg)
    assert config.config_hash(replace(cfg, preview=True)) == config.config_hash(cfg)


@pytest.mark.parametrize("limit,reason", [("MAX_PAGES", "page_limit"), ("MAX_IMAGE_PIXELS", "image_pixel_limit"), ("MAX_STREAM_BYTES", "image_stream_limit")])
def test_scan_preflight_limits_protect_document(tmp_path, monkeypatch, limit, reason):
    path = tmp_path / "scan.pdf"
    make_pdf(path, "scan")
    monkeypatch.setattr(policy, limit, 0)
    assert policy.classify(path, "text_scan").preservation_reason == reason


@pytest.mark.parametrize("candidate_kind", ["text_scan_jpeg_92", "text_scan_bilevel"])
def test_scan_keeps_ocr_links_bookmarks_metadata_and_rejects_missing_text(tmp_path, candidate_kind):
    path, original, target = tmp_path / "scan.pdf", tmp_path / "ocr.pdf", tmp_path / "candidate.pdf"
    make_pdf(path, "scan")
    with fitz.open(path) as doc:
        doc[0].insert_text((10, 25), "OCR 012345", fontsize=9, render_mode=3)
        doc[0].insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(10, 10, 70, 30), "uri": "https://example.com/"})
        doc.set_toc([[1, "chapter", 1]])
        doc.set_metadata({"title": "scan with OCR", "author": "synthetic fixture"})
        doc.save(original)
    assert not policy.classify(original, "text_scan").protected
    cfg = config.default_config(input_dir=tmp_path, output_dir=tmp_path.parent / "unused")
    tool = qpdf.ensure_qpdf()
    budget = text_optimize.Budget(time.monotonic() + 300)
    text_optimize.generate(original, target, candidate_kind, cfg, tool, budget)
    text_optimize.validate_candidate(original, target, candidate_kind, tool, budget)
    with pytest.raises(CandidateRejected, match="structure_mismatch|position_mismatch"):
        text_optimize.validate_candidate(original, path, candidate_kind, tool, budget)


def test_equal_scan_jpeg_sizes_prefer_highest_quality(tmp_path, monkeypatch):
    inputs = tmp_path / "input"
    inputs.mkdir()
    path = inputs / "scan.pdf"
    make_pdf(path, "scan")
    source = discovery.snapshot(path, inputs)
    cfg = config.default_config(input_dir=inputs, output_dir=tmp_path / "out", text_scan_patterns=("*",))
    def generate(src, dst, kind, *args):
        assert src == path
        dst.write_bytes(b"x" * (source.size if kind == "lossless" else source.size - 1))
        return 0 if kind == "lossless" else 1
    monkeypatch.setattr(text_optimize, "generate", generate)
    monkeypatch.setattr(text_optimize, "validate_candidate", lambda *args: None)
    result = worker.process_one_file(source, cfg, tmp_path / "temp", Path("qpdf"))
    assert result.status == ProcessStatus.ADOPTED_LOSSY
    assert result.decision_reason == "adopted_text_scan_jpeg_92"
    assert next(d.kind for d in result.candidate_details if d.selected) == "text_scan_jpeg_92"
