from pathlib import Path
import csv
import subprocess
import sys

import pytest
from PIL import Image

import media_shrink.image as processor
from media_shrink.cli import main
from media_shrink.config import ImageConfig


@pytest.mark.parametrize("fmt", ["jpeg", "png", "webp"])
@pytest.mark.parametrize("source_format", ["jpeg", "png", "webp"])
@pytest.mark.parametrize("strip", [False, True])
def test_format_exif_orientation_and_resume(tmp_path, fmt, source_format, strip):
    source = tmp_path / f"source.{source_format}"
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = "private artist"
    exif[34853] = {1: "N", 2: (35, 0, 0)}
    Image.new("RGB", (60, 40), "red").save(source, exif=exif)
    original = source.read_bytes()
    output = tmp_path / "out" / f"result.{fmt}"
    config = ImageConfig(output_format=fmt, strip_exif=strip)
    result = processor.process_image(source, output, config)
    assert result["action"] == "CONVERTED"
    with Image.open(output) as im:
        assert im.format == fmt.upper()
        assert im.size == (40, 60)
        assert not im.getexif().get(274)
        assert im.getexif().get(315) == (None if strip else "private artist")
        if strip:
            assert not im.info.get("exif")
        else:
            assert im.getexif().get_ifd(34853)[1] == "N"
    assert processor.process_image(source, output, config)["action"] == "SKIPPED_COMPLETE"
    assert source.read_bytes() == original


@pytest.mark.parametrize("fmt", ["png", "webp"])
def test_alpha_resize_and_cli_dry_run(tmp_path, fmt):
    source = tmp_path / "input"
    source.mkdir()
    Image.new("RGBA", (1600, 1200), (200, 0, 0, 100)).save(source / "alpha.png")
    output = tmp_path / "output"
    args = ["resize", "-i", str(source), "-o", str(output), "--format", fmt, "--strip-exif"]
    assert main(args) == 0
    path = output / ("alpha.png" if fmt == "png" else "alpha.png.webp")
    before = path.read_bytes()
    with Image.open(path) as im:
        assert im.size == (1280, 960)
        assert im.getpixel((100, 100))[3] == 100
    assert main(args + ["--dry-run"]) == 0
    assert path.read_bytes() == before


@pytest.mark.parametrize("fmt", ["jpeg", "png", "webp"])
def test_strip_forces_conversion_and_failure_retains_existing(tmp_path, monkeypatch, fmt):
    source = tmp_path / "input.jpg"
    exif = Image.Exif()
    exif[315] = "private"
    Image.new("RGB", (10, 10)).save(source, exif=exif)
    output = tmp_path / "out" / f"result.{fmt}"
    config = ImageConfig(output_format=fmt, strip_exif=True)
    assert processor.process_image(source, output, config)["action"] == "CONVERTED"
    existing = output.read_bytes()
    # Change the source so reuse is not possible.
    Image.new("RGB", (11, 10)).save(source, exif=exif)
    def fail(*args, **kwargs):
        raise OSError("encoder unavailable")
    monkeypatch.setattr(processor, "_save_image", fail)
    with pytest.raises(OSError, match="encoder unavailable"):
        processor.process_image(source, output, config)
    assert output.read_bytes() == existing


@pytest.mark.parametrize("fmt", ["jpeg", "png", "webp"])
def test_naming_collisions_are_unique(tmp_path, fmt):
    source = tmp_path / "input"
    name = "a.bmp"
    sources = [source / name, source / f"{name}.{fmt if fmt != 'jpeg' else 'jpg'}"]
    plans = processor.plan_outputs(source, tmp_path / "out", sources, fmt)
    assert len({p.output.as_posix().casefold() for p in plans}) == 2
    assert all("~" in plan.output.name for plan in plans)


def test_config_hash_binds_every_output_policy():
    configs = [ImageConfig(preset=p, output_format=f, strip_exif=s)
               for p in ("standard", "compact") for f in ("jpeg", "png", "webp")
               for s in (False, True)]
    assert len({c.recipe_hash for c in configs}) == 12


