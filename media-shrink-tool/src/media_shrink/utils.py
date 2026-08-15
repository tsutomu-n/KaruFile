"""ログ、表示、パス検査、一時出力の共通処理。"""
from __future__ import annotations

from contextlib import contextmanager
import logging
import os
from pathlib import Path
import stat
import tempfile
from collections.abc import Iterator

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


class PathValidationError(ValueError):
    """入力と出力を安全に分離できない場合のエラー。"""


def _normalized_path(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _is_within(path: Path, parent: Path) -> bool:
    path_key = _normalized_path(path)
    parent_key = _normalized_path(parent)
    try:
        return os.path.commonpath((path_key, parent_key)) == parent_key
    except ValueError:
        return False


def is_link_like(path: Path) -> bool:
    """symlink と Windows の Junction/reparse point を同じ境界として扱う。"""

    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if is_junction is not None and is_junction():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        return bool(reparse_flag and attributes & reparse_flag)
    except OSError:
        return False


def has_link_component(root: Path, candidate: Path) -> bool:
    """rootからcandidateまでの既存componentにlink/reparse pointがあるか返す。"""

    lexical_root = Path(os.path.abspath(root))
    lexical_candidate = Path(os.path.abspath(candidate))
    try:
        relative = lexical_candidate.relative_to(lexical_root)
    except ValueError:
        return True
    current = lexical_root
    if is_link_like(current):
        return True
    for part in relative.parts:
        current = current / part
        if is_link_like(current):
            return True
    return False


def validate_source_path(input_root: Path, source: Path) -> Path:
    """収集した入力が link/reparse point 経由で入力root外へ出ないことを確認する。"""

    try:
        resolved_root = input_root.resolve(strict=True)
        resolved_source = source.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PathValidationError(f"Source path cannot be resolved: {source}") from exc
    if is_link_like(source) or not resolved_source.is_file():
        raise PathValidationError(f"Linked or invalid source path is not allowed: {source}")
    if not _is_within(resolved_source, resolved_root):
        raise PathValidationError(f"Source path escapes the input directory: {source}")
    return resolved_source


def validate_output_destination(
    input_root: Path,
    output_root: Path,
    destination: Path,
) -> Path:
    """既存Junction等を解決した出力先が指定output内に留まることを確認する。"""

    try:
        resolved_input = input_root.resolve(strict=True)
        resolved_output = output_root.resolve(strict=False)
        resolved_destination = destination.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PathValidationError(f"Output destination cannot be resolved: {destination}") from exc

    lexical_output = Path(os.path.abspath(output_root))
    lexical_destination = Path(os.path.abspath(destination))
    if not _is_within(lexical_destination, lexical_output):
        raise PathValidationError(f"Output destination is outside the output directory: {destination}")
    if has_link_component(lexical_output, lexical_destination):
        raise PathValidationError(f"Linked output path component is not allowed: {destination}")
    if not _is_within(resolved_destination, resolved_output):
        raise PathValidationError(f"Output destination escapes the output directory: {destination}")
    if _is_within(resolved_destination, resolved_input):
        raise PathValidationError(f"Output destination overlaps the input directory: {destination}")
    if _is_within(resolved_input, resolved_destination):
        raise PathValidationError(f"Output destination contains the input directory: {destination}")
    return resolved_destination


def validate_auxiliary_output(input_root: Path, destination: Path) -> Path:
    """sibling reportなどの派生write pathが入力領域と重ならないことを確認する。"""

    try:
        resolved_input = input_root.resolve(strict=True)
        resolved_destination = destination.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PathValidationError(f"Auxiliary output cannot be resolved: {destination}") from exc
    if _is_within(resolved_destination, resolved_input) or _is_within(
        resolved_input, resolved_destination
    ):
        raise PathValidationError(f"Auxiliary output overlaps the input directory: {destination}")
    if resolved_destination.exists() and resolved_destination.is_dir():
        raise PathValidationError(f"Auxiliary output is an existing directory: {destination}")
    if is_link_like(destination):
        raise PathValidationError(f"Linked auxiliary output is not allowed: {destination}")
    if resolved_destination.exists() and resolved_destination.stat().st_nlink > 1:
        raise PathValidationError(f"Hard-linked auxiliary output is not allowed: {destination}")
    return resolved_destination


def make_writable(path: Path) -> None:
    """copy2 が引き継いだ Windows read-only 属性を出力側だけで解除する。"""

    try:
        mode = path.stat().st_mode
    except OSError:
        return
    os.chmod(path, mode | stat.S_IWRITE)


def validate_input_output(input_dir: Path, output_dir: Path | None) -> tuple[Path, Path]:
    """resolve 後の同一・親子パスを Windows の大小無視で拒否する。"""

    try:
        resolved_input = input_dir.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PathValidationError(f"Input directory cannot be resolved: {input_dir}") from exc
    if not resolved_input.is_dir():
        raise PathValidationError(f"Input path is not a directory: {resolved_input}")

    requested_output = output_dir if output_dir is not None else Path(f"{resolved_input}_resized")
    try:
        resolved_output = requested_output.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PathValidationError(f"Output directory cannot be resolved: {requested_output}") from exc
    if resolved_output.exists() and not resolved_output.is_dir():
        raise PathValidationError(f"Output path is not a directory: {resolved_output}")

    input_key = _normalized_path(resolved_input)
    output_key = _normalized_path(resolved_output)
    if input_key == output_key:
        raise PathValidationError("Input and output directories must be different")

    try:
        common_key = _normalized_path(Path(os.path.commonpath((input_key, output_key))))
    except ValueError:
        common_key = ""
    if common_key == input_key:
        raise PathValidationError("Output directory must not be inside the input directory")
    if common_key == output_key:
        raise PathValidationError("Input directory must not be inside the output directory")
    return resolved_input, resolved_output


@contextmanager
def staged_path(
    destination: Path,
    *,
    input_root: Path | None = None,
    output_root: Path | None = None,
) -> Iterator[Path]:
    """正式出力と同じディレクトリに publish 前の一時パスを作る。"""

    if (input_root is None) != (output_root is None):
        raise ValueError("input_root and output_root must be supplied together")
    if input_root is not None and output_root is not None:
        validate_output_destination(input_root, output_root, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if input_root is not None and output_root is not None:
        validate_output_destination(input_root, output_root, destination)
    descriptor, raw_path = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary = Path(raw_path)
    try:
        if input_root is not None and output_root is not None:
            validate_output_destination(input_root, output_root, temporary)
        yield temporary
    finally:
        make_writable(temporary)
        temporary.unlink(missing_ok=True)
