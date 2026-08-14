"""画像リサイズ・変換モジュール。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .utils import ensure_dir, logger

try:
    from pillow_heif import register_heif_opener

    register_heif_opener(thumbnails=False)
    HEIF_AVAILABLE = True
except Exception:
    HEIF_AVAILABLE = False
    logger.warning("pillow-heif is not available; HEIC/HEIF files will be skipped.")

from PIL import Image, ImageOps

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".gif", ".webp", ".heic", ".heif"}

FORMAT_MAP = {
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
    "heic": "HEIF",
    "heif": "HEIF",
    "tif": "TIFF",
    "tiff": "TIFF",
}


def _resample() -> Image.Resampling:
    return Image.Resampling.LANCZOS


def process_image(src: Path, dst: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    max_width = int(cfg.get("max_width", 1200))
    quality = int(cfg.get("quality", 85))
    out_fmt = (cfg.get("format", "jpg") or "jpg").lower()
    preserve_exif = cfg.get("preserve_exif", True)
    preserve_icc = cfg.get("preserve_icc", True)
    skip_if_smaller = cfg.get("skip_if_smaller", True)

    with Image.open(src) as img:
        orig_format = img.format
        orig_mode = img.mode
        orig_size = img.size

        # EXIF orientation を物理的に適用
        img = ImageOps.exif_transpose(img)
        exif = img.info.get("exif") if preserve_exif else None
        icc = img.info.get("icc_profile") if preserve_icc else None

        # RGB 化
        if img.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        elif img.mode == "P":
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # リサイズ判定
        w, h = img.size
        resized = False
        if w > max_width:
            ratio = max_width / w
            new_h = int(round(h * ratio))
            img = img.resize((max_width, new_h), _resample())
            resized = True

        # 出力先決定
        dst = dst.with_suffix(f".{out_fmt}")
        ensure_dir(dst.parent)

        # 元が同じ形式・同じ以下サイズならコピーで再エンコードを避ける
        if (
            skip_if_smaller
            and not resized
            and src.suffix.lower().lstrip(".") == out_fmt
            and exif is not None
        ):
            from shutil import copy2

            copy2(src, dst)
            return {
                "src": str(src),
                "dst": str(dst),
                "action": "copied",
                "orig_size": src.stat().st_size,
                "new_size": dst.stat().st_size,
            }

        save_kwargs: dict[str, Any] = {"optimize": True}
        if out_fmt in ("jpg", "jpeg"):
            save_kwargs["quality"] = quality
            save_kwargs["progressive"] = True
        elif out_fmt == "webp":
            save_kwargs["quality"] = quality
            save_kwargs["method"] = 6
        elif out_fmt == "png":
            save_kwargs["compress_level"] = 9

        if exif:
            save_kwargs["exif"] = exif
        if icc:
            save_kwargs["icc_profile"] = icc

        if out_fmt not in FORMAT_MAP:
            raise ValueError(f"Unsupported output format: {out_fmt}")

        if not cfg.get("dry_run", False):
            img.save(dst, format=FORMAT_MAP[out_fmt], **save_kwargs)
        else:
            return {
                "src": str(src),
                "dst": str(dst),
                "action": "dry-run",
                "orig_size": src.stat().st_size if src.exists() else 0,
                "new_size": 0,
            }

        return {
            "src": str(src),
            "dst": str(dst),
            "action": "converted",
            "orig_size": src.stat().st_size,
            "new_size": dst.stat().st_size,
            "orig_dims": orig_size,
            "new_dims": img.size,
        }


def process_all(input_dir: Path, output_dir: Path, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    dry_run = cfg.get("dry_run", False)
    workers = int(cfg.get("workers", 4))
    files = [p for p in input_dir.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]

    results: list[dict[str, Any]] = []
    errors: list[str] = []

    def task(src: Path) -> dict[str, Any] | None:
        rel = src.relative_to(input_dir)
        dst = output_dir / rel.with_suffix(f".{(cfg.get('format', 'jpg')).lower()}")
        try:
            return process_image(src, dst, cfg)
        except Exception as exc:
            return {"src": str(src), "error": str(exc)}

    if dry_run or workers <= 1:
        for src in files:
            res = task(src)
            if res:
                results.append(res)
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(task, src): src for src in files}
            for future in as_completed(futures):
                res = future.result()
                if res:
                    results.append(res)

    for r in results:
        if "error" in r:
            errors.append(r["error"])
            logger.error("%s: %s", r["src"], r["error"])
        else:
            logger.info("%s -> %s (%s)", r["src"], r["dst"], r["action"])

    logger.info("Images processed: %d, errors: %d", len(results), len(errors))
    return results
