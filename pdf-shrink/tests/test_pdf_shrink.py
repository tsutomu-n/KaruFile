"""pdf-shrink の基本テスト。"""
from __future__ import annotations

from pathlib import Path

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


def test_transform_copy_original(tmp_path: Path, sample_pdfs: dict[str, Path]) -> None:
    dst = tmp_path / "out" / "text_copy.pdf"
    output.copy_original(sample_pdfs["text"], dst)
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
