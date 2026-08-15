"""画像専用 ``media_shrink resize`` CLI。"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .config import ImageConfig
from .image import OutputCollisionError, error_report_path, process_all, write_error_report
from .utils import (
    PathValidationError,
    human_size,
    logger,
    setup_logging,
    validate_auxiliary_output,
    validate_input_output,
)


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("workers must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("workers must be at least 1")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="media-shrink",
        description="KaruFile image resize and JPEG conversion tool",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    resize = subparsers.add_parser("resize", help="Resize and convert images without changing sources")
    resize.add_argument("-i", "--input", required=True, help="Input directory")
    resize.add_argument(
        "-o",
        "--output",
        help="Separate output directory (default: <input>_resized)",
    )
    resize.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Decode and plan without writing image outputs; the error CSV is refreshed",
    )
    resize.add_argument(
        "-j",
        "--workers",
        type=_positive_int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )
    resize.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    resize.set_defaults(func=cmd_resize)
    return parser


def cmd_resize(args: argparse.Namespace) -> int:
    requested_input = Path(args.input)
    requested_output = Path(args.output) if args.output else None
    try:
        input_dir, output_dir = validate_input_output(requested_input, requested_output)
        validate_auxiliary_output(input_dir, error_report_path(output_dir))
    except PathValidationError as exc:
        logger.error("%s", exc)
        return 1

    config = ImageConfig(workers=args.workers, dry_run=args.dry_run)
    if not config.dry_run:
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error("Could not create output directory %s: %s", output_dir, exc)
            return 1

    try:
        results = process_all(input_dir, output_dir, config)
    except (OSError, ValueError, OutputCollisionError) as exc:
        logger.error("Image preflight failed: %s", exc)
        results = [
            {
                "source": str(input_dir),
                "planned_output": str(output_dir),
                "error": f"{type(exc).__name__}: {exc}",
                "orig_size": 0,
                "new_size": 0,
            }
        ]

    report_failed = False
    try:
        report = write_error_report(output_dir, results)
        logger.info("Image error report: %s", report)
    except (OSError, PathValidationError) as exc:
        report_failed = True
        logger.error("Could not update image error report: %s", exc)

    successful = [result for result in results if "error" not in result]
    image_errors = [result for result in results if "error" in result]
    displayed_errors = len(image_errors) + int(report_failed)
    total_input = sum(int(result.get("orig_size", 0)) for result in successful)
    total_output = sum(int(result.get("new_size", 0)) for result in successful)

    # orchestrator が利用している既存 stdout 契約を維持する。
    print(f"Resized {len(successful)} images ({displayed_errors} errors)")
    print(f"  {human_size(total_input)} -> {human_size(total_output)}")
    return 1 if image_errors or report_failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
