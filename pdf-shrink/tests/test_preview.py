"""Visual evidence stays independent of normal processing and survives failures."""
from dataclasses import replace
import json
from pathlib import Path
import random
import re
import shutil
import time

import pymupdf as fitz
import pytest

from pdf_shrink import discovery, preview
from pdf_shrink.config import RunConfig
from pdf_shrink.models import CandidateResult
from pdf_shrink.state import Record


@pytest.fixture
def case(tmp_path):
    inputs = tmp_path / "in"
    outputs = tmp_path / "result" / "files"
    inputs.mkdir()
    outputs.mkdir(parents=True)
    path = inputs / "photo & small.pdf"
    pix = fitz.Pixmap(fitz.csRGB, 800, 600, random.Random(4).randbytes(800 * 600 * 3), False)
    with fitz.open() as doc:
        page = doc.new_page(width=200, height=160)
        xref = page.insert_image(fitz.Rect(10, 10, 190, 145), stream=pix.tobytes("jpeg", jpg_quality=95))
        doc.xref_set_key(xref, "ColorSpace", "/DeviceRGB")
        page.insert_text((10, 155), "unchanged text", fontsize=6)
        page.set_rotation(90)
        doc.save(path)
    source = discovery.snapshot(path, inputs)
    shutil.copyfile(path, outputs / path.name)
    record = Record(
        source_path=str(path), source_sha256=source.sha256, source_size=source.size,
        source_mtime_ns=source.mtime_ns, config_hash="test", mode="lossless", status="UNCHANGED",
        output_size=source.size, output_sha256=source.sha256, saved_bytes=0, saved_percent=0,
        page_count=1, scan_page_ratio=0, error_message=None, pymupdf_version="test", qpdf_version="test",
        processed_at="now", profile="photo", photo_dpi=200, decision_reason="candidate_not_smaller",
        classification="photo", requested_policy="photo", permission_basis="explicit_photo", processing_schema=6,
    )
    cfg = RunConfig(input_dir=inputs, output_dir=outputs, photo_patterns=("*.pdf",), preview=True)
    return cfg, source, record


def read_manifest(cfg):
    return json.loads((cfg.output_dir.parent / ("pdf-preview.dry-run.json" if cfg.dry_run else "pdf-preview.json")).read_text(encoding="utf-8"))


def generate(case):
    cfg, source, record = case
    return preview.generate(cfg, [source], [record], Path("qpdf"), (source.path,))


def test_default_rotated_views_match_and_reruns_preserve_previous_bundle(case):
    cfg, source, record = case
    assert generate(case)
    data = read_manifest(cfg)
    item = data["items"][0]
    assert item["status"] == "READY"
    assert [v["key"] for v in item["variants"]] == ["original", "output"]
    assert len(item["views"]) == 2
    assert [v["render_dpi"] for v in item["views"]] == [144, 300]
    original_index = Path(data["index_path"])
    old_hash = preview.sha256_file(original_index)
    for view in item["views"]:
        original = Path(data["run_dir"]) / view["images"]["original"]
        output = Path(data["run_dir"]) / view["images"]["output"]
        assert original.read_bytes() == output.read_bytes()
        pix = fitz.Pixmap(original)
        assert (pix.width, pix.height) == (view["pixel_width"], view["pixel_height"])
    assert generate(case)
    assert read_manifest(cfg)["index_path"] != str(original_index)
    assert preview.sha256_file(original_index) == old_hash
    assert preview.sha256_file(source.path) == source.sha256
    assert preview.sha256_file(source.output_path(cfg.output_dir)) == record.output_sha256


def test_dry_run_only_records_request_without_tools_or_html(case, monkeypatch):
    cfg, source, record = case
    cfg = replace(cfg, dry_run=True, preview_dpis=(180, 150))
    record = replace(record, status="DRY_RUN_LOSSY", output_size=None, output_sha256=None)
    monkeypatch.setattr(preview, "_document", lambda *a: pytest.fail("rendered during dry run"))
    assert generate((cfg, source, record))
    data = read_manifest(cfg)
    assert data["status"] == "DRY_RUN" and data["preview_dpis"] == [180, 150]
    assert data["run_dir"] is None and data["index_path"] is None
    assert data["items"][0]["status"] == "SKIPPED"
    assert not (cfg.output_dir.parent / "pdf-preview").exists()


