from __future__ import annotations

import csv
import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess

from PIL import Image
import pytest

import media_shrink.image as image_module
from media_shrink.cli import main
from media_shrink.config import ImageConfig
from media_shrink.image import (
    MARKER_ID,
    calculate_output_size,
    error_report_path,
    plan_outputs,
    process_image,
)
from media_shrink.utils import PathValidationError


@pytest.mark.parametrize(
    ("source_size", "expected"),
    [
        ((4032, 3024), (1280, 960)),
        ((3024, 4032), (960, 1280)),
        ((3000, 3000), (960, 960)),
        ((4000, 300), (1280, 96)),
        ((300, 4000), (96, 1280)),
        ((640, 480), (640, 480)),
    ],
)
def test_fixed_dimension_recipe(source_size: tuple[int, int], expected: tuple[int, int]) -> None:
    assert calculate_output_size(source_size) == expected


def test_transparent_png_is_white_jpeg_with_marker_and_source_is_unchanged(tmp_path: Path) -> None:
    source = tmp_path / "input" / "alpha.png"
    output = tmp_path / "output" / "alpha.png.jpg"
    source.parent.mkdir()
    Image.new("RGBA", (32, 24), (255, 0, 0, 0)).save(source)
    source_bytes = source.read_bytes()

    result = process_image(source, output, ImageConfig(workers=1))

    assert result["action"] == "CONVERTED"
    assert "ALPHA_FLATTENED" in result["warnings"]
    assert source.read_bytes() == source_bytes
    with Image.open(output) as converted:
        assert converted.format == "JPEG"
        assert converted.getpixel((16, 12)) == pytest.approx((255, 255, 255), abs=3)
        assert MARKER_ID.encode("ascii") in converted.info["comment"]


def test_orientation_is_applied_and_existing_comment_is_preserved(tmp_path: Path) -> None:
    source = tmp_path / "rotated.jpg"
    output = tmp_path / "out" / "rotated.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (40, 20), "navy").save(
        source,
        "JPEG",
        quality=95,
        exif=exif,
        comment=b"legacy-comment",
    )
    output.parent.mkdir()
    shutil.copy2(source, output)

    result = process_image(source, output, ImageConfig(workers=1))

    assert result["action"] == "CONVERTED"
    with Image.open(output) as converted:
        assert converted.size == (20, 40)
        assert converted.getexif().get(274) is None
        assert b"legacy-comment\n" + MARKER_ID.encode("ascii") in converted.info["comment"]


