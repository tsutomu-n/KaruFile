"""Confirmed regular 11pt Normal fonts, measured in a 96-DPI GDI memory DC.

Excel is not loaded. Unknown/fallback faces are protected; real API failures
remain errors. Font bytes are hashed for diagnostics and are never exported.
"""
from dataclasses import dataclass
import ctypes as C
from ctypes import wintypes as W
import hashlib
import sys

from .package import Protected


@dataclass(frozen=True)
class FontMetrics:
    face: str
    mdw: int
    sha256: str
    basis: str


def measure_font(face: str, charset: int = 0) -> FontMetrics:
    aliases = {"Calibri": {"Calibri"}, "游ゴシック": {"游ゴシック", "Yu Gothic"},
               "Yu Gothic": {"游ゴシック", "Yu Gothic"}}
    if face not in aliases or charset not in ({0, 1} if face == "Calibri" else {128}):
        raise Protected("unverified_normal_font")
    if sys.platform != "win32":
        if face == "Calibri":
            return FontMetrics(face, 7, "", "iso_calibri11")
        raise Protected("windows_font_metrics_unavailable")
    gdi = C.WinDLL("gdi32", use_last_error=True)
    gdi.CreateCompatibleDC.argtypes, gdi.CreateCompatibleDC.restype = [W.HDC], W.HDC
    gdi.CreateFontW.argtypes = [C.c_int] * 5 + [W.DWORD] * 8 + [W.LPCWSTR]
    gdi.CreateFontW.restype = W.HANDLE
    gdi.SelectObject.argtypes, gdi.SelectObject.restype = [W.HDC, W.HANDLE], W.HANDLE
    gdi.DeleteObject.argtypes, gdi.DeleteDC.argtypes = [W.HANDLE], [W.HDC]
    gdi.GetTextFaceW.argtypes = [W.HDC, C.c_int, W.LPWSTR]
    gdi.GetFontData.argtypes, gdi.GetFontData.restype = [W.HDC, W.DWORD, W.DWORD, W.LPVOID, W.DWORD], W.DWORD
    class Size(C.Structure):
        _fields_ = [("cx", W.LONG), ("cy", W.LONG)]
    class TextMetrics(C.Structure):
        _fields_ = [(name, W.LONG) for name in (
            "height", "ascent", "descent", "internal_leading", "external_leading", "ave_width",
            "max_width", "weight", "overhang", "aspect_x", "aspect_y")] + [
            (name, W.WCHAR) for name in ("first", "last", "default", "break_char")] + [
            (name, W.BYTE) for name in ("italic", "underlined", "struckout", "pitch", "charset")]
    gdi.GetTextExtentPoint32W.argtypes = [W.HDC, W.LPCWSTR, C.c_int, C.POINTER(Size)]
    gdi.GetTextMetricsW.argtypes = [W.HDC, C.POINTER(TextMetrics)]
    dc = gdi.CreateCompatibleDC(None)
    if not dc:
        raise C.WinError()
    font, old = None, None
    try:
        # round(11pt * 96/72)=15 logical pixels; MM_TEXT memory DC, regular,
        # no rotation/width override, ClearType quality. No screen-DPI lookup.
        font = gdi.CreateFontW(-15, 0, 0, 0, 400, 0, 0, 0, charset, 0, 0, 5, 0, face)
        if not font:
            raise C.WinError()
        old = gdi.SelectObject(dc, font)
        if not old or old == C.c_void_p(-1).value:
            raise C.WinError()
        actual = C.create_unicode_buffer(128)
        if not gdi.GetTextFaceW(dc, len(actual), actual):
            raise C.WinError()
        if actual.value not in aliases[face]:
            raise Protected("normal_font_fallback")
        metrics = TextMetrics()
        if not gdi.GetTextMetricsW(dc, C.byref(metrics)):
            raise C.WinError()
        if (metrics.weight != 400 or metrics.italic or metrics.underlined or metrics.struckout
                or metrics.height - metrics.internal_leading != 15
                or metrics.charset != (0 if face == "Calibri" else 128)):
            raise Protected("normal_font_style_or_size_mismatch")
        widths = []
        for digit in "0123456789":
            size = Size()
            if not gdi.GetTextExtentPoint32W(dc, digit, 1, C.byref(size)):
                raise C.WinError()
            widths.append(size.cx)
        expected = 7 if face == "Calibri" else 8
        if min(widths) <= 0 or max(widths) != expected:
            raise Protected("unverified_normal_font_metrics")
        count = gdi.GetFontData(dc, 0, 0, None, 0)
        if count == 0xFFFFFFFF:
            raise C.WinError()
        if not 0 < count <= 64 * 1024 * 1024:
            raise Protected("font_data_size_limit")
        data = C.create_string_buffer(count)
        if gdi.GetFontData(dc, 0, 0, data, count) != count:
            raise OSError("GDI font data changed during measurement")
        return FontMetrics(actual.value, expected, hashlib.sha256(data.raw).hexdigest(), "gdi96_regular11")
    finally:
        if old:
            gdi.SelectObject(dc, old)
        if font:
            gdi.DeleteObject(font)
        gdi.DeleteDC(dc)
