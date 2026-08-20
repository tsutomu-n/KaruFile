"""PDF圧縮候補の生成。出力先への採用は ``output`` が担当する。"""
from __future__ import annotations

from pathlib import Path

import pymupdf as fitz  # PyMuPDF

from .config import LossyOptions, QpdfOptions
from .inspect_pdf import _effective_image_dpi, _page_image_infos
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
) -> None:
    """配置実効DPIが目標を超える画像を縮小した非可逆圧縮候補を生成する。"""
    ensure_dir(candidate.parent)
    doc = fitz.open(source)
    try:
        _downsample_oversampled_images(doc, options)
        doc.save(
            candidate,
            garbage=4,
            deflate=True,
            use_objstms=1,
            raise_on_repair=True,
        )
    finally:
        doc.close()


def _downsample_oversampled_images(doc: fitz.Document, options: LossyOptions) -> int:
    if options.dpi_target <= 0:
        return 0

    max_dpi_by_xref = _xref_max_effective_dpi(doc)
    replaced: set[int] = set()
    for page in doc:
        images = {int(img[0]): img for img in page.get_images(full=True)}
        for xref, img in images.items():
            if xref in replaced or xref <= 0:
                continue
            dpi = max_dpi_by_xref.get(xref, 0.0)
            if dpi <= options.dpi_target:
                continue
            if not _should_rewrite_image(img, options):
                continue
            width = int(img[2])
            height = int(img[3])
            scale = options.dpi_target / dpi
            new_width = max(1, round(width * scale))
            new_height = max(1, round(height * scale))
            if new_width >= width and new_height >= height:
                continue
            jpeg, channels = _jpeg_bytes_for_xref(
                doc, xref, new_width, new_height, options.quality
            )
            _put_jpeg_in_xref(doc, xref, jpeg, new_width, new_height, channels)
            replaced.add(xref)
    if replaced:
        logger.info("Downsampled %d PDF image(s) to %s DPI", len(replaced), options.dpi_target)
    return len(replaced)


def _xref_max_effective_dpi(doc: fitz.Document) -> dict[int, float]:
    max_dpi_by_xref: dict[int, float] = {}
    for page in doc:
        for info in _page_image_infos(page):
            xref = int(info.get("xref") or 0)
            if xref <= 0:
                continue
            dpi = _effective_image_dpi(info)
            if dpi > max_dpi_by_xref.get(xref, 0.0):
                max_dpi_by_xref[xref] = dpi
    return max_dpi_by_xref


def _should_rewrite_image(img: tuple, options: LossyOptions) -> bool:
    smask = int(img[1] or 0)
    if smask:
        return False
    bpc = int(img[4] or 0)
    if bpc == 1 and not options.bitonal:
        return False
    colorspace = str(img[5] or "")
    image_filter = str(img[8] or "")
    is_gray = colorspace in {"DeviceGray", "CalGray", "G"}
    is_color = not is_gray
    if is_gray and not options.gray:
        return False
    if is_color and not options.color:
        return False
    is_jpeg = "DCTDecode" in image_filter
    if is_jpeg and not options.lossy:
        return False
    if not is_jpeg and not options.lossless:
        return False
    return True


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
    for extra in ("DecodeParms", "SMask", "Mask", "Intent", "Metadata"):
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
