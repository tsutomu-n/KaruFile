"""圧縮後PDFの検証。"""
from __future__ import annotations

import hashlib
import math
import time
import unicodedata
from pathlib import Path
import pymupdf as fitz  # PyMuPDF

from .qpdf import qpdf_check


_GLOBAL_RENDER_DIFF_THRESHOLD = 0.05
_LOCAL_RENDER_DIFF_THRESHOLD = 0.20
_RENDER_TILE_SIZE = 32
_DETAIL_RENDER_DPI = 300
_DETAIL_RENDER_TILE_SIZE = 256
_DETAIL_RENDER_MAX_PIXELS = 80_000_000
_DETAIL_RENDER_MAX_SECONDS = 120.0
_DETAIL_RENDER_MAX_REGIONS = 10_000


def _page_count(path: Path) -> int:
    with fitz.open(path) as doc:
        return doc.page_count


def _extract_text(path: Path) -> list[str]:
    with fitz.open(path) as doc:
        return [unicodedata.normalize("NFC", page.get_text()) for page in doc]


def _same_geometry(src: Path, dst: Path) -> bool:
    with fitz.open(src) as sdoc, fitz.open(dst) as ddoc:
        return all(
            spage.rotation == dpage.rotation
            and spage.mediabox == dpage.mediabox
            and spage.cropbox == dpage.cropbox
            and spage.rect == dpage.rect
            for spage, dpage in zip(sdoc, ddoc)
        )


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


def _image_fingerprint(
    doc: fitz.Document,
    info: dict,
    cache: dict[int, bytes],
) -> tuple[int, int, bytes]:
    xref = int(info.get("xref") or 0)
    if xref > 0:
        if xref not in cache:
            cache[xref] = hashlib.sha256(doc.xref_stream_raw(xref) or b"").digest()
        digest = cache[xref]
    else:
        digest = bytes(info.get("digest") or b"")
    return int(info["width"]), int(info["height"]), digest


def _same_image_placement(source: dict, candidate: dict) -> bool:
    for field in ("bbox", "transform"):
        left, right = source[field], candidate[field]
        if len(left) != len(right) or any(
            not math.isfinite(float(a)) or not math.isfinite(float(b))
            or abs(float(a) - float(b)) > 0.01
            for a, b in zip(left, right)
        ):
            return False
    return True


