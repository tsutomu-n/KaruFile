"""重複ファイル検出・削除モジュール。"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .utils import logger, safe_delete


def _file_hash(path: Path, algorithm: str = "xxhash") -> str:
    if algorithm == "xxhash":
        try:
            import xxhash

            h = xxhash.xxh64()
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest()
        except ImportError:
            pass
    import hashlib

    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _perceptual_hash(path: Path) -> str | None:
    try:
        from PIL import Image, ImageOps
        import imagehash
    except ImportError:
        return None

    try:
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img)
            img.thumbnail((512, 512))
            return str(imagehash.phash(img))
    except Exception:
        return None


def find_exact_duplicates(input_dir: Path, min_size: int = 1024) -> list[list[Path]]:
    files = [p for p in input_dir.rglob("*") if p.is_file() and p.stat().st_size >= min_size]
    by_size: dict[int, list[Path]] = defaultdict(list)
    for p in files:
        by_size[p.stat().st_size].append(p)

    groups: list[list[Path]] = []
    for paths in by_size.values():
        if len(paths) < 2:
            continue
        by_hash: dict[str, list[Path]] = defaultdict(list)
        for p in paths:
            by_hash[_file_hash(p)].append(p)
        for same_paths in by_hash.values():
            if len(same_paths) > 1:
                groups.append(sorted(same_paths, key=lambda x: str(x)))
    return groups


def find_perceptual_duplicates(
    input_dir: Path,
    image_extensions: set[str] | None = None,
    threshold: int = 5,
) -> list[list[Path]]:
    if image_extensions is None:
        image_extensions = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".gif", ".webp", ".heic", ".heif"}

    files = [p for p in input_dir.rglob("*") if p.is_file() and p.suffix.lower() in image_extensions]
    hashes: dict[str, list[Path]] = defaultdict(list)
    for p in files:
        h = _perceptual_hash(p)
        if h:
            hashes[h].append(p)

    # 簡易的に同一ハッシュのみグループ化
    groups = [sorted(v, key=lambda x: str(x)) for v in hashes.values() if len(v) > 1]

    # ハミング距離閾値内のグループ化（より高度な処理）
    if threshold > 0:
        try:
            import imagehash
        except ImportError:
            return groups

        merged: list[list[Path]] = []
        used = set()
        items = [(k, v) for k, v in hashes.items()]
        for i, (ha_str, paths_a) in enumerate(items):
            if i in used:
                continue
            group = list(paths_a)
            used.add(i)
            ha = imagehash.hex_to_hash(ha_str)
            for j in range(i + 1, len(items)):
                if j in used:
                    continue
                hb_str, paths_b = items[j]
                hb = imagehash.hex_to_hash(hb_str)
                if ha - hb <= threshold:
                    group.extend(paths_b)
                    used.add(j)
            merged.append(sorted(group, key=lambda x: str(x)))
        return [g for g in merged if len(g) > 1]

    return groups


def process_all(input_dir: Path, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    dry_run = cfg.get("dry_run", False)
    trash = cfg.get("trash", True)
    min_size = int(cfg.get("min_size", 1024))
    perceptual = cfg.get("perceptual", False)
    threshold = int(cfg.get("hash_threshold", 5))

    groups = find_exact_duplicates(input_dir, min_size)
    mode = "exact"
    if perceptual:
        groups.extend(find_perceptual_duplicates(input_dir, threshold=threshold))
        mode = "exact+perceptual"

    results: list[dict[str, Any]] = []
    for group in groups:
        keeper = group[0]
        copies = group[1:]
        saved = 0
        removed = []
        for p in copies:
            sz = p.stat().st_size
            if not dry_run:
                try:
                    safe_delete(p, trash=trash)
                    saved += sz
                    removed.append(str(p))
                except Exception as exc:
                    logger.error("Failed to remove duplicate %s: %s", p, exc)
            else:
                saved += sz
                removed.append(str(p))
        results.append(
            {
                "keeper": str(keeper),
                "removed": removed,
                "saved": saved,
                "mode": mode,
            }
        )
        if removed:
            logger.info("Kept %s, removed %d duplicates (saved %s)", keeper, len(removed), saved)

    total_saved = sum(r["saved"] for r in results)
    logger.info("Deduplication complete: groups=%d, total_saved=%s", len(groups), total_saved)
    return results
