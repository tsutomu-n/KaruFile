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
from typing import Any, Mapping

from PIL import Image, ImageOps

from .config import ImageConfig
from .utils import (
    PathValidationError,
    is_link_like,
    logger,
    make_writable,
    staged_path,
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
MARKER_ID = "karufile:image-v1"
MARKER_PREFIX = b"karufile:image-"
JPEG_MIN_SAVINGS = 32 * 1024
JPEG_MIN_REDUCTION = 0.10
_MARKER_RE = re.compile(
    rb"karufile:image-v1;recipe=([0-9a-f]+);src_size=([0-9]+);src_mtime_ns=(-?[0-9]+)",
    re.IGNORECASE,
)


class OutputCollisionError(RuntimeError):
    """固定8桁hashでも出力を一意にできない場合のエラー。"""


@dataclass(frozen=True, slots=True)
class ImagePlan:
    source: Path
    relative_source: Path
    output: Path


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


def _coerce_config(config: ImageConfig | Mapping[str, Any]) -> ImageConfig:
    if isinstance(config, ImageConfig):
        return config
    return ImageConfig(
        workers=int(config.get("workers", 4)),
        dry_run=bool(config.get("dry_run", False)),
    )


def calculate_output_size(size: tuple[int, int], config: ImageConfig | None = None) -> tuple[int, int]:
    """Orientation 適用後の寸法を長辺1280・短辺960の枠へ収める。"""

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


def _parse_current_marker(comment: bytes) -> tuple[str, int, int] | None:
    matches = list(_MARKER_RE.finditer(comment))
    if not matches:
        return None
    recipe, size, mtime = matches[-1].groups()
    return recipe.decode("ascii").lower(), int(size), int(mtime)


def _marker_for(source_stat: os.stat_result, config: ImageConfig) -> bytes:
    return (
        f"{MARKER_ID};recipe={config.recipe_hash};src_size={source_stat.st_size};"
        f"src_mtime_ns={source_stat.st_mtime_ns}"
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


def _completed_output_matches(
    output: Path,
    source_stat: os.stat_result,
    config: ImageConfig,
) -> tuple[int, tuple[int, int]] | None:
    if not output.is_file():
        return None
    try:
        dimensions, comment = _inspect_jpeg(output)
        width, height = dimensions
        if max(width, height) > config.max_long or min(width, height) > config.max_short:
            return None
        marker = _parse_current_marker(comment)
        if marker != (config.recipe_hash, source_stat.st_size, source_stat.st_mtime_ns):
            return None
        return output.stat().st_size, dimensions
    except Exception:
        return None


def _copied_output_matches(
    source: Path,
    output: Path,
    source_stat: os.stat_result,
    config: ImageConfig,
) -> tuple[int, tuple[int, int]] | None:
    if not output.is_file():
        return None
    try:
        output_stat = output.stat()
        if output_stat.st_size != source_stat.st_size or output_stat.st_mtime_ns != source_stat.st_mtime_ns:
            return None
        dimensions, _ = _inspect_jpeg(output)
        if max(dimensions) > config.max_long or min(dimensions) > config.max_short:
            return None
        with source.open("rb") as source_stream, output.open("rb") as output_stream:
            while True:
                source_chunk = source_stream.read(1024 * 1024)
                if source_chunk != output_stream.read(1024 * 1024):
                    return None
                if not source_chunk:
                    break
        return output_stat.st_size, dimensions
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


def _verify_candidate(path: Path, expected_size: tuple[int, int], config: ImageConfig) -> int:
    dimensions, comment = _inspect_jpeg(path)
    if dimensions != expected_size:
        raise ValueError(f"JPEG output dimensions differ: expected {expected_size}, got {dimensions}")
    if max(dimensions) > config.max_long or min(dimensions) > config.max_short:
        raise ValueError(f"JPEG output exceeds dimension limits: {dimensions}")
    if not _has_karufile_marker(comment):
        raise ValueError("JPEG output marker is missing")
    return path.stat().st_size


def _replace_staged(
    temporary: Path,
    output: Path,
    input_root: Path,
    output_root: Path,
    protected_source: Path,
) -> None:
    validate_output_destination(input_root, output_root, output)
    if is_link_like(output):
        raise PathValidationError(f"Linked output file is not allowed: {output}")
    source_identity = _file_identity(protected_source)
    if source_identity is not None:
        _validate_existing_output_identity(output, {source_identity})
    make_writable(temporary)
    if output.exists():
        make_writable(output)
    validate_output_destination(input_root, output_root, output)
    if source_identity is not None:
        _validate_existing_output_identity(output, {source_identity})
    os.replace(temporary, output)


def _publish_copy(
    source: Path,
    output: Path,
    input_root: Path,
    output_root: Path,
) -> int:
    with staged_path(output, input_root=input_root, output_root=output_root) as temporary:
        shutil.copy2(source, temporary)
        make_writable(temporary)
        _inspect_jpeg(temporary)
        size = temporary.stat().st_size
        _replace_staged(temporary, output, input_root, output_root, source)
    return size


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
    source_stat = source.stat()
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
        if source_is_jpeg and _has_karufile_marker(existing_comment):
            if cfg.dry_run:
                return _result(
                    source,
                    output,
                    "DRY_RUN_SKIPPED_GENERATED",
                    source_stat.st_size,
                    0,
                    warnings,
                    original_dimensions=original_dimensions,
                    new_dimensions=original_dimensions,
                )
            copied_size = _publish_copy(
                source,
                output,
                effective_input_root,
                effective_output_root,
            )
            return _result(
                source,
                output,
                "SKIPPED_GENERATED",
                source_stat.st_size,
                copied_size,
                warnings,
                original_dimensions=original_dimensions,
                new_dimensions=original_dimensions,
            )

        completed = _completed_output_matches(output, source_stat, cfg)
        if completed is not None:
            output_size, dimensions = completed
            return _result(
                source,
                output,
                "SKIPPED_COMPLETE",
                source_stat.st_size,
                output_size,
                warnings,
                original_dimensions=original_dimensions,
                new_dimensions=dimensions,
            )

        if source_is_jpeg and not orientation_applied:
            copied = _copied_output_matches(source, output, source_stat, cfg)
            if copied is not None:
                output_size, dimensions = copied
                return _result(
                    source,
                    output,
                    "SKIPPED_COPY",
                    source_stat.st_size,
                    output_size,
                    warnings,
                    original_dimensions=original_dimensions,
                    new_dimensions=dimensions,
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
                return _result(
                    source,
                    output,
                    "DRY_RUN",
                    source_stat.st_size,
                    0,
                    warnings,
                    original_dimensions=original_dimensions,
                    new_dimensions=expected_dimensions,
                )

            marker = _marker_for(source_stat, cfg)
            must_resize = oriented_dimensions != expected_dimensions
            with staged_path(
                output,
                input_root=effective_input_root,
                output_root=effective_output_root,
            ) as temporary:
                _save_jpeg(working, temporary, marker, existing_comment, metadata, warnings, cfg)
                candidate_size = _verify_candidate(temporary, expected_dimensions, cfg)
                savings = source_stat.st_size - candidate_size
                reduction = savings / source_stat.st_size if source_stat.st_size else 0.0
                adopt_candidate = (
                    not source_is_jpeg
                    or must_resize
                    or orientation_applied
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
                    )

            copied_size = _publish_copy(
                source,
                output,
                effective_input_root,
                effective_output_root,
            )
            return _result(
                source,
                output,
                "COPIED_ORIGINAL",
                source_stat.st_size,
                copied_size,
                [],
                original_dimensions=original_dimensions,
                new_dimensions=original_dimensions,
            )
        except Exception as exc:
            if not source_is_jpeg:
                raise
            if cfg.dry_run:
                raise
            _append_warning(warnings, "ENCODE_FAILED_ORIGINAL_COPIED")
            copied_size = _publish_copy(
                source,
                output,
                effective_input_root,
                effective_output_root,
            )
            result = _result(
                source,
                output,
                "COPIED_ENCODE_FAILED",
                source_stat.st_size,
                copied_size,
                warnings,
                original_dimensions=original_dimensions,
                new_dimensions=original_dimensions,
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
        original_size = plan.source.stat().st_size
    except OSError:
        original_size = 0
    return {
        "source": str(plan.source),
        "src": str(plan.source),
        "planned_output": str(plan.output),
        "dst": str(plan.output),
        "error": f"{type(exc).__name__}: {exc}",
        "orig_size": original_size,
        "new_size": 0,
        "warnings": [],
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
        if report.exists():
            if is_link_like(report) or report.stat().st_nlink > 1:
                raise PathValidationError(
                    f"Linked image error report cannot be replaced safely: {report}"
                )
            make_writable(report)
        os.replace(temporary, report)
    return report
