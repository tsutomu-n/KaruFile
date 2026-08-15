"""PDF 事前検査・スキャン主体判定。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pymupdf as fitz  # PyMuPDF

from .config import ScanOptions
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


def _effective_image_dpi(info: dict[str, Any]) -> float:
    displayed_width, displayed_height = _bbox_dimensions(info.get("bbox"))
    if displayed_width <= 0 or displayed_height <= 0:
        return 0.0

    try:
        pixel_width = float(info.get("width", 0))
        pixel_height = float(info.get("height", 0))
    except (TypeError, ValueError):
        return 0.0
    if pixel_width <= 0 or pixel_height <= 0:
        return 0.0

    direct = min(
        pixel_width * 72 / displayed_width,
        pixel_height * 72 / displayed_height,
    )
    swapped = min(
        pixel_width * 72 / displayed_height,
        pixel_height * 72 / displayed_width,
    )
    return max(direct, swapped)


def _page_largest_image_metrics(page: fitz.Page) -> tuple[float, float]:
    try:
        infos = page.get_image_info()
    except Exception:
        infos = []

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


def inspect_file(path: Path, scan: ScanOptions, *, safe: bool) -> InspectionResult:
    """
    PDFを開いて、処理可否・スキャン主体判定を行う。

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
        except Exception:
            pass

        # 電子署名（-1 は「署名なし」を表す）
        try:
            if doc.get_sigflags() > 0:
                return rejected("signed")
        except Exception:
            pass

        # 全ページ読み込み可能かチェック
        for i in range(page_count):
            try:
                _ = doc.load_page(i)
            except Exception as exc:
                return rejected(f"page_load_failed: {exc}")

        # スキャン判定
        scan_pages = 0
        for i in range(page_count):
            page = doc.load_page(i)
            img_ratio, effective_dpi = _page_largest_image_metrics(page)
            text_len = _page_visible_text_len(page)
            if (
                img_ratio >= scan.page_image_ratio
                and text_len <= scan.max_visible_text
                and effective_dpi > _SCAN_DPI_THRESHOLD
            ):
                scan_pages += 1

        scan_ratio = scan_pages / page_count if page_count else 0.0

        # safe モードでは非可逆を無効
        if safe:
            mode = OptimizationMode.LOSSLESS
        elif scan_ratio >= scan.scan_page_ratio:
            mode = OptimizationMode.LOSSY
        else:
            mode = OptimizationMode.LOSSLESS

        return InspectionResult(True, None, page_count, scan_ratio, mode)

    except Exception as exc:
        return rejected(f"inspect_error: {exc}")

    finally:
        doc.close()
