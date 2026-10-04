"""Run the two requested PNG/EXIF policies through the real folder CLI."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from PIL import Image


ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).with_name("png-exif-smoke.json")


def snapshot(path: Path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    results = []
    with tempfile.TemporaryDirectory(prefix="karufile-png-exif-") as directory:
        base = Path(directory)
        source = base / "input"
        (source / "nested").mkdir(parents=True)
        exif = Image.Exif()
        exif[274] = 6
        exif[315] = "synthetic artist"
        exif[36867] = "2026:09:30 00:00:00"
        exif[34853] = {1: "N", 2: (35, 0, 0)}
        Image.new("RGB", (60, 40), "red").save(source / "photo.jpg", exif=exif)
        Image.new("RGBA", (1600, 1200), (200, 0, 0, 100)).save(source / "nested" / "alpha.png")
        Image.new("RGB", (200, 150), "blue").save(
            source / "nested" / "scan.tiff",
            tiffinfo={274: 1, 315: "synthetic artist", 306: "2026:09:30 00:00:00"},
        )
        Image.new("RGB", (20, 10), "green").save(source / "small.bmp")
        (source / "ignored.txt").write_text("synthetic non-image", encoding="utf-8")
        originals = {path: snapshot(path) for path in source.rglob("*") if path.is_file()}

        for strip_exif in (False, True):
            output = base / ("stripped" if strip_exif else "preserved")
            command = [sys.executable, str(ROOT / "karufile.py"), "-i", str(source),
                       "--output", str(output), "--image-format", "png"]
            if strip_exif:
                command.append("--image-strip-exif")
            outputs = {}
            manifest_before_dry_run = None
            runs = []
            for phase, extra in (("normal", []), ("resume", []), ("dry-run", ["--dry-run"])):
                run = subprocess.run(command + extra, cwd=ROOT, capture_output=True,
                                     text=True, encoding="utf-8", errors="replace")
                assert run.returncode == 0, run.stdout + run.stderr
                manifest = Path(f"{output}.image-manifest.csv")
                rows = read_rows(Path(f"{output}.image-manifest.dry-run.csv")
                                 if extra else manifest)
                assert len(rows) == 4
                expected_action = {"normal": "CONVERTED", "resume": "SKIPPED_COMPLETE",
                                   "dry-run": "DRY_RUN"}[phase]
                assert all(row["action"] == expected_action for row in rows)
                assert all(row["output_format"] == "png" and
                           row["strip_exif"] == str(strip_exif).lower() for row in rows)
                if phase == "normal":
                    assert len(list(output.rglob("*.png"))) == 4
                    for row in rows:
                        completed = Path(row["output_path"])
                        outputs[completed] = snapshot(completed)
                        with Image.open(completed) as image:
                            assert image.format == "PNG"
                            assert max(image.size) <= 1280 and min(image.size) <= 960
                            if strip_exif:
                                assert "exif" not in image.info and not image.getexif()
                            elif Path(row["source_path"]).name == "photo.jpg":
                                assert image.size == (40, 60)
                                assert image.getexif()[315] == "synthetic artist"
                                assert image.getexif()[36867] == "2026:09:30 00:00:00"
                                assert image.getexif().get_ifd(34853)[1] == "N"
                                assert not image.getexif().get(274)
                            if completed.name == "alpha.png":
                                assert image.size == (1280, 960)
                                assert image.getpixel((100, 100))[3] == 100
                else:
                    assert all(snapshot(path) == before for path, before in outputs.items())
                if phase == "resume":
                    manifest_before_dry_run = snapshot(manifest)
                elif phase == "dry-run":
                    assert snapshot(manifest) == manifest_before_dry_run
                assert all(snapshot(path) == before for path, before in originals.items())
                assert not list(output.rglob("*.tmp"))
                runs.append({"phase": phase, "exit_code": run.returncode,
                             "image_count": len(rows), "actions": sorted({row["action"] for row in rows})})
            results.append({"strip_exif": strip_exif, "runs": runs,
                            "source_sha256_and_mtime_unchanged": True,
                            "output_sha256_and_mtime_unchanged_on_resume_and_dry_run": True,
                            "normal_manifest_unchanged_on_dry_run": True})
    EVIDENCE.write_text(json.dumps({"output_format": "png", "fixture_images": 4,
                                    "policies": results}, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(json.dumps({"evidence": str(EVIDENCE), "policies": 2, "cli_runs": 6,
                      "images_per_run": 4, "result": "passed"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