def test_output_names_preserve_jpeg_suffix_and_hash_every_collision_member(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    sources = [
        input_dir / "photo.png",
        input_dir / "photo.png.jpg",
        input_dir / "kept.jpeg",
    ]

    plans = plan_outputs(input_dir, output_dir, sources)

    png_hash = hashlib.sha256("photo.png".encode()).hexdigest()[:8]
    jpeg_hash = hashlib.sha256("photo.png.jpg".encode()).hexdigest()[:8]
    assert plans[0].output.name == f"photo.png~{png_hash}.jpg"
    assert plans[1].output.name == f"photo.png~{jpeg_hash}.jpg"
    assert plans[2].output.name == "kept.jpeg"
    assert len({plan.output.name.casefold() for plan in plans}) == 3


def test_hash_generated_name_cannot_collide_with_an_unrelated_base_name(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    first_hash = hashlib.sha256("photo.png".encode()).hexdigest()[:8]
    sources = [
        input_dir / "photo.png",
        input_dir / "photo.png.jpg",
        input_dir / f"photo.png~{first_hash}.jpg",
    ]

    plans = plan_outputs(input_dir, output_dir, sources)

    names = [plan.output.name.casefold() for plan in plans]
    assert len(set(names)) == 3
    assert plans[2].output.name.startswith(f"photo.png~{first_hash}~")


def test_output_file_directory_prefix_collision_hashes_the_file_output(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    sources = [
        input_dir / "photo.png",
        input_dir / "photo.png.jpg" / "child.png",
    ]

    plans = plan_outputs(input_dir, output_dir, sources)

    assert plans[0].output.name != "photo.png.jpg"
    assert plans[0].output.name.startswith("photo.png~")
    assert plans[1].output.relative_to(output_dir).as_posix() == "photo.png.jpg/child.png.jpg"


def test_generated_marker_detection_is_case_insensitive_and_copies_bytes(tmp_path: Path) -> None:
    source = tmp_path / "old-generated.jpg"
    output = tmp_path / "out" / "old-generated.jpg"
    Image.new("RGB", (24, 16), "green").save(
        source,
        "JPEG",
        comment=b"KaruFile:image-v0;recipe=old",
    )
    source_bytes = source.read_bytes()

    result = process_image(source, output, ImageConfig(workers=1))

    assert result["action"] == "SKIPPED_GENERATED"
    assert output.read_bytes() == source_bytes


def test_generated_marker_precedes_same_stat_copy_reuse(tmp_path: Path) -> None:
    source = tmp_path / "generated.jpg"
    output = tmp_path / "out" / "generated.jpg"
    Image.new("RGB", (24, 16), "red").save(
        source,
        "JPEG",
        quality=90,
        comment=b"KaruFile:image-v0;recipe=old",
    )
    output.parent.mkdir()
    Image.new("RGB", (24, 16), "blue").save(
        output,
        "JPEG",
        quality=90,
        comment=b"KaruFile:image-v0;recipe=old",
    )
    assert output.stat().st_size == source.stat().st_size
    source_stat = source.stat()
    os.utime(output, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))

    result = process_image(source, output, ImageConfig(workers=1))

    assert result["action"] == "SKIPPED_GENERATED"
    assert output.read_bytes() == source.read_bytes()


def test_completed_output_is_reused_then_invalidated_by_source_stat_change(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "out" / "source.png.jpg"
    Image.new("RGB", (40, 30), "red").save(source)

    first = process_image(source, output, ImageConfig(workers=1))
    output_bytes = output.read_bytes()
    output_mtime = output.stat().st_mtime_ns
    second = process_image(source, output, ImageConfig(workers=1))

    assert first["action"] == "CONVERTED"
    assert second["action"] == "SKIPPED_COMPLETE"
    assert output.read_bytes() == output_bytes
    assert output.stat().st_mtime_ns == output_mtime

    previous = source.stat()
    Image.new("RGB", (42, 30), "blue").save(source)
    os.utime(source, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000_000))
    third = process_image(source, output, ImageConfig(workers=1))
    assert third["action"] != "SKIPPED_COMPLETE"
    assert third["new_dims"] == (42, 30)


def test_completed_output_reuse_accepts_negative_source_mtime(tmp_path: Path) -> None:
    source = tmp_path / "historical.png"
    output = tmp_path / "out" / "historical.png.jpg"
    Image.new("RGB", (40, 30), "red").save(source)
    historical_ns = -315_619_200_000_000_000
    try:
        os.utime(source, ns=(historical_ns, historical_ns))
    except OSError:
        pytest.skip("filesystem does not support pre-1970 mtimes")
    if source.stat().st_mtime_ns >= 0:
        pytest.skip("filesystem normalized the pre-1970 mtime")

    first = process_image(source, output, ImageConfig(workers=1))
    second = process_image(source, output, ImageConfig(workers=1))

    assert first["action"] == "CONVERTED"
    assert second["action"] == "SKIPPED_COMPLETE"


def test_small_jpeg_below_savings_threshold_is_copied_exactly(tmp_path: Path) -> None:
    source = tmp_path / "small.jpeg"
    output = tmp_path / "out" / "small.jpeg"
    Image.new("RGB", (80, 60), "orange").save(source, "JPEG", quality=80)
    source_bytes = source.read_bytes()

    result = process_image(source, output, ImageConfig(workers=1))

    assert result["action"] == "COPIED_ORIGINAL"
    assert output.read_bytes() == source_bytes
    assert output.stat().st_mtime_ns == source.stat().st_mtime_ns


def test_read_only_copied_output_can_be_replaced_without_temp_residue(tmp_path: Path) -> None:
    source = tmp_path / "small.jpeg"
    output = tmp_path / "out" / "small.jpeg"
    Image.new("RGB", (80, 60), "orange").save(source, "JPEG", quality=80)
    process_image(source, output, ImageConfig(workers=1))
    os.chmod(output, stat.S_IREAD)
    previous = source.stat()
    Image.new("RGB", (81, 60), "purple").save(source, "JPEG", quality=80)
    os.utime(source, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000_000))
    source_bytes = source.read_bytes()

    result = process_image(source, output, ImageConfig(workers=1))

    assert result["action"] == "COPIED_ORIGINAL"
    assert output.read_bytes() == source_bytes
    assert list(output.parent.glob(f".{output.name}.*.tmp")) == []


def test_required_jpeg_transform_failure_copies_original_but_reports_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "large.jpg"
    output = tmp_path / "out" / "large.jpg"
    Image.new("RGB", (1600, 1200), "teal").save(source, "JPEG", quality=90)
    source_bytes = source.read_bytes()

    def fail_save(*args: object, **kwargs: object) -> None:
        raise OSError("simulated encoder failure")

    monkeypatch.setattr(image_module, "_save_jpeg", fail_save)
    result = process_image(source, output, ImageConfig(workers=1))

    assert result["action"] == "COPIED_ENCODE_FAILED"
    assert "error" in result
    assert output.read_bytes() == source_bytes


@pytest.mark.parametrize("failure_point", ["resize", "exif_transpose"])
def test_jpeg_candidate_preparation_failure_copies_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    source = tmp_path / f"{failure_point}.jpg"
    output = tmp_path / "out" / source.name
    if failure_point == "resize":
        Image.new("RGB", (1600, 1200), "teal").save(source, "JPEG", quality=90)

        def fail_resize(*_args: object, **_kwargs: object) -> Image.Image:
            raise OSError("simulated resize failure")

        monkeypatch.setattr(Image.Image, "resize", fail_resize)
    else:
        exif = Image.Exif()
        exif[274] = 6
        Image.new("RGB", (40, 20), "teal").save(source, "JPEG", quality=90, exif=exif)

        def fail_transpose(*_args: object, **_kwargs: object) -> Image.Image:
            raise OSError("simulated orientation failure")

        monkeypatch.setattr(image_module.ImageOps, "exif_transpose", fail_transpose)
    source_bytes = source.read_bytes()

    result = process_image(source, output, ImageConfig(workers=1))

    assert result["action"] == "COPIED_ENCODE_FAILED"
    assert "error" in result
    assert output.read_bytes() == source_bytes


def test_oversized_comment_drops_comment_before_preservable_metadata(tmp_path: Path) -> None:
    source = tmp_path / "large-comment.jpg"
    output = tmp_path / "out" / source.name
    exif = Image.Exif()
    exif[305] = "KaruFile regression"
    Image.new("RGB", (1600, 1200), "navy").save(
        source,
        "JPEG",
        quality=90,
        comment=b"x" * 65_450,
        exif=exif,
    )

    result = process_image(source, output, ImageConfig(workers=1))

    assert result["action"] == "CONVERTED"
    assert "COMMENT_DROPPED" in result["warnings"]
    assert "METADATA_DROPPED" not in result["warnings"]
    with Image.open(output) as converted:
        assert converted.getexif().get(305) == "KaruFile regression"


def _create_windows_junction(link: Path, target: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows Junction regression")
    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip(f"could not create Junction: {completed.stderr or completed.stdout}")


def test_output_junction_escape_is_rejected_without_changing_source(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    source_dir = input_dir / "nested"
    output_dir = tmp_path / "output"
    source_dir.mkdir(parents=True)
    output_dir.mkdir()
    source = source_dir / "large.jpg"
    Image.new("RGB", (1600, 1200), "teal").save(source, "JPEG", quality=90)
    source_hash = hashlib.sha256(source.read_bytes()).digest()
    link = output_dir / "nested"
    _create_windows_junction(link, source_dir)
    try:
        assert main(["resize", "-i", str(input_dir), "-o", str(output_dir), "-j", "1"]) == 1
        assert hashlib.sha256(source.read_bytes()).digest() == source_hash
    finally:
        if link.exists():
            link.rmdir()


def test_output_internal_junction_alias_is_rejected(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    first = input_dir / "a" / "same.png"
    second = input_dir / "b" / "same.png"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    (output_dir / "b").mkdir(parents=True)
    Image.new("RGB", (40, 30), "red").save(first, "PNG")
    Image.new("RGB", (40, 30), "blue").save(second, "PNG")
    source_hashes = {
        first: hashlib.sha256(first.read_bytes()).digest(),
        second: hashlib.sha256(second.read_bytes()).digest(),
    }
    link = output_dir / "a"
    _create_windows_junction(link, output_dir / "b")
    try:
        assert main(["resize", "-i", str(input_dir), "-o", str(output_dir), "-j", "2"]) == 1
        assert all(
            hashlib.sha256(source.read_bytes()).digest() == expected
            for source, expected in source_hashes.items()
        )
        assert not (output_dir / "b" / "same.png.jpg").exists()
    finally:
        if link.exists():
            link.rmdir()


def test_input_junction_is_not_followed(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    external_dir = tmp_path / "external"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    external_dir.mkdir()
    external = external_dir / "photo.jpg"
    Image.new("RGB", (40, 30), "red").save(external, "JPEG")
    external_hash = hashlib.sha256(external.read_bytes()).digest()
    link = input_dir / "linked"
    _create_windows_junction(link, external_dir)
    try:
        assert main(["resize", "-i", str(input_dir), "-o", str(output_dir), "-j", "1"]) == 1
        assert hashlib.sha256(external.read_bytes()).digest() == external_hash
        assert not (output_dir / "linked" / "photo.jpg").exists()
    finally:
        if link.exists():
            link.rmdir()


def test_existing_output_hardlink_to_source_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    output = tmp_path / "out" / "source.jpg"
    output.parent.mkdir()
    Image.new("RGB", (40, 30), "red").save(source, "JPEG")
    try:
        os.link(source, output)
    except OSError:
        pytest.skip("filesystem does not support hardlinks")

    with pytest.raises(PathValidationError):
        process_image(source, output, ImageConfig(workers=1))

    assert os.path.samefile(source, output)


def test_cli_records_decode_error_returns_one_and_clears_stale_report(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    broken = input_dir / "broken.png"
    broken.write_bytes(b"not an image")
    original_bytes = broken.read_bytes()

    exit_code = main(["resize", "-i", str(input_dir), "-o", str(output_dir), "-j", "1"])

    assert exit_code == 1
    assert broken.read_bytes() == original_bytes
    report = error_report_path(output_dir.resolve())
    with report.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["source"] == str(broken.resolve())
    assert rows[0]["planned_output"].endswith("broken.png.jpg")
    assert "Resized 0 images (1 errors)" in capsys.readouterr().out

    Image.new("RGB", (10, 10), "white").save(broken, "PNG")
    assert main(["resize", "-i", str(input_dir), "-o", str(output_dir), "-j", "1"]) == 0
    assert report.read_text(encoding="utf-8") == "source,planned_output,error\n"


def test_cli_empty_input_reports_zero_sizes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    assert main(["resize", "-i", str(input_dir), "-o", str(output_dir)]) == 0

    output = capsys.readouterr().out
    assert "Resized 0 images (0 errors)" in output
    assert "0.00 B -> 0.00 B" in output


def test_cli_replaces_read_only_error_report(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    report = error_report_path(output_dir.resolve())
    report.write_text("stale\n", encoding="utf-8")
    os.chmod(report, stat.S_IREAD)

    assert main(["resize", "-i", str(input_dir), "-o", str(output_dir)]) == 0

    assert report.read_text(encoding="utf-8") == "source,planned_output,error\n"
    assert list(report.parent.glob(f".{report.name}.*.tmp")) == []


def test_cli_rejects_error_report_path_that_contains_input(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    input_dir = Path(f"{output_dir}.image-errors.csv") / "input"
    input_dir.mkdir(parents=True)

    assert main(["resize", "-i", str(input_dir), "-o", str(output_dir)]) == 1
    assert not output_dir.exists()


@pytest.mark.parametrize("relationship", ["same", "output_child", "input_child"])
def test_cli_rejects_equal_and_parent_child_directories(tmp_path: Path, relationship: str) -> None:
    if relationship == "same":
        input_dir = tmp_path / "input"
        output_dir = input_dir
    elif relationship == "output_child":
        input_dir = tmp_path / "input"
        output_dir = input_dir / "output"
    else:
        output_dir = tmp_path / "output"
        input_dir = output_dir / "input"
    input_dir.mkdir(parents=True)

    assert main(["resize", "-i", str(input_dir), "-o", str(output_dir)]) == 1


def test_dry_run_writes_only_the_sibling_report(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    source = input_dir / "photo.png"
    Image.new("RGB", (12, 8), "purple").save(source)
    source_bytes = source.read_bytes()

    exit_code = main(["resize", "-i", str(input_dir), "-o", str(output_dir), "--dry-run"])

    assert exit_code == 0
    assert source.read_bytes() == source_bytes
    assert not output_dir.exists()
    assert error_report_path(output_dir.resolve()).read_text(encoding="utf-8") == (
        "source,planned_output,error\n"
    )


def test_relative_dot_input_default_output_is_a_sibling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    Image.new("RGB", (8, 8), "black").save(input_dir / "photo.png")
    monkeypatch.chdir(input_dir)

    assert main(["resize", "-i", ".", "--dry-run"]) == 0

    default_output = Path(f"{input_dir.resolve()}_resized")
    assert not default_output.exists()
    assert error_report_path(default_output).is_file()
