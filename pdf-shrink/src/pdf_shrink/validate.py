"""圧縮後PDFの検証。"""
from __future__ import annotations

import unicodedata
from pathlib import Path
import pymupdf as fitz  # PyMuPDF

from .qpdf import qpdf_check


def _page_count(path: Path) -> int:
    with fitz.open(path) as doc:
        return doc.page_count


def _extract_text(path: Path) -> list[str]:
    with fitz.open(path) as doc:
        return [unicodedata.normalize("NFC", page.get_text()) for page in doc]


def _render_page(page: fitz.Page) -> fitz.Pixmap:
    return page.get_pixmap(dpi=72, colorspace=fitz.csGRAY)


def _samples(pix: fitz.Pixmap) -> bytes:
    # グレースケールなら 1 チャンネル
    return pix.samples


def _compare_render(src: Path, dst: Path, threshold: float = 0.05) -> tuple[bool, float]:
    with fitz.open(src) as sdoc, fitz.open(dst) as ddoc:
        if sdoc.page_count != ddoc.page_count:
            return False, 1.0
        total_diff = 0.0
        total_pixels = 0
        for spage, dpage in zip(sdoc, ddoc):
            spix = _render_page(spage)
            dpix = _render_page(dpage)
            if spix.width != dpix.width or spix.height != dpix.height:
                return False, 1.0
            s_samples = _samples(spix)
            d_samples = _samples(dpix)
            if len(s_samples) != len(d_samples):
                return False, 1.0
            if not s_samples:
                continue
            for a, b in zip(s_samples, d_samples):
                total_diff += abs(a - b)
            total_pixels += len(s_samples)
        if total_pixels == 0:
            return True, 0.0
        mean_diff = total_diff / total_pixels / 255.0
        return mean_diff <= threshold, mean_diff


def validate(
    src: Path,
    dst: Path,
    qpdf_exe: Path,
) -> tuple[bool, str]:
    """
    圧縮候補を元PDFと比較して検証する。

    Returns:
        (ok, reason)
    """
    # 1. qpdf 構造検査
    rc = qpdf_check(qpdf_exe, dst)
    if rc == 2:
        return False, f"qpdf_check_error (rc={rc})"
    if rc == 3:
        return False, f"qpdf_check_warning (rc={rc})"
    if rc != 0:
        return False, f"qpdf_check_unexpected (rc={rc})"

    # 2. ページ数比較
    try:
        if _page_count(src) != _page_count(dst):
            return False, "page_count_mismatch"
    except Exception as exc:
        return False, f"page_count_error: {exc}"

    # 3. NFC テキスト比較
    try:
        src_text = _extract_text(src)
        dst_text = _extract_text(dst)
        if src_text != dst_text:
            return False, "text_mismatch"
    except Exception as exc:
        return False, f"text_compare_error: {exc}"

    # 4. 72 DPI グレースケール表示比較
    try:
        ok, diff = _compare_render(src, dst)
        if not ok:
            return False, f"render_diff_too_large (diff={diff:.4f})"
    except Exception as exc:
        return False, f"render_compare_error: {exc}"

    return True, ""
