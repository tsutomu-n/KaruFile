from dataclasses import replace
import hashlib
import time

import pytest

from pdf_shrink import cli, config, font_replace, font_validate, worker
from test_font_replace import font_data, make_pdf
from test_font_integration import setup_case


def test_meiryo_cli_and_hash(tmp_path):
    args = cli.build_parser().parse_args(['run', '--input', str(tmp_path),
        '--font-replace-pattern', '*.pdf', '--font-family', 'meiryo'])
    cfg = config.build_config(args)
    assert cfg.replacement_font == 'Meiryo Regular'
    default_args = cli.build_parser().parse_args(['run', '--input', str(tmp_path),
        '--font-replace-pattern', '*.pdf'])
    default_cfg = config.build_config(default_args)
    assert default_cfg.font_family == 'meiryo'
    assert config.config_hash(default_cfg) == config.config_hash(cfg)
    assert config.config_hash(cfg) != config.config_hash(replace(cfg, font_family='yu-gothic'))
    for family in ('meiryo', 'yu-gothic'):
        args = cli.build_parser().parse_args(['run', '--input', str(tmp_path), '--font-family', family])
        with pytest.raises(ValueError, match='requires'):
            config.build_config(args)


def test_selected_file_must_contain_selected_family(tmp_path, monkeypatch):
    folder = tmp_path/'Fonts'
    folder.mkdir()
    monkeypatch.setenv('WINDIR', str(tmp_path))
    path = folder/'meiryo.ttc'
    path.write_bytes(font_data(family='Yu Gothic'))
    with pytest.raises(ValueError, match='selected family'):
        font_replace.prepare_font('meiryo')
    path.write_bytes(font_data(family='Meiryo'))
    assert font_replace.prepare_font('meiryo') == (path, hashlib.sha256(path.read_bytes()).hexdigest())
    assert font_replace.prepare_font() == font_replace.prepare_font('meiryo')


def test_meiryo_generation_and_independent_validation(tmp_path):
    source, target, font = (tmp_path/name for name in ('source.pdf', 'target.pdf', 'font.ttf'))
    make_pdf(source)
    font.write_bytes(font_data(family='Meiryo'))
    digest = hashlib.sha256(font.read_bytes()).hexdigest()
    font_replace.generate(source, target, font, digest, time.monotonic()+30)
    result = font_validate.validate_candidate(source, target, font_path=font,
        expected_font_sha256=digest, deadline=time.monotonic()+30)
    assert result.page_count == 1


@pytest.mark.parametrize('dry', [True, False])
def test_meiryo_request_recorded_even_when_preserved(tmp_path, monkeypatch, dry):
    source, cfg = setup_case(tmp_path)
    cfg = replace(cfg, font_family='meiryo', dry_run=dry)
    monkeypatch.setattr(font_replace, 'preflight', lambda *a: 'unsupported_font_encoding')
    result = worker.process_one_file(source, cfg, tmp_path/'temp', None)
    assert result.replacement_font == 'Meiryo Regular'
    assert result.replacement_font_sha256 == cfg.font_replace_sha256
