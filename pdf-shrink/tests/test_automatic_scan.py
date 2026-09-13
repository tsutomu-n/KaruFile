from dataclasses import replace
from pathlib import Path
import time

import pymupdf as fitz
import pytest

from pdf_shrink import cli, config, discovery, policy, qpdf, raster_scan, runner, worker
from pdf_shrink.lossless_jpeg import CandidateRejected
from pdf_shrink.models import ProcessStatus
from pdf_shrink.utils import sha256_file
from test_protection_text import make_pdf


def scan(path, *, rotation=0, crop=False, clip=True, ocr=False):
    raw = path.with_suffix('.fixture.pdf')
    make_pdf(raw, 'scan')
    with fitz.open(raw) as doc:
        page = doc[0]
        if clip:
            xref = page.get_contents()[0]
            doc.update_stream(xref, b'q 0 0 141.17 143.23 re W n\n' + doc.xref_stream(xref) + b'\nQ')
        if crop:
            page.set_cropbox(fitz.Rect(2.13, 1.17, 143.1, 142.9))
        if ocr:
            page.insert_text((20, 35), 'searchable OCR', render_mode=3)
        page.set_rotation(rotation)
        doc.set_metadata({'title': 'Keep scan metadata'})
        doc.set_toc([[1, 'Keep bookmark', 1]])
        doc.save(path)
    raw.unlink()


@pytest.mark.parametrize('preset', ['standard', 'compact'])
@pytest.mark.parametrize('rotation,crop', [(0, False), (90, False), (270, True), (0, True)])
def test_automatic_clipped_scan_and_pixel_grid(tmp_path, preset, rotation, crop):
    path = tmp_path / 'scan.pdf'
    scan(path, rotation=rotation, crop=crop)
    digest = sha256_file(path)
    cfg = config.default_config(input_dir=path, preset=preset)
    result = worker.process_one_file(discovery.snapshot(path, path), cfg, tmp_path / 'temp', qpdf.ensure_qpdf())
    assert result.status == ProcessStatus.ADOPTED_LOSSY
    assert result.classification == 'raster_scan'
    assert result.permission_basis == 'automatic_scan_raster'
    assert result.images_changed == 1
    assert result.output_size < path.stat().st_size
    assert sha256_file(path) == digest
    assert result.output_path == tmp_path / 'scan_軽量化' / 'files' / 'scan.pdf'
    with fitz.open(path) as src, fitz.open(result.output_path) as dst:
        assert src[0].rect == dst[0].rect and src[0].rotation == dst[0].rotation
        assert src.get_toc() == dst.get_toc() and src.metadata == dst.metadata


def test_ocr_and_text_and_mixed_documents_keep_existing_policy(tmp_path):
    text, ocr, mixed = (tmp_path / name for name in ('text.pdf', 'ocr.pdf', 'mixed.pdf'))
    make_pdf(text, 'text')
    scan(ocr, ocr=True)
    assert policy.classify(text, 'standard').classification == 'text'
    assert policy.classify(ocr, 'standard').protected
    with fitz.open(ocr) as doc, fitz.open(text) as other:
        doc.insert_pdf(other)
        doc.save(mixed)
    assert policy.classify(mixed, 'standard').protected


@pytest.mark.parametrize('option', ['safe', 'preserve', 'dry'])
def test_auto_scan_explicit_preserve_safe_and_dry_do_not_generate(tmp_path, monkeypatch, option):
    path = tmp_path / 'scan.pdf'
    scan(path)
    cfg = config.default_config(input_dir=path)
    cfg = replace(cfg, safe=option == 'safe', preserve_patterns=('*',) if option == 'preserve' else (), dry_run=option == 'dry')
    monkeypatch.setattr(raster_scan, 'generate', lambda *a: pytest.fail('unexpected generation'))
    result = worker.process_one_file(discovery.snapshot(path, path), cfg, tmp_path / 'temp', None)
    assert result.status == (ProcessStatus.DRY_RUN_LOSSY if option == 'dry' else ProcessStatus.PRESERVED_ORIGINAL)
    assert result.candidate_details == ()
    assert result.images_changed == 0
    if option == 'dry':
        assert not cfg.output_dir.exists()
    else:
        assert result.output_path.read_bytes() == path.read_bytes()


def test_single_file_cli_report_and_resume(tmp_path, monkeypatch):
    import csv
    path = tmp_path / 'scan.pdf'
    scan(path)
    (tmp_path / 'unrelated.pdf').write_bytes(b'unreadable neighbor')
    assert cli.main(['run', '--input', str(path), '--preview']) == 0
    assert (tmp_path / 'scan_軽量化' / 'pdf-preview.json').exists()
    cfg = config.default_config(input_dir=path)
    report = runner.WorkspacePaths.from_config(cfg).report
    rows = list(csv.DictReader(report.open(encoding='utf-8-sig', newline='')))
    assert len(rows) == 1 and Path(rows[0]['source_path']) == path
    assert Path(rows[0]['output_path']) == cfg.output_dir / path.name
    before = (cfg.output_dir / path.name).stat()
    monkeypatch.setattr(worker, 'process_one_file', lambda *a: pytest.fail('resume regenerated candidates'))
    assert cli.main(['run', '--input', str(path)]) == 0
    assert (cfg.output_dir / path.name).stat().st_mtime_ns == before.st_mtime_ns


