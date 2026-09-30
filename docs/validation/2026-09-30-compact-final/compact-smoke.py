"""Run compact in a fresh synthetic workspace; never use or overwrite user media."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile
import time

import pymupdf
from PIL import Image


REPO = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(paths: list[Path]) -> dict[str, tuple[str, int]]:
    return {str(path): (digest(path), path.stat().st_mtime_ns) for path in paths}


def run(label: str, command: list[str]) -> dict[str, object]:
    started = time.perf_counter()
    result = subprocess.run(command, cwd=REPO, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=300,
                            env={**os.environ, "PYTHONUTF8": "1"})
    (EVIDENCE / f"{label}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    assert result.returncode == 0, (label, result.returncode, result.stdout[-2000:], result.stderr[-2000:])
    return {"command": command, "exit_code": result.returncode,
            "seconds": round(time.perf_counter() - started, 3)}


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    workspace = Path(tempfile.mkdtemp(prefix="karufile-compact-final-20260930-"))
    source = workspace / "input"
    output = workspace / "output"
    source.mkdir()
    image = Image.frombytes("RGB", (2048, 1320), random.Random(4).randbytes(2048 * 1320 * 3))
    image.save(source / "photo.png")
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    with pymupdf.open() as doc:
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=encoded.getvalue())
        doc.save(source / "scan.pdf")

    generation = run("fixture", [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
        "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "0", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(source / "clip.mp4"),
    ])
    inputs = sorted(source.iterdir())
    input_snapshot = snapshot(inputs)
    command = ["uv", "run", "--script", str(REPO / "karufile.py"), "--preset", "compact",
               "-i", str(source), "-o", str(output), "--pdf-workers", "1",
               "--image-workers", "1", "--video-workers", "1"]
    normal = run("normal", command)
    assert snapshot(inputs) == input_snapshot
    outputs = sorted(output.rglob("*"))
    outputs = [path for path in outputs if path.is_file()]
    assert {path.name for path in outputs} == {"scan.pdf", "photo.png.jpg", "clip.mp4"}
    output_snapshot = snapshot(outputs)
    pdf = rows(workspace / "report.csv")
    images = rows(workspace / "output.image-manifest.csv")
    videos = rows(workspace / "output.video-report.csv")
    assert len(pdf) == len(images) == len(videos) == 1
    assert pdf[0]["status"] == "ADOPTED_LOSSY" and pdf[0]["classification"] == "raster_scan"
    assert images[0]["action"] == "CONVERTED"
    assert (int(images[0]["new_width"]), int(images[0]["new_height"])) == (1024, 660)
    assert videos[0]["status"] == "ADOPTED"
    assert rows(workspace / "output.image-errors.csv") == []
    resume = run("resume", command)
    assert snapshot(inputs) == input_snapshot
    assert snapshot(outputs) == output_snapshot
    assert rows(workspace / "output.image-manifest.csv")[0]["action"] == "SKIPPED_COMPLETE"
    assert rows(workspace / "output.video-report.csv")[0]["status"] == "SKIPPED_COMPLETE"
    # 画像エラーCSVは通常/dry-runで共有され、dry-runでも更新する契約。
    normal_reports = [workspace / "report.csv", workspace / "output.image-manifest.csv",
                      workspace / "output.video-report.csv"]
    report_snapshot = snapshot(normal_reports)
    dry_run = run("dry-run", [*command, "--dry-run"])
    assert snapshot(inputs) == input_snapshot
    assert snapshot(outputs) == output_snapshot
    assert {path for path in output.rglob("*") if path.is_file()} == set(outputs)
    assert snapshot(normal_reports) == report_snapshot
    assert not list(workspace.rglob("*.tmp"))
    evidence = {
        "fixture_kind": "synthetic", "workspace": str(workspace), "fixture": generation,
        "normal": normal, "resume": resume, "dry_run": dry_run,
        "source_snapshot": input_snapshot, "output_snapshot": output_snapshot,
        "pdf": pdf[0], "image": images[0], "video": videos[0],
        "checks": {"input_sha_and_mtime_unchanged": True, "output_sha_and_mtime_unchanged_on_resume_and_dry_run": True,
                   "normal_reports_unchanged_on_dry_run": True, "manifest_report_counts_match": True,
                   "no_temporary_files_remain": True},
    }
    (EVIDENCE / "compact-smoke-summary.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"workspace": str(workspace), "normal": normal["exit_code"],
                      "resume": resume["exit_code"], "dry_run": dry_run["exit_code"],
                      "statuses": [pdf[0]["status"], images[0]["action"], videos[0]["status"]]}))


if __name__ == "__main__":
    main()
