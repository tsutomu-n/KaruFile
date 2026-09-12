"""Developer-only read-only Excel oracle; no Excel dependency in the processor.

Run through uv run --project excel-shrink python excel-shrink/tools/probe_native.py.
Reject active/external content before asking Excel to open a workbook. Output is
geometry only, with no cell text, personal information or embedded image bytes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from excel_shrink.package import Budget, R, S, read_package
from excel_shrink.drawing import XDR, marker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pdf", action="store_true")
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if output.exists() or source == output:
        raise ValueError("Use a new, separate JSON output")
    package = read_package(source, Budget.start())
    denied = ("macro", "vba", "embedding", "connection", "externallink", "activex", "oleobject")
    if any(any(token in (name + package.types.get(name, "")).lower() for token in denied) for name in package.parts):
        raise ValueError("Native oracle excludes active or external parts")
    if any(rel.external for entries in package.relationships.values() for rel in entries.values()):
        raise ValueError("Native oracle excludes external relationships")
    if any(any(token in el.tag.lower() for token in denied) for root in package.xml.values() for el in root.iter()):
        raise ValueError("Native oracle excludes active or external XML")
    sheets = []
    book = package.xml["xl/workbook.xml"]
    for index, sheet in enumerate(book.find(f"{{{S}}}sheets"), 1):
        rel = package.relationships["xl/workbook.xml"][sheet.get(f"{{{R}}}id")]
        root = package.xml[rel.target]
        if root.tag != f"{{{S}}}worksheet":
            raise ValueError("Native oracle accepts ordinary worksheets only")
        max_col, max_row = 1, 1
        for drawing in root.findall(f"{{{S}}}drawing"):
            target = package.relationships[rel.target][drawing.get(f"{{{R}}}id")].target
            for anchor in package.xml[target]:
                for name in ("from", "to"):
                    el = anchor.find(f"{{{XDR}}}{name}")
                    if el is not None:
                        col, row, _, _ = marker(el)
                        max_col, max_row = max(max_col, col + 1), max(max_row, row + 1)
        if max_col > 256 or max_row > 10000:
            raise ValueError("Native oracle grid limit")
        sheets.append(dict(index=index, columns=max_col, rows=max_row))
    output.parent.mkdir(parents=True, exist_ok=True)
    request_path = output.with_suffix(".request.json")
    with request_path.open("x", encoding="utf-8") as stream:
        json.dump(dict(source=str(source), output=str(output), pdf=str(output.with_suffix(".pdf")) if args.pdf else None,
                       sha256=hashlib.sha256(source.read_bytes()).hexdigest(), sheets=sheets), stream)
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-File", str(Path(__file__).with_suffix(".ps1")), "-RequestPath", str(request_path)], check=True)
    print(f"Native geometry saved: {output}")


if __name__ == "__main__":
    main()