@pytest.mark.parametrize("fmt", ["jpeg", "png", "webp"])
@pytest.mark.parametrize("preset", ["standard", "compact"])
def test_root_cli_integration_and_manifest_policy(tmp_path, monkeypatch, fmt, preset):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "orchestrator"))
    import shrink_all

    source = tmp_path / "input"
    source.mkdir()
    exif = Image.Exif()
    exif[315] = "private"
    original = source / "source.jpg"
    Image.new("RGB", (1300, 1000), "red").save(original, exif=exif)
    original_bytes = original.read_bytes()
    output = tmp_path / "output"
    command = [sys.executable, str(root / "karufile.py"), "-i", str(source),
               "--output", str(output), "--preset", preset,
               "--image-format", fmt, "--image-strip-exif"]
    for extra in ([], [], ["--dry-run"]):
        run = subprocess.run(command + extra, cwd=root, capture_output=True, text=True)
        assert run.returncode == 0, run.stdout + run.stderr
    manifest = shrink_all.parse_image_manifest(Path(f"{output}.image-manifest.csv"))
    assert manifest["rows"][0]["action"] == "SKIPPED_COMPLETE"
    kwargs = dict(input_dir=source, output_dir=output, preset=preset, dry_run=False,
                  output_format=fmt, strip_exif=True)
    assert shrink_all.image_manifest_matches_inputs(manifest, [original], **kwargs)
    kwargs["strip_exif"] = False
    assert not shrink_all.image_manifest_matches_inputs(manifest, [original], **kwargs)
    completed = Path(manifest["rows"][0]["output_path"])
    with Image.open(completed) as im:
        assert im.format == fmt.upper()
        assert not im.getexif()
        assert max(im.size) <= (1024 if preset == "compact" else 1280)
    assert original.read_bytes() == original_bytes


@pytest.mark.parametrize("fmt", ["jpeg", "png", "webp"])
def test_policy_change_never_reuses_exif_output(tmp_path, fmt):
    source = tmp_path / "input.png"
    exif = Image.Exif()
    exif[315] = "private"
    Image.new("RGB", (20, 20)).save(source, exif=exif)
    output = tmp_path / "out" / f"result.{fmt}"
    processor.process_image(source, output, ImageConfig(output_format=fmt))
    result = processor.process_image(source, output, ImageConfig(output_format=fmt, strip_exif=True))
    assert result["action"] == "CONVERTED"
    with Image.open(output) as im:
        assert not im.getexif()


@pytest.mark.parametrize("fmt", ["png", "webp"])
def test_non_jpeg_encoder_failure_continues_independent_files(tmp_path, monkeypatch, fmt):
    source = tmp_path / "input"
    source.mkdir()
    for name in ("bad", "good"):
        Image.new("RGB", (20, 20)).save(source / f"{name}.jpg")
    output = tmp_path / "output"
    save = processor._save_image
    def fail_one(image, temporary, *args):
        if "bad" in str(temporary):
            raise OSError("injected encoding failure")
        return save(image, temporary, *args)
    monkeypatch.setattr(processor, "_save_image", fail_one)
    assert main(["resize", "-i", str(source), "-o", str(output), "--format", fmt]) == 1
    with Path(f"{output}.image-manifest.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["action"] for row in rows] == ["ERROR", "CONVERTED"]
    assert not (output / f"bad.jpg.{fmt}").exists()


@pytest.mark.parametrize("fmt", ["jpeg", "png", "webp"])
def test_candidate_with_exif_is_rejected_before_publication(tmp_path, monkeypatch, fmt):
    source = tmp_path / "input.png"
    Image.new("RGB", (20, 20)).save(source)
    output = tmp_path / "out" / f"result.{fmt}"
    config = ImageConfig(output_format=fmt, strip_exif=True)
    processor.process_image(source, output, config)
    previous = output.read_bytes()
    Image.new("RGB", (21, 20)).save(source)
    save = processor._save_image
    def inject_exif(image, temporary, marker, comment, metadata, warnings, cfg):
        exif = Image.Exif()
        exif[315] = "must not leak"
        return save(image, temporary, marker, comment,
                    dict(metadata, exif=exif.tobytes()), warnings, cfg)
    monkeypatch.setattr(processor, "_save_image", inject_exif)
    with pytest.raises(ValueError, match="EXIF remains"):
        processor.process_image(source, output, config)
    assert output.read_bytes() == previous


@pytest.mark.parametrize("fmt", ["jpeg", "png", "webp"])
def test_root_and_child_resolve_file_directory_collisions_equally(tmp_path, monkeypatch, fmt):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "orchestrator"))
    import shrink_all
    source = tmp_path / "input"
    source.mkdir()
    suffix = "jpg" if fmt == "jpeg" else fmt
    directory = source / f"a.bmp.{suffix}"
    directory.mkdir()
    files = [source / "a.bmp", directory / "b.png"]
    for file in files:
        Image.new("RGB", (10, 10)).save(file)
    output = tmp_path / "output"
    child = processor.plan_outputs(source, output, files, fmt)
    parent = shrink_all._plan_image_destinations(source, output, files, fmt)
    assert [(p.source, p.output) for p in child] == parent
    assert "~" in parent[0][1].name