@pytest.mark.parametrize('limit,value', [('page_pixels', 1), ('total_pixels', 1), ('source_bytes', 1), ('image_pixels', 1)])
def test_auto_scan_limits_are_preflight_protection(tmp_path, monkeypatch, limit, value):
    path = tmp_path / 'scan.pdf'
    scan(path)
    monkeypatch.setitem(raster_scan.RECIPE, limit, value)
    decision = policy.classify(path, 'standard')
    assert decision.protected and decision.preservation_reason.startswith('raster_scan_')


def test_missing_page_and_local_erasure_rejected(tmp_path):
    path = tmp_path / 'scan.pdf'
    scan(path, clip=False)
    exe = qpdf.ensure_qpdf()
    bad = tmp_path / 'bad.pdf'
    raster_scan.generate(path, bad, raster_scan.Budget(time.monotonic()+60))
    altered = tmp_path / 'altered.pdf'
    with fitz.open(bad) as doc:
        doc[0].draw_rect(fitz.Rect(9, 17, 44, 26), fill=(1,1,1), color=None)
        doc.save(altered)
    with pytest.raises(CandidateRejected, match='difference'):
        raster_scan.validate(path, altered, exe, raster_scan.Budget(time.monotonic()+60))
    with fitz.open(bad) as doc:
        doc.new_page()
        doc.save(tmp_path / 'extra.pdf')
    with pytest.raises(CandidateRejected, match='document_mismatch'):
        raster_scan.validate(path, tmp_path / 'extra.pdf', exe, raster_scan.Budget(time.monotonic()+60))
    with pytest.raises(CandidateRejected, match='time_limit'):
        raster_scan.generate(path, tmp_path / 'expired.pdf', raster_scan.Budget(0))


def test_tool_failure_remains_error_and_source_unchanged(tmp_path):
    path = tmp_path / 'scan.pdf'
    scan(path)
    digest = sha256_file(path)
    cfg = config.default_config(input_dir=path)
    result = worker.process_one_file(discovery.snapshot(path, path), cfg, tmp_path / 'temp', tmp_path / 'missing-qpdf')
    assert result.status == ProcessStatus.ERROR
    assert result.error_message and sha256_file(path) == digest
    assert not list((tmp_path / 'temp').rglob('*.pdf'))


def test_single_file_unsafe_destinations_and_non_pdf(tmp_path):
    path = tmp_path / 'scan.pdf'
    scan(path)
    for out in (path, tmp_path):
        with pytest.raises(ValueError):
            discovery.validate_directories(path, out)
    wrong = tmp_path / 'text.txt'
    wrong.write_text('not PDF')
    assert cli.main(['run', '--input', str(wrong)]) == 1


def test_recipe_changes_invalidate_resume_hash(tmp_path, monkeypatch):
    cfg = config.default_config(input_dir=tmp_path)
    before = config.config_hash(cfg)
    monkeypatch.setitem(raster_scan.RECIPE, 'jpeg_quality', 85)
    assert config.config_hash(cfg) != before


def test_single_pdf_hardlink_output_rejected_before_processing(tmp_path, monkeypatch):
    import os
    path = tmp_path / 'scan.pdf'
    scan(path)
    cfg = config.default_config(input_dir=path)
    cfg.output_dir.mkdir(parents=True)
    os.link(path, cfg.output_dir / path.name)
    monkeypatch.setattr(runner, '_prepare_tools', lambda *a: pytest.fail('tools before path validation'))
    assert runner.run(cfg) == 1


def test_auto_scan_prefers_lossless_on_equal_size_and_hash_checked(tmp_path, monkeypatch):
    path = tmp_path / 'scan.pdf'
    scan(path)
    cfg = config.default_config(input_dir=path)
    result = worker.process_one_file(discovery.snapshot(path, path), cfg, tmp_path / 'temp', qpdf.ensure_qpdf())
    chosen_bytes = result.output_path.read_bytes()
    from pdf_shrink import text_optimize
    def copy_candidate(source, target, *args):
        target.write_bytes(chosen_bytes)
        return 0
    monkeypatch.setattr(text_optimize, 'generate', copy_candidate)
    monkeypatch.setattr(raster_scan, 'generate', copy_candidate)
    monkeypatch.setattr(raster_scan, 'validate', lambda *a, **kw: None)
    result = worker.process_one_file(discovery.snapshot(path, path), cfg, tmp_path / 'temp', qpdf.ensure_qpdf())
    assert result.status == ProcessStatus.ADOPTED_LOSSLESS
    assert [c.kind for c in result.candidate_details if c.selected] == ['lossless']
    assert result.images_changed == 0
