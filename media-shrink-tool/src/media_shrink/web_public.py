"""掲載用マスターの固定recipeと、原本から一度だけ行う変換・検証。

CLI/UIと通常resizeのmetadata/marker契約には依存しない。
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
import logging
from pathlib import Path
import struct
import zlib

from PIL import Image, ImageCms, ImageOps, JpegImagePlugin, features
import PIL
import pillow_heif

from .image import (
    SourceChangedError, _capture_source_fingerprint, _assert_source_unchanged,
    _replace_staged,
)
from .utils import has_link_component, staged_path, validate_source_path

MAX_BYTES = 64 * 1024 * 1024
MAX_PIXELS = 80_000_000
FORMATS = frozenset({"JPEG", "PNG", "WEBP", "HEIF", "BMP", "TIFF", "GIF"})
_SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
SRGB_BYTES = _SRGB.tobytes()
logger = logging.getLogger(__name__)


class PublicImageError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class WebPublicConfig:
    kind: str = "photo"
    workers: int = 2

    def __post_init__(self):
        if self.kind not in ("photo", "graphic"):
            raise ValueError("用途はphotoまたはgraphicを選択してください")
        if type(self.workers) is not int or not 1 <= self.workers <= 4:
            raise ValueError("並列数は1〜4を指定してください")

    @property
    def output_format(self):
        return "JPEG" if self.kind == "photo" else "PNG"

    @property
    def suffix(self):
        return ".jpg" if self.kind == "photo" else ".png"

    @property
    def recipe(self):
        return {"version": 2, "kind": self.kind, "width": 1400,
                "rounding": "half-up-min1", "upscale": False, "crop": False,
                "format": self.output_format, "jpeg": {"quality": 90, "subsampling": 0,
                "optimize": True, "progressive": True}, "png": {"compress_level": 6},
                "color": "8bit-sRGB-perceptual", "alpha": "preserve-or-reject-photo",
                "metadata": "new-sRGB-only", "resampling": "Pillow-LANCZOS"}

    @property
    def recipe_hash(self):
        return hashlib.sha256(json.dumps(self.recipe, sort_keys=True).encode()).hexdigest()


def engine_versions():
    return {"Pillow": PIL.__version__, "pillow-heif": pillow_heif.__version__,
            "LittleCMS": features.version("littlecms2"), "libjpeg": features.version("jpg"),
            "zlib": features.version("zlib"), "libheif": pillow_heif.libheif_version()}


def output_size(size):
    w, h = size
    return (w, h) if w <= 1400 else (1400, max(1, (h * 2800 + w) // (2 * w)))


def _color_error():
    return PublicImageError("UNSUPPORTED_COLOR", "色情報を安全に変換できません。sRGBのJPEG/PNGとして編集ソフトから書き出してください")


def _bmp_input_color(source, im):
    """Pillow omits V4/V5 color fields; never treat their absence in info as sRGB."""
    with source.open("rb") as stream:
        header = stream.read(138)
        if len(header) < 18 or header[:2] != b"BM":
            raise _color_error()
        dib_size = struct.unpack_from("<I", header, 14)[0]
        if dib_size in (12, 40, 52, 56, 64):
            return  # legacy headers have no V4/V5 color declaration
        if dib_size not in (108, 124) or len(header) < 14 + dib_size:
            raise _color_error()
        color_space = struct.unpack_from("<I", header, 14+56)[0]
        offset = length = 0
        if dib_size == 124:
            offset, length = struct.unpack_from("<II", header, 14+112)
        if color_space in (0x73524742, 0x57696E20):  # sRGB / Windows sRGB
            if offset or length:
                raise _color_error()
            return
        # Calibrated RGB, linked profiles and unknown declarations stay unsupported.
        if color_space != 0x4D424544 or dib_size != 124:
            raise _color_error()
        bits = struct.unpack_from("<H", header, 14+14)[0]
        compression = struct.unpack_from("<I", header, 14+16)[0]
        pixel_offset = struct.unpack_from("<I", header, 10)[0]
        pixel_end = pixel_offset + ((im.width * bits + 31)//32)*4*im.height
        profile_start = 14 + offset
        if (compression not in (0, 3) or bits not in (1, 4, 8, 16, 24, 32)
                or pixel_offset < 14+dib_size or profile_start < pixel_end
                or not 128 <= length <= 1024*1024
                or profile_start + length > min(source.stat().st_size, MAX_BYTES)):
            raise _color_error()
        stream.seek(profile_start)
        profile = stream.read(length)
        if len(profile) != length:
            raise _color_error()
        im.info["icc_profile"] = profile  # validated/transformed by the common ICC path


def _exif_color(im, icc):
    exif = im.getexif()
    fields = exif.get_ifd(34665) if 34665 in exif else {}
    color_space = fields.get(40961)
    interop = exif.get_ifd(40965).get(1) if 40965 in fields else None
    if isinstance(interop, bytes):
        interop = interop.decode("ascii", errors="strict")
    if isinstance(interop, str):
        interop = interop.rstrip("\0")
    if ((interop == "R03" and color_space == 1)
            or (interop == "R98" and color_space == 2)):
        raise _color_error()
    if icc and _icc_identity(icc) == _icc_identity(SRGB_BYTES):
        if color_space == 2 or interop == "R03":
            raise _color_error()
    if not icc and (color_space not in (None, 1) or interop == "R03"):
        raise _color_error()


def _png_input_color(source, info):
    """Pillowが無視/欠落扱いにするHDR・壊れたICCも実chunkから判定する。"""
    seen = set()
    image_data = False
    with source.open("rb") as stream:
        if stream.read(8) != b"\x89PNG\r\n\x1a\n":
            raise _color_error()
        while stream.tell() <= MAX_BYTES:
            header = stream.read(8)
            if len(header) != 8:
                raise _color_error()
            length, kind = struct.unpack(">I4s", header)
            if length > MAX_BYTES or stream.tell() + length + 4 > MAX_BYTES:
                raise _color_error()
            payload = stream.read(length)
            crc = stream.read(4)
            if len(payload) != length or len(crc) != 4 or zlib.crc32(kind+payload) != int.from_bytes(crc, "big"):
                raise _color_error()
            if kind in (b"cLLi", b"mDCv"):
                raise _color_error()
            if kind in (b"iCCP", b"cICP", b"sRGB", b"gAMA", b"cHRM"):
                if kind in seen or image_data:
                    raise _color_error()
                seen.add(kind)
            if kind == b"iCCP":
                try:
                    name, compressed = payload.split(b"\0", 1)
                    if not 1 <= len(name) <= 79 or not compressed or compressed[0] != 0:
                        raise _color_error()
                    decoder = zlib.decompressobj()
                    icc = decoder.decompress(compressed[1:], 1024*1024+1)
                    if not decoder.eof or decoder.unused_data or len(icc) > 1024*1024 or icc != info.get("icc_profile"):
                        raise _color_error()
                except (ValueError, zlib.error) as exc:
                    raise _color_error() from exc
            if kind == b"cICP" and payload != bytes((1,13,0,1)):
                raise _color_error()
            if kind == b"sRGB" and (len(payload) != 1 or payload[0] > 3):
                raise _color_error()
            if kind == b"IDAT":
                image_data = True
            if kind == b"IEND":
                break
        else:
            raise _color_error()
    if info.get("icc_profile") and (b"sRGB" in seen or b"cICP" in seen):
        if _icc_identity(info["icc_profile"]) != _icc_identity(SRGB_BYTES):
            raise _color_error()


def _check_header(im, source):
    if im.format not in FORMATS:
        raise PublicImageError("UNSUPPORTED_FORMAT", "対応していない画像形式です")
    if im.width * im.height > MAX_PIXELS or min(im.size) < 1:
        raise PublicImageError("INPUT_LIMIT", "画像は80,000,000画素以内にしてください")
    if getattr(im, "n_frames", 1) != 1:
        raise PublicImageError("MULTIFRAME", "複数フレーム・ページの画像は対応していません")
    if im.mode not in ("1", "RGB", "RGBA", "L", "LA", "P", "CMYK", "LAB"):
        raise _color_error()
    info = im.info
    if info.get("bit_depth", 8) != 8:
        raise _color_error()
    if im.format == "BMP":
        _bmp_input_color(source, im)
    if im.format == "PNG":
        # Pillow silently reduces 16-bit RGB on load, so inspect original IHDR first.
        with source.open("rb") as stream:
            header = stream.read(29)
        if len(header) != 29 or header[24] > 8:
            raise _color_error()
        _png_input_color(source, info)
    if im.format == "JPEG":
        icc_parts = [p for name,p in im.applist if name == "APP2" and p.startswith(b"ICC_PROFILE\0")]
        if icc_parts and (not info.get("icc_profile") or any(
                len(p) < 14 or p[12:14] != bytes((i+1, len(icc_parts))) for i,p in enumerate(icc_parts))):
            raise _color_error()
    if im.format == "TIFF" and any(x > 8 for x in im.tag_v2.get(258, (8,))):
        raise _color_error()
    if any(key in info for key in ("content_light_level", "mastering_display_colour_volume")):
        raise _color_error()
    nclx = info.get("nclx_profile")
    if nclx is not None:
        # libheif handles YCbCr/range; only verified 8-bit sRGB primaries/transfer qualify.
        if not isinstance(nclx, dict) or (nclx.get("color_primaries"),
                nclx.get("transfer_characteristics")) != (1, 13):
            raise _color_error()
        if nclx.get("matrix_coefficients") not in (0, 1, 6):
            raise _color_error()
    cicp = info.get("cicp")
    if cicp is not None and tuple(cicp) != (1, 13, 0, 1):
        raise _color_error()
    # A non-sRGB gamma/chromaticity without a usable ICC is not an sRGB declaration.
    if not info.get("icc_profile"):
        if "gamma" in info and abs(info["gamma"] - 0.45455) > 0.00002:
            raise _color_error()
        chroma = info.get("chromaticity")
        srgb_chroma = (.3127, .3290, .64, .33, .30, .60, .15, .06)
        if chroma is not None and (len(chroma) != 8 or any(
                abs(a-b) > .0001 for a,b in zip(chroma, srgb_chroma))):
            raise _color_error()


def _prepare(source: Path, config: WebPublicConfig):
    with Image.open(source) as raw:
        _check_header(raw, source)
        source_size = raw.size
        raw.load()
        if raw.width * raw.height > MAX_PIXELS:
            raise PublicImageError("INPUT_LIMIT", "デコード後の画像寸法が上限を超えました")
        # HEIF decoder already applies orientation and clears EXIF Orientation.
        oriented = ImageOps.exif_transpose(raw)
        oriented_size = oriented.size
        alpha = (oriented.convert("RGBA").getchannel("A")
                 if oriented.mode in ("RGBA", "LA", "P") or "transparency" in oriented.info else None)
        if config.kind == "photo" and alpha is not None and alpha.getextrema()[0] < 255:
            raise PublicImageError("TRANSPARENT_PHOTO", "透明な画素があります。「透過画像・図版」を選択してください")
        icc = raw.info.get("icc_profile")
        _exif_color(raw, icc)
        warnings = []
        if icc:
            try:
                if len(icc) < 128 or int.from_bytes(icc[:4], "big") != len(icc) or icc[36:40] != b"acsp":
                    raise _color_error()
                profile = ImageCms.ImageCmsProfile(BytesIO(icc))
                color_space = profile.profile.xcolor_space.strip()
                if color_space == "RGB" and oriented.mode in ("1", "L", "LA", "P", "RGB", "RGBA"):
                    color = oriented.convert("RGB")
                elif color_space == "GRAY" and oriented.mode in ("1", "L", "LA"):
                    color = oriented.convert("L")
                elif (color_space, oriented.mode) in (("CMYK", "CMYK"), ("Lab", "LAB")):
                    color = oriented
                else:
                    raise _color_error()
                normalized = ImageCms.profileToProfile(color, profile, _SRGB,
                    renderingIntent=ImageCms.Intent.PERCEPTUAL, outputMode="RGB")
            except Exception as exc:
                raise _color_error() from exc
        else:
            if oriented.mode in ("CMYK", "LAB"):
                raise _color_error()
            normalized = oriented.convert("RGB")
            warnings.append("SRGB_ASSUMED")
        if alpha is not None and config.kind == "graphic":
            normalized.putalpha(alpha)
        dimensions = output_size(normalized.size)
        if config.kind == "photo" and max(dimensions) > 65500:
            raise PublicImageError("ENCODER_DIMENSIONS", "縦横寸法がJPEGの対応範囲を超えています")
        if dimensions != normalized.size:
            normalized = normalized.resize(dimensions, Image.Resampling.LANCZOS)
        # Fresh pixel container severs info and EXIF inherited through Pillow operations.
        clean = Image.frombytes(normalized.mode, normalized.size, normalized.tobytes())
        return clean, source_size, oriented_size, warnings


def _save_public(image, path, config):
    if config.kind == "photo":
        image.save(path, format="JPEG", quality=90, subsampling=0, optimize=True,
                   progressive=True, icc_profile=SRGB_BYTES)
    else:
        image.save(path, format="PNG", compress_level=6, icc_profile=SRGB_BYTES)


def _icc_identity(data):
    # LCMS embeds creation time; it is not a change of recipe/profile colorimetry.
    if not isinstance(data, bytes) or len(data) < 128:
        return None
    return data[:24] + b"\0"*12 + data[36:84] + b"\0"*16 + data[100:]


def _check_container(path, format):
    """Inspect actual segments/chunks, including JPEG metadata after scans."""
    data = path.read_bytes()
    if format == "PNG":
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("PNG signature")
        offset, chunks = 8, []
        while offset + 12 <= len(data):
            size = struct.unpack_from(">I", data, offset)[0]
            kind = data[offset+4:offset+8]
            if kind not in (b"IHDR", b"iCCP", b"IDAT", b"IEND"):
                raise ValueError("PNG metadata outside allowlist")
            chunks.append(kind)
            offset += size + 12
            if kind == b"IEND":
                break
        if offset != len(data) or not chunks or chunks[0] != b"IHDR" or chunks[-1] != b"IEND" or chunks.count(b"iCCP") != 1:
            raise ValueError("PNG layout")
        return
    if data[:2] != b"\xff\xd8":
        raise ValueError("JPEG signature")
    pos, ended, icc_parts, jfif_count = 2, False, [], 0
    while pos < len(data):
        if data[pos] != 255:
            raise ValueError("JPEG marker")
        while pos < len(data) and data[pos] == 255:
            pos += 1
        marker = data[pos]
        pos += 1
        if marker == 0xD9:
            ended = True
            break
        if marker not in (0xE0, 0xE2, 0xDB, 0xC0, 0xC2, 0xC4, 0xDD, 0xDA):
            raise ValueError("JPEG metadata/structure outside allowlist")
        length = int.from_bytes(data[pos:pos+2], "big")
        if length < 2 or pos + length > len(data):
            raise ValueError("JPEG segment length")
        payload = data[pos+2:pos+length]
        if marker == 0xE0:
            jfif_count += 1
            if payload != b"JFIF\0\x01\x01\x00\x00\x01\x00\x01\x00\x00" or jfif_count > 1:
                raise ValueError("Unexpected JFIF/density")
        if marker == 0xE2:
            if not payload.startswith(b"ICC_PROFILE\0"):
                raise ValueError("Unexpected APP2")
            icc_parts.append(payload)
        pos += length
        if marker == 0xDA:
            while True:
                pos = data.find(b"\xff", pos)
                if pos < 0 or pos + 1 >= len(data):
                    raise ValueError("Missing EOI")
                following = data[pos+1]
                if following == 0 or 0xD0 <= following <= 0xD7:
                    pos += 2
                elif following == 255:
                    pos += 1
                else:
                    break
    if not ended or pos != len(data) or not icc_parts:
        raise ValueError("JPEG trailing data or missing profile")
    count = len(icc_parts)
    if any(len(p) < 14 or p[12:14] != bytes((i+1, count)) for i,p in enumerate(icc_parts)):
        raise ValueError("ICC segment sequence")
    if _icc_identity(b"".join(p[14:] for p in icc_parts)) != _icc_identity(SRGB_BYTES):
        raise ValueError("Unexpected ICC")


def verify_public(path, config, dimensions, expected=None):
    _check_container(path, config.output_format)
    with Image.open(path) as check:
        check.verify()
    with Image.open(path) as check:
        if check.format != config.output_format or check.size != tuple(dimensions):
            raise ValueError("出力の形式・寸法が一致しません")
        check.load()
        if check.mode not in (("RGB",) if config.kind == "photo" else ("RGB", "RGBA")):
            raise ValueError("出力の色モードが一致しません")
        if check.getexif() or getattr(check, "text", {}):
            raise ValueError("禁止metadataが残っています")
        if _icc_identity(check.info.get("icc_profile")) != _icc_identity(SRGB_BYTES):
            raise ValueError("出力sRGBプロファイルが一致しません")
        if config.kind == "photo":
            if JpegImagePlugin.get_sampling(check) != 0 or not check.info.get("progressive"):
                raise ValueError("JPEG recipeが一致しません")
        elif expected is not None and (check.mode != expected.mode or check.tobytes() != expected.tobytes()):
            raise ValueError("PNGの画素・透過が一致しません")


def empty_result(source_path):
    return dict(source_path=source_path, source_sha256=None, source_size=None,
        source_mtime_ns=None, source_width=None, source_height=None,
        oriented_width=None, oriented_height=None, output_path=None, output_sha256=None,
        output_size=None, output_width=None, output_height=None, output_format=None,
        action="ERROR", warnings=[], error=None)


def process_web_public_image(source, destination, config, *, input_root, output_root,
                             dry_run=False, reuse=None):
    source, destination = Path(source), Path(destination)
    result = empty_result(source.relative_to(input_root).as_posix())
    stage = "input"
    try:
        if has_link_component(Path(source.anchor), source):
            raise PublicImageError("UNSAFE_PATH", "リンクを含む入力は使用できません")
        validate_source_path(input_root, source)
        if source.stat().st_size > MAX_BYTES:
            raise PublicImageError("INPUT_LIMIT", "画像は64 MiB以内にしてください")
        fingerprint = _capture_source_fingerprint(source)
        if fingerprint.stat.st_size > MAX_BYTES:
            raise PublicImageError("INPUT_LIMIT", "画像は64 MiB以内にしてください")
        result.update(source_sha256=fingerprint.sha256, source_size=fingerprint.stat.st_size,
                      source_mtime_ns=fingerprint.stat.st_mtime_ns)
        stage = "decode_color"
        clean, source_size, oriented_size, warnings = _prepare(source, config)
        result.update(source_width=source_size[0], source_height=source_size[1],
            oriented_width=oriented_size[0], oriented_height=oriented_size[1], warnings=warnings)
        if dry_run:
            stage = "source_recheck"
            _assert_source_unchanged(source, fingerprint, input_root)
            result.update(action="DRY_RUN", output_width=clean.width,
                          output_height=clean.height, output_format=config.output_format)
            return result
        stage = "output_prepare"
        with staged_path(destination, input_root=input_root, output_root=output_root) as temporary:
            stage = "reuse"
            reused = False
            if reuse is not None:
                # Batch supplies a bounded, path-checked copy callback; validate pixels/policy again.
                reused = reuse(temporary, fingerprint, clean)
            if not reused:
                stage = "encode"
                _save_public(clean, temporary, config)
            stage = "validate"
            verify_public(temporary, config, clean.size, clean)
            output_fp = _capture_source_fingerprint(temporary)
            stage = "publish"
            _replace_staged(temporary, destination, input_root, output_root, source, fingerprint)
        result.update(output_path=destination.relative_to(output_root).as_posix(),
            output_sha256=output_fp.sha256, output_size=output_fp.stat.st_size,
            output_width=clean.width, output_height=clean.height, output_format=config.output_format,
            action="SKIPPED_COMPLETE" if reused else "CONVERTED")
        if output_fp.stat.st_size > fingerprint.stat.st_size:
            result["warnings"].append("OUTPUT_LARGER_THAN_SOURCE")
    except Exception as exc:
        code = getattr(exc, "code", "SOURCE_CHANGED" if isinstance(exc, SourceChangedError) else "CONVERSION_FAILED")
        logger.warning("web-public failure stage=%s exception=%s code=%s source=%r",
                       stage, type(exc).__name__, code, result["source_path"])
        result["error"] = {"code": code, "message": str(exc) if isinstance(exc, PublicImageError)
                           else "画像の読込み・変換・検証・保存に失敗しました"}
    return result


def run_web_public(input_dir, output_dir, config, *, selected_files=None, dry_run=False, on_result=None):
    from .web_public_batch import run_batch
    return run_batch(input_dir, output_dir, config, selected_files=selected_files,
                     dry_run=dry_run, on_result=on_result)
