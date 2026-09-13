"""Conservative document-wide permissions, evaluated before every candidate."""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
import time
from pathlib import Path

import pymupdf as fitz

from .inspect_pdf import _effective_image_dpis

MAX_PAGES = 100
MAX_IMAGE_PIXELS = 80_000_000
MAX_STREAM_BYTES = 64 * 1024 * 1024


def _stream_length(doc: fitz.Document, xref: int) -> int:
    """Read a direct or indirect integer without loading the image stream."""
    kind, value = doc.xref_get_key(xref, "Length")
    if kind == "xref":
        value = doc.xref_object(int(value.split()[0])).strip()
    elif kind != "int":
        raise ValueError("invalid scan image stream length")
    if not re.fullmatch(r"\+?[0-9]+", value):
        raise ValueError("invalid scan image stream length")
    return int(value)


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


def scan_images(doc: fitz.Document, *, deadline: float = float("inf")) -> tuple[dict[int, tuple[float, float]], str]:
    """Preflight dictionaries/limits before decoding; reject the entire document."""
    xrefs = set()
    for page in doc:
        if time.monotonic() > deadline:
            return {}, "scan_preflight_time_limit"
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
            if _stream_length(doc, xref) > MAX_STREAM_BYTES:
                return {}, "image_stream_limit"
    # Digest matching is ambiguous when two resource xrefs decode identically.
    # Bound dictionaries first and check time between individual decodes.
    digests = set()
    for xref in sorted(xrefs):
        if time.monotonic() > deadline:
            return {}, "scan_preflight_time_limit"
        pix = fitz.Pixmap(doc, xref)
        digest = pix.digest
        del pix
        if digest in digests:
            return {}, "ambiguous_image_reference"
        digests.add(digest)
    minimums = {}
    placed = set()
    for page in doc:
        if time.monotonic() > deadline:
            return {}, "scan_preflight_time_limit"
        if not page.get_images(full=True) and any(k == "fill-image" for k, _ in page.get_bboxlog()):
            return {}, "inline_image"
        for info in page.get_image_info(xrefs=True):
            xref = info.get("xref", 0)
            if xref <= 0:
                return {}, "inline_image"
            if xref not in xrefs:
                return {}, "ambiguous_image_placement"
            dpis = _effective_image_dpis(info)
            previous = minimums.get(xref, dpis)
            minimums[xref] = tuple(min(a, b) for a, b in zip(previous, dpis))
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


def classify(path: Path, requested: str, *, safe: bool = False) -> Decision:
    deadline = time.monotonic() + 300
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
        if requested in {"standard", "compact"} and not safe:
            from . import raster_scan
            if raster_scan.automatic_scan(doc, deadline):
                reason = raster_scan.preflight(doc, path)
                return Decision("protected" if reason else "raster_scan", "automatic_scan_raster", reason)
        if requested in {"text_scan", "text_scan_bilevel"}:
            _, reason = scan_images(doc, deadline=deadline)
            if reason:
                return preserve(reason)
        has_text = False
        has_images = False
        for page in doc:
            if time.monotonic() > deadline:
                return preserve("preflight_time_limit")
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
            if requested in {"text_scan", "text_scan_bilevel"}:
                allowed.add("fill-image")
            elif images:
                return preserve("unpermitted_image")
            if kinds - allowed:
                return preserve("non_text_paint")
        if requested in {"text_scan", "text_scan_bilevel"}:
            if not has_images:
                return preserve("no_scan_image")
            return Decision("text_scan", basis)
        if not has_text:
            return preserve("no_confirmed_text")
        return Decision("text_table" if requested == "text" else "text", basis)
