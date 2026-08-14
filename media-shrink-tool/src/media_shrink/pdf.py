"""PDF 圧縮モジュール。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .utils import logger

PDF_EXTENSIONS = {".pdf"}


def _lossless_compress(src: Path, dst: Path, dry_run: bool) -> dict[str, Any]:
    import pikepdf

    if dry_run:
        return {"src": str(src), "dst": str(dst), "action": "dry-run", "mode": "pikepdf-lossless"}

    with pikepdf.open(src) as pdf:
        pdf.save(
            dst,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            compress_streams=True,
            linearize=True,
        )
    return {"src": str(src), "dst": str(dst), "action": "compressed", "mode": "pikepdf-lossless"}


def _lossy_compress(src: Path, dst: Path, cfg: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    import fitz  # PyMuPDF

    if dry_run:
        return {"src": str(src), "dst": str(dst), "action": "dry-run", "mode": "pymupdf-lossy"}

    doc = fitz.open(src)
    text_len = sum(len(page.get_text()) for page in doc)
    threshold = int(cfg.get("text_threshold", 100))
    dpi = int(cfg.get("dpi", 150))

    out_doc = fitz.open()
    if text_len < threshold:
        # 画像主体とみなし、低 DPI で再ラスタライズ
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        for page in doc:
            pix = page.get_pixmap(matrix=mat)
            new_page = out_doc.new_page(width=pix.width, height=pix.height)
            new_page.insert_image(new_page.rect, pixmap=pix)
    else:
        # テキスト主体はページをコピーして構造最適化のみ
        out_doc.insert_pdf(doc)

    out_doc.save(dst, garbage=4, deflate=True, clean=True)
    out_doc.close()
    doc.close()

    return {
        "src": str(src),
        "dst": str(dst),
        "action": "compressed",
        "mode": "pymupdf-lossy" if text_len < threshold else "pymupdf-optimize",
    }


def process_pdf(src: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    dry_run = cfg.get("dry_run", False)
    mode = cfg.get("mode", "lossless")

    temp = src.with_suffix(".compressed.pdf")
    final = src  # 置き換え前提

    try:
        if mode == "lossless":
            result = _lossless_compress(src, temp, dry_run)
        else:
            result = _lossy_compress(src, temp, cfg, dry_run)

        if dry_run:
            return result

        if not temp.exists() or temp.stat().st_size == 0:
            return {"src": str(src), "error": "output missing"}

        in_size = src.stat().st_size
        out_size = temp.stat().st_size

        if out_size < in_size:
            temp.replace(final)
            result["orig_size"] = in_size
            result["new_size"] = out_size
            result["kept"] = False
        else:
            temp.unlink()
            result["orig_size"] = in_size
            result["new_size"] = in_size
            result["kept"] = True
            result["dst"] = str(src)
        return result
    except Exception as exc:
        if temp.exists():
            temp.unlink(missing_ok=True)
        logger.error("PDF compression failed for %s: %s", src, exc)
        return {"src": str(src), "error": str(exc)}


def process_all(input_dir: Path, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    files = sorted(p for p in input_dir.rglob("*") if p.is_file() and p.suffix.lower() in PDF_EXTENSIONS)
    results: list[dict[str, Any]] = []
    for src in files:
        logger.info("Processing PDF: %s", src)
        results.append(process_pdf(src, cfg))
    return results
