from __future__ import annotations

import json
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from video_shrink.config import CompactRecipe
from video_shrink.ffmpeg import ToolError
from video_shrink.models import ProcessStatus, StreamInfo
from video_shrink.probe import (
    inspect_eligibility,
    parse_fraction,
    parse_probe_json,
    target_dimensions,
)


def test_target_dimensions_never_upscales_and_stays_even() -> None:
    recipe = CompactRecipe()
    assert target_dimensions(1920, 1080, recipe) == (1280, 720)
    assert target_dimensions(1080, 1920, recipe) == (404, 720)
    assert target_dimensions(640, 360, recipe) == (640, 360)
    assert target_dimensions(641, 359, recipe) == (640, 358)


def test_parse_fraction_rejects_missing_invalid_and_nonpositive() -> None:
    assert parse_fraction("30000/1001") == Fraction(30000, 1001)
    assert parse_fraction("0/0") is None
    assert parse_fraction("-1") is None
    assert parse_fraction("garbage") is None


def test_parse_probe_json_extracts_stream_and_chapter_data(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1280,
                    "height": 720,
                    "pix_fmt": "yuv420p",
                    "field_order": "progressive",
                    "sample_aspect_ratio": "1:1",
                    "r_frame_rate": "30/1",
                    "avg_frame_rate": "30/1",
                    "bits_per_raw_sample": "8",
                    "tags": {"rotate": "90"},
                    "side_data_list": [{"rotation": 90}],
                }
            ],
            "format": {"format_name": "mov,mp4", "duration": "2.5"},
            "chapters": [{"id": 0}],
        }
    )
    media = parse_probe_json(tmp_path / "clip.mp4", payload)
    assert media.duration == 2.5
    assert media.chapter_count == 1
    assert media.video_streams[0].r_frame_rate == Fraction(30, 1)
    assert media.video_streams[0].tags["rotate"] == "90"


@pytest.mark.parametrize("payload", ["[]", "{}", '{"streams": [], "format": {}}'])
def test_parse_probe_json_rejects_incomplete_payload(tmp_path: Path, payload: str) -> None:
    with pytest.raises(ToolError):
        parse_probe_json(tmp_path / "clip.mp4", payload)


def test_minimal_eligible_media_is_planned_conservatively(
    tmp_path: Path, media_factory, stereo_audio: StreamInfo
) -> None:
    media = media_factory(tmp_path / "clip.mp4", audio=stereo_audio)
    eligibility = inspect_eligibility(media, CompactRecipe())
    assert eligibility.eligible
    assert eligibility.status is None
    assert (eligibility.target_width, eligibility.target_height) == (1280, 720)
    assert eligibility.target_fps == Fraction(30, 1)
    assert eligibility.audio is stereo_audio


@pytest.mark.parametrize(
    ("change", "expected_status"),
    [
        ({"pix_fmt": "yuv420p10le"}, ProcessStatus.SKIPPED_UNSUPPORTED),
        ({"bits_per_raw_sample": 10}, ProcessStatus.SKIPPED_UNSUPPORTED),
        ({"color_transfer": "smpte2084"}, ProcessStatus.SKIPPED_COMPLEX),
        ({"color_primaries": "bt2020"}, ProcessStatus.SKIPPED_COMPLEX),
        ({"field_order": "tt"}, ProcessStatus.SKIPPED_COMPLEX),
        ({"field_order": ""}, ProcessStatus.SKIPPED_COMPLEX),
        ({"sample_aspect_ratio": "4:3"}, ProcessStatus.SKIPPED_COMPLEX),
        ({"sample_aspect_ratio": ""}, ProcessStatus.SKIPPED_COMPLEX),
        ({"sample_aspect_ratio": "N/A"}, ProcessStatus.SKIPPED_COMPLEX),
        ({"avg_frame_rate": Fraction(24, 1)}, ProcessStatus.SKIPPED_COMPLEX),
        ({"tags": {"rotate": "45"}}, ProcessStatus.SKIPPED_COMPLEX),
        ({"disposition": {"attached_pic": 1}}, ProcessStatus.SKIPPED_COMPLEX),
    ],
)
def test_video_complexity_and_unsupported_signals_are_skipped(
    tmp_path: Path, media_factory, change: dict[str, object], expected_status: ProcessStatus
) -> None:
    base = media_factory(tmp_path / "clip.mp4").video_streams[0]
    media = media_factory(tmp_path / "clip.mp4", video=replace(base, **change))
    eligibility = inspect_eligibility(media, CompactRecipe())
    assert not eligibility.eligible
    assert eligibility.status is expected_status


def test_subtitles_multiple_audio_and_chapters_are_complex(
    tmp_path: Path, media_factory, stereo_audio: StreamInfo
) -> None:
    subtitle = StreamInfo(index=2, codec_type="subtitle", codec_name="subrip")
    cases = (
        media_factory(tmp_path / "clip.mp4", extras=(subtitle,)),
        media_factory(
            tmp_path / "clip.mp4",
            audio=stereo_audio,
            extras=(replace(stereo_audio, index=2),),
        ),
        media_factory(tmp_path / "clip.mp4", chapters=1),
    )
    for media in cases:
        eligibility = inspect_eligibility(media, CompactRecipe())
        assert eligibility.status is ProcessStatus.SKIPPED_COMPLEX


def test_container_must_match_suffix(tmp_path: Path, media_factory) -> None:
    media = media_factory(tmp_path / "renamed.webm", format_name="mov,mp4")
    eligibility = inspect_eligibility(media, CompactRecipe())
    assert eligibility.status is ProcessStatus.SKIPPED_UNSUPPORTED


def test_right_angle_rotation_uses_display_dimensions(tmp_path: Path, media_factory) -> None:
    base = media_factory(tmp_path / "clip.mp4").video_streams[0]
    media = media_factory(tmp_path / "clip.mp4", video=replace(base, tags={"rotate": "90"}))
    eligibility = inspect_eligibility(media, CompactRecipe())
    assert eligibility.eligible
    assert (eligibility.display_width, eligibility.display_height) == (1080, 1920)
    assert (eligibility.target_width, eligibility.target_height) == (404, 720)
