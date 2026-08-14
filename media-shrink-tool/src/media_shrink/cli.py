"""media-shrink CLI。"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

from . import config as cfg_module
from . import dedup, image, pdf, video
from .utils import dir_size, file_count, human_size, logger, setup_logging


def _build_config(args: argparse.Namespace) -> dict[str, Any]:
    cfg = cfg_module.load_config(
        Path(args.config) if args.config else None,
        input_dir=Path(args.input),
    )
    if args.output:
        cfg["output_dir"] = args.output
    cfg["dry_run"] = args.dry_run
    cfg["workers"] = args.workers
    if args.no_trash:
        cfg["trash"] = False

    # 各サブモジュールが dry_run / trash / workers を取得できるよう伝播
    for section in ("image", "video", "pdf", "dedup"):
        cfg[section]["dry_run"] = cfg["dry_run"]
    cfg["image"]["workers"] = cfg["workers"]
    cfg["dedup"]["trash"] = cfg.get("trash", True)
    return cfg


def _remove_source_images(input_dir: Path, output_dir: Path, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """元画像のうち、リサイズ済みが存在するものを削除する。"""
    dry_run = cfg.get("dry_run", False)
    trash = cfg.get("trash", True)
    removed: list[dict[str, Any]] = []
    for src in input_dir.rglob("*"):
        if not src.is_file() or src.suffix.lower() not in image.IMAGE_EXTENSIONS:
            continue
        rel = src.relative_to(input_dir)
        dst = (output_dir / rel).with_suffix(f".{cfg['image'].get('format', 'jpg').lower()}")
        if dst.exists() and dst.stat().st_size > 0:
            sz = src.stat().st_size
            if not dry_run:
                try:
                    from .utils import safe_delete

                    safe_delete(src, trash=trash)
                    removed.append({"src": str(src), "size": sz, "status": "deleted"})
                    logger.info("Removed source image: %s", src)
                except Exception as exc:
                    removed.append({"src": str(src), "size": sz, "status": f"error: {exc}"})
                    logger.error("Failed to remove source image %s: %s", src, exc)
            else:
                removed.append({"src": str(src), "size": sz, "status": "dry-run"})
    return removed


def _print_summary(
    input_dir: Path,
    output_dir: Path | None,
    before_input: int,
    before_total: int,
    image_results: list[dict[str, Any]],
    video_results: list[dict[str, Any]],
    pdf_results: list[dict[str, Any]],
    dedup_results: list[dict[str, Any]],
    removed_sources: list[dict[str, Any]] | None,
) -> None:
    after_input = dir_size(input_dir)
    after_total = after_input + (dir_size(output_dir) if output_dir and output_dir.exists() else 0)

    img_orig = sum(r.get("orig_size", 0) for r in image_results if "error" not in r)
    img_new = sum(r.get("new_size", 0) for r in image_results if "error" not in r)
    vid_orig = sum(r.get("orig_size", 0) for r in video_results if "error" not in r)
    vid_new = sum(r.get("new_size", 0) for r in video_results if "error" not in r)
    pdf_orig = sum(r.get("orig_size", 0) for r in pdf_results if "error" not in r)
    pdf_new = sum(r.get("new_size", 0) for r in pdf_results if "error" not in r)
    dedup_saved = sum(r.get("saved", 0) for r in dedup_results)

    print("\n" + "=" * 50)
    print("Media Shrink Summary")
    print("=" * 50)
    print(f"Input directory : {input_dir}")
    if output_dir:
        print(f"Output directory: {output_dir}")
    print(f"Input dir size  : {human_size(before_input)} -> {human_size(after_input)}")
    print(f"Total size      : {human_size(before_total)} -> {human_size(after_total)}")
    print("-" * 50)
    print(f"Images          : {len(image_results)} files")
    if image_results:
        print(f"                  {human_size(img_orig)} -> {human_size(img_new)}")
    print(f"Videos          : {len(video_results)} files")
    if video_results:
        print(f"                  {human_size(vid_orig)} -> {human_size(vid_new)}")
    print(f"PDFs            : {len(pdf_results)} files")
    if pdf_results:
        print(f"                  {human_size(pdf_orig)} -> {human_size(pdf_new)}")
    print(f"Duplicates saved: {human_size(dedup_saved)}")
    if removed_sources:
        print(f"Source images removed: {len(removed_sources)}")
    print("=" * 50)


def cmd_shrink(args: argparse.Namespace) -> int:
    cfg = _build_config(args)
    input_dir = Path(cfg["input_dir"]).resolve()
    output_dir = cfg_module.get_output_dir(cfg).resolve()

    if not input_dir.exists():
        logger.error("Input directory does not exist: %s", input_dir)
        return 1

    if args.dry_run:
        logger.info("DRY-RUN mode enabled")
    else:
        cfg_module.get_output_dir(cfg).mkdir(parents=True, exist_ok=True)

    before_input = dir_size(input_dir)
    before_total = before_input + (dir_size(output_dir) if output_dir.exists() else 0)

    # 1. 画像リサイズ
    img_results = image.process_all(input_dir, output_dir, cfg["image"])

    # 2. 動画圧縮
    vid_results = video.process_all(input_dir, cfg["video"])

    # 3. PDF 圧縮
    pdf_results = pdf.process_all(input_dir, cfg["pdf"])

    # 4. 元画像削除（--remove-source-images 指定時）
    removed_sources = None
    if args.remove_source_images:
        removed_sources = _remove_source_images(input_dir, output_dir, cfg)

    # 5. 重複削除
    dedup_results = dedup.process_all(input_dir, cfg["dedup"])

    _print_summary(
        input_dir,
        output_dir,
        before_input,
        before_total,
        img_results,
        vid_results,
        pdf_results,
        dedup_results,
        removed_sources,
    )
    return 0


def cmd_resize(args: argparse.Namespace) -> int:
    cfg = _build_config(args)
    input_dir = Path(cfg["input_dir"]).resolve()
    output_dir = cfg_module.get_output_dir(cfg).resolve()
    if not input_dir.exists():
        logger.error("Input directory does not exist: %s", input_dir)
        return 1
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
    results = image.process_all(input_dir, output_dir, cfg["image"])
    total_in = sum(r.get("orig_size", 0) for r in results if "error" not in r)
    total_out = sum(r.get("new_size", 0) for r in results if "error" not in r)
    errors = len([r for r in results if "error" in r])
    print(f"Resized {len([r for r in results if 'error' not in r])} images ({errors} errors)")
    if results:
        print(f"  {human_size(total_in)} -> {human_size(total_out)}")
    return 0


def cmd_video(args: argparse.Namespace) -> int:
    cfg = _build_config(args)
    input_dir = Path(cfg["input_dir"]).resolve()
    if not input_dir.exists():
        logger.error("Input directory does not exist: %s", input_dir)
        return 1
    results = video.process_all(input_dir, cfg["video"])
    total_in = sum(r.get("orig_size", 0) for r in results if "error" not in r)
    total_out = sum(r.get("new_size", 0) for r in results if "error" not in r and r.get("action") == "replaced")
    kept = len([r for r in results if "error" not in r and r.get("action") != "replaced"])
    errors = len([r for r in results if "error" in r])
    print(f"Processed {len([r for r in results if 'error' not in r])} videos ({kept} kept, {errors} errors)")
    if results:
        print(f"  {human_size(total_in)} -> {human_size(total_out)}")
    return 0


def cmd_pdf(args: argparse.Namespace) -> int:
    cfg = _build_config(args)
    if args.lossy:
        cfg["pdf"]["mode"] = "lossy"
    input_dir = Path(cfg["input_dir"]).resolve()
    if not input_dir.exists():
        logger.error("Input directory does not exist: %s", input_dir)
        return 1
    results = pdf.process_all(input_dir, cfg["pdf"])
    total_in = sum(r.get("orig_size", 0) for r in results if "error" not in r)
    total_out = sum(r.get("new_size", 0) for r in results if "error" not in r and not r.get("kept"))
    kept = len([r for r in results if "error" not in r and r.get("kept")])
    errors = len([r for r in results if "error" in r])
    print(f"Processed {len([r for r in results if 'error' not in r])} PDFs ({kept} unchanged, {errors} errors)")
    if results:
        print(f"  {human_size(total_in)} -> {human_size(total_out)}")
    return 0


def cmd_dedup(args: argparse.Namespace) -> int:
    cfg = _build_config(args)
    input_dir = Path(cfg["input_dir"]).resolve()
    if not input_dir.exists():
        logger.error("Input directory does not exist: %s", input_dir)
        return 1
    results = dedup.process_all(input_dir, cfg["dedup"])
    total_saved = sum(r.get("saved", 0) for r in results)
    print(f"Removed duplicates from {len(results)} groups, saved {human_size(total_saved)}")
    return 0


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-i", "--input", required=True, help="Input directory")
    parser.add_argument("-o", "--output", help="Output directory for resized images")
    parser.add_argument("-c", "--config", help="Path to TOML config file")
    parser.add_argument("-n", "--dry-run", action="store_true", help="Show what would be done")
    parser.add_argument("-j", "--workers", type=int, default=4, help="Number of parallel workers")
    parser.add_argument("--no-trash", action="store_true", help="Permanently delete files instead of sending to trash")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="shrink", description="One-shot media shrink toolkit")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # shrink
    p_shrink = subparsers.add_parser("shrink", help="Run all optimizations in one shot")
    _add_common_args(p_shrink)
    p_shrink.add_argument("--remove-source-images", action="store_true", help="Delete original images after successful resize")
    p_shrink.set_defaults(func=cmd_shrink)

    # resize
    p_resize = subparsers.add_parser("resize", help="Resize and convert images only")
    _add_common_args(p_resize)
    p_resize.set_defaults(func=cmd_resize)

    # video
    p_video = subparsers.add_parser("video", help="Compress videos only")
    _add_common_args(p_video)
    p_video.set_defaults(func=cmd_video)

    # pdf
    p_pdf = subparsers.add_parser("pdf", help="Compress PDFs only")
    _add_common_args(p_pdf)
    p_pdf.add_argument("--lossy", action="store_true", help="Use lossy image downsampling for PDFs")
    p_pdf.set_defaults(func=cmd_pdf)

    # dedup
    p_dedup = subparsers.add_parser("dedup", help="Remove duplicate files only")
    _add_common_args(p_dedup)
    p_dedup.add_argument("--perceptual", action="store_true", help="Also detect visually similar images")
    p_dedup.set_defaults(func=cmd_dedup)

    args = parser.parse_args(argv)
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
