"""Command-line interface for explicitly selected XLSX workbooks."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .config import ExcelConfig
from .runner import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="excel-shrink", description="Resize oversized embedded XLSX images into a separate output tree")
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("run", help="process selected .xlsx workbooks")
    command.add_argument("--input", required=True, help="input directory")
    command.add_argument("--output", required=True, help="separate output directory")
    command.add_argument("--pattern", action="append", required=True, help="input-relative glob, repeatable and case-insensitive")
    sizing = command.add_mutually_exclusive_group()
    sizing.add_argument("--dpi", type=int, help="use placement resolution instead of pixel cap, 150 to 300")
    sizing.add_argument("--max-side", type=int, help="maximum long side in pixels, 100 to 10000 (default: 800)")
    command.add_argument("--jpeg-quality", type=int, help="JPEG quality, 40 to 95 (default: 72 for pixel cap, 85 for DPI)")
    command.add_argument("--dry-run", action="store_true", help="inspect and report without writing completed workbooks")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.dpi is None and args.max_side is None:
        args.max_side = 800
    if args.jpeg_quality is None:
        args.jpeg_quality = 72 if args.max_side is not None else 85
    try:
        config = ExcelConfig(Path(args.input), Path(args.output), tuple(args.pattern), args.dpi, args.dry_run,
                             args.max_side, args.jpeg_quality)
    except ValueError as exc:
        parser.error(str(exc))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    outcome = run(config)
    errors = sum(result.status == "ERROR" for result in outcome.results)
    print(f"Excel: {len(outcome.results)} workbooks, {errors} per-file errors")
    if outcome.error:
        print(f"Excel processing failed: {outcome.error}")
    if outcome.report_path is not None:
        print(f"Excel report: {outcome.report_path}")
    return outcome.exit_code
