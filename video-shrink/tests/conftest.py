from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

from video_shrink.models import MediaInfo, StreamInfo


@pytest.fixture
def media_factory():
    def make(
        path: Path,
        *,
        video: StreamInfo | None = None,
        audio: StreamInfo | None = None,
        extras: tuple[StreamInfo, ...] = (),
        chapters: int = 0,
        duration: float = 10.0,
        format_name: str = "mov,mp4,m4a,3gp,3g2,mj2",
    ) -> MediaInfo:
        selected_video = video or StreamInfo(
            index=0,
            codec_type="video",
            codec_name="h264",
            width=1920,
            height=1080,
            pix_fmt="yuv420p",
            field_order="progressive",
            sample_aspect_ratio="1:1",
            r_frame_rate=Fraction(60, 1),
            avg_frame_rate=Fraction(60, 1),
            color_primaries="bt709",
            color_transfer="bt709",
            color_space="bt709",
            bits_per_raw_sample=8,
        )
        streams = [selected_video]
        if audio is not None:
            streams.append(audio)
        streams.extend(extras)
        return MediaInfo(
            path=path,
            format_name=format_name,
            duration=duration,
            streams=tuple(streams),
            chapter_count=chapters,
        )

    return make


@pytest.fixture
def stereo_audio() -> StreamInfo:
    return StreamInfo(
        index=1,
        codec_type="audio",
        codec_name="aac",
        channels=2,
        sample_rate=48_000,
    )
