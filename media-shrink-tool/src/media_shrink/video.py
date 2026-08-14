"""動画圧縮モジュール。"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from .utils import logger

VIDEO_EXTENSIONS = {".mov", ".mp4", ".avi", ".mkv", ".m4v", ".mts", ".m2ts"}


def _ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        # システム ffmpeg を探す
        exe = shutil.which("ffmpeg")
        if exe:
            return exe
        raise RuntimeError("ffmpeg not found. Install imageio-ffmpeg or system ffmpeg.") from exc


def process_video(src: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    dry_run = cfg.get("dry_run", False)
    codec = cfg.get("codec", "libx264")
    crf = int(cfg.get("crf", 23))
    preset = cfg.get("preset", "medium")
    max_height = int(cfg.get("max_height", 1080))
    audio_codec = cfg.get("audio_codec", "aac")
    audio_bitrate = cfg.get("audio_bitrate", "128k")

    ffmpeg = _ffmpeg_exe()

    # 一時出力パス
    temp = src.with_stem(f"{src.stem}_ms").with_suffix(".mp4")
    final = src.with_suffix(".mp4")

    vf = f"scale=-2:{max_height}:force_original_aspect_ratio=decrease"
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(src),
        "-c:v",
        codec,
        "-crf",
        str(crf),
        "-preset",
        preset,
        "-vf",
        vf,
        "-c:a",
        audio_codec,
        "-b:a",
        audio_bitrate,
        "-movflags",
        "+faststart",
        str(temp),
    ]

    if dry_run:
        logger.info("DRY-RUN video: %s -> %s", src, final)
        return {"src": str(src), "dst": str(final), "action": "dry-run", "cmd": " ".join(cmd)}

    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    except subprocess.CalledProcessError as exc:
        if temp.exists():
            temp.unlink(missing_ok=True)
        logger.error("FFmpeg failed for %s: %s", src, exc.stderr.decode("utf-8", "ignore")[:300])
        return {"src": str(src), "error": "ffmpeg failed"}

    if not temp.exists() or temp.stat().st_size == 0:
        return {"src": str(src), "error": "output missing"}

    in_size = src.stat().st_size
    out_size = temp.stat().st_size

    action = "kept"
    if out_size < in_size:
        # 元を削除して mp4 に統一
        src.unlink()
        if final.exists():
            final.unlink()
        temp.rename(final)
        action = "replaced"
    else:
        temp.unlink()

    return {
        "src": str(src),
        "dst": str(final) if action == "replaced" else str(src),
        "action": action,
        "orig_size": in_size,
        "new_size": out_size if action == "replaced" else in_size,
    }


def process_all(input_dir: Path, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    files = sorted(p for p in input_dir.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS)
    results: list[dict[str, Any]] = []
    for src in files:
        logger.info("Processing video: %s", src)
        results.append(process_video(src, cfg))
    return results
