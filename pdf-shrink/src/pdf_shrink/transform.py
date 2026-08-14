"""PDF圧縮候補の生成。出力先への採用は ``output`` が担当する。"""
from __future__ import annotations

from pathlib import Path

import pymupdf as fitz  # PyMuPDF

from .config import LossyOptions, QpdfOptions
from .qpdf import qpdf_optimize
from .utils import ensure_dir


def optimize_lossless(
    source: Path,
    candidate: Path,
    qpdf_exe: Path,
    options: QpdfOptions,
) -> None:
    """qpdfで可逆圧縮候補を生成する。"""
    ensure_dir(candidate.parent)
    qpdf_optimize(qpdf_exe, source, candidate, options)


def optimize_lossy(
    source: Path,
    candidate: Path,
    options: LossyOptions,
) -> None:
    """PyMuPDFで画像縮小済みの非可逆圧縮候補を生成する。"""
    ensure_dir(candidate.parent)
    doc = fitz.open(source)
    try:
        doc.rewrite_images(
            dpi_threshold=options.dpi_threshold,
            dpi_target=options.dpi_target,
            quality=options.quality,
            lossy=options.lossy,
            lossless=options.lossless,
            bitonal=options.bitonal,
            color=options.color,
            gray=options.gray,
            set_to_gray=options.set_to_gray,
        )
        doc.save(
            candidate,
            garbage=4,
            deflate=True,
            use_objstms=1,
            raise_on_repair=True,
        )
    finally:
        doc.close()
