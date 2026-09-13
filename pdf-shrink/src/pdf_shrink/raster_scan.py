"""Bounded page-image compression for image-only PDFs, including clipping paths."""
from __future__ import annotations

import math
from pathlib import Path
import time

import pymupdf as fitz
from PIL import Image, ImageChops, ImageStat

from .lossless_jpeg import CandidateRejected
from .qpdf import qpdf_check

RECIPE = {"version": 3, "dpi": 300, "jpeg_quality": 92, "pages": 100,
          "page_pixels": 32_000_000, "image_pixels": 80_000_000, "total_pixels": 600_000_000,
          "source_bytes": 128 * 1024 * 1024, "seconds": 300,
          "mean_difference": 5, "local_difference": 10, "tile": 32}


def page_pixels(page) -> int:
    rect = page.rect
    if not all(math.isfinite(v) for v in rect) or rect.is_empty or rect.is_infinite:
        raise ValueError("invalid scan page geometry")
    return math.ceil(rect.width * RECIPE["dpi"] / 72) * math.ceil(rect.height * RECIPE["dpi"] / 72)


def automatic_scan(doc, deadline: float) -> bool:
    """Structural eligibility, not semantic recognition of scans versus photos.

    Every nonblank page must contain images, no text (including invisible OCR)
    and no vector paint. Clip paths are allowed because rendering applies them.
    Existing document-level protection is checked by the caller.
    """
    found = False
    for page in doc:
        if time.monotonic() > deadline:
            return False
        if list(page.annots() or ()) or page.first_widget:
            return False
        kinds = {entry[0] for entry in page.get_bboxlog()}
        if kinds - {"fill-image"} or page.get_texttrace() or page.get_text().strip():
            return False
        if any(d.get("type") != "clip" for d in page.get_drawings(extended=True)):
            return False
        found |= "fill-image" in kinds
    return found


def preflight(doc, source: Path) -> str:
    if source.stat().st_size > RECIPE["source_bytes"]:
        return "raster_scan_source_limit"
    total = 0
    for page in doc:
        for info in page.get_image_info():
            if info["width"] * info["height"] > RECIPE["image_pixels"]:
                return "raster_scan_source_image_limit"
        pixels = page_pixels(page)
        if pixels > RECIPE["page_pixels"]:
            return "raster_scan_page_pixel_limit"
        total += pixels * 3  # generation plus independent source/output renders
    return "raster_scan_total_pixel_limit" if total > RECIPE["total_pixels"] else ""


class Budget:
    def __init__(self, deadline: float):
        self.deadline = deadline
        self.pixels = 0

    def check(self, pixels: int = 0):
        self.pixels += pixels
        if time.monotonic() > self.deadline:
            raise CandidateRejected("raster_scan_time_limit")
        if self.pixels > RECIPE["total_pixels"]:
            raise CandidateRejected("raster_scan_total_pixel_limit")


def render(page, budget: Budget, *, exact: bool = False):
    pixels = page_pixels(page)
    if pixels > RECIPE["page_pixels"]:
        raise CandidateRejected("raster_scan_page_pixel_limit")
    budget.check(pixels)
    pix = page.get_pixmap(dpi=RECIPE["dpi"], colorspace=fitz.csRGB if exact else fitz.csGRAY, alpha=False)
    budget.check()
    return pix


def generate(source: Path, target: Path, budget: Budget) -> int:
    # Keep the original page tree, boxes, rotation, links, bookmarks and metadata.
    # Replace page paint and resources only. Garbage collection removes old images.
    with fitz.open(source) as doc:
        for page in doc:
            rotation = page.rotation
            page.set_rotation(0)
            pix = render(page, budget)
            encoded = pix.tobytes("jpeg", jpg_quality=RECIPE["jpeg_quality"])
            xref = doc.get_new_xref()
            doc.update_object(xref, "<<>>")
            doc.update_stream(xref, b"")
            page.set_contents(xref)
            doc.xref_set_key(page.xref, "Resources", "<<>>")
            # Match the render pixel grid exactly. Fitting rounded pixel dimensions
            # back into a fractional page rectangle would resample thin strokes.
            rect = fitz.Rect(0, 0, pix.width * 72 / RECIPE["dpi"], pix.height * 72 / RECIPE["dpi"])
            page.insert_image(rect, stream=encoded, keep_proportion=False)
            page.set_rotation(rotation)
            budget.check()
        count = len(doc)
        doc.save(target, garbage=4, deflate=True, raise_on_repair=True)
    budget.check()
    return count


def validate(source: Path, target: Path, qpdf: Path, budget: Budget, *, exact: bool = False):
    from .text_optimize import _stable, _paths, _placements
    budget.check()
    if qpdf_check(qpdf, target):
        raise RuntimeError("raster scan qpdf check failed")
    with fitz.open(source) as src, fitz.open(target) as dst:
        if src.is_repaired or dst.is_repaired:
            raise RuntimeError("raster scan PDF required repair")
        if (len(src) != len(dst) or src.metadata != dst.metadata
                or src.get_xml_metadata() != dst.get_xml_metadata()
                or _stable(src.get_toc(simple=False)) != _stable(dst.get_toc(simple=False))
                or _stable(src.resolve_names()) != _stable(dst.resolve_names())):
            raise CandidateRejected("raster_scan_document_mismatch")
        for a, b in zip(src, dst):
            if ((a.rotation, a.mediabox, a.cropbox, a.rect) != (b.rotation, b.mediabox, b.cropbox, b.rect)
                    or a.get_text() != b.get_text()
                    or _stable(a.get_links()) != _stable(b.get_links())):
                raise CandidateRejected("raster_scan_geometry_or_text_mismatch")
            if exact and (_paths(a) != _paths(b) or _placements(a) != _placements(b)):
                raise CandidateRejected("raster_scan_lossless_structure_mismatch")
            pa, pb = render(a, budget, exact=exact), render(b, budget, exact=exact)
            if (pa.width, pa.height) != (pb.width, pb.height):
                raise CandidateRejected("raster_scan_render_geometry_mismatch")
            if exact:
                if pa.samples != pb.samples:
                    raise CandidateRejected("raster_scan_lossless_render_mismatch")
                continue
            ia = Image.frombytes("L", (pa.width, pa.height), pa.samples)
            ib = Image.frombytes("L", (pb.width, pb.height), pb.samples)
            diff = ImageChops.difference(ia, ib)
            if ImageStat.Stat(diff).mean[0] > RECIPE["mean_difference"]:
                raise CandidateRejected("raster_scan_global_difference")
            for y in range(0, pa.height, RECIPE["tile"]):
                budget.check()
                for x in range(0, pa.width, RECIPE["tile"]):
                    tile = diff.crop((x, y, min(x + RECIPE["tile"], pa.width), min(y + RECIPE["tile"], pa.height)))
                    if ImageStat.Stat(tile).mean[0] > RECIPE["local_difference"]:
                        raise CandidateRejected("raster_scan_local_difference")
    budget.check()
