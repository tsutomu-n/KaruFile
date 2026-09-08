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
from media_shrink.config import (
    COMPACT_RECIPE,
    RECIPE_HASH,
    STANDARD_RECIPE,
    ImageConfig,
    ImagePreset,
    ImageRecipe,
)
from media_shrink.image import (
    MANIFEST_COLUMNS,
    MARKER_ID,
    calculate_output_size,
    error_report_path,
    manifest_path,
    plan_outputs,
    process_image,
    write_error_report,
    write_result_manifest,
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


def test_presets_keep_standard_recipe_compatible_and_define_compact_recipe() -> None:
    standard = ImageConfig()
    compact = ImageConfig(preset="compact")

    assert (standard.max_long, standard.max_short, standard.quality) == (1280, 960, 72)
    assert standard.recipe_hash == RECIPE_HASH == STANDARD_RECIPE.recipe_hash
    assert RECIPE_HASH == "2f60924f29b4cedccd15bd92d6dab4da72b22c1358c23e2edf1174fa3b70f420"
    assert (compact.max_long, compact.max_short, compact.quality) == (1024, 768, 60)
    assert compact.recipe_hash == COMPACT_RECIPE.recipe_hash
    assert compact.recipe_hash != standard.recipe_hash
    assert compact.subsampling == standard.subsampling == 2


@pytest.mark.parametrize(
    ("source_size", "expected"),
    [
        ((4032, 3024), (1024, 768)),
        ((3024, 4032), (768, 1024)),
        ((2000, 2000), (768, 768)),
        ((640, 480), (640, 480)),
    ],
)
def test_compact_dimension_recipe_preserves_aspect_and_never_upscales(
    source_size: tuple[int, int],
    expected: tuple[int, int],
) -> None:
    assert calculate_output_size(source_size, ImageConfig(preset="compact")) == expected


def test_unknown_preset_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown image preset"):
        ImageConfig(preset="unknown")  # type: ignore[arg-type]


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


@pytest.mark.parametrize(
    "marker",
    [
        b"KaruFile:image-v0;recipe=old",
        (
            f"{MARKER_ID};recipe={'f' * 64};src_size=1;src_mtime_ns=1"
        ).encode("ascii"),
    ],
)
def test_unknown_generated_marker_does_not_bypass_normal_jpeg_policy(
    tmp_path: Path,
    marker: bytes,
) -> None:
    source = tmp_path / "old-generated.jpg"
    output = tmp_path / "out" / "old-generated.jpg"
    Image.new("RGB", (24, 16), "green").save(
        source,
        "JPEG",
        comment=marker,
    )
    source_bytes = source.read_bytes()

    result = process_image(source, output, ImageConfig(workers=1))

    assert result["action"] in {"CONVERTED", "COPIED_ORIGINAL"}
    assert result["action"] != "SKIPPED_GENERATED"
    if result["action"] == "COPIED_ORIGINAL":
        assert output.read_bytes() == source_bytes


def test_unknown_generated_marker_does_not_enable_generated_shortcut(tmp_path: Path) -> None:
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

    assert result["action"] == "COPIED_ORIGINAL"
    assert output.read_bytes() == source.read_bytes()


def _mutate_source_content_preserving_size_and_mtime(source: Path) -> None:
    """公開直前の同一stat差し替えを再現する。"""

    original_stat = source.stat()
    payload = bytearray(source.read_bytes())
    assert payload
    payload[len(payload) // 2] ^= 0x01
    source.write_bytes(payload)
    assert source.stat().st_size == original_stat.st_size
    os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    if source.stat().st_mtime_ns != original_stat.st_mtime_ns:
        pytest.skip("filesystem did not preserve the requested nanosecond mtime")


@pytest.mark.parametrize(
    "marker",
    [
        b"KaruFile:image-v0;recipe=unknown",
        (
            f"{MARKER_ID};recipe={STANDARD_RECIPE.recipe_hash};"
            "src_size=1;src_mtime_ns=1;src_sha256=" + "0" * 64
        ).encode("ascii"),
    ],
    ids=("unknown-marker", "current-marker"),
)
def test_generated_copy_rejects_source_change_before_publish_and_preserves_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    marker: bytes,
) -> None:
    source = tmp_path / "generated.jpg"
    output = tmp_path / "out" / "generated.jpg"
    Image.new("RGB", (80, 60), "green").save(source, "JPEG", comment=marker)
    output.parent.mkdir()
    Image.new("RGB", (16, 12), "navy").save(output, "JPEG")
    healthy_output = output.read_bytes()
    original_replace = image_module._replace_staged

    def mutate_then_replace(*args: object, **kwargs: object) -> None:
        _mutate_source_content_preserving_size_and_mtime(source)
        original_replace(*args, **kwargs)

    monkeypatch.setattr(image_module, "_replace_staged", mutate_then_replace)

    with pytest.raises(image_module.SourceChangedError, match="Source changed"):
        process_image(source, output, ImageConfig(workers=1))

    assert output.read_bytes() == healthy_output
    assert list(output.parent.glob(f".{output.name}.*.tmp")) == []


def test_compact_resizes_oversized_jpeg_even_with_unknown_generated_marker(
    tmp_path: Path,
) -> None:
    source = tmp_path / "oversized-generated.jpg"
    output = tmp_path / "out" / source.name
    Image.new("RGB", (1600, 1200), "green").save(
        source,
        "JPEG",
        quality=90,
        comment=b"KaruFile:image-v0;recipe=unknown",
    )

    result = process_image(source, output, ImageConfig(workers=1, preset="compact"))

    assert result["action"] == "CONVERTED"
    assert result["new_dims"] == (1024, 768)
    with Image.open(output) as converted:
        assert converted.size == (1024, 768)


@pytest.mark.parametrize(
    ("source_recipe", "target_preset"),
    [
        (STANDARD_RECIPE, "standard"),
        (COMPACT_RECIPE, "compact"),
        (COMPACT_RECIPE, "standard"),
    ],
)
def test_generated_jpeg_same_or_compact_to_standard_is_not_reencoded(
    tmp_path: Path,
    source_recipe: ImageRecipe,
    target_preset: ImagePreset,
) -> None:
    recipe_hash = source_recipe.recipe_hash
    source = tmp_path / "generated.jpg"
    output = tmp_path / "out" / "generated.jpg"
    marker = (
        f"{MARKER_ID};recipe={recipe_hash};src_size=1;src_mtime_ns=1;"
        f"src_sha256={'0' * 64}"
    ).encode("ascii")
    Image.new("RGB", (800, 600), "green").save(source, "JPEG", quality=90, comment=marker)
    source_bytes = source.read_bytes()

    result = process_image(
        source,
        output,
        ImageConfig(workers=1, preset=target_preset),
    )

    assert result["action"] == "SKIPPED_GENERATED"
    assert output.read_bytes() == source_bytes


def test_standard_generated_jpeg_is_reprocessed_by_compact_without_marker_stacking(
    tmp_path: Path,
) -> None:
    original = tmp_path / "original.png"
    standard = tmp_path / "standard" / "generated.jpg"
    compact = tmp_path / "compact" / "generated.jpg"
    Image.effect_noise((800, 600), 100).convert("RGB").save(original, "PNG")
    standard_result = process_image(original, standard, ImageConfig(workers=1))
    assert standard_result["action"] == "CONVERTED"

    result = process_image(standard, compact, ImageConfig(workers=1, preset="compact"))

    assert result["action"] == "CONVERTED"
    assert result["new_dims"] == (800, 600)
    assert compact.stat().st_size < standard.stat().st_size
    with Image.open(compact) as converted:
        comment = converted.info["comment"]
        assert COMPACT_RECIPE.recipe_hash.encode("ascii") in comment
        assert STANDARD_RECIPE.recipe_hash.encode("ascii") not in comment


def test_compact_rechecks_unmarked_jpeg_previously_copied_by_standard(tmp_path: Path) -> None:
    source = tmp_path / "small.jpeg"
    output = tmp_path / "out" / "small.jpeg"
    Image.new("RGB", (80, 60), "orange").save(source, "JPEG", quality=80)

    first = process_image(source, output, ImageConfig(workers=1))
    second = process_image(source, output, ImageConfig(workers=1, preset="compact"))

    assert first["action"] == "COPIED_ORIGINAL"
    assert second["action"] == "COPIED_ORIGINAL"
    assert second["action"] != "SKIPPED_COPY"
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


def test_completed_output_is_invalidated_when_same_stat_source_content_changes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.bmp"
    output = tmp_path / "out" / "source.bmp.jpg"
    Image.new("RGB", (64, 64), "red").save(source, "BMP")
    original_stat = source.stat()

    first = process_image(source, output, ImageConfig(workers=1, preset="compact"))
    assert first["action"] == "CONVERTED"

    Image.new("RGB", (64, 64), "blue").save(source, "BMP")
    assert source.stat().st_size == original_stat.st_size
    os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    if source.stat().st_mtime_ns != original_stat.st_mtime_ns:
        pytest.skip("filesystem did not preserve the requested nanosecond mtime")

    second = process_image(source, output, ImageConfig(workers=1, preset="compact"))

    assert second["action"] == "CONVERTED"
    assert second["action"] != "SKIPPED_COMPLETE"
    with Image.open(output) as converted:
        red, _green, blue = converted.getpixel((32, 32))
        assert blue > red


def test_completed_reuse_rejects_source_change_before_return_and_preserves_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.bmp"
    output = tmp_path / "out" / "source.bmp.jpg"
    Image.new("RGB", (64, 64), "red").save(source, "BMP")
    assert process_image(source, output, ImageConfig(workers=1))["action"] == "CONVERTED"
    healthy_output = output.read_bytes()
    original_match = image_module._completed_output_matches

    def mutate_after_match(*args: object, **kwargs: object) -> object:
        matched = original_match(*args, **kwargs)
        assert matched is not None
        _mutate_source_content_preserving_size_and_mtime(source)
        return matched

    monkeypatch.setattr(image_module, "_completed_output_matches", mutate_after_match)

    with pytest.raises(image_module.SourceChangedError, match="Source changed"):
        process_image(source, output, ImageConfig(workers=1))

    assert output.read_bytes() == healthy_output


def test_copied_reuse_rejects_source_change_before_return_and_preserves_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.jpg"
    output = tmp_path / "out" / "source.jpg"
    Image.new("RGB", (80, 60), "orange").save(source, "JPEG", quality=80)
    assert process_image(source, output, ImageConfig(workers=1))["action"] == "COPIED_ORIGINAL"
    healthy_output = output.read_bytes()
    original_match = image_module._copied_output_matches

    def mutate_after_match(*args: object, **kwargs: object) -> object:
        matched = original_match(*args, **kwargs)
        assert matched is not None
        _mutate_source_content_preserving_size_and_mtime(source)
        return matched

    monkeypatch.setattr(image_module, "_copied_output_matches", mutate_after_match)

    with pytest.raises(image_module.SourceChangedError, match="Source changed"):
        process_image(source, output, ImageConfig(workers=1))

    assert output.read_bytes() == healthy_output


@pytest.mark.parametrize("reuse_kind", ["completed", "copied"])
def test_reuse_rejects_output_replacement_after_initial_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reuse_kind: str,
) -> None:
    if reuse_kind == "completed":
        source = tmp_path / "source.bmp"
        output = tmp_path / "out" / "source.bmp.jpg"
        Image.new("RGB", (64, 64), "red").save(source, "BMP")
        assert process_image(source, output, ImageConfig(workers=1))["action"] == "CONVERTED"
    else:
        source = tmp_path / "source.jpg"
        output = tmp_path / "out" / "source.jpg"
        Image.new("RGB", (80, 60), "orange").save(source, "JPEG", quality=80)
        assert process_image(source, output, ImageConfig(workers=1))["action"] == "COPIED_ORIGINAL"

    replacement = tmp_path / "replacement.jpg"
    with Image.open(output) as current:
        dimensions = current.size
    Image.new("RGB", dimensions, "purple").save(replacement, "JPEG", quality=70)
    replacement_bytes = replacement.read_bytes()
    original_assert = image_module._assert_source_unchanged
    calls = 0

    def replace_after_source_check(*args: object, **kwargs: object) -> None:
        nonlocal calls
        original_assert(*args, **kwargs)
        calls += 1
        if calls == 1:
            os.replace(replacement, output)

    monkeypatch.setattr(image_module, "_assert_source_unchanged", replace_after_source_check)

    with pytest.raises(image_module.OutputCollisionError, match="changed before reuse"):
        process_image(source, output, ImageConfig(workers=1))

    assert output.read_bytes() == replacement_bytes


