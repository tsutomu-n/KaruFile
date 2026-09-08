"""Opt-in JPEG entropy optimization; preserves image dictionaries and pixels."""
from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import TYPE_CHECKING

import pymupdf as fitz

from .qpdf import qpdf_optimize

if TYPE_CHECKING:
    from .config import RunConfig


RECIPE = {
    "version": 1,
    "tool_version": "3.2.0",
    "arguments": ["-copy", "all", "-optimize", "-maxmemory", "128M", "-maxscans", "100", "-strict"],
    "max_pixels": 20_000_000,
    "max_stream_bytes": 32 * 1024 * 1024,
    "call_seconds": 30,
    "document_seconds": 300,
    "validation": "DQT-frame-native-pixels-dictionary-geometry-text-paths-RGB72+300-exact-v1",
}


class CandidateRejected(Exception):
    """A valid attempt failed equality or the cooperative document budget."""


def check_budget(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise CandidateRejected("jpeg_document_time_limit")


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare_tool(explicit: Path | None) -> tuple[Path, str, str]:
    found = explicit if explicit is not None else shutil.which("jpegtran")
    if not found or not Path(found).is_file():
        raise RuntimeError("jpegtran 3.2.0 not found; prepare it manually and use --jpegtran-path")
    path = Path(found).resolve()
    before = file_sha256(path)
    run = subprocess.run([str(path), "-version"], capture_output=True, timeout=10)
    version = (run.stdout + run.stderr).decode("utf-8", errors="replace").strip()
    if run.returncode or version.split(" (build ")[0] != "libjpeg-turbo version 3.2.0":
        raise RuntimeError(f"unsupported jpegtran version: {version}")
    if file_sha256(path) != before:
        raise RuntimeError("jpegtran changed during preparation")
    return path, version, before


def jpeg_header(data: bytes) -> tuple[bytes, tuple]:
    """Read SOF components and DQT, including markers between scans.

    Malformed or unsupported JPEG headers are errors, not quality rejections.
    Decoding and jpegtran -strict additionally validate the compressed payload.
    """
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("missing JPEG SOI")
    i, frame, tables = 2, None, {}
    while i < len(data):
        if data[i] != 255:
            i += 1
            continue
        while i < len(data) and data[i] == 255:
            i += 1
        if i >= len(data):
            break
        marker = data[i]
        i += 1
        if marker == 0 or 0xD0 <= marker <= 0xD7:
            continue
        if marker == 0xD9:
            if frame is None or not tables:
                raise ValueError("incomplete JPEG header")
            return frame, tuple(sorted(tables.items()))
        if i + 2 > len(data):
            break
        size = int.from_bytes(data[i:i + 2], "big")
        if size < 2 or i + size > len(data):
            raise ValueError("invalid JPEG marker length")
        payload = data[i + 2:i + size]
        if marker in (0xC0, 0xC1, 0xC2):
            if frame is not None or len(payload) < 6 or len(payload) != 6 + 3 * payload[5]:
                raise ValueError("invalid JPEG frame")
            frame = payload
        if marker == 0xDB:
            pos = 0
            while pos < len(payload):
                key, precision = payload[pos] & 15, payload[pos] >> 4
                if precision not in (0, 1):
                    raise ValueError("invalid DQT precision")
                end = pos + 1 + 64 * (precision + 1)
                if end > len(payload) or key in tables:
                    raise ValueError("invalid or redefined DQT")
                tables[key] = payload[pos:end]
                pos = end
        i += size
    raise ValueError("missing JPEG EOI")


def eligible(doc: fitz.Document, xref: int) -> bool:
    def get(key: str) -> tuple[str, str]:
        return doc.xref_get_key(xref, key)

    if not (
        get("Filter") == ("name", "/DCTDecode")
        and get("BitsPerComponent") == ("int", "8")
        and get("ColorSpace") in (("name", "/DeviceRGB"), ("name", "/DeviceGray"))
        and get("ImageMask") in (("null", "null"), ("bool", "false"))
        and all(get(k)[0] == "null" for k in ("Mask", "SMask", "Decode", "DecodeParms"))
    ):
        return False
    width, height = int(get("Width")[1]), int(get("Height")[1])
    if width <= 0 or height <= 0:
        raise ValueError("invalid PDF image dimensions")
    return width * height <= RECIPE["max_pixels"]


def same_pixels(left: bytes, right: bytes) -> bool:
    a, b = fitz.Pixmap(left), fitz.Pixmap(right)
    return (a.width, a.height, a.n, a.alpha, a.samples) == (b.width, b.height, b.n, b.alpha, b.samples)


def replace_stream(doc: fitz.Document, xref: int, data: bytes) -> None:
    """Keep every dictionary entry except the necessarily changed Length."""
    before = {k: doc.xref_get_key(xref, k) for k in doc.xref_get_keys(xref) if k != "Length"}
    doc.update_stream(xref, data, compress=False)
    doc.xref_set_key(xref, "Filter", "/DCTDecode")
    after = {k: doc.xref_get_key(xref, k) for k in doc.xref_get_keys(xref) if k != "Length"}
    if before != after:
        raise RuntimeError("JPEG image dictionary changed")


def optimize(source: Path, candidate: Path, cfg: RunConfig, qpdf: Path, *, progressive: bool, deadline: float) -> int:
    check_budget(deadline)
    if cfg.jpegtran_path is None or file_sha256(cfg.jpegtran_path) != cfg.jpegtran_sha256:
        raise RuntimeError("jpegtran missing or changed after preparation")
    changed = 0
    with tempfile.TemporaryDirectory(prefix="jpeg-", dir=candidate.parent) as workspace:
        work = Path(workspace)
        with fitz.open(source) as doc:
            if doc.is_repaired:
                raise RuntimeError("JPEG source required repair")
            xrefs = set()
            for page in doc:
                check_budget(deadline)
                xrefs.update(img[0] for img in page.get_images(full=True) if img[0] > 0)
            for xref in sorted(xrefs):
                check_budget(deadline)
                if not eligible(doc, xref):
                    continue
                # Inspect stored length before loading the compressed stream.
                if int(doc.xref_get_key(xref, "Length")[1]) > RECIPE["max_stream_bytes"]:
                    continue
                raw = doc.xref_stream_raw(xref)
                if not raw:
                    raise ValueError("empty DCT stream")
                if len(raw) > RECIPE["max_stream_bytes"]:
                    continue
                header = jpeg_header(raw)
                frame = header[0]
                height, width = int.from_bytes(frame[1:3], "big"), int.from_bytes(frame[3:5], "big")
                if width * height > RECIPE["max_pixels"]:
                    continue
                expected_components = 3 if doc.xref_get_key(xref, "ColorSpace")[1] == "/DeviceRGB" else 1
                if frame[0] != 8 or frame[5] != expected_components or (width, height) != (int(doc.xref_get_key(xref, "Width")[1]), int(doc.xref_get_key(xref, "Height")[1])):
                    raise ValueError("JPEG frame disagrees with PDF image dictionary")
                input_jpeg, output_jpeg = work / "input.jpg", work / "output.jpg"
                input_jpeg.write_bytes(raw)
                cmd = [str(cfg.jpegtran_path), *RECIPE["arguments"]]
                if progressive:
                    cmd.append("-progressive")
                cmd.extend(["-outfile", str(output_jpeg), str(input_jpeg)])
                check_budget(deadline)
                run = subprocess.run(cmd, capture_output=True, timeout=RECIPE["call_seconds"])
                if run.returncode or run.stderr.strip():
                    raise RuntimeError(f"jpegtran failed (rc={run.returncode}): {run.stderr[-500:]!r}")
                check_budget(deadline)
                if not output_jpeg.is_file() or output_jpeg.stat().st_size == 0:
                    raise RuntimeError("jpegtran produced no JPEG")
                # A larger stream cannot be adopted; bound reads/decodes of it.
                if output_jpeg.stat().st_size > RECIPE["max_stream_bytes"]:
                    raise CandidateRejected("jpeg_candidate_stream_limit")
                encoded = output_jpeg.read_bytes()
                if jpeg_header(encoded) != header:
                    raise CandidateRejected("jpeg_header_mismatch")
                if not same_pixels(raw, encoded):
                    raise CandidateRejected("jpeg_pixel_mismatch")
                check_budget(deadline)
                if len(encoded) < len(raw):
                    replace_stream(doc, xref, encoded)
                    changed += 1
            if not changed:
                return 0
            intermediate = work / "streams.pdf"
            doc.save(intermediate, garbage=0, deflate=False, raise_on_repair=True)
        check_budget(deadline)
        qpdf_optimize(qpdf, intermediate, candidate, cfg.qpdf, reject_warnings=True)
        check_budget(deadline)
    return changed


def validate_exact(source: Path, candidate: Path, deadline: float) -> None:
    """qpdf is checked by the caller; this adds exact content/render checks."""
    check_budget(deadline)
    with fitz.open(source) as src, fitz.open(candidate) as dst:
        if src.is_repaired or dst.is_repaired:
            raise RuntimeError("JPEG candidate required PDF repair")
        if src.page_count != dst.page_count:
            raise RuntimeError("JPEG candidate page count mismatch")
        for sp, dp in zip(src, dst):
            check_budget(deadline)
            if (sp.rotation, sp.mediabox, sp.cropbox, sp.rect) != (dp.rotation, dp.mediabox, dp.cropbox, dp.rect):
                raise RuntimeError("JPEG candidate geometry mismatch")
            if sp.get_text() != dp.get_text() or sp.get_drawings() != dp.get_drawings():
                raise RuntimeError("JPEG candidate text/path mismatch")
            for dpi in (72, 300):
                # Tile full pages to bound memory even on oversized pages.
                scale = dpi / 72
                width, height = sp.rect.width, sp.rect.height
                step = 512 / scale
                y = 0.0
                while y < height:
                    x = 0.0
                    while x < width:
                        check_budget(deadline)
                        clip = fitz.Rect(x, y, min(x + step, width), min(y + step, height))
                        a = sp.get_pixmap(dpi=dpi, clip=clip, colorspace=fitz.csRGB, alpha=False)
                        b = dp.get_pixmap(dpi=dpi, clip=clip, colorspace=fitz.csRGB, alpha=False)
                        if (a.width, a.height, a.n, a.samples) != (b.width, b.height, b.n, b.samples):
                            raise CandidateRejected(f"jpeg_render_mismatch_page_{sp.number + 1}_{dpi}dpi")
                        x += step
                    y += step
    check_budget(deadline)
