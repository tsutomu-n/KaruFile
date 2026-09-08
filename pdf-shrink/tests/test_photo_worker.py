"""Candidate choices, real failure paths, and explicit photo selection."""
from dataclasses import replace
from pathlib import Path

import pytest

from pdf_shrink import cli, config, discovery, worker
from pdf_shrink.models import InspectionResult, OptimizationMode, ProcessStatus


def _case(tmp_path, monkeypatch, *, photo=True):
    source_dir = tmp_path / "input"
    source_dir.mkdir()
    path = source_dir / "photo.pdf"
    path.write_bytes(b"S" * 500_000)
    # This unit isolates legacy candidate arbitration; policy is tested using
    # real PDFs in test_protection_text, independently of synthetic byte sizes.
    from pdf_shrink.policy import Decision
    monkeypatch.setattr(worker.policy, "classify", lambda *a: Decision("photo", "explicit_photo"))
    cfg = config.default_config(
        input_dir=source_dir, output_dir=tmp_path / "output",
        photo_patterns=("photo.pdf",) if photo else (),
    )
    monkeypatch.setattr(worker, "inspect_file", lambda *a, **k: InspectionResult(
        True, None, 1, 0.0, OptimizationMode.LOSSY,
    ))

    def lossy(src, dst, options):
        assert src == path
        dst.write_bytes(b"J" * 350_000)
        return 2

    def lossless(src, dst, exe, options):
        assert src == path  # Always start with the original, never a JPEG candidate.
        dst.write_bytes(b"L" * 400_000)

    monkeypatch.setattr(worker.transform, "optimize_lossy", lossy)
    monkeypatch.setattr(worker.transform, "optimize_lossless", lossless)
    monkeypatch.setattr(worker.validate, "validate", lambda *a, **k: (True, ""))
    return discovery.snapshot(path, source_dir), cfg


def test_photo_selection_is_explicit_normalized_and_hashed(tmp_path):
    args = cli.build_parser().parse_args([
        "run", "--input", str(tmp_path), "--photo-pattern", r".\Photos\*.PDF",
    ])
    cfg = config.build_config(args)
    assert config.profile_for_path(cfg, Path("photos/a.pdf")) == "photo"
    assert config.profile_for_path(cfg, Path("report.pdf")) == "standard"
    selected = config.config_for_path(cfg, Path("photos/a.pdf"))
    assert selected.lossy.photo_mode and selected.lossy.dpi_target == 200
    assert cfg.lossy.dpi_target == 300
    assert config.config_hash(cfg) != config.config_hash(replace(cfg, photo_patterns=()))
    with pytest.raises(ValueError, match="safe"):
        replace(cfg, safe=True)
    for pattern in ("", "../*.pdf", "C:/data/*.pdf", "/data/*.pdf", "."):
        with pytest.raises(ValueError):
            replace(cfg, photo_patterns=(pattern,))


def test_photo_compares_original_based_candidates_and_uses_smaller_valid_one(tmp_path, monkeypatch):
    source, cfg = _case(tmp_path, monkeypatch)
    calls = []

    def validate(src, dst, exe, **kwargs):
        calls.append(kwargs)
        return True, ""

    monkeypatch.setattr(worker.validate, "validate", validate)
    result = worker.process_one_file(source, cfg, tmp_path / "temp", Path("qpdf"))
    assert result.status is ProcessStatus.ADOPTED_LOSSY
    assert result.profile == "photo"
    assert result.photo_dpi == 200
    assert result.candidate_size == 350_000 and result.candidate_saved_bytes == 150_000
    assert result.images_changed == 2
    assert [c.selected for c in result.candidate_details] == [True, False]
    assert all(c["detail"] for c in calls)
    assert result.output_path.read_bytes() == b"J" * 350_000
    assert source.path.read_bytes() == b"S" * 500_000
    assert not list((tmp_path / "temp").glob("*.pdf"))


