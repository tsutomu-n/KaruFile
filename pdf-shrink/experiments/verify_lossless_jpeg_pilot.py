"""Read-only verification of CP-009/011 files; writes one new evidence JSON."""
import argparse
import csv
import json
from pathlib import Path

import pymupdf as fitz

from compare_lossless_jpeg import sha, strict_pdf_check


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--qpdf", type=Path, required=True)
    args = parser.parse_args()
    protected = json.loads((args.comparison / "protected-before.json").read_text(encoding="utf-8"))
    changed = [path for path, digest in protected.items() if sha(Path(path)) != digest]
    if changed:
        raise RuntimeError(f"protected files changed: {changed}")
    evidence = {"protected_files": len(protected), "protected_unchanged": True, "cases": {}}
    for case in ("standard", "photo", "threshold-only", "dry-run"):
        report = args.pilot / case / ("report.dry-run.csv" if case == "dry-run" else "report.csv")
        with report.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 5
        results = []
        for row in rows:
            source, output = Path(row["source_path"]), Path(row["output_path"])
            assert sha(source) == row["source_sha256"]
            assert row["lossless_jpeg_requested"] == ("false" if case == "threshold-only" else "true")
            detail = json.loads(row["candidate_details"])
            selected = [c for c in detail if c["selected"]]
            if case == "dry-run":
                assert not output.exists() and row["output_size"] == "" and not selected
                assert row["status"] in ("DRY_RUN_LOSSLESS", "DRY_RUN_LOSSY")
                validation = {"no_completed_output": True}
            else:
                assert len(selected) == 1
                assert output.stat().st_size == int(row["output_size"]) == selected[0]["size"]
                assert sha(output) == row["output_sha256"]
                assert source.stat().st_size - output.stat().st_size == int(row["saved_bytes"])
                if row["status"] == "ADOPTED_LOSSLESS":
                    validation = strict_pdf_check(source, output, args.qpdf)
                    assert validation["valid"]
                else:
                    with fitz.open(source) as a, fitz.open(output) as b:
                        assert a.page_count == b.page_count
                        assert all((p.rotation, p.rect, p.mediabox, p.cropbox, p.get_text(), p.get_drawings()) == (q.rotation, q.rect, q.mediabox, q.cropbox, q.get_text(), q.get_drawings()) for p, q in zip(a, b))
                    validation = {"geometry_text_paths_equal": True, "lossy_rgb_not_asserted_equal": True}
            results.append({"name": source.name, "source_bytes": int(row["source_size"]), "output_bytes": int(row["output_size"]) if row["output_size"] else None, "saved_bytes": int(row["saved_bytes"]), "status": row["status"], "selected": selected[0]["kind"] if selected else None, "validation": validation})
        evidence["cases"][case] = results
    rows = evidence["cases"]["threshold-only"]
    assert [(rows[i]["selected"], rows[i]["saved_bytes"]) for i in (0, 2, 3)] == [("lossless", 61345), ("lossless", 17346), ("lossless", 39453)]
    for case, rows in evidence["cases"].items():
        print(case, "saved", sum(row["saved_bytes"] for row in rows), "bytes")
    destination = args.pilot / "pilot-verification.json"
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=2)
    print(f"protected {len(protected)} files: unchanged; evidence: {destination}")


if __name__ == "__main__":
    main()