def test_empty_selection_has_index(case):
    cfg, _, _ = case
    assert preview.generate(cfg, [], [], None, ())
    data = read_manifest(cfg)
    assert data["items"] == [] and data["status"] == "COMPLETE"
    assert Path(data["index_path"]).is_file()


@pytest.mark.parametrize("status", ["ERROR", "SKIPPED_SMALL", "SKIPPED_SIGNED", "SKIPPED_COMPLEX", "SKIPPED_ENCRYPTED"])
def test_unprocessed_pdfs_are_not_rendered(case, monkeypatch, status):
    cfg, source, record = case
    monkeypatch.setattr(preview, "_document", lambda *a: pytest.fail("rendered skipped PDF"))
    assert generate((cfg, source, replace(record, status=status)))
    assert read_manifest(cfg)["items"][0]["status"] == "SKIPPED"


@pytest.mark.parametrize("reason, expected_status, available", [
    ("eligible", "READY", True), ("candidate_not_smaller", "READY", True),
    ("reduction_below_threshold", "READY", True), ("quality_rejected", "READY", False),
    ("processing_error", "ERROR", False), ("no_image_savings", "READY", True),
])
def test_independent_candidates_do_not_change_actual_output(case, monkeypatch, reason, expected_status, available):
    cfg, source, record = case
    cfg = replace(cfg, preview_dpis=(150,))
    calls = []
    def evaluate(original, candidate_cfg, path, mode, profile, qpdf):
        calls.append(candidate_cfg)
        assert original.sha256 == source.sha256
        shutil.copyfile(original.path, path)
        return CandidateResult("photo", size=source.size, images_changed=1, reason=reason)
    monkeypatch.setattr(preview.worker, "_evaluate_candidate", evaluate)
    result = generate((cfg, source, record))
    assert result is (expected_status != "ERROR")
    item = read_manifest(cfg)["items"][0]
    assert item["status"] == expected_status
    assert len(calls) == 1 and calls[0].lossy.dpi_target == 150 and calls[0].lossy.quality == 80
    assert ("dpi150" in item["views"][0]["images"]) is available
    assert item["selected_kind"] == "original" and item["pdf_status"] == "UNCHANGED"
    assert preview.sha256_file(source.output_path(cfg.output_dir)) == record.output_sha256
    assert not list(Path(read_manifest(cfg)["run_dir"]).rglob(".candidate-*.pdf"))


def test_low_dpi_candidate_reuses_original_without_transform(case, monkeypatch):
    cfg, source, record = case
    cfg = replace(cfg, preview_dpis=(300,))  # placement is 320 DPI: use inspection stub for low-DPI path
    inspect = preview.inspect_file
    def inspection(path, *a, **kw):
        result = inspect(path, *a, **kw)
        return replace(result, mode=preview.OptimizationMode.LOSSLESS)
    monkeypatch.setattr(preview, "inspect_file", inspection)
    monkeypatch.setattr(preview.worker, "_evaluate_candidate", lambda *a: pytest.fail("low DPI transformed"))
    assert generate((cfg, source, record))
    item = read_manifest(cfg)["items"][0]
    assert item["variants"][-1]["reason"] == "no_image_savings"
    assert item["variants"][-1]["href"] == item["variants"][0]["href"]


@pytest.mark.parametrize("limit, value, reason", [
    ("MAX_PAGES", 0, "preview_page_limit"), ("MAX_REGIONS", 0, "preview_region_limit"),
    ("MAX_RENDER_PIXELS", 1, "preview_render_pixel_limit"),
    ("MAX_DOCUMENT_PIXELS", 1, "preview_document_pixel_limit"),
    ("DOCUMENT_SECONDS", -1, "preview_time_limit"),
])
def test_limits_are_preview_errors_preserving_completed_pdf(case, monkeypatch, limit, value, reason):
    cfg, source, record = case
    monkeypatch.setattr(preview, limit, value)
    assert not generate(case)
    data = read_manifest(cfg)
    assert data["status"] == "ERROR" and reason in data["items"][0]["reason"]
    assert Path(data["index_path"]).exists()
    assert preview.sha256_file(source.output_path(cfg.output_dir)) == record.output_sha256


