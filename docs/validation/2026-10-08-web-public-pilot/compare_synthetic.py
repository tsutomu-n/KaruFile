"""同じ合成入力を共通化前後で比較する。実写真/NAS/Pilotの代替ではない。"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import csv
import hashlib
from io import StringIO
import json
from pathlib import Path
import shutil

from PIL import Image, ImageCms, ImageDraw, JpegImagePlugin, PngImagePlugin

from media_shrink.cli import main as image_cli
from media_shrink.web_public import WebPublicConfig, run_web_public, verify_public


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(path):
    return {p.relative_to(path).as_posix(): digest(p)
            for p in sorted(path.rglob("*")) if p.is_file()}


def prepare(workspace):
    root = workspace / "input"
    if root.exists():
        return root
    root.mkdir()
    gradient = Image.linear_gradient("L").resize((2801, 1500)).convert("RGB")
    ImageDraw.Draw(gradient).rectangle((10, 20, 180, 250), fill="red")
    gradient.save(root / "landscape.jpg", quality=95)
    Image.new("RGB", (800, 2400), "green").save(root / "portrait.png")
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "synthetic private metadata"
    gradient.resize((2800, 1000)).save(root / "orientation.png", exif=exif)
    Image.new("RGB", (600, 400), "blue").save(root / "small.png")
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes()
    Image.new("LAB", (200, 150), (140, 135, 120)).save(root / "lab.tiff", icc_profile=profile)
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    Image.new("RGB", (320, 180), "orange").save(root / "synthetic.heic", quality=90,
                                               exif=exif, icc_profile=srgb)
    info = PngImagePlugin.PngInfo()
    info.add_text("private", "synthetic metadata")
    Image.new("RGBA", (900, 1500), (20, 80, 180, 100)).save(root / "alpha.png", pnginfo=info)
    lines = Image.new("RGB", (2800, 800), "white")
    draw = ImageDraw.Draw(lines)
    for x in range(0, 2800, 20):
        draw.line((x, 0, x, 799), fill="black", width=2)
    lines.save(root / "lines.png")
    Image.new("CMYK", (20, 30), (0, 50, 100, 0)).save(root / "cmyk.jpg")
    (root / "broken.jpg").write_bytes(b"not an image")
    resize_root = workspace / "resize-input"
    resize_root.mkdir()
    for name in ("landscape.jpg", "portrait.png", "orientation.png", "small.png"):
        shutil.copyfile(root / name, resize_root / name)
    return root


def image_snapshot(path):
    with Image.open(path) as image:
        image.load()
        icc = image.info.get("icc_profile", b"")
        # ICC creation time (24:36) and profile ID (84:100) may differ by process.
        icc_color = icc[:24] + bytes(12) + icc[36:84] + bytes(16) + icc[100:] if icc else b""
        return {"format": image.format, "dimensions": list(image.size), "mode": image.mode,
                "pixels_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
                "icc_color_sha256": hashlib.sha256(icc_color).hexdigest() if icc else None,
                "metadata_keys": sorted(image.info), "exif": sorted(image.getexif()),
                "text": getattr(image, "text", {}),
                "sampling": JpegImagePlugin.get_sampling(image) if image.format == "JPEG" else None,
                "progressive": bool(image.info.get("progressive"))}


def public_rows(result, out, config):
    rows = []
    for row in result.results:
        clean = {k: v for k, v in row.items()
                 if k not in ("output_path", "output_sha256", "source_mtime_ns")}
        if row["output_path"]:
            path = out / row["output_path"]
            assert digest(path) == row["output_sha256"]
            verify_public(path, config, (row["output_width"], row["output_height"]))
            clean["image"] = image_snapshot(path)
        rows.append(clean)
    return rows


def snapshot(workspace, phase):
    root = prepare(workspace)
    source_before = tree(root)
    resize_before = tree(workspace / "resize-input")
    phase_root = workspace / phase
    assert not phase_root.exists(), "Use a new phase; never overwrite previous runs"
    result = {"fixture_kind": "synthetic-only", "input_count": len(source_before),
              "source_sha256": source_before, "public": {}, "resize": {}}
    for kind in ("photo", "graphic"):
        config = WebPublicConfig(kind, workers=1)
        out = phase_root / kind
        dry_out = phase_root / (kind + "-dry-run")
        dry = run_web_public(root, dry_out, config, dry_run=True)
        assert not dry_out.exists()
        first = run_web_public(root, out, config)
        old_files = tree(first.files_dir)
        reused = run_web_public(root, out, config)
        assert first.run_id != reused.run_id
        assert tree(first.files_dir) == old_files
        for a, b in zip(first.results, reused.results):
            if a["action"] != "ERROR":
                assert b["action"] == "SKIPPED_COMPLETE"
                assert a["output_sha256"] == b["output_sha256"]
        manifest = json.loads((out / "manifest.web-public.json").read_text("utf-8"))
        assert manifest["results"] == reused.results
        result["public"][kind] = {"recipe": config.recipe, "recipe_hash": config.recipe_hash,
            "engine_versions": manifest["engine_versions"], "schema_version": manifest["schema_version"],
            "first_exit": first.exit_code, "reuse_exit": reused.exit_code, "dry_exit": dry.exit_code,
            "dry_no_writes": True, "old_run_unchanged": True, "reuse_bytes_equal": True,
            "first": public_rows(first, out, config), "reuse": public_rows(reused, out, config),
            "dry": public_rows(dry, dry_out, config)}
    for preset in ("standard", "compact"):
        out = phase_root / ("resize-" + preset)
        cli_args = ["resize", "-i", str(workspace / "resize-input"), "-o", str(out),
                    "--preset", preset, "--workers", "1"]
        rounds = []
        for _ in range(2):
            with redirect_stdout(StringIO()):
                code = image_cli(cli_args)
            assert code == 0
            with Path(str(out) + ".image-manifest.csv").open(encoding="utf-8", newline="") as stream:
                rows = []
                for row in csv.DictReader(stream):
                    path = Path(row.pop("output_path"))
                    row["source_path"] = Path(row["source_path"]).relative_to(workspace / "resize-input").as_posix()
                    assert digest(path) == row.pop("output_sha256")
                    row["image"] = image_snapshot(path)
                    rows.append(row)
            rounds.append({"exit": code, "rows": rows})
        result["resize"][preset] = rounds
    assert tree(root) == source_before
    assert tree(workspace / "resize-input") == resize_before
    result["originals_unchanged"] = True
    with redirect_stdout(StringIO()):
        result["cli_exit"] = [image_cli(["web-public", "-i", str(root), "-o", str(phase_root / "cli"),
                               "--file", name]) for name in ("small.png", "broken.jpg", "missing.jpg")]
    assert result["cli_exit"] == [0, 1, 2]
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    parser.add_argument("phase", choices=("baseline", "final"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    protected = tree(args.workspace / "baseline") if args.phase == "final" else None
    result = snapshot(args.workspace, args.phase)
    if protected is not None:
        assert tree(args.workspace / "baseline") == protected
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"phase": args.phase, "synthetic_inputs": result["input_count"],
                      "originals_unchanged": result["originals_unchanged"], "exit_codes": result["cli_exit"],
                      "previous_phase_unchanged": protected is not None}))
