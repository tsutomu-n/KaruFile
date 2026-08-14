"""テスト用PDFフィクスチャ。"""
from __future__ import annotations

from pathlib import Path

import pymupdf as fitz
import pytest


def _make_text_pdf(path: Path, text: str = "Hello world\n") -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=12)
    doc.save(str(path))
    doc.close()


def _make_scan_pdf(path: Path) -> None:
    """小さなページを高DPIでレンダリングし、画像主体PDFを作る。"""
    source = fitz.open()
    page = source.new_page(width=144, height=144)
    page.insert_text((10, 20), "Scan sample text " * 100, fontsize=8)
    pixmap = page.get_pixmap(dpi=600, colorspace=fitz.csRGB)
    document = fitz.open()
    output_page = document.new_page(width=144, height=144)
    output_page.insert_image(output_page.rect, pixmap=pixmap)
    document.save(str(path))
    document.close()
    source.close()


@pytest.fixture
def sample_pdfs(tmp_path: Path) -> dict[str, Path]:
    pdf_dir = tmp_path / "PDF"
    pdf_dir.mkdir()

    text_pdf = pdf_dir / "text.pdf"
    _make_text_pdf(text_pdf, "これは通常PDFのテストです。\n" * 50)

    small_pdf = pdf_dir / "small.pdf"
    _make_text_pdf(small_pdf, "x")

    scan_pdf = pdf_dir / "scan.pdf"
    _make_scan_pdf(scan_pdf)

    return {"text": text_pdf, "small": small_pdf, "scan": scan_pdf}
