import hashlib
import os
from pathlib import Path

import pytest
import shrink_all
from test_shrink_all import _write_pdf_report


@pytest.mark.parametrize('dry', [False, True])
def test_single_pdf_default_output_and_only_pdf_child(tmp_path, monkeypatch, dry):
    source = tmp_path / 'scan.PDF'
    source.write_bytes(b'%PDF-1.7\n' + b'a' * 1000)
    neighbor = tmp_path / 'unrelated.pdf'
    neighbor.write_bytes(b'not a PDF')
    seen = []
    output = tmp_path / 'scan_軽量化' / 'files'
    def run(name, project, args):
        seen.append(name)
        assert name == 'pdf-shrink'
        assert Path(args[args.index('--input')+1]) == source
        assert Path(args[args.index('--output')+1]) == output
        target = output / source.name
        data = b'%PDF-1.7\nsmaller'
        if not dry:
            target.write_bytes(data)
        row = {'source_path':str(source), 'source_size':source.stat().st_size,
               'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
               'output_path':str(target), 'output_size':None if dry else len(data),
               'output_sha256':'' if dry else hashlib.sha256(data).hexdigest(),
               'saved_bytes':0 if dry else source.stat().st_size-len(data),
               'saved_percent':0 if dry else 1-len(data)/source.stat().st_size,
               'status':'DRY_RUN_LOSSY' if dry else 'ADOPTED_LOSSY',
               'preset':'standard', 'profile':'standard', 'requested_policy':'standard',
               'classification':'raster_scan', 'permission_basis':'automatic_scan_raster',
               'preservation_reason':'', 'processing_schema':6}
        report = output.parent / ('report.dry-run.csv' if dry else 'report.csv')
        report.parent.mkdir(parents=True, exist_ok=True)
        _write_pdf_report(report, [row])
        return 0, [], 0.01
    monkeypatch.setattr(shrink_all, 'run_command', run)
    assert shrink_all.main(['-i',str(source)] + (['-n'] if dry else [])) == 0
    assert seen == ['pdf-shrink']
    assert neighbor.read_bytes() == b'not a PDF'
    if dry:
        assert not output.exists()


@pytest.mark.parametrize('kind', ['same', 'ancestor', 'hardlink', 'not_pdf'])
def test_single_pdf_unsafe_paths_rejected_before_child(tmp_path, monkeypatch, kind):
    source = tmp_path / ('a.txt' if kind == 'not_pdf' else 'a.pdf')
    source.write_bytes(b'%PDF-1.7\noriginal')
    output = tmp_path / 'out'
    if kind == 'same':
        output = source
    elif kind == 'ancestor':
        output = tmp_path
    elif kind == 'hardlink':
        output.mkdir()
        os.link(source, output / source.name)
    monkeypatch.setattr(shrink_all, 'run_command', lambda *a: pytest.fail('unsafe child'))
    assert shrink_all.main(['-i',str(source),'-o',str(output)]) == 1
    assert source.read_bytes() == b'%PDF-1.7\noriginal'


@pytest.mark.parametrize('mutation', [None, 'classification', 'basis', 'explicit'])
def test_auto_scan_report_binding(tmp_path, mutation):
    source = tmp_path / 'a.pdf'
    source.write_bytes(b'%PDF-1.7\n' + b'x' * 100)
    output = tmp_path / 'out'
    output.mkdir()
    target = output / source.name
    target.write_bytes(b'%PDF-1.7\ny')
    saved = source.stat().st_size-target.stat().st_size
    row={'source_path':str(source), 'source_size':source.stat().st_size,
         'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
         'output_path':str(target), 'output_size':target.stat().st_size,
         'output_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
         'saved_bytes':saved,'saved_percent':saved/source.stat().st_size,
         'status':'ADOPTED_LOSSY','preset':'standard','profile':'standard',
         'requested_policy':'standard','classification':'raster_scan',
         'permission_basis':'automatic_scan_raster','preservation_reason':'','processing_schema':6}
    if mutation == 'classification': row['classification'] = 'text'
    if mutation == 'basis': row['permission_basis'] = 'automatic_text_only'
    report = tmp_path / 'report.csv'
    _write_pdf_report(report,[row])
    parsed = shrink_all.parse_pdf_report(report)
    assert shrink_all.pdf_report_matches_inputs(parsed,[source],input_dir=source,output_dir=output,
        preset='standard',dry_run=False,preserve_patterns=['*'] if mutation=='explicit' else []) == (mutation is None)
