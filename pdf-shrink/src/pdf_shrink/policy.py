"""Conservative document-wide permissions, evaluated before every candidate."""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

import pymupdf as fitz

from .inspect_pdf import _photo_xref_min_effective_dpis

MAX_PAGES = 100
MAX_IMAGE_PIXELS = 80_000_000
MAX_STREAM_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class Decision:
    classification: str
    permission_basis: str
    preservation_reason: str = ""

    @property
    def protected(self) -> bool:
        return bool(self.preservation_reason)


def _simple_rules(page: fitz.Page) -> bool:
    for drawing in page.get_drawings(extended=True):
        if drawing.get("type") != "s" or drawing.get("fill") is not None:
            return False
        if drawing.get("layer") or drawing.get("stroke_opacity", 1) != 1:
            return False
        for item in drawing["items"]:
            if item[0] == "re":
                continue
            if item[0] != "l":
                return False
            a, b = item[1:3]
            if a.x != b.x and a.y != b.y:
                return False
    return True


def scan_images(doc: fitz.Document) -> tuple[dict[int, tuple[float, float]], str]:
    """Preflight dictionaries/limits before decoding; reject the entire document."""
    xrefs = set()
    for page in doc:
        for image in page.get_images(full=True):
            xref = image[0]
            if xref <= 0:
                return {}, "inline_image"
            xrefs.add(xref)
            get = lambda key: doc.xref_get_key(xref, key)
            if (image[1] or image[4] != 8 or get("ColorSpace") not in {
                ("name", "/DeviceRGB"), ("name", "/DeviceGray"),
            } or any(get(k)[0] != "null" for k in ("Mask", "SMask", "Decode", "DecodeParms"))
                or get("ImageMask") not in {("null", "null"), ("bool", "false")}
                or get("Filter") not in {("name", "/DCTDecode"), ("name", "/FlateDecode"), ("null", "null")}):
                return {}, "unsupported_scan_image"
            if image[2] <= 0 or image[3] <= 0:
                raise ValueError("invalid scan image dimensions")
            if image[2] * image[3] > MAX_IMAGE_PIXELS:
                return {}, "image_pixel_limit"
            if int(get("Length")[1]) > MAX_STREAM_BYTES:
                return {}, "image_stream_limit"
    minimums = _photo_xref_min_effective_dpis(doc)
    placed = set()
    for page in doc:
        for info in page.get_image_info(xrefs=True):
            xref = info.get("xref", 0)
            if xref <= 0:
                return {}, "inline_image"
            if xref not in minimums or xref not in xrefs:
                return {}, "ambiguous_image_placement"
            matrix = info.get("transform", ())
            if len(matrix) != 6 or not all(math.isfinite(v) for v in matrix):
                return {}, "ambiguous_image_placement"
            if abs(matrix[0] * matrix[3] - matrix[1] * matrix[2]) < 1e-9:
                return {}, "degenerate_image_placement"
            if any(not math.isfinite(dpi) or dpi <= 0 for dpi in minimums[xref]):
                return {}, "ambiguous_image_placement"
            placed.add(xref)
    if xrefs - minimums.keys():
        return {}, "ambiguous_image_reference"
    return {xref: minimums[xref] for xref in placed}, ""


def classify(path: Path, requested: str) -> Decision:
    basis = "automatic_text_only" if requested in {"standard", "compact"} else f"explicit_{requested}"
    def preserve(reason: str) -> Decision:
        return Decision("protected", basis, reason)
    if requested == "preserve":
        return preserve("explicit_preserve")
    with fitz.open(path) as doc:
        if doc.is_encrypted or doc.needs_pass:
            return preserve("encrypted")
        if doc.is_repaired:
            return preserve("repaired")
        if not doc.page_count:
            return preserve("no_pages")
        if doc.get_sigflags() > 0:
            return preserve("signed")
        if doc.is_form_pdf or doc.embfile_names():
            return preserve("form_or_attachments")
        if requested == "photo":
            return Decision("photo", basis)
        if doc.page_count > MAX_PAGES:
            return preserve("page_limit")
        # Layers, annotation appearances and transparency groups require broader
        # semantics than the first text/scan recipe supports.
        if doc.get_ocgs():
            return preserve("optional_content")
        has_text = False
        has_images = False
        for page in doc:
            if list(page.annots() or ()) or page.first_widget:
                return preserve("annotations")
            kinds = {entry[0] for entry in page.get_bboxlog()}
            has_text |= bool(page.get_text().strip())
            images = bool(page.get_images(full=True) or page.get_image_info(xrefs=True))
            has_images |= images
            drawings = page.get_drawings(extended=True)
            allowed = {"fill-text", "stroke-text", "ignore-text"}
            if requested == "text":
                allowed.add("stroke-path")
                if not _simple_rules(page):
                    return preserve("non_table_drawing")
            elif drawings:
                return preserve("drawing")
            if requested == "text_scan":
                allowed.add("fill-image")
            elif images:
                return preserve("unpermitted_image")
            if kinds - allowed:
                return preserve("non_text_paint")
        if requested == "text_scan":
            _, reason = scan_images(doc)
            if reason:
                return preserve(reason)
            if not has_images:
                return preserve("no_scan_image")
            return Decision("text_scan", basis)
        if not has_text:
            return preserve("no_confirmed_text")
        return Decision("text_table" if requested == "text" else "text", basis)