def test_visual_rejection_falls_back_without_hiding_candidate_reason(tmp_path, monkeypatch):
    source, cfg = _case(tmp_path, monkeypatch)
    monkeypatch.setattr(worker.validate, "validate", lambda src, dst, exe, **k:
        (False, "render_detail_local_diff_too_large (diff=0.30)")
        if dst.read_bytes().startswith(b"J") else (True, ""))
    result = worker.process_one_file(source, cfg, tmp_path / "temp", Path("qpdf"))
    assert result.status is ProcessStatus.ADOPTED_LOSSLESS
    assert result.mode is OptimizationMode.LOSSLESS
    assert result.decision_reason == "fallback_lossless"
    assert result.photo_dpi == 200
    assert result.candidate_details[0].reason == "quality_rejected"
    assert result.candidate_details[1].selected
    assert result.candidate_size == 350_000  # Primary attempt, not adopted size.
    assert result.output_size == 400_000


def test_small_document_standard_adopts_20k_lossless_gain_but_rejects_lossy_gain(tmp_path, monkeypatch):
    source, cfg = _case(tmp_path, monkeypatch, photo=False)
    monkeypatch.setattr(worker.transform, "optimize_lossless", lambda src, dst, *a:
        dst.write_bytes(b"L" * 480_000))
    result = worker.process_one_file(source, cfg, tmp_path / "temp", Path("qpdf"))
    assert result.status is ProcessStatus.ADOPTED_LOSSLESS
    assert result.photo_dpi is None
    assert result.decision_reason == "fallback_lossless"
    assert result.candidate_details[0].reason == "reduction_below_threshold"
    assert result.candidate_saved_percent == .3
    assert result.saved_bytes == 20_000
    assert result.output_path.read_bytes() == b"L" * 480_000


@pytest.mark.parametrize("failure", ["text_mismatch", "qpdf_check_error (rc=2)", "render_detail_compare_error: failed"])
def test_real_candidate_failure_remains_error_with_recovery_copy(tmp_path, monkeypatch, failure):
    source, cfg = _case(tmp_path, monkeypatch)
    monkeypatch.setattr(worker.validate, "validate", lambda *a, **k: (False, failure))
    result = worker.process_one_file(source, cfg, tmp_path / "temp", Path("qpdf"))
    assert result.status is ProcessStatus.ERROR
    assert result.photo_dpi == 200
    assert failure in result.error_message
    assert result.candidate_details[0].reason == "processing_error"
    assert result.output_path.read_bytes() == source.path.read_bytes()


def test_photo_inspection_failure_is_error_not_unsupported_skip(tmp_path, monkeypatch):
    source, cfg = _case(tmp_path, monkeypatch)
    monkeypatch.setattr(worker, "inspect_file", lambda *a, **k: InspectionResult(
        False, "inspect_error: cannot read placements", 1, 0.0, None,
    ))
    result = worker.process_one_file(source, cfg, tmp_path / "temp", None)
    assert result.status is ProcessStatus.ERROR
    assert result.photo_dpi == 200
    assert result.decision_reason == "processing_error"
    assert "placements" in result.error_message
    assert result.output_path.read_bytes() == source.path.read_bytes()


@pytest.mark.parametrize("dpi", [150, 180, 300])
@pytest.mark.parametrize("dry_run", [False, True])
def test_requested_photo_dpi_reaches_transform_and_all_result_paths(tmp_path, monkeypatch, dpi, dry_run):
    source, cfg = _case(tmp_path, monkeypatch)
    cfg = replace(cfg, photo_dpi=dpi, dry_run=dry_run)
    called = []

    def lossy(src, dst, options):
        called.append(options.dpi_target)
        assert options.quality == 80
        dst.write_bytes(b"J" * 350_000)
        return 2

    monkeypatch.setattr(worker.transform, "optimize_lossy", lossy)
    result = worker.process_one_file(source, cfg, tmp_path / "temp", None if dry_run else Path("qpdf"))
    assert result.photo_dpi == dpi
    assert called == ([] if dry_run else [dpi])
    assert result.status is (ProcessStatus.DRY_RUN_LOSSY if dry_run else ProcessStatus.ADOPTED_LOSSY)
    if dry_run:
        assert result.output_size is None and not result.output_path.exists()
