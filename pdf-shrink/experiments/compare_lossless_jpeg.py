"""Independent CP-009 experiment; never called by the product CLI.

Run with the PDF project's Python. Tools must already be prepared manually.
The output directory must not exist. No input or prior output is overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

import pymupdf as fitz

from pdf_shrink.config import QpdfOptions
from pdf_shrink.qpdf import qpdf_optimize


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def jpeg_header(data: bytes) -> tuple:
    """Compare precision, dimensions, component descriptors and all DQT tables.

    Read all markers, including DQT between progressive scans. Entropy data is
    skipped with JPEG byte-stuffing and restart markers respected.
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
        marker = data[i]
        i += 1
        if marker == 0 or 0xD0 <= marker <= 0xD7:
            continue
        if marker == 0xD9:
            if frame is None or not tables:
                raise ValueError("incomplete JPEG header")
            return frame, tuple(sorted(tables.items()))
        size = int.from_bytes(data[i:i + 2], "big")
        if size < 2 or i + size > len(data):
            raise ValueError("invalid JPEG marker length")
        payload = data[i + 2:i + size]
        if marker in (0xC0, 0xC1, 0xC2):
            if frame is not None:
                raise ValueError("multiple frames")
            frame = payload
        if marker == 0xDB:
            pos = 0
            while pos < len(payload):
                key = payload[pos] & 15
                precision = payload[pos] >> 4
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
    get = lambda key: doc.xref_get_key(xref, key)
    return (
        get("Filter") == ("name", "/DCTDecode")
        and get("BitsPerComponent") == ("int", "8")
        and get("ColorSpace") in (("name", "/DeviceRGB"), ("name", "/DeviceGray"))
        and get("ImageMask") in (("null", "null"), ("bool", "false"))
        and all(get(k)[0] == "null" for k in ("Mask", "SMask", "Decode", "DecodeParms"))
        and int(get("Width")[1]) * int(get("Height")[1]) <= 20_000_000
    )


def pixels(data: bytes) -> tuple:
    pix = fitz.Pixmap(data)
    return pix.width, pix.height, pix.n, pix.alpha, pix.samples


def strict_pdf_check(source: Path, candidate: Path, qpdf: Path) -> dict:
    checked = subprocess.run([str(qpdf), "--check", str(candidate)], capture_output=True, timeout=300)
    if checked.returncode:
        raise RuntimeError(f"qpdf check rc={checked.returncode}: {checked.stderr!r}")
    pages = []
    with fitz.open(source) as src, fitz.open(candidate) as dst:
        if src.page_count != dst.page_count:
            return {"valid": False, "reason": "page_count"}
        for sp, dp in zip(src, dst):
            if (sp.rotation, sp.mediabox, sp.cropbox, sp.rect) != (dp.rotation, dp.mediabox, dp.cropbox, dp.rect):
                return {"valid": False, "reason": "geometry"}
            if sp.get_text() != dp.get_text() or sp.get_drawings() != dp.get_drawings():
                return {"valid": False, "reason": "text_or_paths"}
            # Full-page RGB equality at both screen and 300 DPI resolutions.
            for dpi in (72, 300):
                a = sp.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
                b = dp.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
                if (a.width, a.height, a.n, a.samples) != (b.width, b.height, b.n, b.samples):
                    return {"valid": False, "reason": f"rgb_page_{sp.number + 1}_{dpi}dpi"}
            pages.append(sp.number + 1)
    return {"valid": True, "pages": pages, "rgb_dpi": [72, 300], "qpdf_rc": 0}


