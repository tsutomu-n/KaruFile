"""Independent text candidates with bounded, content-preserving validation."""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import tempfile
import time

import pymupdf as fitz

from .config import BILEVEL_THRESHOLD, RunConfig
from .lossless_jpeg import CandidateRejected
from .policy import scan_images
from .qpdf import qpdf_check, qpdf_optimize
from .validate import _GLOBAL_RENDER_DIFF_THRESHOLD, _LOCAL_RENDER_DIFF_THRESHOLD, _tile_ranges


@dataclass
class Budget:
    deadline: float
    pixels: int = 0
    maximum: int = 600_000_000

    def check(self, pixels: int = 0) -> None:
        self.pixels += pixels
        if time.monotonic() > self.deadline:
            raise CandidateRejected("text_document_time_limit")
        if self.pixels > self.maximum:
            raise CandidateRejected("text_validation_pixel_limit")


def _bilevel_samples(gray: fitz.Pixmap, budget: Budget) -> bytes:
    """Pack rows MSB first, with white padding and no dithering or glyph matching."""
    samples = gray.samples
    packed = bytearray()
    table = bytes(0 if value < BILEVEL_THRESHOLD else 1 for value in range(256))
    for y in range(gray.height):
        if y % 64 == 0:
            budget.check()
        row = samples[y * gray.stride:y * gray.stride + gray.width].translate(table)
        row += b"\x01" * (-gray.width % 8)
        for x in range(0, len(row), 8):
            value = 0
            for bit in row[x:x + 8]:
                value = (value << 1) | bit
            packed.append(value)
    budget.check()
    return bytes(packed)


def generate(source: Path, target: Path, kind: str, cfg: RunConfig,
             qpdf: Path, budget: Budget) -> int:
    budget.check()
    if kind == "lossless":
        qpdf_optimize(qpdf, source, target, cfg.qpdf, reject_warnings=True)
        budget.check()
        return 0
    changed = 0
    with tempfile.TemporaryDirectory(prefix="text-", dir=target.parent) as folder:
        intermediate = Path(folder) / "prepared.pdf"
        with fitz.open(source) as doc:
            if kind.startswith("text_scan_"):
                minimums, reason = scan_images(doc, deadline=budget.deadline)
                if reason:
                    if reason == "scan_preflight_time_limit":
                        raise CandidateRejected("text_document_time_limit")
                    raise RuntimeError(f"scan preflight changed: {reason}")
                for xref, dpis in sorted(minimums.items()):
                    budget.check()
                    pix = fitz.Pixmap(doc, xref)
                    gray = fitz.Pixmap(fitz.csGRAY, pix)
                    width, height = (
                        size if dpi <= 300 else max(1, min(size, math.ceil(size * 300 / dpi)))
                        for size, dpi in zip((pix.width, pix.height), dpis)
                    )
                    if (width, height) != (pix.width, pix.height):
                        gray = fitz.Pixmap(gray, width, height, None)
                    if kind == "text_scan_bilevel":
                        doc.update_stream(xref, _bilevel_samples(gray, budget), compress=True)
                        doc.xref_set_key(xref, "BitsPerComponent", "1")
                    else:
                        quality = int(kind.rsplit("_", 1)[1])
                        encoded = gray.tobytes("jpeg", jpg_quality=quality)
                        doc.update_stream(xref, encoded, compress=False)
                        doc.xref_set_key(xref, "Filter", "/DCTDecode")
                    for key, value in (("ColorSpace", "/DeviceGray"),
                                       ("Width", str(width)), ("Height", str(height))):
                        doc.xref_set_key(xref, key, value)
                    changed += 1
                    budget.check()
            elif kind == "text_gray":
                for page in doc:
                    budget.check()
                    page.recolor(components=1)
            budget.check()
            doc.subset_fonts(fallback=False)
            budget.check()
            doc.save(intermediate, garbage=4, deflate=True, deflate_images=True,
                     deflate_fonts=True, use_objstms=1, raise_on_repair=True)
        budget.check()
        qpdf_optimize(qpdf, intermediate, target, cfg.qpdf, reject_warnings=True)
        budget.check()
    return changed


def _stable(value):
    """Object numbers may change; semantic values and coordinates may not."""
    if isinstance(value, dict):
        return {key: _stable(item) for key, item in value.items() if key not in {"xref", "id"}}
    if isinstance(value, (tuple, list)):
        return [_stable(item) for item in value]
    return value


