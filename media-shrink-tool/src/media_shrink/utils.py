"""共通ユーティリティ。"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable

logger = logging.getLogger("media_shrink")


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def human_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_delete(path: Path, *, trash: bool = True) -> None:
    """ファイルを削除する。trash=True ならゴミ箱へ、不可なら通常削除。"""
    if trash:
        try:
            import send2trash

            send2trash.send2trash(str(path))
            logger.info("Sent to trash: %s", path)
            return
        except Exception:
            logger.warning("Trash failed, falling back to permanent delete: %s", path)
    path.unlink()
    logger.info("Deleted: %s", path)


def collect_files(root: Path, extensions: Iterable[str]) -> list[Path]:
    exts = {e.lower().lstrip(".") for e in extensions}
    return [p for p in root.rglob("*") if p.is_file() and p.suffix.lower().lstrip(".") in exts]


def dir_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def file_count(path: Path) -> int:
    count = 0
    for root, _, files in os.walk(path):
        count += len(files)
    return count
