"""KaruFile v1 の画像変換、再利用判定、エラーレポート。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
from typing import Any, Mapping, cast

from PIL import Image, ImageOps

from .config import ImageConfig, ImagePreset, image_preset_for_recipe_hash
from .utils import (
    PathValidationError,
    is_link_like,
    logger,
    make_writable,
    staged_path,
    validate_auxiliary_output,
    validate_output_destination,
    validate_source_path,
)

try:
    from pillow_heif import register_heif_opener

    register_heif_opener(thumbnails=False)
except Exception as exc:  # pragma: no cover - platform/DLL failure is reported per HEIF file
    logger.warning("pillow-heif could not be initialized: %s", exc)


IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif", ".webp", ".heic", ".heif"}
)
JPEG_EXTENSIONS = frozenset({".jpg", ".jpeg"})
MARKER_VERSION = 2
MARKER_ID = f"karufile:image-v{MARKER_VERSION}"
MARKER_PREFIX = b"karufile:image-"
JPEG_MIN_SAVINGS = 32 * 1024
JPEG_MIN_REDUCTION = 0.10
MANIFEST_COLUMNS = (
    "source_path",
    "source_size",
    "source_sha256",
    "output_path",
    "output_size",
    "output_sha256",
    "action",
    "error",
    "preset",
    "recipe_hash",
    "orig_width",
    "orig_height",
    "new_width",
    "new_height",
)
NORMAL_IMAGE_ACTIONS = frozenset(
    {
        "CONVERTED",
        "SKIPPED_GENERATED",
        "SKIPPED_COMPLETE",
        "SKIPPED_COPY",
        "COPIED_ORIGINAL",
        "COPIED_ENCODE_FAILED",
    }
)
DRY_RUN_IMAGE_ACTIONS = frozenset({"DRY_RUN", "DRY_RUN_SKIPPED_GENERATED"})
_MARKER_RE = re.compile(
    rb"karufile:image-v([12]);recipe=([0-9a-f]+);src_size=([0-9]+);"
    rb"src_mtime_ns=(-?[0-9]+)(?:;src_sha256=([0-9a-f]{64}))?",
    re.IGNORECASE,
)


class OutputCollisionError(RuntimeError):
    """固定8桁hashでも出力を一意にできない場合のエラー。"""


class SourceChangedError(OSError):
    """処理中に入力画像の内容またはファイル同一性が変化した。"""


@dataclass(frozen=True, slots=True)
class ImagePlan:
    source: Path
    relative_source: Path
    output: Path


@dataclass(frozen=True, slots=True)
class SourceFingerprint:
    """入力画像の1時点における安定したstatと内容SHA-256。"""

    stat: os.stat_result
    sha256: str

    @property
    def stat_signature(self) -> tuple[int, int, int, int, int]:
        return _stat_signature(self.stat)


@dataclass(frozen=True, slots=True)
class OutputFingerprint:
    """再利用候補JPEGの安定した内容・metadata snapshot。"""

    stat: os.stat_result
    sha256: str
    dimensions: tuple[int, int]
    comment: bytes

    @property
    def stat_signature(self) -> tuple[int, int, int, int, int]:
        return _stat_signature(self.stat)


def _file_identity(path: Path) -> tuple[int, int] | None:
    try:
        file_stat = path.stat()
    except OSError:
        return None
    return file_stat.st_dev, file_stat.st_ino


def _validate_existing_output_identity(
    output: Path,
    source_identities: set[tuple[int, int]],
) -> None:
    if is_link_like(output):
        raise PathValidationError(f"Linked output file is not allowed: {output}")
    try:
        output_stat = output.stat()
    except OSError:
        return
    if output_stat.st_nlink > 1:
        raise PathValidationError(f"Hard-linked output is not allowed: {output}")
    output_identity = output_stat.st_dev, output_stat.st_ino
    if output_identity is not None and output_identity in source_identities:
        raise PathValidationError(f"Existing output is the same file as an input source: {output}")


def _validate_replaceable_file(path: Path, *, label: str) -> None:
    """正式ファイルをchmodせず、安全に置換可能な既存fileだけを許可する。"""

    if is_link_like(path):
        raise PathValidationError(f"Linked {label} is not allowed: {path}")
    try:
        file_stat = path.stat()
    except FileNotFoundError:
        return
    if not path.is_file() or file_stat.st_nlink > 1:
        raise PathValidationError(f"Unsafe {label} cannot be replaced: {path}")
    if not file_stat.st_mode & stat.S_IWRITE:
        raise PathValidationError(f"Read-only {label} cannot be replaced: {path}")


def _coerce_config(config: ImageConfig | Mapping[str, Any]) -> ImageConfig:
    if isinstance(config, ImageConfig):
        return config
    return ImageConfig(
        workers=int(config.get("workers", 4)),
        dry_run=bool(config.get("dry_run", False)),
        preset=cast(ImagePreset, str(config.get("preset", "standard"))),
    )


def calculate_output_size(size: tuple[int, int], config: ImageConfig | None = None) -> tuple[int, int]:
    """Orientation適用後の寸法を選択レシピの枠へ拡大せず収める。"""

    width, height = size
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid image dimensions: {size}")
    cfg = config or ImageConfig()
    long_side = max(width, height)
    short_side = min(width, height)
    scale = min(1.0, cfg.max_long / long_side, cfg.max_short / short_side)
    return max(1, round(width * scale)), max(1, round(height * scale))


def _relative_output_path(relative_source: Path) -> Path:
    if relative_source.suffix.lower() in JPEG_EXTENSIONS:
        return relative_source
    return relative_source.with_name(f"{relative_source.name}.jpg")


def _case_insensitive_key(path: Path) -> str:
    return path.as_posix().casefold()


def _hashed_output(path: Path, relative_source: Path) -> Path:
    digest = hashlib.sha256(relative_source.as_posix().encode("utf-8")).hexdigest()[:8]
    return path.with_name(f"{path.stem}~{digest}{path.suffix}")


def plan_outputs(input_dir: Path, output_dir: Path, sources: list[Path]) -> list[ImagePlan]:
    """全出力を先に決め、大小無視の同名・file/dir衝突をhashで解消する。"""

    base_plans: list[ImagePlan] = []
    groups: dict[str, list[int]] = {}
    for source in sources:
        relative = source.relative_to(input_dir)
        output = output_dir / _relative_output_path(relative)
        index = len(base_plans)
        base_plans.append(ImagePlan(source, relative, output))
        groups.setdefault(_case_insensitive_key(output.relative_to(output_dir)), []).append(index)

    hashed_indexes = {index for indexes in groups.values() if len(indexes) > 1 for index in indexes}
    while True:
        plans = [
            ImagePlan(plan.source, plan.relative_source, _hashed_output(plan.output, plan.relative_source))
            if index in hashed_indexes
            else plan
            for index, plan in enumerate(base_plans)
        ]
        final_groups: dict[str, list[int]] = {}
        for index, plan in enumerate(plans):
            key = _case_insensitive_key(plan.output.relative_to(output_dir))
            final_groups.setdefault(key, []).append(index)
        remaining = [indexes for indexes in final_groups.values() if len(indexes) > 1]

        path_parts = [
            tuple(part.casefold() for part in plan.output.relative_to(output_dir).parts)
            for plan in plans
        ]
        prefix_indexes = {
            left_index
            for left_index, left in enumerate(path_parts)
            for right_index, right in enumerate(path_parts)
            if left_index != right_index
            and len(left) < len(right)
            and right[: len(left)] == left
        }
        if not remaining and not prefix_indexes:
            return plans

        newly_hashed = {
            index
            for indexes in remaining
            for index in indexes
            if index not in hashed_indexes
        }
        newly_hashed.update(index for index in prefix_indexes if index not in hashed_indexes)
        if newly_hashed:
            hashed_indexes.update(newly_hashed)
            continue

        sources_text = ", ".join(
            str(plans[index].relative_source)
            for index in sorted(
                {index for indexes in remaining for index in indexes} | prefix_indexes
            )
        )
        raise OutputCollisionError(
            f"Could not resolve output file/directory collision with 8-digit hashes: {sources_text}"
        )


def collect_images(input_dir: Path) -> list[Path]:
    """Junction/symlinkを辿らず、入力root内の通常ファイルだけを列挙する。"""

    try:
        root = input_dir.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PathValidationError(f"Input directory cannot be resolved: {input_dir}") from exc

    sources: list[Path] = []
    directories = [root]
    while directories:
        directory = directories.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                if is_link_like(path):
                    raise PathValidationError(f"Linked input path is not allowed: {path}")
                if entry.is_dir(follow_symlinks=False):
                    directories.append(path)
                elif entry.is_file(follow_symlinks=False) and path.suffix.lower() in IMAGE_EXTENSIONS:
                    validate_source_path(root, path)
                    sources.append(path)
    return sorted(
        sources,
        key=lambda path: (
            path.relative_to(input_dir).as_posix().casefold(),
            path.relative_to(input_dir).as_posix(),
        ),
    )


def _comment_payloads(image: Image.Image) -> list[bytes]:
    """Pillow の ``info`` だけで失われる複数COM segmentも読む。"""

    payloads: list[bytes] = []
    for marker, payload in getattr(image, "applist", ()):  # JPEG plugin specific
        if marker == "COM":
            if isinstance(payload, bytes):
                payloads.append(payload)
            elif isinstance(payload, str):
                payloads.append(payload.encode("utf-8", "replace"))
    if payloads:
        return payloads

    payload = image.info.get("comment")
    if isinstance(payload, bytes):
        return [payload]
    if isinstance(payload, str):
        return [payload.encode("utf-8", "replace")]
    return []


def _combined_comment(image: Image.Image) -> bytes:
    return b"\n".join(_comment_payloads(image))


def _has_karufile_marker(comment: bytes) -> bool:
    return MARKER_PREFIX in comment.lower()


def _parse_current_marker(comment: bytes) -> tuple[int, str, int, int, str | None] | None:
    matches = list(_MARKER_RE.finditer(comment))
    if not matches:
        return None
    version, recipe, size, mtime, source_sha256 = matches[-1].groups()
    return (
        int(version),
        recipe.decode("ascii").lower(),
        int(size),
        int(mtime),
        source_sha256.decode("ascii").lower() if source_sha256 else None,
    )


def _known_generated_preset(comment: bytes) -> ImagePreset | None:
    """完全な現行markerと既知recipeだけを生成済み入力として信頼する。"""

    marker = _parse_current_marker(comment)
    if marker is None:
        return None
    version, recipe_hash, _source_size, _source_mtime_ns, source_sha256 = marker
    if version != MARKER_VERSION or source_sha256 is None:
        return None
    return image_preset_for_recipe_hash(recipe_hash)


def _generated_jpeg_requires_reprocessing(comment: bytes, config: ImageConfig) -> bool:
    """未知・破損markerとstandard→compactは生成済み短絡を許可しない。"""

    if not _has_karufile_marker(comment):
        return False
    source_preset = _known_generated_preset(comment)
    if source_preset is None:
        return True
    return source_preset == "standard" and config.preset == "compact"


def _without_karufile_marker_lines(comment: bytes) -> bytes:
    """再エンコード時に旧内部markerだけを除き、利用者commentは残す。"""

    return b"\n".join(
        line for line in comment.splitlines() if MARKER_PREFIX not in line.lower()
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _stat_signature(file_stat: os.stat_result) -> tuple[int, int, int, int, int]:
    """置換と同一サイズ・mtime偽装も検知できるsource identity。"""

    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_size,
        file_stat.st_mtime_ns,
        file_stat.st_ctime_ns,
    )


def _capture_source_fingerprint(source: Path) -> SourceFingerprint:
    """hash中にstatが変わらなかった入力のfingerprintだけを返す。"""

    before = source.stat()
    source_sha256 = _sha256_file(source)
    after = source.stat()
    if _stat_signature(before) != _stat_signature(after):
        raise SourceChangedError(f"Source changed while hashing: {source}")
    return SourceFingerprint(stat=after, sha256=source_sha256)


def _assert_source_unchanged(
    source: Path,
    expected: SourceFingerprint,
    input_root: Path,
) -> None:
    """公開または再利用確定の直前に入力の同一性と内容を再検証する。"""

    try:
        validate_source_path(input_root, source)
        observed = _capture_source_fingerprint(source)
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


def _marker_for(
    source_stat: os.stat_result,
    source_sha256: str,
    config: ImageConfig,
) -> bytes:
    return (
        f"{MARKER_ID};recipe={config.recipe_hash};src_size={source_stat.st_size};"
        f"src_mtime_ns={source_stat.st_mtime_ns};src_sha256={source_sha256}"
    ).encode("ascii")


def _inspect_jpeg(path: Path) -> tuple[tuple[int, int], bytes]:
    if path.stat().st_size <= 0:
        raise ValueError("JPEG output is empty")
    with Image.open(path) as image:
        if image.format != "JPEG":
            raise ValueError(f"Expected JPEG output, got {image.format!r}")
        size = image.size
        comment = _combined_comment(image)
        image.load()
    return size, comment


def _capture_output_fingerprint(output: Path) -> OutputFingerprint:
    """linkでなく、読取り中も同一だったJPEG出力だけをsnapshot化する。"""

    if is_link_like(output):
        raise PathValidationError(f"Linked output file is not allowed: {output}")
    before = output.stat()
    if not output.is_file() or before.st_nlink > 1:
        raise PathValidationError(f"Unsafe image output cannot be reused: {output}")
    dimensions, comment = _inspect_jpeg(output)
    digest = _sha256_file(output)
    after = output.stat()
    if _stat_signature(before) != _stat_signature(after):
        raise OutputCollisionError(f"Image output changed while validating reuse: {output}")
    return OutputFingerprint(after, digest, dimensions, comment)


def _assert_reusable_output_unchanged(
    output: Path,
    expected: OutputFingerprint,
    *,
    input_root: Path,
    output_root: Path,
    source_identity: tuple[int, int],
) -> OutputFingerprint:
    """source検査で生じた窓の後にreuse対象とdestinationを再確認する。"""

    validate_output_destination(input_root, output_root, output)
    _validate_existing_output_identity(output, {source_identity})
    observed = _capture_output_fingerprint(output)
    if (
        observed.stat_signature != expected.stat_signature
        or observed.sha256 != expected.sha256
        or observed.dimensions != expected.dimensions
        or observed.comment != expected.comment
    ):
        raise OutputCollisionError(f"Image output changed before reuse: {output}")
    validate_output_destination(input_root, output_root, output)
    _validate_existing_output_identity(output, {source_identity})
    return observed


def _completed_output_matches(
    output: Path,
    source_stat: os.stat_result,
    source_sha256: str,
    config: ImageConfig,
) -> OutputFingerprint | None:
    if not output.is_file():
        return None
    try:
        fingerprint = _capture_output_fingerprint(output)
        dimensions, comment = fingerprint.dimensions, fingerprint.comment
        width, height = dimensions
        if max(width, height) > config.max_long or min(width, height) > config.max_short:
            return None
        marker = _parse_current_marker(comment)
        if marker != (
            MARKER_VERSION,
            config.recipe_hash,
            source_stat.st_size,
            source_stat.st_mtime_ns,
            source_sha256,
        ):
            return None
        return fingerprint
    except Exception:
        return None


def _copied_output_matches(
    output: Path,
    source_stat: os.stat_result,
    source_sha256: str,
    config: ImageConfig,
) -> OutputFingerprint | None:
    if not output.is_file():
        return None
    try:
        fingerprint = _capture_output_fingerprint(output)
        output_stat = fingerprint.stat
        if output_stat.st_size != source_stat.st_size or output_stat.st_mtime_ns != source_stat.st_mtime_ns:
            return None
        dimensions = fingerprint.dimensions
        if max(dimensions) > config.max_long or min(dimensions) > config.max_short:
            return None
        if fingerprint.sha256 != source_sha256:
            return None
        return fingerprint
    except Exception:
        return None


def _has_alpha(image: Image.Image) -> bool:
    return "A" in image.getbands() or (image.mode == "P" and "transparency" in image.info)


def _to_rgb(image: Image.Image, warnings: list[str]) -> Image.Image:
    if _has_alpha(image):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        background.alpha_composite(rgba)
        rgba.close()
        warnings.append("ALPHA_FLATTENED")
        converted = background.convert("RGB")
        background.close()
        return converted
    if image.mode == "RGB":
        return image.copy()
    return image.convert("RGB")


def _optional_metadata(
    source: Image.Image,
    oriented: Image.Image,
    source_mode: str,
    warnings: list[str],
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    try:
        exif = oriented.getexif()
        exif.pop(274, None)  # Orientationは画素へ適用済み。
        if exif:
            metadata["exif"] = exif.tobytes()
    except Exception:
        warnings.append("EXIF_DROPPED")

    icc = source.info.get("icc_profile")
    if icc:
        if source_mode in {"RGB", "RGBA", "RGBX", "RGBa", "P"}:
            metadata["icc_profile"] = icc
        else:
            warnings.append("ICC_DROPPED")

    xmp = oriented.info.get("xmp", source.info.get("xmp"))
    if isinstance(xmp, (bytes, str)) and xmp:
        metadata["xmp"] = xmp
    elif xmp:
        warnings.append("XMP_DROPPED")

    dpi = source.info.get("dpi")
    if isinstance(dpi, tuple) and len(dpi) == 2:
        try:
            if float(dpi[0]) > 0 and float(dpi[1]) > 0:
                metadata["dpi"] = dpi
        except (TypeError, ValueError):
            warnings.append("DPI_DROPPED")
    return metadata


def _append_warning(warnings: list[str], warning: str) -> None:
    if warning not in warnings:
        warnings.append(warning)


def _save_jpeg(
    image: Image.Image,
    temporary: Path,
    marker: bytes,
    existing_comment: bytes,
    metadata: Mapping[str, Any],
    warnings: list[str],
    config: ImageConfig,
) -> None:
    core: dict[str, Any] = {
        "quality": config.quality,
        "subsampling": config.subsampling,
        "optimize": config.optimize,
        "progressive": config.progressive,
    }
    combined_comment = existing_comment + (b"\n" if existing_comment else b"") + marker

    attempts: list[tuple[bytes, Mapping[str, Any], tuple[str, ...]]] = [
        (combined_comment, metadata, ()),
    ]
    if existing_comment:
        # 長すぎる既存COMだけを捨て、保存可能なEXIF/ICC/XMPは先に残す。
        attempts.append((marker, metadata, ("COMMENT_DROPPED",)))
    if metadata:
        attempts.append((combined_comment, {}, ("METADATA_DROPPED",)))
    if existing_comment and metadata:
        attempts.append((marker, {}, ("COMMENT_DROPPED", "METADATA_DROPPED")))

    last_error: BaseException | None = None
    for comment, attempt_metadata, attempt_warnings in attempts:
        try:
            image.save(
                temporary,
                format="JPEG",
                comment=comment,
                **core,
                **attempt_metadata,
            )
        except (OSError, TypeError, ValueError) as exc:
            last_error = exc
            continue
        for warning in attempt_warnings:
            _append_warning(warnings, warning)
        return
    raise ValueError("JPEG candidate could not be saved with its required marker") from last_error


def _verify_candidate(
    path: Path,
    expected_size: tuple[int, int],
    config: ImageConfig,
) -> OutputFingerprint:
    fingerprint = _capture_output_fingerprint(path)
    dimensions, comment = fingerprint.dimensions, fingerprint.comment
    if dimensions != expected_size:
        raise ValueError(f"JPEG output dimensions differ: expected {expected_size}, got {dimensions}")
    if max(dimensions) > config.max_long or min(dimensions) > config.max_short:
        raise ValueError(f"JPEG output exceeds dimension limits: {dimensions}")
    if not _has_karufile_marker(comment):
        raise ValueError("JPEG output marker is missing")
    return fingerprint


def _replace_staged(
    temporary: Path,
    output: Path,
    input_root: Path,
    output_root: Path,
    protected_source: Path,
    source_fingerprint: SourceFingerprint,
) -> None:
    # 正式出力へ一切触れる前と os.replace の直前の双方で確認する。
    # これにより、競合検知時は既存の正常出力をそのまま残せる。
    _assert_source_unchanged(protected_source, source_fingerprint, input_root)
    validate_output_destination(input_root, output_root, output)
    if is_link_like(output):
        raise PathValidationError(f"Linked output file is not allowed: {output}")
    source_identity = (
        source_fingerprint.stat.st_dev,
        source_fingerprint.stat.st_ino,
    )
    _validate_existing_output_identity(output, {source_identity})
    make_writable(temporary)
    validate_output_destination(input_root, output_root, output)
    _validate_existing_output_identity(output, {source_identity})
    _assert_source_unchanged(protected_source, source_fingerprint, input_root)
    # source SHAの再読中にoutput側の親がjunction等へ差し替わる場合があるため、
    # source確認後にもdestinationと既存ファイルの安全性を確定する。
    validate_output_destination(input_root, output_root, output)
    _validate_existing_output_identity(output, {source_identity})
    _validate_replaceable_file(output, label="image output")
    os.replace(temporary, output)


def _publish_copy(
    source: Path,
    output: Path,
    input_root: Path,
    output_root: Path,
    source_fingerprint: SourceFingerprint,
) -> OutputFingerprint:
    with staged_path(output, input_root=input_root, output_root=output_root) as temporary:
        shutil.copy2(source, temporary)
        make_writable(temporary)
        size = temporary.stat().st_size
        if (
            size != source_fingerprint.stat.st_size
            or _sha256_file(temporary) != source_fingerprint.sha256
        ):
            raise SourceChangedError(f"Source changed while copying: {source}")
        _inspect_jpeg(temporary)
        _replace_staged(
            temporary,
            output,
            input_root,
            output_root,
            source,
            source_fingerprint,
        )
    published = _capture_output_fingerprint(output)
    if (
        published.stat.st_size != size
        or published.sha256 != source_fingerprint.sha256
    ):
        raise OutputCollisionError(f"Published image copy changed unexpectedly: {output}")
    return published


def _result(
    source: Path,
    output: Path,
    action: str,
    original_size: int,
    new_size: int,
    warnings: list[str],
    *,
    original_dimensions: tuple[int, int] | None = None,
    new_dimensions: tuple[int, int] | None = None,
    source_fingerprint: SourceFingerprint,
    output_fingerprint: OutputFingerprint | None = None,
) -> dict[str, Any]:
    return {
        "source": str(source),
        "src": str(source),  # 既存の内部呼出しとの互換フィールド。
        "planned_output": str(output),
        "dst": str(output),
        "action": action,
        "orig_size": original_size,
        "new_size": new_size,
        "orig_dims": original_dimensions,
        "new_dims": new_dimensions,
        "warnings": warnings,
        "_source_fingerprint": source_fingerprint,
        "_output_fingerprint": output_fingerprint,
    }


def process_image(
    source: Path,
    output: Path,
    config: ImageConfig | Mapping[str, Any],
    *,
    input_root: Path | None = None,
    output_root: Path | None = None,
) -> dict[str, Any]:
    """1画像を処理する。入力ファイルへ書込みや削除は行わない。"""

    cfg = _coerce_config(config)
    resolved_source = source.resolve(strict=True)
    effective_input_root = (
        input_root.resolve(strict=True) if input_root is not None else resolved_source
    )
    effective_output_root = (
        output_root.resolve(strict=False) if output_root is not None else output.parent.resolve(strict=False)
    )
    validate_source_path(effective_input_root, source)
    validate_output_destination(effective_input_root, effective_output_root, output)
    source_identity = _file_identity(source)
    if source_identity is not None:
        _validate_existing_output_identity(output, {source_identity})
    source_fingerprint = _capture_source_fingerprint(source)
    source_stat = source_fingerprint.stat
    source_sha256 = source_fingerprint.sha256
    warnings: list[str] = []
    with Image.open(source) as opened:
        source_format = opened.format
        source_mode = opened.mode
        original_dimensions = opened.size
        try:
            orientation_value = opened.getexif().get(274)
        except Exception:
            orientation_value = None
        orientation_applied = orientation_value in {2, 3, 4, 5, 6, 7, 8}
        frame_count = int(getattr(opened, "n_frames", 1))
        if frame_count > 1:
            if source_format in {"GIF", "WEBP"}:
                warnings.append("ANIMATION_DROPPED")
            elif source_format in {"TIFF", "MPO"}:
                warnings.append("MULTIPAGE_DROPPED")
        opened.seek(0)
        opened.load()

        source_is_jpeg = source_format == "JPEG"
        existing_comment = _combined_comment(opened)
        reprocess_generated = source_is_jpeg and _generated_jpeg_requires_reprocessing(
            existing_comment,
            cfg,
        )
        generated_copy_safe = (
            source_is_jpeg
            and _known_generated_preset(existing_comment) is not None
            and not reprocess_generated
            and not orientation_applied
            and calculate_output_size(original_dimensions, cfg) == original_dimensions
        )
        if generated_copy_safe:
            if cfg.dry_run:
                _assert_source_unchanged(source, source_fingerprint, effective_input_root)
                return _result(
                    source,
                    output,
                    "DRY_RUN_SKIPPED_GENERATED",
                    source_stat.st_size,
                    0,
                    warnings,
                    original_dimensions=original_dimensions,
                    new_dimensions=original_dimensions,
                    source_fingerprint=source_fingerprint,
                )
            copied = _publish_copy(
                source,
                output,
                effective_input_root,
                effective_output_root,
                source_fingerprint,
            )
            return _result(
                source,
                output,
                "SKIPPED_GENERATED",
                source_stat.st_size,
                copied.stat.st_size,
                warnings,
                original_dimensions=original_dimensions,
                new_dimensions=original_dimensions,
                source_fingerprint=source_fingerprint,
                output_fingerprint=copied,
            )

        completed = _completed_output_matches(output, source_stat, source_sha256, cfg)
        if completed is not None:
            _assert_source_unchanged(source, source_fingerprint, effective_input_root)
            completed = _assert_reusable_output_unchanged(
                output,
                completed,
                input_root=effective_input_root,
                output_root=effective_output_root,
                source_identity=(source_stat.st_dev, source_stat.st_ino),
            )
            _assert_source_unchanged(source, source_fingerprint, effective_input_root)
            return _result(
                source,
                output,
                "SKIPPED_COMPLETE",
                source_stat.st_size,
                completed.stat.st_size,
                warnings,
                original_dimensions=original_dimensions,
                new_dimensions=completed.dimensions,
                source_fingerprint=source_fingerprint,
                output_fingerprint=completed,
            )

        # 原本コピーにはmarkerを書けないため、どのレシピで候補が却下されたか
        # 後から識別できない。compactでは毎回再評価し、standard時のコピーを
        # SKIPPED_COPYとして誤再利用しない。
        if (
            source_is_jpeg
            and not orientation_applied
            and not reprocess_generated
            and cfg.preset == "standard"
        ):
            copied = _copied_output_matches(output, source_stat, source_sha256, cfg)
            if copied is not None:
                _assert_source_unchanged(source, source_fingerprint, effective_input_root)
                copied = _assert_reusable_output_unchanged(
                    output,
                    copied,
                    input_root=effective_input_root,
                    output_root=effective_output_root,
                    source_identity=(source_stat.st_dev, source_stat.st_ino),
                )
                _assert_source_unchanged(source, source_fingerprint, effective_input_root)
                return _result(
                    source,
                    output,
                    "SKIPPED_COPY",
                    source_stat.st_size,
                    copied.stat.st_size,
                    warnings,
                    original_dimensions=original_dimensions,
                    new_dimensions=copied.dimensions,
                    source_fingerprint=source_fingerprint,
                    output_fingerprint=copied,
                )

        predicted_oriented_dimensions = (
            (original_dimensions[1], original_dimensions[0])
            if orientation_value in {5, 6, 7, 8}
            else original_dimensions
        )
        predicted_output_dimensions = calculate_output_size(predicted_oriented_dimensions, cfg)
        requires_pixel_transform = (
            orientation_applied or predicted_output_dimensions != predicted_oriented_dimensions
        )
        working: Image.Image | None = None
        try:
            oriented = ImageOps.exif_transpose(opened)
            try:
                oriented.load()
                metadata = _optional_metadata(opened, oriented, source_mode, warnings)
                oriented_dimensions = oriented.size
                working = _to_rgb(oriented, warnings)
            finally:
                oriented.close()

            expected_dimensions = calculate_output_size(working.size, cfg)
            if working.size != expected_dimensions:
                resized = working.resize(expected_dimensions, Image.Resampling.LANCZOS)
                working.close()
                working = resized

            if cfg.dry_run:
                _assert_source_unchanged(source, source_fingerprint, effective_input_root)
                return _result(
                    source,
                    output,
                    "DRY_RUN",
                    source_stat.st_size,
                    0,
                    warnings,
                    original_dimensions=original_dimensions,
                    new_dimensions=expected_dimensions,
                    source_fingerprint=source_fingerprint,
                )

            marker = _marker_for(source_stat, source_sha256, cfg)
            candidate_comment = (
                _without_karufile_marker_lines(existing_comment)
                if reprocess_generated
                else existing_comment
            )
            must_resize = oriented_dimensions != expected_dimensions
            with staged_path(
                output,
                input_root=effective_input_root,
                output_root=effective_output_root,
            ) as temporary:
                _save_jpeg(working, temporary, marker, candidate_comment, metadata, warnings, cfg)
                candidate = _verify_candidate(temporary, expected_dimensions, cfg)
                candidate_size = candidate.stat.st_size
                savings = source_stat.st_size - candidate_size
                reduction = savings / source_stat.st_size if source_stat.st_size else 0.0
                adopt_candidate = (
                    not source_is_jpeg
                    or must_resize
                    or orientation_applied
                    or (reprocess_generated and savings > 0)
                    or (savings >= JPEG_MIN_SAVINGS and reduction >= JPEG_MIN_REDUCTION)
                )
                if adopt_candidate:
                    if not source_is_jpeg and candidate_size > source_stat.st_size:
                        _append_warning(warnings, "OUTPUT_LARGER_THAN_SOURCE")
                    _replace_staged(
                        temporary,
                        output,
                        effective_input_root,
                        effective_output_root,
                        source,
                        source_fingerprint,
                    )
                    published = _capture_output_fingerprint(output)
                    if (
                        published.sha256 != candidate.sha256
                        or published.dimensions != candidate.dimensions
                        or published.comment != candidate.comment
                    ):
                        raise OutputCollisionError(
                            f"Published image changed unexpectedly: {output}"
                        )
                    return _result(
                        source,
                        output,
                        "CONVERTED",
                        source_stat.st_size,
                        candidate_size,
                        warnings,
                        original_dimensions=original_dimensions,
                        new_dimensions=expected_dimensions,
                        source_fingerprint=source_fingerprint,
                        output_fingerprint=published,
                    )

            copied = _publish_copy(
                source,
                output,
                effective_input_root,
                effective_output_root,
                source_fingerprint,
            )
            return _result(
                source,
                output,
                "COPIED_ORIGINAL",
                source_stat.st_size,
                copied.stat.st_size,
                [],
                original_dimensions=original_dimensions,
                new_dimensions=original_dimensions,
                source_fingerprint=source_fingerprint,
                output_fingerprint=copied,
            )
        except Exception as exc:
            if isinstance(
                exc,
                (SourceChangedError, OutputCollisionError, PathValidationError),
            ):
                raise
            if not source_is_jpeg:
                raise
            if cfg.dry_run:
                raise
            _append_warning(warnings, "ENCODE_FAILED_ORIGINAL_COPIED")
            copied = _publish_copy(
                source,
                output,
                effective_input_root,
                effective_output_root,
                source_fingerprint,
            )
            result = _result(
                source,
                output,
                "COPIED_ENCODE_FAILED",
                source_stat.st_size,
                copied.stat.st_size,
                warnings,
                original_dimensions=original_dimensions,
                new_dimensions=original_dimensions,
                source_fingerprint=source_fingerprint,
                output_fingerprint=copied,
            )
            if requires_pixel_transform:
                result["error"] = (
                    "JPEG conversion failed; the original was copied but the required pixel transform "
                    f"was not applied: {type(exc).__name__}: {exc}"
                )
            return result
        finally:
            if working is not None:
                working.close()


def _error_result(plan: ImagePlan, exc: BaseException) -> dict[str, Any]:
    try:
        source_fingerprint: SourceFingerprint | None = _capture_source_fingerprint(
            plan.source
        )
        original_size = source_fingerprint.stat.st_size
    except OSError:
        source_fingerprint = None
        original_size = 0
    return {
        "source": str(plan.source),
        "src": str(plan.source),
        "planned_output": str(plan.output),
        "dst": str(plan.output),
        "action": "ERROR",
        "error": f"{type(exc).__name__}: {exc}",
        "orig_size": original_size,
        "new_size": 0,
        "orig_dims": None,
        "new_dims": None,
        "warnings": [],
        "_source_fingerprint": source_fingerprint,
        "_output_fingerprint": None,
    }


def process_all(
    input_dir: Path,
    output_dir: Path,
    config: ImageConfig | Mapping[str, Any],
) -> list[dict[str, Any]]:
    cfg = _coerce_config(config)
    resolved_input = input_dir.resolve(strict=True)
    resolved_output = output_dir.resolve(strict=False)
    sources = collect_images(resolved_input)
    plans = plan_outputs(resolved_input, resolved_output, sources)
    source_identities = {
        identity for source in sources if (identity := _file_identity(source)) is not None
    }
    for plan in plans:
        validate_source_path(resolved_input, plan.source)
        validate_output_destination(resolved_input, resolved_output, plan.output)
        _validate_existing_output_identity(plan.output, source_identities)
    results: list[dict[str, Any] | None] = [None] * len(plans)

    def task(index: int, plan: ImagePlan) -> tuple[int, dict[str, Any]]:
        try:
            return index, process_image(
                plan.source,
                plan.output,
                cfg,
                input_root=resolved_input,
                output_root=resolved_output,
            )
        except Exception as exc:
            return index, _error_result(plan, exc)

    if cfg.workers <= 1 or len(plans) <= 1:
        for index, plan in enumerate(plans):
            result_index, result = task(index, plan)
            results[result_index] = result
    else:
        with ThreadPoolExecutor(max_workers=cfg.workers) as executor:
            futures = [executor.submit(task, index, plan) for index, plan in enumerate(plans)]
            for future in as_completed(futures):
                result_index, result = future.result()
                results[result_index] = result

    completed_results = [result for result in results if result is not None]
    for result in completed_results:
        if "error" in result:
            logger.error("%s: %s", result["source"], result["error"])
            continue
        logger.info("%s -> %s (%s)", result["source"], result["planned_output"], result["action"])
        for warning in result["warnings"]:
            logger.warning("%s: %s", result["source"], warning)
    return completed_results


def error_report_path(output_dir: Path) -> Path:
    return Path(f"{output_dir}.image-errors.csv")


def manifest_path(output_dir: Path, *, dry_run: bool) -> Path:
    suffix = ".image-manifest.dry-run.csv" if dry_run else ".image-manifest.csv"
    return Path(f"{output_dir}{suffix}")


def _dimension_columns(
    dimensions: tuple[int, int] | None,
) -> tuple[int | str, int | str]:
    if dimensions is None:
        return "", ""
    return dimensions


def _validated_dimensions(
    value: object,
    *,
    label: str,
    required: bool,
) -> tuple[int, int] | None:
    if value is None and not required:
        return None
    if (
        not isinstance(value, tuple)
        or len(value) != 2
        or any(not isinstance(item, int) or isinstance(item, bool) or item <= 0 for item in value)
    ):
        raise OutputCollisionError(f"Invalid {label} dimensions: {value!r}")
    return value


def _validated_manifest_rows(
    input_dir: Path,
    output_dir: Path,
    results: list[dict[str, Any]],
    config: ImageConfig,
) -> list[dict[str, Any]]:
    """処理時snapshotと現在の全source/outputが一致する行だけを構築する。"""

    rows: list[dict[str, Any]] = []
    for result in results:
        source = Path(str(result["source"]))
        output = Path(str(result["planned_output"]))
        expected_source = result.get("_source_fingerprint")
        if not isinstance(expected_source, SourceFingerprint):
            raise SourceChangedError(f"Stable source fingerprint is unavailable: {source}")
        _assert_source_unchanged(source, expected_source, input_dir)
        validate_output_destination(input_dir, output_dir, output)

        action = str(result.get("action") or "ERROR")
        error = str(result.get("error") or "")
        expected_output = result.get("_output_fingerprint")
        if config.dry_run:
            if action not in DRY_RUN_IMAGE_ACTIONS | {"ERROR"}:
                raise OutputCollisionError(f"Invalid dry-run image action: {action}")
        elif action not in NORMAL_IMAGE_ACTIONS | {"ERROR"}:
            raise OutputCollisionError(f"Invalid image action: {action}")
        if action == "ERROR" and not error:
            raise OutputCollisionError(f"Image ERROR row has no error: {source}")
        if error and action not in {"ERROR", "COPIED_ENCODE_FAILED"}:
            raise OutputCollisionError(
                f"Image action/error combination is invalid: {action}"
            )
        has_planned_image = action != "ERROR"
        original_dimensions = _validated_dimensions(
            result.get("orig_dims"),
            label="original",
            required=has_planned_image,
        )
        new_dimensions = _validated_dimensions(
            result.get("new_dims"),
            label="new",
            required=has_planned_image,
        )
        if new_dimensions is not None and (
            max(new_dimensions) > config.max_long
            or min(new_dimensions) > config.max_short
        ):
            raise OutputCollisionError(
                f"Image result exceeds {config.preset} dimension limits: {new_dimensions}"
            )
        observed_output: OutputFingerprint | None = None
        if expected_output is not None:
            if not isinstance(expected_output, OutputFingerprint):
                raise OutputCollisionError(f"Invalid output fingerprint: {output}")
            if config.dry_run:
                raise OutputCollisionError(
                    f"Dry-run result unexpectedly owns an output: {output}"
                )
            observed_output = _assert_reusable_output_unchanged(
                output,
                expected_output,
                input_root=input_dir,
                output_root=output_dir,
                source_identity=(
                    expected_source.stat.st_dev,
                    expected_source.stat.st_ino,
                ),
            )
            _assert_source_unchanged(source, expected_source, input_dir)
            if observed_output.dimensions != new_dimensions:
                raise OutputCollisionError(
                    f"Image output dimensions differ from result: {output}"
                )
        elif not error and not config.dry_run:
            raise OutputCollisionError(
                f"Successful image result has no stable output: {output}"
            )

        orig_width, orig_height = _dimension_columns(original_dimensions)
        new_width, new_height = _dimension_columns(new_dimensions)
        rows.append(
            {
                "source_path": str(source.resolve(strict=True)),
                "source_size": expected_source.stat.st_size,
                "source_sha256": expected_source.sha256,
                "output_path": str(output.resolve(strict=False)),
                "output_size": (
                    observed_output.stat.st_size if observed_output is not None else ""
                ),
                "output_sha256": (
                    observed_output.sha256 if observed_output is not None else ""
                ),
                "action": action,
                "error": error,
                "preset": config.preset,
                "recipe_hash": config.recipe_hash,
                "orig_width": orig_width,
                "orig_height": orig_height,
                "new_width": new_width,
                "new_height": new_height,
            }
        )
    return rows


def write_result_manifest(
    input_dir: Path,
    output_dir: Path,
    results: list[dict[str, Any]],
    config: ImageConfig,
) -> Path:
    """全件manifestを検証後にnormal/dry-run別のsiblingへ原子的に公開する。"""

    report = manifest_path(output_dir, dry_run=config.dry_run)
    validate_auxiliary_output(input_dir, report)
    rows = _validated_manifest_rows(input_dir, output_dir, results, config)
    with staged_path(report) as temporary:
        with temporary.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=MANIFEST_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

        # 一時CSV構築中のsource/output差し替えを公開直前にもう一度検出する。
        _validated_manifest_rows(input_dir, output_dir, results, config)
        validate_auxiliary_output(input_dir, report)
        _validate_replaceable_file(report, label="image manifest")
        os.replace(temporary, report)
    return report


def write_error_report(output_dir: Path, results: list[dict[str, Any]]) -> Path:
    """現在実行のエラーだけで sibling CSV を原子的に置き換える。"""

    report = error_report_path(output_dir)
    with staged_path(report) as temporary:
        with temporary.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=("source", "planned_output", "error"))
            writer.writeheader()
            for result in results:
                if "error" in result:
                    writer.writerow(
                        {
                            "source": result["source"],
                            "planned_output": result["planned_output"],
                            "error": result["error"],
                        }
                    )
        _validate_replaceable_file(report, label="image error report")
        os.replace(temporary, report)
    return report
