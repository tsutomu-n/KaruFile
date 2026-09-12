"""Resize permitted embedded raster parts without saving/rebuilding a workbook DOM."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from io import BytesIO
from pathlib import Path
import struct
import warnings
import zlib

from PIL import Image, ImageChops, ImageStat

from .drawing import DrawingPlan, inspect_drawings
from .diagnostics import Analysis
from .recipe import capped_size, resolve_recipe
from .package import (
    Budget, MAX_DECODE_PIXELS, MAX_PIXELS, Package, Protected, check_workbook,
    read_package, verify_candidate, write_candidate,
)


JPEG_QUALITY = 85
JPEG_SUBSAMPLING = 0


@dataclass(frozen=True)
class CoreResult:
    status: str
    reason: str
    images_total: int | None = None
    images_changed: int = 0
    changed_parts: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImagePlan:
    part: str
    format: str
    original_size: tuple[int, int]
    output_size: tuple[int, int]


def _png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("PNG signature mismatch")
    offset = 8
    chunks: list[tuple[bytes, bytes]] = []
    allowed = {b"IHDR", b"IDAT", b"IEND", b"tRNS", b"iCCP", b"eXIf", b"pHYs",
               b"cHRM", b"gAMA", b"sRGB", b"tEXt", b"zTXt", b"iTXt"}
    while offset < len(data):
        if len(chunks) >= 100_000:
            raise Protected("png_chunk_count_limit")
        if len(data) - offset < 12:
            raise ValueError("truncated PNG chunk")
        length, kind = struct.unpack_from(">I4s", data, offset)
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("PNG chunk exceeds image stream")
        if kind not in allowed:
            raise Protected("unsupported_png_chunk_or_palette")
        if kind == b"IHDR" and chunks:
            raise ValueError("duplicate or misplaced PNG header")
        if kind == b"IEND" and length:
            raise ValueError("PNG end chunk must be empty")
        chunks.append((kind, data[offset + 8:offset + 8 + length]))
        offset = end
        if kind == b"IEND":
            if offset != len(data):
                raise Protected("trailing_png_data")
            break
    if not chunks or chunks[0][0] != b"IHDR" or chunks[-1][0] != b"IEND":
        raise ValueError("missing PNG header/end")
    header = chunks[0][1]
    if len(header) != 13:
        raise ValueError("invalid PNG header")
    if header[8] != 8:
        raise Protected("non_8_bit_png")
    return chunks


def _check_jpeg_metadata(data: bytes) -> None:
    """Accept only metadata that the encoder explicitly preserves.

    Walk scan boundaries too: Pillow exposes APP/COM markers before the first
    scan, while later application markers and trailing editing data can be lost
    on save. Unsupported metadata protects the image instead of being removed.
    """
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("JPEG signature mismatch")
    position = 2
    entropy = False
    scanned = False
    marker_count = 0
    seen: dict[int, int] = {}
    while position < len(data):
        if entropy:
            position = data.find(b"\xff", position)
            if position < 0:
                raise ValueError("missing JPEG end marker")
        elif data[position] != 0xFF:
            raise ValueError("invalid JPEG marker boundary")
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            raise ValueError("truncated JPEG marker")
        marker = data[position]
        position += 1
        if entropy and (marker == 0 or 0xD0 <= marker <= 0xD7):
            continue
        entropy = False
        marker_count += 1
        if marker_count > 100_000:
            raise Protected("jpeg_marker_count_limit")
        if marker == 0xD9:
            if not scanned:
                raise ValueError("JPEG has no image scan")
            if position != len(data):
                raise Protected("trailing_jpeg_data")
            return
        if marker in {0, 0xD8} or 0xD0 <= marker <= 0xD7:
            raise ValueError("unexpected standalone JPEG marker")
        if marker == 0x01:
            raise Protected("unsupported_jpeg_marker")
        if position + 2 > len(data):
            raise ValueError("truncated JPEG segment length")
        length = struct.unpack_from(">H", data, position)[0]
        if length < 2 or position + length > len(data):
            raise ValueError("invalid JPEG segment length")
        payload = data[position + 2:position + length]
        position += length
        if 0xE0 <= marker <= 0xEF or marker == 0xFE:
            if scanned:
                raise Protected("jpeg_metadata_after_image_scan")
            seen[marker] = seen.get(marker, 0) + 1
            if marker == 0xE0:
                if not payload.startswith(b"JFIF\0") or len(payload) != 14 or payload[12:] != b"\0\0":
                    raise Protected("jpeg_extended_metadata")
            elif marker == 0xE1:
                if not payload.startswith(b"Exif\0\0"):
                    raise Protected("jpeg_extended_metadata")
            elif marker == 0xE2:
                if not payload.startswith(b"ICC_PROFILE\0") or len(payload) < 14:
                    raise Protected("jpeg_extended_metadata")
            elif marker != 0xFE:
                raise Protected("jpeg_extended_metadata")
            if marker != 0xE2 and seen[marker] != 1:
                raise Protected("duplicate_jpeg_metadata")
        if marker == 0xDA:
            scanned = True
            entropy = True
    raise ValueError("missing JPEG end marker")


def _restore_png_metadata(original: bytes, encoded: bytes) -> bytes:
    # PngInfo silently ignores some standard chunks, including pHYs. Retain
    # supported source metadata exactly; only encoded pixel/header chunks and
    # the color-key-to-alpha change come from Pillow.
    metadata = [(kind, value) for kind, value in _png_chunks(original)
                if kind not in {b"IHDR", b"IDAT", b"IEND", b"tRNS"}]
    encoded_chunks = _png_chunks(encoded)
    pixels = [(kind, value) for kind, value in encoded_chunks if kind in {b"IDAT", b"IEND"}]
    result = bytearray(b"\x89PNG\r\n\x1a\n")
    for kind, value in [encoded_chunks[0], *metadata, *pixels]:
        result.extend(struct.pack(">I", len(value)))
        result.extend(kind)
        result.extend(value)
        result.extend(struct.pack(">I", zlib.crc32(kind + value)))
    return bytes(result)


def _inspect_image(data: bytes, content_type: str, part: str) -> tuple[str, tuple[int, int]]:
    suffix = Path(part).suffix.lower()
    if not part.startswith("xl/media/") or suffix not in {".jpg", ".jpeg", ".png"}:
        raise Protected("unsupported_image_part")
    expected = "PNG" if suffix == ".png" else "JPEG"
    if content_type != ("image/png" if expected == "PNG" else "image/jpeg"):
        raise ValueError("image extension/content type mismatch")
    png_exif = Image.Exif()
    if expected == "PNG":
        exif_chunks = [value for kind, value in _png_chunks(data) if kind == b"eXIf"]
        if len(exif_chunks) > 1:
            raise Protected("duplicate_png_exif")
        if exif_chunks:
            png_exif.load(exif_chunks[0])
    else:
        _check_jpeg_metadata(data)
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(data)) as image:
            if image.format != expected:
                raise ValueError("image content does not match its declared format")
            width, height = image.size
            if width < 1 or height < 1 or width * height > MAX_PIXELS:
                raise Protected("image_pixel_limit")
            allowed = {"L", "RGB"} if expected == "JPEG" else {"L", "LA", "RGB", "RGBA"}
            if image.mode not in allowed or getattr(image, "n_frames", 1) != 1:
                raise Protected("unsupported_image_mode_or_animation")
            # PNG.getexif() loads all pixels even when there is no EXIF. Read the
            # bounded eXIf chunk directly so preflight stays header-only and
            # verify() still operates on the freshly opened PNG stream.
            exif = png_exif if expected == "PNG" else image.getexif()
            if exif.get(274, 1) != 1:
                raise Protected("exif_orientation")
            if expected == "JPEG" and ("xmp" in image.info or "mp" in image.info):
                raise Protected("jpeg_extended_metadata")
            if (expected == "JPEG" and any(kind == "APP2" for kind, _ in image.applist)
                    and not image.info.get("icc_profile")):
                raise Protected("invalid_or_ambiguous_jpeg_icc")
            image.verify()
    return expected, (width, height)


def _resized_size(size: tuple[int, int], required: tuple[int, int]) -> tuple[int, int]:
    scale = max(Fraction(required[0], size[0]), Fraction(required[1], size[1]))
    if scale >= 1:
        return size
    def ceiling(value: Fraction) -> int:
        return (value.numerator + value.denominator - 1) // value.denominator
    return tuple(min(original, max(1, ceiling(original * scale))) for original in size)  # type: ignore[return-value]


def plan_images(package: Package, drawings: DrawingPlan, dpi: int | None, budget: Budget,
                max_side: int | None = None) -> tuple[list[ImagePlan], dict[str, str]]:
    plans = []
    reasons = dict(drawings.protected)
    estimated_pixels = 0
    for part in package.images:
        budget.check()
        if part in reasons:
            continue
        try:
            fmt, size = _inspect_image(package.parts[part], package.types[part], part)
        except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
            raise Protected("image_pixel_limit") from exc
        except Protected as exc:
            reasons[part] = str(exc)
            continue
        if max_side is not None:
            output_size = capped_size(size, max_side)
        else:
            requirements = [p.required_pixels(dpi) for p in drawings.placements[part]]
            required = (max(p[0] for p in requirements), max(p[1] for p in requirements))
            output_size = _resized_size(size, required)
        if output_size == size and not (max_side is not None and fmt == "JPEG"):
            reasons[part] = "already_within_resolution"
            continue
        estimated_pixels += size[0] * size[1] + output_size[0] * output_size[1]
        if estimated_pixels > MAX_DECODE_PIXELS:
            raise Protected("cumulative_image_pixel_limit")
        plans.append(ImagePlan(part, fmt, size, output_size))
    return plans, reasons


def _encode_image(data: bytes, plan: ImagePlan, budget: Budget, *, jpeg_quality: int = JPEG_QUALITY) -> bytes | None:
    budget.decode(plan.original_size[0] * plan.original_size[1])
    with Image.open(BytesIO(data)) as source:
        source.load()
        info = dict(source.info)
        if source.size != plan.original_size:
            raise ValueError("source dimensions changed during decode")
        # Color-key transparency is converted to an explicit alpha channel before filtering.
        working = source.convert("RGBA") if "transparency" in info else source.copy()
    with working:
        with working.resize(plan.output_size, Image.Resampling.LANCZOS) as resized:
            budget.check()
            parameters: dict = {}
            if info.get("icc_profile"):
                parameters["icc_profile"] = info["icc_profile"]
            if info.get("exif"):
                parameters["exif"] = info["exif"]
            if plan.format == "JPEG":
                parameters.update(quality=jpeg_quality, subsampling=JPEG_SUBSAMPLING, optimize=True)
                if "dpi" in info:
                    parameters["dpi"] = info["dpi"]
            else:
                parameters["optimize"] = True
            buffer = BytesIO()
            resized.save(buffer, format=plan.format, **parameters)
            candidate = buffer.getvalue()
            if plan.format == "PNG":
                candidate = _restore_png_metadata(data, candidate)
            budget.check()
            if len(candidate) >= len(data):
                return None
            budget.decode(plan.output_size[0] * plan.output_size[1])
            with Image.open(BytesIO(candidate)) as decoded:
                decoded.load()
                if decoded.format != plan.format or decoded.size != plan.output_size:
                    raise ValueError("encoded image format/dimensions mismatch")
                if decoded.info.get("icc_profile") != info.get("icc_profile"):
                    raise ValueError("encoded image ICC profile changed")
                if decoded.info.get("exif") != info.get("exif"):
                    raise ValueError("encoded image EXIF metadata changed")
                if plan.format == "JPEG" and decoded.info.get("comment") != info.get("comment"):
                    raise ValueError("encoded image JPEG comment changed")
                if decoded.getexif().get(274, 1) != 1:
                    raise ValueError("encoded image orientation changed")
                with resized.convert("RGBA") as reference, decoded.convert("RGBA") as actual:
                    if plan.format == "PNG":
                        if reference.tobytes() != actual.tobytes():
                            raise ValueError("PNG resized samples/alpha mismatch")
                    else:
                        with ImageChops.difference(reference.convert("RGB"), actual.convert("RGB")) as diff:
                            if max(ImageStat.Stat(diff).mean) > 8:
                                return None
                            # Averages alone hide small areas damaged by JPEG encoding.
                            for y in range(0, diff.height, 128):
                                for x in range(0, diff.width, 128):
                                    with diff.crop((x, y, min(x + 128, diff.width), min(y + 128, diff.height))) as tile:
                                        if max(ImageStat.Stat(tile).mean) > 16:
                                            return None
            return candidate


def _reason(prefix: str, reasons: dict[str, str]) -> str:
    counts: dict[str, int] = {}
    for reason in reasons.values():
        counts[reason] = counts.get(reason, 0) + 1
    details = "; ".join(f"{reason}={count}" for reason, count in sorted(counts.items()))
    return prefix + ("; " + details if details else "")


def process_workbook(source: Path, candidate: Path | None, *, dpi: int | None = None, dry_run: bool = False,
                     analysis: Analysis | None = None, max_side: int | None = None,
                     jpeg_quality: int | None = None) -> CoreResult:
    analysis = analysis if analysis is not None else Analysis()
    dpi, max_side, jpeg_quality = resolve_recipe(dpi, max_side, jpeg_quality)
    if not dry_run and (candidate is None or candidate.resolve() == source.resolve()):
        raise ValueError("a separate candidate path is required")
    if candidate is not None and candidate.exists() and source.samefile(candidate):
        raise ValueError("candidate aliases source")
    budget = Budget.start()
    package = None
    try:
        package = read_package(source, budget)
        analysis.images_total = len(package.images)
        check_workbook(package)
        drawings = inspect_drawings(package, budget)
        plans, reasons = plan_images(package, drawings, dpi, budget, max_side)
        planned = {plan.part: plan for plan in plans}
        for part in package.images:
            budget.check()
            image_reasons = [reasons[part]] if part in reasons else []
            fmt, size = "UNKNOWN", None
            try:
                fmt, size = _inspect_image(package.parts[part], package.types[part], part)
            except Protected as exc:
                if str(exc) not in image_reasons:
                    image_reasons.append(str(exc))
            placements = drawings.placements.get(part, [])
            requirements = ([capped_size(size, max_side)] if size and placements else []) if max_side is not None else [p.required_pixels(dpi) for p in placements]
            required = ([max(p[0] for p in requirements), max(p[1] for p in requirements)]
                        if requirements and part not in drawings.protected else None)
            analysis.records.append(dict(part=part, format=fmt, size=list(size) if size else None,
                placements=drawings.uses.get(part, len(placements)), required_pixels=required,
                geometry_basis=("pixel_cap" if max_side is not None else ",".join(sorted({p.geometry_basis for p in placements}))) if required else "unresolved",
                reasons=image_reasons, outcome="planned" if part in planned else "preserved"))
        analysis.complete = True
    except Protected as exc:
        if analysis.images_total is None:
            analysis.images_total = exc.images_total
        return CoreResult("DRY_RUN_PRESERVED" if dry_run else "PRESERVED_ORIGINAL", str(exc),
                          analysis.images_total)
    total = len(package.images)
    if not plans:
        return CoreResult("DRY_RUN_PRESERVED" if dry_run else "PRESERVED_ORIGINAL",
                          _reason("no_resize_candidate", reasons), total)
    if dry_run:
        return CoreResult("DRY_RUN", _reason(f"eligible_images={len(plans)}; no_candidates_written", reasons), total)
    replacements: dict[str, bytes] = {}
    for plan in plans:
        budget.check()
        resized = _encode_image(package.parts[plan.part], plan, budget, jpeg_quality=jpeg_quality)
        if resized is None:
            reasons[plan.part] = "image_savings_or_quality_rejected"
        else:
            replacements[plan.part] = resized
    if not replacements:
        for record in analysis.records:
            if record["outcome"] == "planned":
                record.update(outcome="rejected", reasons=[reasons[record["part"]]])
        return CoreResult("PRESERVED_ORIGINAL", _reason("no_smaller_validated_images", reasons), total)
    assert candidate is not None
    write_candidate(package, replacements, candidate, budget)
    if candidate.stat().st_size >= source.stat().st_size:
        for record in analysis.records:
            if record["outcome"] == "planned":
                record.update(outcome="rejected", reasons=["workbook_not_smaller"])
        return CoreResult("PRESERVED_ORIGINAL", _reason("workbook_not_smaller", reasons), total)
    try:
        verification = read_package(candidate, budget)
    except Protected as exc:
        raise ValueError(f"candidate validation limit/structure: {exc}") from exc
    verify_candidate(package, verification, replacements)
    budget.check()
    changed = tuple(sorted(replacements))
    for record in analysis.records:
        if record["part"] in replacements:
            record["outcome"] = "adopted"
        elif record["outcome"] == "planned":
            record["outcome"] = "rejected"
            record["reasons"] = [reasons.get(record["part"], "workbook_not_smaller")]
    return CoreResult("ADOPTED_LOSSY", _reason("validated_image_parts_only", reasons), total, len(changed), changed)
