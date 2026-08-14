"""検証済み候補または原本を出力先へ安全に公開する。"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from .utils import ensure_dir


def _publish_copy(source: Path, destination: Path, timestamp_source: Path) -> None:
    """同一ディレクトリ内の一時ファイルを経由して出力を置換する。"""
    ensure_dir(destination.parent)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        shutil.copy2(source, temp_path)
        timestamp = timestamp_source.stat()
        os.utime(temp_path, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))
        os.replace(temp_path, destination)
    finally:
        temp_path.unlink(missing_ok=True)


def copy_original(source: Path, destination: Path) -> None:
    _publish_copy(source, destination, source)


def adopt_candidate(original: Path, candidate: Path, destination: Path) -> None:
    _publish_copy(candidate, destination, original)