def test_one_document_failure_continues_next(case, monkeypatch):
    cfg, source, record = case
    second = source.path.with_name("second.pdf")
    shutil.copyfile(source.path, second)
    source2 = discovery.snapshot(second, cfg.input_dir)
    shutil.copyfile(second, source2.output_path(cfg.output_dir))
    record2 = replace(record, source_path=str(second), source_sha256=source2.sha256)
    real = preview._document
    def document(s, *a):
        if s == source:
            raise OSError("simulated I/O failure")
        return real(s, *a)
    monkeypatch.setattr(preview, "_document", document)
    assert not preview.generate(cfg, [source, source2], [record, record2], Path("qpdf"), (source.path, second))
    assert [i["status"] for i in read_manifest(cfg)["items"]] == ["ERROR", "READY"]


def test_completed_pdf_tampering_rejects_preview(case):
    cfg, source, record = case
    source.output_path(cfg.output_dir).write_bytes(b"changed")
    assert not generate(case)
    assert "completed PDF changed" in read_manifest(cfg)["items"][0]["reason"]


def test_html_json_cannot_close_script():
    value = {"name": '</script><script>alert("x")</script>&\u2028'}
    escaped = preview._json(value)
    assert "<" not in escaped and ">" not in escaped and "&" not in escaped
    assert json.loads(escaped) == value


def test_manifest_hardlink_is_rejected_without_modifying_source(case):
    cfg, source, _ = case
    manifest = cfg.output_dir.parent / "pdf-preview.dry-run.json"
    manifest.hardlink_to(source.path)
    with pytest.raises(ValueError, match="hard"):
        generate((replace(cfg, dry_run=True), source, case[2]))
    assert preview.sha256_file(source.path) == source.sha256


def test_budget_rejects_before_expensive_render():
    budget = preview.Budget(time.monotonic() + 30, pixels=preview.MAX_DOCUMENT_PIXELS)
    with pytest.raises(preview.PreviewLimitError, match="document_pixel"):
        budget.render(1)


def test_input_and_output_siblings_are_supported(case):
    cfg, source, record = case
    cfg = replace(cfg, output_dir=cfg.input_dir.with_name("out"))
    cfg.output_dir.mkdir()
    shutil.copyfile(source.path, source.output_path(cfg.output_dir))
    assert generate((cfg, source, record))
    assert read_manifest(cfg)["items"][0]["status"] == "READY"


def test_page_limit_is_checked_before_full_inspection(case, monkeypatch):
    monkeypatch.setattr(preview, "MAX_PAGES", 0)
    monkeypatch.setattr(preview, "inspect_file", lambda *a, **kw: pytest.fail("late page limit"))
    assert not generate(case)
    assert read_manifest(case[0])["items"][0]["reason"] == "preview_page_limit"


def font_case(case, *, status="ADOPTED_LOSSY", changed=True):
    cfg, source, record = case
    cfg = replace(cfg, photo_patterns=(), font_replace_patterns=("*.pdf",),
                  font_replace_path=Path("installed-font.ttc"), font_replace_sha256="a" * 64,
                  preview_dpis=(180, 150))
    target = source.output_path(cfg.output_dir)
    if status != "PRESERVED_ORIGINAL":
        # A distinct completed PDF exposes the old false "protected" classification.
        with fitz.open(source.path) as document:
            document.set_metadata({"subject": "completed font trial fixture"})
            document.save(target)
    protected = status == "PRESERVED_ORIGINAL"
    kind = "font_replace" if status == "ADOPTED_LOSSY" else "lossless"
    record = replace(record, profile="font_replace", requested_policy="font_replace", photo_dpi=None,
                     classification="protected" if protected else "font_replace",
                     permission_basis="explicit_font_replace", status=status,
                     preservation_reason="font_replace_unsupported" if protected else "",
                     output_size=target.stat().st_size, output_sha256=preview.sha256_file(target),
                     font_replacement_requested=True, replacement_font="Meiryo Regular",
                     replacement_font_sha256="a" * 64, text_extraction_changed=changed,
                     candidate_details=() if protected else (CandidateResult(kind, selected=True,
                                                                             text_extraction_changed=changed),))
    return cfg, source, record


@pytest.mark.parametrize(("status", "changed"), [
    ("ADOPTED_LOSSY", True), ("ADOPTED_LOSSY", False),
    ("ADOPTED_LOSSLESS", False), ("PRESERVED_ORIGINAL", False),
])
def test_font_preview_renders_completed_result_and_carries_diagnostics(case, monkeypatch, status, changed):
    cfg, source, record = font_case(case, status=status, changed=changed)
    monkeypatch.setattr(preview, "classify", lambda *a: pytest.fail("ordinary text classifier for font profile"))
    monkeypatch.setattr(preview.worker, "_evaluate_candidate", lambda *a: pytest.fail("non-photo preview candidate"))
    assert generate((cfg, source, record))
    data = read_manifest(cfg)
    item = data["items"][0]
    assert item["status"] == "READY" and item["pdf_status"] == status
    assert item["font_replacement_requested"] is True
    assert item["replacement_font"] == "Meiryo Regular"
    assert item["text_extraction_changed"] is changed
    assert [variant["key"] for variant in item["variants"]] == ["original", "output"]
    html = Path(data["index_path"]).read_text(encoding="utf-8")
    embedded = json.loads(re.search(r'<script type="application/json" id="preview-data">(.*?)</script>', html, re.S)[1])
    assert embedded["items"][0] == item
    assert preview.sha256_file(source.path) == source.sha256
    assert preview.sha256_file(source.output_path(cfg.output_dir)) == record.output_sha256


@pytest.mark.parametrize(("field", "value"), [
    ("classification", "protected"), ("permission_basis", "explicit_photo"),
    ("font_replacement_requested", False), ("replacement_font_sha256", "b" * 64),
    ("replacement_font", "Yu Mincho"), ("text_extraction_changed", "false"),
    ("source_sha256", "b" * 64), ("processing_schema", 5),
])
def test_font_preview_rejects_inconsistent_processing_state(case, field, value):
    cfg, source, record = font_case(case)
    assert not generate((cfg, source, replace(record, **{field: value})))
    data = read_manifest(cfg)
    assert data["status"] == "ERROR"
    assert data["items"][0]["reason"] == "font preview processing state mismatch"
    assert preview.sha256_file(source.output_path(cfg.output_dir)) == record.output_sha256


def test_font_preview_requires_selected_family(case):
    cfg, source, record = font_case(case, changed=False)
    cfg = replace(cfg, font_family="yu-gothic")
    with pytest.raises(RuntimeError, match="font preview processing state mismatch"):
        preview._font_preview_decision(source, record, cfg)
    record = replace(record, replacement_font="Yu Gothic Regular")
    assert preview._font_preview_decision(source, record, cfg).classification == "font_replace"


def test_font_preview_dry_run_carries_request_without_html_or_render(case, monkeypatch):
    cfg, source, record = font_case(case, changed=False)
    cfg = replace(cfg, dry_run=True)
    record = replace(record, status="DRY_RUN_LOSSY", output_size=None, output_sha256=None, candidate_details=())
    monkeypatch.setattr(preview, "_document", lambda *a: pytest.fail("font dry-run render"))
    assert generate((cfg, source, record))
    data = read_manifest(cfg)
    item = data["items"][0]
    assert item["font_replacement_requested"] is True and item["replacement_font"] == "Meiryo Regular"
    assert item["text_extraction_changed"] is False
    assert data["index_path"] is None
    assert not (cfg.output_dir.parent / "pdf-preview").exists()


def test_font_preview_preserves_separate_page_limit(case, monkeypatch):
    cfg, source, record = font_case(case)
    monkeypatch.setattr(preview, "MAX_PAGES", 0)
    monkeypatch.setattr(preview, "_font_preview_decision", lambda *a: pytest.fail("late font page limit"))
    assert not generate((cfg, source, record))
    assert read_manifest(cfg)["items"][0]["reason"] == "preview_page_limit"
    assert preview.sha256_file(source.output_path(cfg.output_dir)) == record.output_sha256
