"""PDF 事前検査・スキャン主体判定。"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pymupdf as fitz  # PyMuPDF

from .config import LossyOptions, ScanOptions
from .models import InspectionResult, OptimizationMode

_SCAN_DPI_THRESHOLD = 450.0


def _bbox_area(bbox: Any) -> float:
    try:
        return float(bbox.get_area())
    except Exception:
        pass
    try:
        x0, y0, x1, y1 = bbox
        return max(float(x1) - float(x0), 0.0) * max(float(y1) - float(y0), 0.0)
    except Exception:
        return 0.0


def _bbox_dimensions(bbox: Any) -> tuple[float, float]:
    try:
        x0, y0, x1, y1 = bbox
        return (
            max(float(x1) - float(x0), 0.0),
            max(float(y1) - float(y0), 0.0),
        )
    except Exception:
        return 0.0, 0.0


def _effective_image_dpis(info: dict[str, Any]) -> tuple[float, float]:
    """Return effective DPI along the image's intrinsic x and y axes.

    ``get_image_info()`` exposes the image-space unit square transform.  The
    lengths of its first and second basis vectors are therefore the displayed
    sizes of the image's intrinsic axes, even for rotated or skewed placement.
    Keeping the axes separate is important: taking their minimum can miss a
    stretched image whose resolution exceeds the limit on only one axis.
    """
    displayed_width, displayed_height = _bbox_dimensions(info.get("bbox"))
    if displayed_width <= 0 or displayed_height <= 0:
        return 0.0, 0.0

    try:
        pixel_width = float(info.get("width", 0))
        pixel_height = float(info.get("height", 0))
    except (TypeError, ValueError):
        return 0.0, 0.0
    if pixel_width <= 0 or pixel_height <= 0:
        return 0.0, 0.0

    transform = info.get("transform")
    try:
        a, b, c, d, _e, _f = (float(value) for value in transform)
        displayed_x = math.hypot(a, b)
        displayed_y = math.hypot(c, d)
    except (TypeError, ValueError):
        displayed_x = displayed_y = 0.0
    if displayed_x > 0 and displayed_y > 0:
        return (
            pixel_width * 72 / displayed_x,
            pixel_height * 72 / displayed_y,
        )

    # Compatibility fallback for synthetic/older PyMuPDF data without a
    # transform.  Select the orientation whose aspect ratio most closely
    # matches the intrinsic image.  Real inspection data uses the branch above.
    pixel_ratio = pixel_width / pixel_height
    direct_ratio = displayed_width / displayed_height
    swapped_ratio = displayed_height / displayed_width
    direct_error = abs(math.log(direct_ratio / pixel_ratio))
    swapped_error = abs(math.log(swapped_ratio / pixel_ratio))
    if swapped_error < direct_error:
        displayed_x, displayed_y = displayed_height, displayed_width
    else:
        displayed_x, displayed_y = displayed_width, displayed_height
    return (
        pixel_width * 72 / displayed_x,
        pixel_height * 72 / displayed_y,
    )


def _effective_image_dpi(info: dict[str, Any]) -> float:
    """Return the larger effective DPI of an image placement."""
    return max(_effective_image_dpis(info))


def _page_image_infos(page: fitz.Page) -> list[dict[str, Any]]:
    try:
        infos = page.get_image_info(xrefs=True)
    except TypeError:
        try:
            infos = page.get_image_info()
        except Exception:
            return []
    except Exception:
        return []
    return [info for info in infos if isinstance(info, dict)]


def _is_dct_jpeg(img: tuple) -> bool:
    return "DCTDecode" in str(img[8] or "")


def _should_rewrite_image(img: tuple, options: LossyOptions) -> bool:
    smask = int(img[1] or 0)
    if smask:
        return False
    bpc = int(img[4] or 0)
    if bpc == 1 and not options.bitonal:
        return False
    colorspace = str(img[5] or "")
    is_gray = colorspace in {"DeviceGray", "CalGray", "G"}
    is_color = not is_gray
    if is_gray and not options.gray:
        return False
    if is_color and not options.color:
        return False
    if _is_dct_jpeg(img) and not options.lossy:
        return False
    if not _is_dct_jpeg(img) and not options.lossless:
        return False
    return True


def _photo_xref_min_effective_dpis(
    doc: fitz.Document,
) -> dict[int, tuple[float, float]]:
    """Preserve the lowest-resolution placement of every shared image axis."""
    # PyMuPDF infers placement xrefs from pixel digests, with the last resource
    # winning when multiple xrefs decode to the same pixels. Include unpainted
    # resources: a duplicate there can hide a larger placement of a shared xref.
    # Build this map once per document scan and exclude every ambiguous group.
    seen_xrefs: set[int] = set()
    xref_by_digest: dict[bytes, int] = {}
    ambiguous_xrefs: set[int] = set()
    for page in doc:
        for image in page.get_images(full=True):
            xref = int(image[0])
            if xref <= 0 or xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            pixmap = fitz.Pixmap(doc, xref)
            digest = pixmap.digest
            del pixmap
            previous = xref_by_digest.setdefault(digest, xref)
            if previous != xref:
                ambiguous_xrefs.update((previous, xref))

    minimums: dict[int, tuple[float, float]] = {}
    for page in doc:
        # Missing a placement could downsample a shared image too far. Unlike
        # the legacy best-effort scan metrics, fail if placements cannot be read.
        for info in page.get_image_info(xrefs=True):
            xref = int(info.get("xref") or 0)
            if xref <= 0 or xref in ambiguous_xrefs:
                continue
            dpi_x, dpi_y = _effective_image_dpis(info)
            previous_x, previous_y = minimums.get(xref, (dpi_x, dpi_y))
            minimums[xref] = (min(previous_x, dpi_x), min(previous_y, dpi_y))
    return minimums


def _photo_candidate_dimensions(
    doc: fitz.Document,
    img: tuple,
    dpis: tuple[float, float],
    options: LossyOptions,
) -> tuple[int, int] | None:
    """Return safe photo dimensions, without claiming to classify image content.

    The caller explicitly selected a photo PDF. Only ordinary 8-bit RGB/gray
    JPEGs are eligible; masks and nontrivial decoding/color transforms are
    excluded. Low-DPI axes retain their dimensions, including images shared
    with a larger placement. A resize of the other axis still re-encodes JPEG.
    """
    if not _should_rewrite_image(img, options) or int(img[4] or 0) != 8:
        return None
    xref = int(img[0] or 0)
    if xref <= 0 or not _is_dct_jpeg(img):
        return None
    if doc.xref_get_key(xref, "Filter") != ("name", "/DCTDecode"):
        return None
    if doc.xref_get_key(xref, "ColorSpace") not in {
        ("name", "/DeviceRGB"), ("name", "/DeviceGray"),
    }:
        return None
    if any(
        doc.xref_get_key(xref, key)[0] != "null"
        for key in ("Mask", "SMask", "Decode", "DecodeParms")
    ):
        return None
    if doc.xref_get_key(xref, "ImageMask") not in {
        ("null", "null"), ("bool", "false"),
    }:
        return None
    if any(not math.isfinite(dpi) or dpi <= 0 for dpi in dpis):
        return None
    width, height = int(img[2]), int(img[3])
    # Round up so an axis above 200 DPI does not fall below 200 merely because
    # the target pixel count is fractional. Existing <=200 DPI axes stay put.
    dimensions = tuple(
        dimension if dpi <= options.dpi_target else max(
            1, min(dimension, math.ceil(dimension * options.dpi_target / dpi))
        )
        for dimension, dpi in zip((width, height), dpis)
    )
    return dimensions if dimensions != (width, height) else None


def _has_recompressible_jpeg(page: fitz.Page, options: LossyOptions) -> bool:
    if not options.recompress_existing_jpeg:
        return False
    placed_xrefs = {
        int(info.get("xref") or 0)
        for info in _page_image_infos(page)
        if int(info.get("xref") or 0) > 0
    }
    return any(
        int(img[0] or 0) in placed_xrefs
        and _is_dct_jpeg(img)
        and _should_rewrite_image(img, options)
        for img in page.get_images(full=True)
    )


def _page_max_effective_dpi(page: fitz.Page) -> float:
    max_dpi = 0.0
    for info in _page_image_infos(page):
        max_dpi = max(max_dpi, _effective_image_dpi(info))
    return max_dpi


def _page_has_oversampled_inline_image(
    page: fitz.Page,
    options: LossyOptions,
) -> bool:
    return any(
        int(info.get("xref") or 0) <= 0
        and _effective_image_dpi(info) > options.dpi_target
        for info in _page_image_infos(page)
    )


def _page_largest_image_metrics(page: fitz.Page) -> tuple[float, float]:
    infos = _page_image_infos(page)

    largest_info: dict[str, Any] | None = None
    largest_area = 0.0
    for info in infos:
        bbox = info.get("bbox")
        if bbox is None:
            continue
        area = _bbox_area(bbox)
        if area > largest_area:
            largest_info = info
            largest_area = area

    page_area = page.rect.width * page.rect.height
    if page_area <= 0 or largest_info is None:
        return 0.0, 0.0
    return (
        min(largest_area / page_area, 1.0),
        _effective_image_dpi(largest_info),
    )


def _page_visible_text_len_from_dict(page: fitz.Page) -> int:
    """``get_texttrace()`` が使えない場合の保守的なフォールバック。"""
    try:
        text_dict = page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)
    except Exception:
        text_dict = page.get_text("dict")
    length = 0
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                # 色だけでは可視性を判断できないため、白色文字も数える。
                length += len(span.get("text", ""))
    return length


def _page_visible_text_len(page: fitz.Page) -> int:
    try:
        texttrace = page.get_texttrace()
        length = 0
        for span in texttrace:
            if span.get("type") == 3:
                continue
            try:
                opacity = float(span.get("opacity", 1))
            except (TypeError, ValueError):
                opacity = 1.0
            if opacity <= 0:
                continue
            chars = span.get("chars")
            if chars is None:
                raise ValueError("texttrace span has no chars")
            length += len(chars)
        return length
    except Exception:
        return _page_visible_text_len_from_dict(page)


def inspect_file(
    path: Path,
    scan: ScanOptions,
    *,
    safe: bool,
    lossy_options: LossyOptions | None = None,
) -> InspectionResult:
    """
    PDFを開いて、処理可否・スキャン主体判定・lossy要否を行う。

    Returns:
        検査結果。処理不可の場合は ``skip_reason`` を含む。
    """
    page_count = 0
    scan_ratio = 0.0

    def rejected(reason: str) -> InspectionResult:
        return InspectionResult(False, reason, page_count, scan_ratio, None)

    try:
        doc = fitz.open(path)
    except Exception as exc:
        return rejected(f"open_failed: {exc}")

    try:
        # 暗号化
        if doc.is_encrypted or doc.needs_pass:
            return rejected("encrypted")

        # 修復済み
        if getattr(doc, "is_repaired", False):
            return rejected("repaired")

        page_count = doc.page_count
        if page_count == 0:
            return rejected("no_pages")

        # フォーム
        if getattr(doc, "is_form_pdf", False):
            return rejected("form")

        # 添付ファイル
        try:
            if doc.embfile_names():
                return rejected("attachments")
        except Exception as exc:
            return rejected(f"attachment_check_failed: {exc}")

        # 電子署名（-1 は「署名なし」を表す）
        try:
            if doc.get_sigflags() > 0:
                return rejected("signed")
        except Exception as exc:
            return rejected(f"signature_check_failed: {exc}")

        # 全ページ読み込み可能かチェック
        for i in range(page_count):
            try:
                _ = doc.load_page(i)
            except Exception as exc:
                return rejected(f"page_load_failed: {exc}")

        options = lossy_options or LossyOptions()
        photo_dpis = _photo_xref_min_effective_dpis(doc) if options.photo_mode else {}

        # スキャン判定（レポート用）と、配置画像によるlossy要否
        scan_pages = 0
        max_effective_dpi = 0.0
        has_recompressible_jpeg = False
        has_oversampled_inline_image = False
        has_photo_candidate = False
        for i in range(page_count):
            page = doc.load_page(i)
            img_ratio, largest_dpi = _page_largest_image_metrics(page)
            max_effective_dpi = max(max_effective_dpi, _page_max_effective_dpi(page))
            has_recompressible_jpeg = (
                has_recompressible_jpeg
                or _has_recompressible_jpeg(page, options)
            )
            has_oversampled_inline_image = (
                has_oversampled_inline_image
                or _page_has_oversampled_inline_image(page, options)
            )
            if options.photo_mode and not has_photo_candidate:
                has_photo_candidate = any(
                    _photo_candidate_dimensions(
                        doc, img, photo_dpis.get(int(img[0]), (0.0, 0.0)), options,
                    ) is not None
                    for img in page.get_images(full=True)
                )
            text_len = _page_visible_text_len(page)
            if (
                img_ratio >= scan.page_image_ratio
                and text_len <= scan.max_visible_text
                and largest_dpi > _SCAN_DPI_THRESHOLD
            ):
                scan_pages += 1

        scan_ratio = scan_pages / page_count if page_count else 0.0

        # PyMuPDF cannot replace inline images (xref=0) through the xref-based
        # transform.  Do not claim a lossy 300-DPI result while leaving an
        # oversampled inline placement untouched.  Safe mode remains lossless.
        if not safe and not options.photo_mode and has_oversampled_inline_image:
            return rejected("unsupported_oversampled_inline_image")

        # safe モードでは非可逆を無効
        if safe:
            mode = OptimizationMode.LOSSLESS
        elif options.photo_mode:
            mode = (
                OptimizationMode.LOSSY if has_photo_candidate
                else OptimizationMode.LOSSLESS
            )
        elif max_effective_dpi > options.dpi_target:
            mode = OptimizationMode.LOSSY
        elif has_recompressible_jpeg:
            mode = OptimizationMode.LOSSY
        else:
            mode = OptimizationMode.LOSSLESS

        return InspectionResult(True, None, page_count, scan_ratio, mode)

    except Exception as exc:
        return rejected(f"inspect_error: {exc}")

    finally:
        doc.close()
