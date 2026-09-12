"""Experimental GDI digit measurement; CP-011 evidence, not a runtime recipe."""
import ctypes as C
from ctypes import wintypes as W
import json

gdi = C.WinDLL("gdi32", use_last_error=True)
gdi.CreateCompatibleDC.argtypes = [W.HDC]
gdi.CreateCompatibleDC.restype = W.HDC
gdi.CreateFontW.argtypes = [C.c_int] * 5 + [W.DWORD] * 8 + [W.LPCWSTR]
gdi.CreateFontW.restype = W.HANDLE
gdi.SelectObject.argtypes = [W.HDC, W.HANDLE]
gdi.SelectObject.restype = W.HANDLE
gdi.DeleteObject.argtypes = [W.HANDLE]
gdi.DeleteDC.argtypes = [W.HDC]
gdi.GetTextFaceW.argtypes = [W.HDC, C.c_int, W.LPWSTR]
class Size(C.Structure):
    _fields_ = [("cx", W.LONG), ("cy", W.LONG)]
gdi.GetTextExtentPoint32W.argtypes = [W.HDC, W.LPCWSTR, C.c_int, C.POINTER(Size)]
for face, charset in [("Calibri",0), ("游ゴシック",128), ("Yu Gothic",128), ("Missing-KaruFile-Font",128)]:
    dc = gdi.CreateCompatibleDC(None)
    font = gdi.CreateFontW(-15,0,0,0,400,0,0,0,charset,0,0,5,0,face)
    old = gdi.SelectObject(dc,font)
    try:
        actual=C.create_unicode_buffer(128); gdi.GetTextFaceW(dc,128,actual)
        digits=[]
        for digit in "0123456789":
            size=Size()
            if not gdi.GetTextExtentPoint32W(dc,digit,1,C.byref(size)):raise C.WinError()
            digits.append([size.cx,size.cy])
        print(json.dumps(dict(request=face,actual=actual.value,digits=digits),ensure_ascii=False))
    finally:
        gdi.SelectObject(dc,old);gdi.DeleteObject(font);gdi.DeleteDC(dc)
