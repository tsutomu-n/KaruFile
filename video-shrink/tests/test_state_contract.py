from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from video_shrink.config import CompactRecipe
from video_shrink.models import Preset, ProcessStatus, SourceSnapshot
from video_shrink.state import Record, reusable_result
from video_shrink.utils import sha256_file, stable_sha256_file


def _fixture(tmp_path: Path) -> tuple[SourceSnapshot, Path, Record]:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source_path = input_dir / "clip.mp4"
    destination = output_dir / "clip.mp4"
    source_path.write_bytes(b"same-content")
    destination.write_bytes(b"same-content")
    source_sha256, source_identity = stable_sha256_file(source_path)
    source = SourceSnapshot(
        source_path,
        Path("clip.mp4"),
        source_sha256,
        source_identity,
    )
    record = Record(
        source_path=str(source_path),
        source_sha256=source.sha256,
        source_size=source.size,
        source_mtime_ns=source.mtime_ns,
        config_hash="config-hash",
        output_path=str(destination),
        output_size=destination.stat().st_size,
        output_sha256=sha256_file(destination),
        saved_bytes=0,
        saved_percent=0.0,
        status=ProcessStatus.SKIPPED_STANDARD.value,
        error_message="",
        preset=Preset.STANDARD.value,
        reason="standard copy",
        video_codec="",
        audio_codec="",
        width=None,
        height=None,
        fps=None,
        duration=None,
        vmaf_mean=None,
        vmaf_p5=None,
        ffmpeg_version="",
    )
    return source, destination, record


def _reuse(record: Record, source: SourceSnapshot, destination: Path):
    return reusable_result(
        record,
        source,
        "config-hash",
        expected_destination=destination,
        expected_preset=Preset.STANDARD,
        recipe=CompactRecipe(),
        dry_run=False,
    )


def test_valid_record_reuses_only_the_expected_destination(tmp_path: Path) -> None:
    source, destination, record = _fixture(tmp_path)
    result = _reuse(record, source, destination)
    assert result is not None
    assert result.status is ProcessStatus.SKIPPED_COMPLETE
    assert result.output_path == str(destination)


@pytest.mark.parametrize("location", ["external", "input"])
def test_record_pointing_outside_expected_output_is_not_reused(
    tmp_path: Path, location: str
) -> None:
    source, destination, record = _fixture(tmp_path)
    unexpected = (
        tmp_path / "external.mp4" if location == "external" else source.path
    )
    if location == "external":
        unexpected.write_bytes(source.path.read_bytes())
    tampered = replace(
        record,
        output_path=str(unexpected),
        output_size=unexpected.stat().st_size,
        output_sha256=sha256_file(unexpected),
    )
    assert _reuse(tampered, source, destination) is None


@pytest.mark.parametrize(
    "change",
    [
        {"preset": "not-a-preset"},
        {"status": "NOT_A_STATUS"},
        {"status": ProcessStatus.DRY_RUN.value},
        {"source_size": 999},
        {"output_size": 1},
        {"saved_bytes": 1},
        {"saved_percent": 1.0},
        {"output_sha256": "not-a-sha256"},
        {"error_message": "legacy error"},
    ],
)
def test_invalid_enum_and_inconsistent_numeric_record_is_reprocessed(
    tmp_path: Path, change: dict[str, object]
) -> None:
    source, destination, record = _fixture(tmp_path)
    assert _reuse(replace(record, **change), source, destination) is None


def test_record_preset_must_match_requested_preset(tmp_path: Path) -> None:
    source, destination, record = _fixture(tmp_path)
    result = reusable_result(
        record,
        source,
        "config-hash",
        expected_destination=destination,
        expected_preset=Preset.COMPACT,
        recipe=CompactRecipe(),
        dry_run=False,
    )
    assert result is None


def test_copy_status_cannot_claim_a_smaller_nonoriginal_output(tmp_path: Path) -> None:
    source, destination, record = _fixture(tmp_path)
    destination.write_bytes(b"small")
    saved = source.size - destination.stat().st_size
    tampered = replace(
        record,
        output_size=destination.stat().st_size,
        output_sha256=sha256_file(destination),
        saved_bytes=saved,
        saved_percent=saved / source.size * 100,
    )
    assert _reuse(tampered, source, destination) is None


def test_copy_status_cannot_reuse_same_size_different_content(tmp_path: Path) -> None:
    source, destination, record = _fixture(tmp_path)
    destination.write_bytes(b"evil-content")
    assert destination.stat().st_size == source.size
    tampered = replace(record, output_sha256=sha256_file(destination))
    assert _reuse(tampered, source, destination) is None


def _compact_fixture(tmp_path: Path) -> tuple[SourceSnapshot, Path, Record]:
    input_dir = tmp_path / "compact-input"
    output_dir = tmp_path / "compact-output"
    input_dir.mkdir()
    output_dir.mkdir()
    source_path = input_dir / "clip.mp4"
    destination = output_dir / "clip.mp4"
    source_path.write_bytes(b"s" * (2 * 1024 * 1024))
    destination.write_bytes(b"d" * (512 * 1024))
    source_sha256, source_identity = stable_sha256_file(source_path)
    source = SourceSnapshot(
        source_path,
        Path("clip.mp4"),
        source_sha256,
        source_identity,
    )
    saved = source.size - destination.stat().st_size
    record = Record(
        source_path=str(source.path),
        source_sha256=source.sha256,
        source_size=source.size,
        source_mtime_ns=source.mtime_ns,
        config_hash="config-hash",
        output_path=str(destination),
        output_size=destination.stat().st_size,
        output_sha256=sha256_file(destination),
        saved_bytes=saved,
        saved_percent=saved / source.size * 100,
        status=ProcessStatus.ADOPTED.value,
        error_message="",
        preset=Preset.COMPACT.value,
        reason="adopted CRF 38",
        video_codec="av1",
        audio_codec="aac",
        width=1280,
        height=720,
        fps=30.0,
        duration=1.0,
        vmaf_mean=85.0,
        vmaf_p5=70.0,
        ffmpeg_version="ffmpeg test",
    )
    return source, destination, record


def _reuse_compact(
    record: Record,
    source: SourceSnapshot,
    destination: Path,
    *,
    recipe: CompactRecipe = CompactRecipe(),
):
    return reusable_result(
        record,
        source,
        "config-hash",
        expected_destination=destination,
        expected_preset=Preset.COMPACT,
        recipe=recipe,
        dry_run=False,
    )


def test_valid_adopted_record_meets_current_recipe_before_reuse(tmp_path: Path) -> None:
    source, destination, record = _compact_fixture(tmp_path)
    result = _reuse_compact(record, source, destination)
    assert result is not None
    assert result.status is ProcessStatus.SKIPPED_COMPLETE


@pytest.mark.parametrize(
    "change",
    [
        {"video_codec": "h264"},
        {"audio_codec": "opus"},
        {"width": 1282},
        {"width": 1279},
        {"height": 722},
        {"fps": 30.1},
        {"vmaf_mean": 84.9},
        {"vmaf_p5": 69.9},
        {"ffmpeg_version": ""},
    ],
)
def test_adopted_record_metadata_must_match_current_recipe(
    tmp_path: Path, change: dict[str, object]
) -> None:
    source, destination, record = _compact_fixture(tmp_path)
    assert _reuse_compact(replace(record, **change), source, destination) is None


def test_adopted_record_savings_must_match_current_recipe(tmp_path: Path) -> None:
    source, destination, record = _compact_fixture(tmp_path)
    assert _reuse_compact(
        record,
        source,
        destination,
        recipe=CompactRecipe(min_saved_percent=0.80),
    ) is None
