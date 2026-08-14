"""PDF 事前検査・スキャン主体判定。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pymupdf as fitz  # PyMuPDF

from .config import ScanOptions
from .models import InspectionResult, OptimizationMode


def _is_visible_color(color: Any) -> bool:
    """白または白に近い色は不可視とみなす。"""
    if isinstance(color, int):
        red, green, blue = fitz.sRGB_to_rgb(color)
        return (red + green + blue) / 3 < 0.99 * 255
    if not isinstance(color, (list, tuple)):
        return True
    if len(color) == 3:
        maximum = 255 if any(float(component) > 1 for component in color) else 1
        return sum(float(component) for component in color) / 3 < 0.99 * maximum
    if len(color) == 4:
        # CMYKの白は (0, 0, 0, 0)。いずれかのインク成分があれば可視とする。
        return any(float(component) > 0.01 for component in color)
    else:
        return True


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


def _page_image_area_ratio(page: fitz.Page) -> float:
    try:
        infos = page.get_image_info()
    except Exception:
        infos = []
    img_area = 0.0
    for info in infos:
        bbox = info.get("bbox")
        if bbox is None:
            continue
        img_area += _bbox_area(bbox)
    page_area = page.rect.width * page.rect.height
    if page_area <= 0:
        return 0.0
    return min(img_area / page_area, 1.0)


def _page_visible_text_len(page: fitz.Page) -> int:
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
                if _is_visible_color(span.get("color")):
                    length += len(span.get("text", ""))
    return length


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
            img_ratio = _page_image_area_ratio(page)
            text_len = _page_visible_text_len(page)
            if (
                img_ratio >= scan.page_image_ratio
                and text_len <= scan.max_visible_text
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
