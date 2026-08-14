"""入力ディレクトリの検証、PDF探索、処理前スナップショット。"""
from __future__ import annotations

import random
from pathlib import Path

from .models import SourceSnapshot
from .utils import sha256_file


def _is_nested(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_directories(input_dir: Path, output_dir: Path) -> None:
    if not input_dir.exists():
        raise ValueError(f"Input directory does not exist: {input_dir}")
    if not input_dir.is_dir():
        raise ValueError(f"Input path is not a directory: {input_dir}")
    if input_dir == output_dir:
        raise ValueError("Output directory must differ from input directory")
    if _is_nested(input_dir, output_dir) or _is_nested(output_dir, input_dir):
        raise ValueError("Input and output directories must not be nested")


def collect_pdfs(input_dir: Path) -> list[Path]:
    return sorted(
        path for path in input_dir.rglob("*")
        if path.is_file() and path.suffix.casefold() == ".pdf"
    )


def select_pilot(files: list[Path], limit: int | None) -> list[Path]:
    if limit is None or limit >= len(files):
        return list(files)

    largest_count = limit // 2
    by_size = sorted(files, key=lambda path: path.stat().st_size, reverse=True)
    largest = set(by_size[:largest_count])
    remaining = [path for path in files if path not in largest]
    random_sample = random.Random(0).sample(remaining, limit - largest_count)
    return sorted(largest | set(random_sample))


def snapshot(path: Path, input_dir: Path) -> SourceSnapshot:
    resolved = path.resolve()
    file_hash = sha256_file(resolved)
    stat = resolved.stat()
    return SourceSnapshot(
        path=resolved,
        relative_path=resolved.relative_to(input_dir),
        sha256=file_hash,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )
