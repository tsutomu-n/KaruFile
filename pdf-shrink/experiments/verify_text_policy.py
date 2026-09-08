"""Local acceptance pilot. Never overwrite an existing verification folder."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import time

import pymupdf as fitz


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def fixtures(folder):
    folder.mkdir()
    source = folder / "日本語文章.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=216, height=288)
        for index in range(18):
            page.insert_text((12, 22 + index * 13), "細字の確認 0123456789 調査報告", fontsize=7,
                             fontname="japan", color=(0.1, 0.15, 0.2))
        doc.save(source)
    with fitz.open(source) as doc:
        page = doc[0]
        page.draw_rect(fitz.Rect(8, 8, 207, 267))
        for y in range(30, 266, 26):
            page.draw_line((8, y), (207, y))
        doc.save(folder / "日本語罫線表.pdf")
        for dpi in (300, 600):
            pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB)
            with fitz.open() as scan:
                sp = scan.new_page(width=216, height=288)
                xref = sp.insert_image(sp.rect, pixmap=pix)
                scan.xref_set_key(xref, "ColorSpace", "/DeviceRGB")
                scan.xref_set_key(xref, "DecodeParms", "null")
                scan.save(folder / f"文章スキャン{dpi}.pdf")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protect", type=Path, action="append", default=[])
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    if args.output.exists():
        raise ValueError("verification output must be new")
    roots = [args.input.resolve(), *(p.resolve() for p in args.protect)]
    for root in roots:
        if not root.is_dir() or args.output.resolve().is_relative_to(root):
            raise ValueError(f"invalid protected root: {root}")
    protected = sorted({p for root in roots for p in root.rglob("*") if p.is_file()})
    baseline = {str(p): sha(p) for p in protected}
    args.output.mkdir(parents=True)
    write(args.output / "before.json", baseline)
    inputs = args.output / "synthetic-input"
    fixtures(inputs)
    baseline.update({str(p): sha(p) for p in inputs.glob("*.pdf")})
    write(args.output / "before.json", baseline)
    runs = []
    cases = [
        ("default-standard", args.input, ["--preset", "standard"]),
        ("default-compact", args.input, ["--preset", "compact"]),
        ("photo-two", args.input, ["--pdf-photo-pattern", "2.*.pdf", "--pdf-photo-pattern", "5.*.pdf", "--pdf-photo-dpi", "150"]),
        ("synthetic", inputs, ["--pdf-text-pattern", "*罫線表.pdf", "--pdf-text-scan-pattern", "文章スキャン*.pdf", "--pdf-preview"]),
        ("protected-preview", inputs, ["--pdf-preserve-pattern", "*", "--pdf-photo-pattern", "*", "--pdf-preview", "--pdf-preview-dpi", "150"]),
        ("dry-run", inputs, ["--pdf-text-pattern", "*罫線表.pdf", "--pdf-text-scan-pattern", "文章スキャン*.pdf", "--pdf-preview", "--dry-run"]),
    ]
    try:
        for name, source, options in cases:
            folder = args.output / name
            folder.mkdir()
            command = ["uv", "run", "--script", "karufile.py", "-i", str(source), "-o", str(folder / "files"), *options]
            started = time.monotonic()
            result = subprocess.run(command, cwd=repo, capture_output=True)
            (folder / "stdout.txt").write_bytes(result.stdout)
            (folder / "stderr.txt").write_bytes(result.stderr)
            report = folder / ("report.dry-run.csv" if "--dry-run" in options else "report.csv")
            with report.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            runs.append({"name": name, "command": command, "exit": result.returncode,
                         "seconds": round(time.monotonic() - started, 3), "rows": rows})
            write(args.output / "runs.json", runs)
            if result.returncode:
                raise RuntimeError(f"pilot failed: {name}; see logs")
            if name.startswith("default-"):
                assert len(rows) == 5
                assert all(r["status"] == "PRESERVED_ORIGINAL" and r["source_sha256"] == r["output_sha256"] and r["candidate_details"] == "[]" for r in rows)
            if name == "photo-two":
                assert sum(r["status"] == "ADOPTED_LOSSY" and r["profile"] == "photo" for r in rows) == 2
                assert sum(r["status"] == "PRESERVED_ORIGINAL" for r in rows) == 3
            if name == "protected-preview":
                data = json.loads((folder / "pdf-preview.json").read_text(encoding="utf-8"))
                assert all(len(item["variants"]) == 2 and item["preservation_reason"] == "explicit_preserve" for item in data["items"])
            if name == "dry-run":
                assert not list(folder.rglob("*.pdf")) and not list(folder.rglob("*.png")) and not list(folder.rglob("*.html"))
    finally:
        after = {path: sha(Path(path)) for path in baseline}
        write(args.output / "after.json", after)
        write(args.output / "summary.json", {"protected_files": len(baseline), "unchanged": baseline == after, "runs": runs})
        if baseline != after:
            raise RuntimeError("protected bytes changed")
    print(args.output)


if __name__ == "__main__":
    main()
