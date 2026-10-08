"""画像変換に依存しないファイルのSHA・stat・処理中の原本変更検知。"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path

from .utils import PathValidationError, validate_source_path


class SourceChangedError(OSError):
    """処理中に入力ファイルの内容またはファイル同一性が変化した。"""


@dataclass(frozen=True, slots=True)
class SourceFingerprint:
    """入力ファイルの1時点における安定したstatと内容SHA-256。"""

    stat: os.stat_result
    sha256: str

    @property
    def stat_signature(self) -> tuple[int, int, int, int, int]:
        return stat_signature(self.stat)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def stat_signature(file_stat: os.stat_result) -> tuple[int, int, int, int, int]:
    """置換と同一サイズ・mtime偽装も検知できるsource identity。"""

    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_size,
        file_stat.st_mtime_ns,
        file_stat.st_ctime_ns,
    )


def _capture_with_hash(
    source: Path,
    hash_file: Callable[[Path], str],
) -> SourceFingerprint:
    """旧image helperのhash呼出し互換を保つ共通実装。"""

    before = source.stat()
    source_sha256 = hash_file(source)
    after = source.stat()
    if stat_signature(before) != stat_signature(after):
        raise SourceChangedError(f"Source changed while hashing: {source}")
    return SourceFingerprint(stat=after, sha256=source_sha256)


def capture_source_fingerprint(source: Path) -> SourceFingerprint:
    """hash中にstatが変わらなかった入力のfingerprintだけを返す。"""

    return _capture_with_hash(source, sha256_file)


def _assert_with_capture(
    source: Path,
    expected: SourceFingerprint,
    input_root: Path,
    capture: Callable[[Path], SourceFingerprint],
) -> None:
    """旧image helperのcapture呼出し互換を保つ共通実装。"""

    try:
        validate_source_path(input_root, source)
        observed = capture(source)
        validate_source_path(input_root, source)
    except SourceChangedError:
        raise
    except (OSError, RuntimeError, ValueError, PathValidationError) as exc:
        raise SourceChangedError(f"Source changed during processing: {source}") from exc

    if (
        observed.sha256 != expected.sha256
        or observed.stat_signature != expected.stat_signature
    ):
        raise SourceChangedError(f"Source changed during processing: {source}")


def assert_source_unchanged(
    source: Path,
    expected: SourceFingerprint,
    input_root: Path,
) -> None:
    """公開または再利用確定の直前に入力の同一性と内容を再検証する。"""

    _assert_with_capture(source, expected, input_root, capture_source_fingerprint)
