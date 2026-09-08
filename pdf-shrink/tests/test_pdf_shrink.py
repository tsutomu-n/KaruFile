"""pdf-shrink の基本テスト。"""
from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

from pdf_shrink import cli, config, discovery, inspect_pdf, output, qpdf, validate
from pdf_shrink.models import ProcessStatus
from pdf_shrink.utils import sha256_file

def test_qpdf_ensure_and_version(tmp_path: Path) -> None:
    exe = qpdf.ensure_qpdf()
    assert exe.exists()
    version = qpdf.qpdf_version(exe)
    assert "qpdf" in version.lower()


def test_inspect_text_pdf(sample_pdfs: dict[str, Path]) -> None:
    cfg = config.default_config()
    info = inspect_pdf.inspect_file(sample_pdfs["text"], cfg.scan, safe=cfg.safe)
    assert info.ok
    assert info.mode == "lossless"


def test_inspect_scan_pdf(sample_pdfs: dict[str, Path]) -> None:
    cfg = config.default_config()
    info = inspect_pdf.inspect_file(sample_pdfs["scan"], cfg.scan, safe=cfg.safe)
    assert info.ok
    assert info.mode == "lossy"


def test_validate_identical_pdf(sample_pdfs: dict[str, Path]) -> None:
    exe = qpdf.ensure_qpdf()
    ok, reason = validate.validate(sample_pdfs["text"], sample_pdfs["text"], exe)
    assert ok, reason


def test_validate_rejects_local_loss_hidden_by_global_average(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.pdf"
    candidate = tmp_path / "candidate.pdf"
    for path, include_patch in ((source, True), (candidate, False)):
        document = fitz.open()
        page = document.new_page(width=256, height=256)
        if include_patch:
            page.draw_rect(
                fitz.Rect(64, 64, 84, 84),
                color=(0, 0, 0),
                fill=(0, 0, 0),
            )
        document.save(path)
        document.close()
    monkeypatch.setattr(validate, "qpdf_check", lambda *_args: 0)

    ok, mean_diff, max_tile_diff = validate._compare_render(
        source,
        candidate,
        enhanced=True,
    )
    assert mean_diff < validate._GLOBAL_RENDER_DIFF_THRESHOLD
    assert max_tile_diff > validate._LOCAL_RENDER_DIFF_THRESHOLD
    assert not ok

    valid, reason = validate.validate(
        source,
        candidate,
        tmp_path / "qpdf.exe",
        enhanced=True,
    )
    assert not valid
    assert reason.startswith("render_local_diff_too_large")


def test_validate_rejects_chromatic_change_with_similar_grayscale(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source-color.pdf"
    candidate = tmp_path / "candidate-color.pdf"
    colors = ((222 / 255, 98 / 255, 33 / 255), (33 / 255, 157 / 255, 220 / 255))
    for path, color in zip((source, candidate), colors):
        document = fitz.open()
        page = document.new_page(width=128, height=128)
        page.draw_rect(page.rect, color=color, fill=color)
        document.save(path)
        document.close()
    monkeypatch.setattr(validate, "qpdf_check", lambda *_args: 0)

    valid, reason = validate.validate(
        source,
        candidate,
        tmp_path / "qpdf.exe",
        enhanced=True,
    )

    assert not valid
    assert reason.startswith("render_diff_too_large")


def test_transform_copy_original(tmp_path: Path, sample_pdfs: dict[str, Path]) -> None:
    dst = tmp_path / "out" / "text_copy.pdf"
    output.copy_original(
        discovery.snapshot(sample_pdfs["text"], tmp_path / "PDF"),
        dst,
        input_root=tmp_path / "PDF",
        output_root=tmp_path / "out",
    )
    assert dst.exists()
    assert sha256_file(sample_pdfs["text"]) == sha256_file(dst)


def test_worker_processes_files(tmp_path: Path, sample_pdfs: dict[str, Path]) -> None:
    input_dir = tmp_path / "PDF"
    output_dir = tmp_path / "PDF_軽量化"
    temp_root = tmp_path / ".pdf-shrink" / "temp"
    temp_root.mkdir(parents=True)
    cfg = config.default_config(input_dir=input_dir, output_dir=output_dir)
    exe = qpdf.ensure_qpdf()

    from pdf_shrink import worker

    results = []
    for src in sorted(input_dir.iterdir()):
        if src.suffix.lower() == ".pdf":
            source = discovery.snapshot(src, input_dir)
            results.append(worker.process_one_file(source, cfg, temp_root, exe))

    statuses = {result.status for result in results}
    assert statuses
    # 少なくとも小ファイルはスキップされる
    assert ProcessStatus.SKIPPED_SMALL in statuses
    # 出力ミラーが存在する
    for result in results:
        assert result.output_path.exists()


def test_cli_dry_run(tmp_path: Path, sample_pdfs: dict[str, Path]) -> None:
    input_dir = tmp_path / "PDF"
    output_dir = tmp_path / "PDF_軽量化"
    rc = cli.main([
        "run", "--input", str(input_dir),
        "--output", str(output_dir),
        "--dry-run", "--limit", "10",
    ])
    assert rc == 0


def test_cli_smoke(tmp_path: Path, sample_pdfs: dict[str, Path]) -> None:
    input_dir = tmp_path / "PDF"
    output_dir = tmp_path / "PDF_軽量化"
    rc = cli.main([
        "run", "--input", str(input_dir),
        "--output", str(output_dir),
        "--workers", "1", "--limit", "10",
    ])
    assert rc == 0
    # レポートが作られる
    report = tmp_path / "report.csv"
    assert report.exists()
