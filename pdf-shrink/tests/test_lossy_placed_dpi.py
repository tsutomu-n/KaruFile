from __future__ import annotations

from pathlib import Path

import pymupdf as fitz
import pytest

from dataclasses import replace

from pdf_shrink import config, discovery, inspect_pdf, qpdf, transform, worker
from pdf_shrink.models import OptimizationMode, ProcessStatus


def _max_effective_dpi(path: Path) -> float:
    document = fitz.open(path)
    try:
        return max(
            (
                inspect_pdf._effective_image_dpi(info)
                for page in document
                for info in inspect_pdf._page_image_infos(page)
            ),
            default=0.0,
        )
    finally:
        document.close()


def _write_jpeg_page(
    path: Path,
    *,
    page_size: float = 144,
    pixel_size: int,
    text: str | None = None,
) -> None:
    pixmap = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, pixel_size, pixel_size), 0)
    pixmap.clear_with(80)
    for offset in range(0, pixel_size, 17):
        pixmap.set_rect(fitz.IRect(offset, 0, offset + 3, pixel_size), (20,))
    jpeg = pixmap.tobytes("jpeg", jpg_quality=80)
    document = fitz.open()
    page = document.new_page(width=page_size, height=page_size)
    page.insert_image(page.rect, stream=jpeg)
    if text is not None:
        page.insert_text((8, 24), text, fontsize=8)
    document.save(path)
    document.close()


def test_text_only_pdf_stays_lossless(tmp_path: Path) -> None:
    path = tmp_path / "text.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "visible document text " * 8, fontsize=12)
    document.save(path)
    document.close()

    result = inspect_pdf.inspect_file(path, config.default_config().scan, safe=False)
    assert result.mode is OptimizationMode.LOSSLESS


def test_visible_text_with_600_dpi_image_is_lossy(tmp_path: Path) -> None:
    path = tmp_path / "text-and-photo.pdf"
    _write_jpeg_page(path, pixel_size=1200, text="visible body text " * 8)

    result = inspect_pdf.inspect_file(path, config.default_config().scan, safe=False)
    assert result.ok
    assert result.mode is OptimizationMode.LOSSY


def test_lossy_downsamples_placed_600_dpi_even_when_jfif_is_low(tmp_path: Path) -> None:
    source = tmp_path / "scan-jfif.pdf"
    candidate = tmp_path / "scan-jfif-out.pdf"
    _write_jpeg_page(source, pixel_size=1200)

    document = fitz.open(source)
    info = document[0].get_image_info()[0]
    jfif_dpi = min(float(info.get("xres") or 0), float(info.get("yres") or 0))
    document.close()
    assert jfif_dpi < 300
    assert _max_effective_dpi(source) == pytest.approx(600, rel=0.02)

    transform.optimize_lossy(source, candidate, config.LossyOptions())

    assert candidate.exists()
    assert _max_effective_dpi(candidate) == pytest.approx(300, rel=0.05)
    out = fitz.open(candidate)
    images = out[0].get_images(full=True)
    out.close()
    assert len(images) == 1
    image = images[0]
    assert image[2] == pytest.approx(600, rel=0.05)
    assert image[3] == pytest.approx(600, rel=0.05)


def test_lossy_keeps_vector_text(tmp_path: Path) -> None:
    source = tmp_path / "captioned.pdf"
    candidate = tmp_path / "captioned-out.pdf"
    text = "Caption text kept"
    _write_jpeg_page(source, pixel_size=1200, text=text)

    source_doc = fitz.open(source)
    source_text = source_doc[0].get_text()
    source_doc.close()
    assert text in source_text

    transform.optimize_lossy(source, candidate, config.LossyOptions())

    output = fitz.open(candidate)
    extracted = output[0].get_text()
    output.close()
    assert text in extracted
    assert extracted == source_text


def test_worker_adopts_lossy_600_dpi_jpeg(tmp_path: Path) -> None:
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    temp_root = tmp_path / "temp"
    input_dir.mkdir()
    temp_root.mkdir()
    source_path = input_dir / "scan.pdf"
    _write_jpeg_page(source_path, pixel_size=1200)

    cfg = replace(
        config.default_config(input_dir=input_dir, output_dir=output_dir),
        reduction=replace(
            config.ReductionOptions(),
            skip_below_bytes=1,
            lossy_min_bytes=1,
            lossy_min_percent=0.0,
        ),
    )
    source = discovery.snapshot(source_path, input_dir)
    result = worker.process_one_file(source, cfg, temp_root, qpdf.ensure_qpdf())

    assert result.status is ProcessStatus.ADOPTED_LOSSY
    assert result.error_message is None
    assert _max_effective_dpi(result.output_path) == pytest.approx(300, rel=0.05)


def test_lossy_does_not_upscale_72_dpi_image(tmp_path: Path) -> None:
    source = tmp_path / "low-dpi.pdf"
    candidate = tmp_path / "low-dpi-out.pdf"
    _write_jpeg_page(source, pixel_size=144)

    assert inspect_pdf.inspect_file(
        source, config.default_config().scan, safe=False
    ).mode is OptimizationMode.LOSSLESS
    transform.optimize_lossy(source, candidate, config.LossyOptions())
    assert _max_effective_dpi(candidate) == pytest.approx(72, rel=0.05)
