"""画像専用 ``media_shrink resize`` CLI。"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .config import IMAGE_PRESETS, ImageConfig
from .image import (
    OutputCollisionError,
    error_report_path,
    manifest_path,
    process_all,
    write_error_report,
    write_result_manifest,
)
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
        description="KaruFile image resize, JPEG/PNG/WebP output, and optional EXIF removal",
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
        help="Decode and plan without writing image outputs; reports are refreshed",
    )
    resize.add_argument(
        "-j",
        "--workers",
        type=_positive_int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )
    resize.add_argument(
        "--preset",
        choices=IMAGE_PRESETS,
        default="standard",
        help="Compression preset (default: standard)",
    )
    resize.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    resize.add_argument(
        "--format", choices=("jpeg", "png", "webp"), default="jpeg",
        help="Output format (default: jpeg)",
    )
    resize.add_argument(
        "--strip-exif", action="store_true", help="Remove EXIF after applying Orientation",
    )
    resize.set_defaults(func=cmd_resize)
    public = subparsers.add_parser("web-public", help="掲載用JPEG/PNGマスターを作成")
    public.add_argument("-i", "--input", required=True, help="入力フォルダー")
    public.add_argument("-o", "--output", help="出力ルート (既定: <入力名>_HP掲載用)")
    public.add_argument("--kind", choices=("photo", "graphic"), default="photo")
    public.add_argument("--file", action="append", help="入力ルート相対の画像ファイル名（繰り返し可）")
    public.add_argument("-j", "--workers", type=int, choices=range(1, 5), default=2)
    public.add_argument("--dry-run", action="store_true", help="検査のみ。出力・manifestを書き込まない")
    public.set_defaults(func=cmd_web_public)
    gui = subparsers.add_parser("gui", help="掲載用マスターの日本語ローカルGUI")
    gui.set_defaults(func=cmd_gui)
    return parser


def cmd_web_public(args: argparse.Namespace) -> int:
    from .web_public import WebPublicConfig, run_web_public
    from .web_public_batch import SelectionError
    try:
        result = run_web_public(Path(args.input), Path(args.output) if args.output else None,
            WebPublicConfig(args.kind, args.workers), selected_files=args.file, dry_run=args.dry_run)
    except SelectionError as exc:
        print(f"入力・選択エラー: {exc}")
        return 2
    except (OSError, ValueError) as exc:
        print(f"実行エラー: {exc}")
        return 1
    for row in result.results:
        detail = row["error"]["message"] if row["error"] else ", ".join(row["warnings"])
        print(f"{row['action']}: {row['source_path']} {detail}")
    print(f"{'確認' if args.dry_run else '成功'} {result.success_count}枚（うち警告 {result.warning_count}枚）、失敗 {result.error_count}枚")
    if not args.dry_run:
        print(f"成功分: {human_size(result.source_bytes)} -> {human_size(result.output_bytes)}")
    if result.manifest_error:
        print(f"実行失敗: {result.manifest_error}")
    elif result.files_dir:
        print(f"今回の出力: {result.files_dir}")
    return result.exit_code


def cmd_gui(args: argparse.Namespace) -> int:
    try:
        from .gui import main as gui_main
        return gui_main()
    except ImportError:
        print("GUI環境が未セットアップです。SEは uv sync --project media-shrink-tool --extra gui --extra dev を実行してください")
        return 1


def cmd_resize(args: argparse.Namespace) -> int:
    requested_input = Path(args.input)
    requested_output = Path(args.output) if args.output else None
    try:
        input_dir, output_dir = validate_input_output(requested_input, requested_output)
        validate_auxiliary_output(input_dir, error_report_path(output_dir))
        validate_auxiliary_output(input_dir, manifest_path(output_dir, dry_run=False))
        validate_auxiliary_output(input_dir, manifest_path(output_dir, dry_run=True))
    except PathValidationError as exc:
        logger.error("%s", exc)
        return 1

    config = ImageConfig(
        workers=args.workers,
        dry_run=args.dry_run,
        preset=getattr(args, "preset", "standard"),
        output_format=getattr(args, "format", "jpeg"),
        strip_exif=getattr(args, "strip_exif", False),
    )
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

    manifest_failed = False
    try:
        manifest = write_result_manifest(input_dir, output_dir, results, config)
        logger.info("Image result manifest: %s", manifest)
    except (OSError, PathValidationError, OutputCollisionError) as exc:
        manifest_failed = True
        logger.error("Could not update image result manifest: %s", exc)

    successful = [result for result in results if "error" not in result]
    image_errors = [result for result in results if "error" in result]
    displayed_errors = len(image_errors) + int(report_failed) + int(manifest_failed)
    total_input = sum(int(result.get("orig_size", 0)) for result in successful)
    total_output = sum(int(result.get("new_size", 0)) for result in successful)

    # orchestrator が利用している既存 stdout 契約を維持する。
    print(f"Resized {len(successful)} images ({displayed_errors} errors)")
    print(f"  {human_size(total_input)} -> {human_size(total_output)}")
    return 1 if image_errors or report_failed or manifest_failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    setup_logging(logging.DEBUG if getattr(args, "verbose", False) else logging.INFO)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
