"""Command-line interface for video-shrink."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .config import VideoConfig
from .models import Preset, ProcessStatus
from .runner import run


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("workers must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("workers must be at least 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="video-shrink",
        description="KaruFile non-destructive video processor",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("run", help="copy or compact supported videos")
    command.add_argument("--input", required=True, help="input directory")
    command.add_argument("--output", required=True, help="separate output directory")
    command.add_argument(
        "--preset",
        choices=tuple(item.value for item in Preset),
        default=Preset.STANDARD.value,
        help="standard copies without transcoding; compact uses validated AV1",
    )
    command.add_argument("--workers", type=_positive_int, default=1)
    command.add_argument("--dry-run", action="store_true", help="do not create video outputs")
    command.add_argument("--ffmpeg-path", help="explicit ffmpeg executable")
    command.add_argument("--ffprobe-path", help="explicit ffprobe executable")
    command.add_argument("-v", "--verbose", action="store_true")
    return parser


def _human_size(value: int) -> str:
    number = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(number) < 1024.0:
            return f"{number:.2f} {unit}"
        number /= 1024.0
    return f"{number:.2f} PB"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    config = VideoConfig(
        input_dir=Path(args.input),
        output_dir=Path(args.output),
        preset=Preset(args.preset),
        workers=args.workers,
        dry_run=args.dry_run,
        ffmpeg_path=Path(args.ffmpeg_path) if args.ffmpeg_path else None,
        ffprobe_path=Path(args.ffprobe_path) if args.ffprobe_path else None,
    )
    outcome = run(config)
    errors = sum(result.status is ProcessStatus.ERROR for result in outcome.results)
    successes = len(outcome.results) - errors
    total_input = sum(result.source_size for result in outcome.results)
    output_known = [
        result.output_size
        for result in outcome.results
        if result.output_size is not None
    ]
    total_output = sum(output_known)
    if outcome.exit_code and not outcome.results:
        print("Video processing failed before per-file results were available")
    else:
        print(f"Processed {successes} videos ({errors} errors)")
    if config.dry_run:
        print(f"  {_human_size(total_input)} -> not written (dry-run)")
    else:
        print(f"  {_human_size(total_input)} -> {_human_size(total_output)}")
    if outcome.report_path is not None:
        print(f"Video report: {outcome.report_path}")
    return outcome.exit_code