def test_conversion_rejects_source_change_before_publish_and_preserves_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.bmp"
    output = tmp_path / "out" / "source.bmp.jpg"
    Image.new("RGB", (1600, 1200), "teal").save(source, "BMP")
    output.parent.mkdir()
    Image.new("RGB", (16, 12), "navy").save(output, "JPEG")
    healthy_output = output.read_bytes()
    original_replace = image_module._replace_staged

    def mutate_then_replace(*args: object, **kwargs: object) -> None:
        _mutate_source_content_preserving_size_and_mtime(source)
        original_replace(*args, **kwargs)

    monkeypatch.setattr(image_module, "_replace_staged", mutate_then_replace)

    with pytest.raises(image_module.SourceChangedError, match="Source changed"):
        process_image(source, output, ImageConfig(workers=1))

    assert output.read_bytes() == healthy_output
    assert list(output.parent.glob(f".{output.name}.*.tmp")) == []


def test_legacy_v1_completion_marker_is_regenerated_once(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "out" / "source.png.jpg"
    Image.new("RGB", (40, 30), "teal").save(source, "PNG")
    source_stat = source.stat()
    output.parent.mkdir()
    legacy_marker = (
        f"karufile:image-v1;recipe={STANDARD_RECIPE.recipe_hash};"
        f"src_size={source_stat.st_size};src_mtime_ns={source_stat.st_mtime_ns}"
    ).encode("ascii")
    Image.new("RGB", (40, 30), "teal").save(
        output,
        "JPEG",
        quality=72,
        comment=legacy_marker,
    )

    result = process_image(source, output, ImageConfig(workers=1))

    assert result["action"] == "CONVERTED"
    with Image.open(output) as converted:
        assert MARKER_ID.encode("ascii") in converted.info["comment"]
        assert b"src_sha256=" in converted.info["comment"]


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


def test_read_only_copied_output_fails_closed_without_temp_residue(tmp_path: Path) -> None:
    source = tmp_path / "small.jpeg"
    output = tmp_path / "out" / "small.jpeg"
    Image.new("RGB", (80, 60), "orange").save(source, "JPEG", quality=80)
    process_image(source, output, ImageConfig(workers=1))
    os.chmod(output, stat.S_IREAD)
    previous = source.stat()
    Image.new("RGB", (81, 60), "purple").save(source, "JPEG", quality=80)
    os.utime(source, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000_000))
    source_bytes = source.read_bytes()
    output_bytes = output.read_bytes()

    with pytest.raises(PathValidationError, match="Read-only image output"):
        process_image(source, output, ImageConfig(workers=1))

    assert source.read_bytes() == source_bytes
    assert output.read_bytes() == output_bytes
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
    with manifest_path(output_dir.resolve(), dry_run=False).open(
        encoding="utf-8", newline=""
    ) as stream:
        manifest_rows = list(csv.DictReader(stream))
    assert len(manifest_rows) == 1
    assert manifest_rows[0]["action"] == "ERROR"
    assert manifest_rows[0]["error"]
    assert manifest_rows[0]["source_sha256"] == hashlib.sha256(original_bytes).hexdigest()
    assert manifest_rows[0]["output_size"] == ""
    assert manifest_rows[0]["output_sha256"] == ""

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