def _compare_render_detail(src: Path, dst: Path) -> tuple[bool, str]:
    """Compare changed placements at 300 DPI without a full-page high-DPI bitmap.

    Match paint-order placements and their geometry, not xref numbers: saving
    with garbage collection can renumber image objects. The comparison covers
    every tile of each changed placement and uses the existing RGB thresholds.
    This is a visual-difference guard, not an OCR/readability guarantee.
    """
    deadline = time.monotonic() + _DETAIL_RENDER_MAX_SECONDS
    pixel_count = 0
    region_count = 0
    difference = 0
    sample_count = 0
    scale = _DETAIL_RENDER_DPI / 72
    with fitz.open(src) as sdoc, fitz.open(dst) as ddoc:
        source_fingerprints: dict[int, bytes] = {}
        candidate_fingerprints: dict[int, bytes] = {}
        for spage, dpage in zip(sdoc, ddoc):
            if time.monotonic() > deadline:
                return False, "render_detail_time_limit"
            source_images = spage.get_image_info(xrefs=True)
            candidate_images = dpage.get_image_info(xrefs=True)
            if len(source_images) != len(candidate_images):
                return False, "render_detail_placement_count_mismatch"
            for source_image, candidate_image in zip(source_images, candidate_images):
                if not _same_image_placement(source_image, candidate_image):
                    return False, "render_detail_placement_mismatch"
                if _image_fingerprint(sdoc, source_image, source_fingerprints) == (
                    _image_fingerprint(ddoc, candidate_image, candidate_fingerprints)
                ):
                    continue
                region_count += 1
                if region_count > _DETAIL_RENDER_MAX_REGIONS:
                    return False, "render_detail_region_limit"
                region = fitz.Rect(source_image["bbox"]) * spage.rotation_matrix
                region = region & spage.rect
                if region.is_empty:
                    continue
                x0, y0 = math.floor(region.x0 * scale), math.floor(region.y0 * scale)
                x1, y1 = math.ceil(region.x1 * scale), math.ceil(region.y1 * scale)
                pixel_count += (x1 - x0) * (y1 - y0)
                if pixel_count > _DETAIL_RENDER_MAX_PIXELS:
                    return False, "render_detail_pixel_limit"
                for y in range(y0, y1, _DETAIL_RENDER_TILE_SIZE):
                    for x in range(x0, x1, _DETAIL_RENDER_TILE_SIZE):
                        if time.monotonic() > deadline:
                            return False, "render_detail_time_limit"
                        clip = fitz.Rect(
                            x / scale, y / scale,
                            min(x + _DETAIL_RENDER_TILE_SIZE, x1) / scale,
                            min(y + _DETAIL_RENDER_TILE_SIZE, y1) / scale,
                        ) & spage.rect
                        spix = spage.get_pixmap(
                            dpi=_DETAIL_RENDER_DPI, colorspace=fitz.csRGB,
                            alpha=False, clip=clip,
                        )
                        dpix = dpage.get_pixmap(
                            dpi=_DETAIL_RENDER_DPI, colorspace=fitz.csRGB,
                            alpha=False, clip=clip,
                        )
                        if (
                            spix.width != dpix.width or spix.height != dpix.height
                            or spix.n != 3 or dpix.n != 3
                            or spix.stride != dpix.stride
                            or max(spix.width, spix.height) > _DETAIL_RENDER_TILE_SIZE + 2
                        ):
                            return False, "render_detail_compare_failed"
                        ss, ds = memoryview(spix.samples), memoryview(dpix.samples)
                        if len(ss) != len(ds):
                            return False, "render_detail_compare_failed"
                        for ly, ly_stop in _tile_ranges(spix.height, _RENDER_TILE_SIZE):
                            for lx, lx_stop in _tile_ranges(spix.width, _RENDER_TILE_SIZE):
                                local_diff = 0
                                for row in range(ly, ly_stop):
                                    start = row * spix.stride + lx * 3
                                    stop = row * spix.stride + lx_stop * 3
                                    local_diff += sum(
                                        abs(a - b) for a, b in zip(ss[start:stop], ds[start:stop])
                                    )
                                count = (ly_stop - ly) * (lx_stop - lx) * 3
                                difference += local_diff
                                sample_count += count
                                local_mean = local_diff / count / 255
                                if local_mean > _LOCAL_RENDER_DIFF_THRESHOLD:
                                    return False, (
                                        "render_detail_local_diff_too_large "
                                        f"(diff={local_mean:.4f}, dpi={_DETAIL_RENDER_DPI}, "
                                        f"tile={_RENDER_TILE_SIZE})"
                                    )
    if time.monotonic() > deadline:
        return False, "render_detail_time_limit"
    mean = difference / sample_count / 255 if sample_count else 0.0
    if mean > _GLOBAL_RENDER_DIFF_THRESHOLD:
        return False, f"render_detail_diff_too_large (diff={mean:.4f})"
    return True, ""


def validate(
    src: Path,
    dst: Path,
    qpdf_exe: Path,
    *,
    enhanced: bool = False,
    detail: bool = False,
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
    if detail:
        try:
            if not _same_geometry(src, dst):
                return False, "page_geometry_mismatch"
        except Exception as exc:
            return False, f"page_geometry_error: {exc}"

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
            enhanced=enhanced or detail,
        )
        if mean_diff > _GLOBAL_RENDER_DIFF_THRESHOLD:
            return False, f"render_diff_too_large (diff={mean_diff:.4f})"
        if (enhanced or detail) and max_tile_diff > _LOCAL_RENDER_DIFF_THRESHOLD:
            return False, (
                "render_local_diff_too_large "
                f"(diff={max_tile_diff:.4f}, tile={_RENDER_TILE_SIZE})"
            )
        if not ok:
            return False, "render_compare_failed"
    except Exception as exc:
        return False, f"render_compare_error: {exc}"

    if detail:
        try:
            return _compare_render_detail(src, dst)
        except Exception as exc:
            return False, f"render_detail_compare_error: {exc}"

    return True, ""