def _text_positions(page):
    return [(span["type"], span["dir"], span["size"], span["opacity"],
             tuple((char[0], char[2], char[3]) for char in span["chars"]))
            for span in page.get_texttrace()]


def _paths(page):
    return [{key: value for key, value in drawing.items()
             if key not in {"color", "fill", "seqno"}}
            for drawing in page.get_drawings(extended=True)]


def _placements(page):
    return [(i["bbox"], i["transform"]) for i in page.get_image_info(xrefs=True)]


def _render_compare(sp, dp, dpi: int, region, gray: bool, exact: bool, budget: Budget):
    scale = dpi / 72
    step = 256 / scale
    difference = count = 0
    y = region.y0
    while y < region.y1:
        x = region.x0
        while x < region.x1:
            budget.check()
            clip = fitz.Rect(x, y, min(x + step, region.x1), min(y + step, region.y1))
            cs = fitz.csGRAY if gray else fitz.csRGB
            expected = math.ceil(clip.width * scale + 2) * math.ceil(clip.height * scale + 2) * 2
            budget.check(expected)
            a = sp.get_pixmap(dpi=dpi, clip=clip, colorspace=cs, alpha=False)
            b = dp.get_pixmap(dpi=dpi, clip=clip, colorspace=cs, alpha=False)
            if (a.width, a.height, a.n, a.stride) != (b.width, b.height, b.n, b.stride):
                raise CandidateRejected("text_render_geometry_mismatch")
            ss, ds = a.samples, b.samples
            if exact:
                if ss != ds:
                    raise CandidateRejected(f"text_render_mismatch_{dpi}dpi")
            elif ss != ds:
                for ly, end_y in _tile_ranges(a.height, 32):
                    for lx, end_x in _tile_ranges(a.width, 32):
                        local = 0
                        for row in range(ly, end_y):
                            start, end = row * a.stride + lx * a.n, row * a.stride + end_x * a.n
                            local += sum(abs(u - v) for u, v in zip(ss[start:end], ds[start:end]))
                        n = (end_y - ly) * (end_x - lx) * a.n
                        if local / n / 255 > _LOCAL_RENDER_DIFF_THRESHOLD:
                            raise CandidateRejected(f"text_scan_local_diff_{dpi}dpi")
                        difference += local
            count += len(ss)
            budget.check()
            x += step
        y += step
    if count and difference / count / 255 > _GLOBAL_RENDER_DIFF_THRESHOLD:
        raise CandidateRejected(f"text_scan_global_diff_{dpi}dpi")


def validate_candidate(source: Path, candidate: Path, kind: str,
                       qpdf: Path, budget: Budget) -> None:
    budget.check()
    rc = qpdf_check(qpdf, candidate)
    if rc:
        raise RuntimeError(f"qpdf check failed (rc={rc})")
    gray = kind == "text_gray" or kind.startswith("text_scan_")
    exact = not kind.startswith("text_scan_")
    with fitz.open(source) as src, fitz.open(candidate) as dst:
        if src.is_repaired or dst.is_repaired:
            raise RuntimeError("text candidate required PDF repair")
        if (src.page_count != dst.page_count or _stable(src.get_toc(simple=False)) != _stable(dst.get_toc(simple=False))
                or src.metadata != dst.metadata or src.get_xml_metadata() != dst.get_xml_metadata()
                or _stable(src.resolve_names()) != _stable(dst.resolve_names())):
            raise CandidateRejected("text_document_structure_mismatch")
        for sp, dp in zip(src, dst):
            budget.check()
            if ((sp.rotation, sp.mediabox, sp.cropbox, sp.rect) != (dp.rotation, dp.mediabox, dp.cropbox, dp.rect)
                or sp.get_text() != dp.get_text() or _text_positions(sp) != _text_positions(dp)
                or _paths(sp) != _paths(dp) or _placements(sp) != _placements(dp)
                or _stable(sp.get_links()) != _stable(dp.get_links())):
                raise CandidateRejected("text_page_content_or_position_mismatch")
            _render_compare(sp, dp, 72, sp.rect, gray, exact, budget)
            if exact:
                _render_compare(sp, dp, 300, sp.rect, gray, True, budget)
            else:
                for info in sp.get_image_info(xrefs=True):
                    region = (fitz.Rect(info["bbox"]) * sp.rotation_matrix) & sp.rect
                    if not region.is_empty:
                        _render_compare(sp, dp, 300, region, True, False, budget)
    budget.check()