def test_cli_compact_preset_uses_compact_dimensions(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    Image.new("RGB", (1600, 1200), "navy").save(input_dir / "photo.png")

    exit_code = main(
        [
            "resize",
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "--preset",
            "compact",
            "-j",
            "1",
        ]
    )

    assert exit_code == 0
    with Image.open(output_dir / "photo.png.jpg") as converted:
        assert converted.size == (1024, 768)
        assert COMPACT_RECIPE.recipe_hash.encode("ascii") in converted.info["comment"]
    report = manifest_path(output_dir.resolve(), dry_run=False)
    with report.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        assert tuple(reader.fieldnames or ()) == MANIFEST_COLUMNS
        rows = list(reader)
    assert len(rows) == 1
    row = rows[0]
    source = input_dir / "photo.png"
    converted = output_dir / "photo.png.jpg"
    assert row["source_path"] == str(source.resolve())
    assert row["output_path"] == str(converted.resolve())
    assert int(row["source_size"]) == source.stat().st_size
    assert row["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert int(row["output_size"]) == converted.stat().st_size
    assert row["output_sha256"] == hashlib.sha256(converted.read_bytes()).hexdigest()
    assert row["action"] == "CONVERTED"
    assert row["error"] == ""
    assert row["preset"] == "compact"
    assert row["recipe_hash"] == COMPACT_RECIPE.recipe_hash
    assert (int(row["orig_width"]), int(row["orig_height"])) == (1600, 1200)
    assert (int(row["new_width"]), int(row["new_height"])) == (1024, 768)


def test_cli_rejects_read_only_error_report_without_changing_it(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    report = error_report_path(output_dir.resolve())
    report.write_text("stale\n", encoding="utf-8")
    os.chmod(report, stat.S_IREAD)

    assert main(["resize", "-i", str(input_dir), "-o", str(output_dir)]) == 1

    assert report.read_text(encoding="utf-8") == "stale\n"
    assert list(report.parent.glob(f".{report.name}.*.tmp")) == []


@pytest.mark.parametrize(
    "suffix",
    [".image-errors.csv", ".image-manifest.csv", ".image-manifest.dry-run.csv"],
)
def test_cli_rejects_report_path_that_contains_input(tmp_path: Path, suffix: str) -> None:
    output_dir = tmp_path / "output"
    input_dir = Path(f"{output_dir}{suffix}") / "input"
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
    assert not manifest_path(output_dir.resolve(), dry_run=False).exists()
    dry_manifest = manifest_path(output_dir.resolve(), dry_run=True)
    with dry_manifest.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["action"] == "DRY_RUN"
    assert rows[0]["output_size"] == ""
    assert rows[0]["output_sha256"] == ""
    assert rows[0]["source_sha256"] == hashlib.sha256(source_bytes).hexdigest()
    assert (int(rows[0]["new_width"]), int(rows[0]["new_height"])) == (12, 8)


@pytest.mark.parametrize("race_target", ["source", "output"])
def test_manifest_rejects_changed_files_and_preserves_previous_manifest(
    tmp_path: Path,
    race_target: str,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    source = input_dir / "photo.bmp"
    Image.new("RGB", (64, 64), "red").save(source, "BMP")
    config = ImageConfig(workers=1)
    results = image_module.process_all(input_dir, output_dir, config)
    report = manifest_path(output_dir, dry_run=False)
    report.write_text("previous-manifest\n", encoding="utf-8")
    target = source if race_target == "source" else output_dir / "photo.bmp.jpg"
    _mutate_source_content_preserving_size_and_mtime(target)

    expected_error = (
        image_module.SourceChangedError
        if race_target == "source"
        else image_module.OutputCollisionError
    )
    with pytest.raises(expected_error):
        write_result_manifest(input_dir.resolve(), output_dir.resolve(), results, config)

    assert report.read_text(encoding="utf-8") == "previous-manifest\n"
    assert list(report.parent.glob(f".{report.name}.*.tmp")) == []


def test_manifest_hardlink_swap_after_validation_does_not_modify_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    source = input_dir / "photo.bmp"
    Image.new("RGB", (64, 64), "red").save(source, "BMP")
    os.chmod(source, stat.S_IREAD)
    config = ImageConfig(workers=1)
    results = image_module.process_all(input_dir, output_dir, config)
    report = manifest_path(output_dir, dry_run=False)
    source_bytes = source.read_bytes()
    original_mode = source.stat().st_mode
    original_validate = image_module.validate_auxiliary_output
    calls = 0

    def inject_hardlink(input_root: Path, destination: Path) -> Path:
        nonlocal calls
        resolved = original_validate(input_root, destination)
        if destination == report:
            calls += 1
            if calls == 2:
                try:
                    os.link(source, report)
                except OSError:
                    pytest.skip("filesystem does not support hardlinks")
        return resolved

    monkeypatch.setattr(image_module, "validate_auxiliary_output", inject_hardlink)

    with pytest.raises(PathValidationError, match="Unsafe image manifest"):
        write_result_manifest(input_dir.resolve(), output_dir.resolve(), results, config)

    assert source.read_bytes() == source_bytes
    assert source.stat().st_mode == original_mode
    assert os.path.samefile(source, report)


def test_image_output_hardlink_swap_after_last_check_never_chmods_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.bmp"
    output = tmp_path / "out" / "source.bmp.jpg"
    Image.new("RGB", (1600, 1200), "teal").save(source, "BMP")
    os.chmod(source, stat.S_IREAD)
    output.parent.mkdir()
    Image.new("RGB", (16, 12), "navy").save(output, "JPEG")
    source_bytes = source.read_bytes()
    original_mode = source.stat().st_mode
    original_check = image_module._validate_replaceable_file
    injected = False

    def inject_after_check(path: Path, *, label: str) -> None:
        nonlocal injected
        original_check(path, label=label)
        if label == "image output" and not injected:
            injected = True
            path.unlink()
            try:
                os.link(source, path)
            except OSError:
                pytest.skip("filesystem does not support hardlinks")

    monkeypatch.setattr(image_module, "_validate_replaceable_file", inject_after_check)

    try:
        process_image(source, output, ImageConfig(workers=1))
    except OSError:
        pass  # Windowsではread-only hardlinkの置換自体がfail-closedになる。

    assert source.read_bytes() == source_bytes
    assert source.stat().st_mode == original_mode


def test_error_report_hardlink_swap_after_last_check_never_chmods_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "protected.bin"
    source.write_bytes(b"protected")
    os.chmod(source, stat.S_IREAD)
    output_dir = tmp_path / "output"
    report = error_report_path(output_dir)
    report.write_text("old\n", encoding="utf-8")
    source_bytes = source.read_bytes()
    original_mode = source.stat().st_mode
    original_check = image_module._validate_replaceable_file
    injected = False

    def inject_after_check(path: Path, *, label: str) -> None:
        nonlocal injected
        original_check(path, label=label)
        if label == "image error report" and not injected:
            injected = True
            path.unlink()
            try:
                os.link(source, path)
            except OSError:
                pytest.skip("filesystem does not support hardlinks")

    monkeypatch.setattr(image_module, "_validate_replaceable_file", inject_after_check)

    try:
        write_error_report(output_dir, [])
    except OSError:
        pass

    assert source.read_bytes() == source_bytes
    assert source.stat().st_mode == original_mode


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
