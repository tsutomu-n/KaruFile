"""圧縮後PDFの検証。"""
from __future__ import annotations

import unicodedata
from pathlib import Path
import pymupdf as fitz  # PyMuPDF

from .qpdf import qpdf_check


_GLOBAL_RENDER_DIFF_THRESHOLD = 0.05
_LOCAL_RENDER_DIFF_THRESHOLD = 0.20
_RENDER_TILE_SIZE = 32


def _page_count(path: Path) -> int:
    with fitz.open(path) as doc:
        return doc.page_count


def _extract_text(path: Path) -> list[str]:
    with fitz.open(path) as doc:
        return [unicodedata.normalize("NFC", page.get_text()) for page in doc]


def _render_page(page: fitz.Page, *, enhanced: bool) -> fitz.Pixmap:
    colorspace = fitz.csRGB if enhanced else fitz.csGRAY
    return page.get_pixmap(dpi=72, colorspace=colorspace)


def _samples(pix: fitz.Pixmap) -> bytes:
    return pix.samples


def _tile_ranges(length: int, maximum_size: int) -> list[tuple[int, int]]:
    """端に極端に小さいタイルを作らず、指定サイズ以下に均等分割する。"""
    if length <= 0:
        return []
    if maximum_size < 1:
        raise ValueError("tile size must be at least 1")
    count = (length + maximum_size - 1) // maximum_size
    base, extra = divmod(length, count)
    ranges: list[tuple[int, int]] = []
    start = 0
    for index in range(count):
        stop = start + base + (1 if index < extra else 0)
        ranges.append((start, stop))
        start = stop
    return ranges


def _compare_render(
    src: Path,
    dst: Path,
    *,
    global_threshold: float = _GLOBAL_RENDER_DIFF_THRESHOLD,
    local_threshold: float = _LOCAL_RENDER_DIFF_THRESHOLD,
    tile_size: int = _RENDER_TILE_SIZE,
    enhanced: bool = False,
) -> tuple[bool, float, float]:
    with fitz.open(src) as sdoc, fitz.open(dst) as ddoc:
        if sdoc.page_count != ddoc.page_count:
            return False, 1.0, 1.0
        total_diff = 0.0
        total_pixels = 0
        max_tile_diff = 0.0
        for spage, dpage in zip(sdoc, ddoc):
            spix = _render_page(spage, enhanced=enhanced)
            dpix = _render_page(dpage, enhanced=enhanced)
            if spix.width != dpix.width or spix.height != dpix.height:
                return False, 1.0, 1.0
            s_samples = memoryview(_samples(spix))
            d_samples = memoryview(_samples(dpix))
            channels = spix.n - spix.alpha
            if (
                len(s_samples) != len(d_samples)
                or spix.stride != dpix.stride
                or channels != dpix.n - dpix.alpha
                or channels <= 0
            ):
                return False, 1.0, 1.0
            if not s_samples:
                continue
            if not enhanced:
                total_diff += sum(
                    abs(a - b) for a, b in zip(s_samples, d_samples)
                )
                total_pixels += len(s_samples)
                continue
            y_ranges = _tile_ranges(spix.height, tile_size)
            x_ranges = _tile_ranges(spix.width, tile_size)
            for tile_y, tile_y_stop in y_ranges:
                tile_height = tile_y_stop - tile_y
                for tile_x, tile_x_stop in x_ranges:
                    tile_width = tile_x_stop - tile_x
                    tile_diff = 0
                    for y in range(tile_y, tile_y_stop):
                        start = y * spix.stride + tile_x * channels
                        stop = y * spix.stride + tile_x_stop * channels
                        tile_diff += sum(
                            abs(a - b)
                            for a, b in zip(
                                s_samples[start:stop],
                                d_samples[start:stop],
                            )
                        )
                    tile_pixels = tile_width * tile_height * channels
                    total_diff += tile_diff
                    total_pixels += tile_pixels
                    max_tile_diff = max(
                        max_tile_diff,
                        tile_diff / tile_pixels / 255.0,
                    )
        if total_pixels == 0:
            return True, 0.0, 0.0
        mean_diff = total_diff / total_pixels / 255.0
        return (
            mean_diff <= global_threshold
            and (not enhanced or max_tile_diff <= local_threshold),
            mean_diff,
            max_tile_diff,
        )


def validate(
    src: Path,
    dst: Path,
    qpdf_exe: Path,
    *,
    enhanced: bool = False,
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

    # 4. standardは従来の全体平均、compactはRGBと局所タイルも比較
    try:
        ok, mean_diff, max_tile_diff = _compare_render(
            src,
            dst,
            enhanced=enhanced,
        )
        if mean_diff > _GLOBAL_RENDER_DIFF_THRESHOLD:
            return False, f"render_diff_too_large (diff={mean_diff:.4f})"
        if enhanced and max_tile_diff > _LOCAL_RENDER_DIFF_THRESHOLD:
            return False, (
                "render_local_diff_too_large "
                f"(diff={max_tile_diff:.4f}, tile={_RENDER_TILE_SIZE})"
            )
        if not ok:
            return False, "render_compare_failed"
    except Exception as exc:
        return False, f"render_compare_error: {exc}"

    return True, ""
