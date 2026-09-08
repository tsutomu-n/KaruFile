"""PDF圧縮候補の生成。出力先への採用は ``output`` が担当する。"""
from __future__ import annotations

import math
from pathlib import Path

import pymupdf as fitz  # PyMuPDF

from .config import LossyOptions, QpdfOptions
from .inspect_pdf import (
    _effective_image_dpis,
    _is_dct_jpeg,
    _page_image_infos,
    _photo_candidate_dimensions,
    _photo_xref_min_effective_dpis,
    _should_rewrite_image,
)
from .qpdf import qpdf_optimize
from .utils import ensure_dir, logger


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
) -> int:
    """配置画像をプリセットに従って縮小または再圧縮した候補を生成する。"""
    ensure_dir(candidate.parent)
    doc = fitz.open(source)
    try:
        changed_images = _rewrite_pdf_images(doc, options)
        doc.save(
            candidate,
            garbage=4,
            deflate=True,
            use_objstms=1,
            raise_on_repair=True,
        )
        return changed_images
    finally:
        doc.close()


def _rewrite_pdf_images(doc: fitz.Document, options: LossyOptions) -> int:
    if options.dpi_target <= 0:
        return 0

    dpis_by_xref = (
        _photo_xref_min_effective_dpis(doc) if options.photo_mode
        else _xref_max_effective_dpis(doc)
    )
    replaced: set[int] = set()
    for page in doc:
        images = {int(img[0]): img for img in page.get_images(full=True)}
        for xref, img in images.items():
            if xref in replaced or xref <= 0:
                continue
            dpi_x, dpi_y = dpis_by_xref.get(xref, (0.0, 0.0))
            if dpi_x <= 0 or dpi_y <= 0:
                continue
            if options.photo_mode:
                dimensions = _photo_candidate_dimensions(
                    doc, img, (dpi_x, dpi_y), options,
                )
                if dimensions is None:
                    continue
                new_width, new_height = dimensions
                jpeg, channels = _jpeg_bytes_for_xref(
                    doc, xref, new_width, new_height, options.quality,
                )
                _put_jpeg_in_xref(doc, xref, jpeg, new_width, new_height, channels)
                replaced.add(xref)
                continue
            should_downsample = (
                dpi_x > options.dpi_target or dpi_y > options.dpi_target
            )
            should_recompress = (
                options.recompress_existing_jpeg and _is_dct_jpeg(img)
            )
            if not should_downsample and not should_recompress:
                continue
            if not _should_rewrite_image(img, options):
                continue
            width = int(img[2])
            height = int(img[3])
            if should_downsample:
                new_width = _dimension_at_target_dpi(
                    width, dpi_x, options.dpi_target
                )
                new_height = _dimension_at_target_dpi(
                    height, dpi_y, options.dpi_target
                )
                if new_width >= width and new_height >= height:
                    continue
            elif should_recompress:
                new_width = width
                new_height = height
            else:
                continue
            jpeg, channels = _jpeg_bytes_for_xref(
                doc, xref, new_width, new_height, options.quality
            )
            if should_recompress and not should_downsample:
                original_stream = doc.xref_stream_raw(xref)
                if not original_stream:
                    continue
                saved_percent = 1 - len(jpeg) / len(original_stream)
                if saved_percent < options.jpeg_recompress_min_percent:
                    logger.debug(
                        "Kept PDF JPEG xref %d because recompression saved only %.2f%%",
                        xref,
                        saved_percent * 100,
                    )
                    continue
            _put_jpeg_in_xref(doc, xref, jpeg, new_width, new_height, channels)
            replaced.add(xref)
    if replaced:
        logger.info(
            "Re-encoded %d PDF image(s) with a %s DPI candidate target",
            len(replaced),
            options.dpi_target,
        )
    return len(replaced)


def _dimension_at_target_dpi(dimension: int, dpi: float, target: int) -> int:
    """Scale one pixel axis down without rounding above the DPI target."""
    if dpi <= target:
        return dimension
    return max(1, min(dimension, math.floor(dimension * target / dpi)))


def _xref_max_effective_dpis(
    doc: fitz.Document,
) -> dict[int, tuple[float, float]]:
    max_dpis_by_xref: dict[int, tuple[float, float]] = {}
    for page in doc:
        for info in _page_image_infos(page):
            xref = int(info.get("xref") or 0)
            if xref <= 0:
                continue
            dpi_x, dpi_y = _effective_image_dpis(info)
            previous_x, previous_y = max_dpis_by_xref.get(xref, (0.0, 0.0))
            max_dpis_by_xref[xref] = (
                max(previous_x, dpi_x),
                max(previous_y, dpi_y),
            )
    return max_dpis_by_xref


def _xref_max_effective_dpi(doc: fitz.Document) -> dict[int, float]:
    """Compatibility view used by callers that only need the maximum axis."""
    return {
        xref: max(dpis)
        for xref, dpis in _xref_max_effective_dpis(doc).items()
    }


def _jpeg_bytes_for_xref(
    doc: fitz.Document,
    xref: int,
    width: int,
    height: int,
    quality: int,
) -> tuple[bytes, int]:
    pixmap = _prepare_jpeg_pixmap(fitz.Pixmap(doc, xref))
    if pixmap.width != width or pixmap.height != height:
        pixmap = fitz.Pixmap(pixmap, width, height)
    channels = pixmap.n - pixmap.alpha
    return pixmap.tobytes("jpeg", jpg_quality=quality), channels


def _put_jpeg_in_xref(
    doc: fitz.Document,
    xref: int,
    jpeg: bytes,
    width: int,
    height: int,
    channels: int,
) -> None:
    """既存画像xrefへJPEGを直接書き、replace_imageの資源重複を避ける。"""
    doc.update_stream(xref, jpeg, new=True, compress=False)
    doc.xref_set_key(xref, "Width", str(width))
    doc.xref_set_key(xref, "Height", str(height))
    doc.xref_set_key(xref, "BitsPerComponent", "8")
    doc.xref_set_key(xref, "Filter", "/DCTDecode")
    if channels <= 1:
        doc.xref_set_key(xref, "ColorSpace", "/DeviceGray")
    else:
        doc.xref_set_key(xref, "ColorSpace", "/DeviceRGB")
    keys = set(doc.xref_get_keys(xref))
    for extra in (
        "Decode",
        "DecodeParms",
        "SMask",
        "Mask",
        "Intent",
        "Metadata",
    ):
        if extra in keys:
            doc.xref_set_key(xref, extra, "null")


def _prepare_jpeg_pixmap(pixmap: fitz.Pixmap) -> fitz.Pixmap:
    if pixmap.colorspace is None:
        raise ValueError("Cannot recompress an image mask")
    if pixmap.n - pixmap.alpha > 3:
        pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
    if pixmap.alpha:
        pixmap = fitz.Pixmap(pixmap, 0)
    return pixmap