def compare(source: Path, folder: Path, jpegtran: Path, qpdf: Path) -> dict:
    folder.mkdir()
    original = folder / "original.pdf"
    shutil.copy2(source, original)
    result = {"source": str(source), "source_sha256": sha(source), "original_bytes": source.stat().st_size, "candidates": []}
    for kind in ("qpdf", "baseline", "progressive"):
        started = time.monotonic()
        candidate = folder / f"{kind}.pdf"
        images = []
        intermediate = original
        if kind != "qpdf":
            with fitz.open(original) as doc:
                xrefs = sorted({img[0] for page in doc for img in page.get_images(full=True) if img[0] > 0})
                for xref in xrefs:
                    if time.monotonic() - started > 300:
                        raise RuntimeError("experiment document budget exceeded")
                    if not eligible(doc, xref):
                        images.append({"xref": xref, "result": "ineligible"})
                        continue
                    raw = doc.xref_stream_raw(xref)
                    if len(raw) > 32 * 1024 * 1024:
                        images.append({"xref": xref, "result": "stream_limit"})
                        continue
                    cmd = [str(jpegtran), "-copy", "all", "-optimize", "-maxmemory", "128M", "-maxscans", "100", "-strict"]
                    if kind == "progressive":
                        cmd.append("-progressive")
                    run = subprocess.run(cmd, input=raw, capture_output=True, timeout=30)
                    if run.returncode or run.stderr.strip():
                        raise RuntimeError(f"jpegtran rc={run.returncode}: {run.stderr!r}")
                    output = run.stdout
                    same_header = jpeg_header(raw) == jpeg_header(output)
                    same_pixels = pixels(raw) == pixels(output)
                    smaller = len(output) < len(raw)
                    row = {"xref": xref, "before": len(raw), "after": len(output), "same_header": same_header, "same_pixels": same_pixels, "selected": same_header and same_pixels and smaller}
                    images.append(row)
                    if row["selected"]:
                        dictionary = {key: doc.xref_get_key(xref, key) for key in doc.xref_get_keys(xref) if key != "Length"}
                        doc.update_stream(xref, output, compress=False)
                        doc.xref_set_key(xref, "Filter", "/DCTDecode")
                        after = {key: doc.xref_get_key(xref, key) for key in doc.xref_get_keys(xref) if key != "Length"}
                        if dictionary != after:
                            raise RuntimeError("image dictionary changed")
                intermediate = folder / f"{kind}-streams.pdf"
                doc.save(intermediate, garbage=0, deflate=False, raise_on_repair=True)
        qpdf_optimize(qpdf, intermediate, candidate, QpdfOptions())
        row = {"kind": kind, "bytes": candidate.stat().st_size, "sha256": sha(candidate), "images": images, "validation": strict_pdf_check(original, candidate, qpdf), "seconds": time.monotonic() - started}
        result["candidates"].append(row)
        print(json.dumps({k: v for k, v in row.items() if k != "images"}), flush=True)
    baseline_size = result["candidates"][0]["bytes"]
    for row in result["candidates"][1:]:
        saved = baseline_size - row["bytes"]
        row["saved_vs_qpdf"] = saved
        row["fraction_vs_qpdf"] = saved / baseline_size
        row["integration_gate"] = row["validation"]["valid"] and saved >= 16 * 1024 and saved / baseline_size >= 0.02
    if sha(source) != result["source_sha256"]:
        raise RuntimeError("source changed")
    (folder / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jpegtran", type=Path, required=True)
    parser.add_argument("--qpdf", type=Path, required=True)
    parser.add_argument("--protect", type=Path, action="append", default=[])
    args = parser.parse_args()
    source, target = args.input.resolve(), args.output.resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("input and output must be separate")
    target.mkdir(parents=True, exist_ok=False)
    protected = {str(p): sha(p) for root in [source, *args.protect] for p in root.rglob("*") if p.is_file()}
    (target / "protected-before.json").write_text(json.dumps(protected, ensure_ascii=False, indent=2), encoding="utf-8")
    version_run = subprocess.run([str(args.jpegtran), "-version"], capture_output=True, check=True, timeout=10)
    version = (version_run.stdout + version_run.stderr).decode().strip()
    if version != "libjpeg-turbo version 3.2.0 (build 20260630)":
        raise RuntimeError(f"unexpected jpegtran version: {version}")
    results = {"jpegtran": {"path": str(args.jpegtran), "version": version, "sha256": sha(args.jpegtran)}, "pymupdf": fitz.VersionBind, "documents": []}
    for index, path in enumerate(sorted(source.glob("*.pdf")), 1):
        if path.name.startswith(("2.", "5.")):
            results["documents"].append(compare(path, target / f"photo-{index}", args.jpegtran, args.qpdf))
    results["integration_gate"] = any(c.get("integration_gate", False) for d in results["documents"] for c in d["candidates"])
    results["protected_unchanged"] = all(sha(Path(p)) == digest for p, digest in protected.items())
    (target / "comparison.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"integration_gate": results["integration_gate"], "protected_unchanged": results["protected_unchanged"]}))


if __name__ == "__main__":
    main()
