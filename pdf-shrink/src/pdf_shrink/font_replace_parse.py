"""Bounded PDF analysis for explicit horizontal TrueType replacement.

Only ``Unsupported`` represents a valid but unsupported input. Broken objects,
invalid compressed streams and I/O failures deliberately remain exceptions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import io
import math
from pathlib import Path
import re
import time
import zlib

import pikepdf as pq
from fontTools.ttLib import TTFont


RECIPE = {
    "version": 6, "pages": 200, "source_bytes": 128 * 1024**2,
    "font_stream_bytes": 32 * 1024**2, "decoded_font_bytes": 64 * 1024**2,
    "content_bytes": 32 * 1024**2, "decoded_total_bytes": 256 * 1024**2,
    "image_stream_bytes": 32 * 1024**2, "decoded_image_bytes": 64 * 1024**2,
    "image_pixels": 32_000_000, "page_render_pixels": 32_000_000,
    "font_count": 256, "char_count": 1_000_000, "mapping_count": 1_000_000, "seconds": 300,
    "validation_pixels_per_candidate": 600_000_000, "render_dpi": 144,
    "font_face": 0, "font_fs_type": 8,
    "width_rounding": "nearest_integer_1000_hmtx_upem",
    "text_show": "one_source_Tj_or_TJ_to_one_TJ",
}


class Unsupported(Exception):
    """A supported parser found a documented, non-error protection boundary."""


def protect(reason: str) -> None:
    raise Unsupported("font_replace_" + reason)


def number(value) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("PDF number expected")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("non-finite PDF number")
    return result


def integer(value) -> int:
    result = number(value)
    if result != result.to_integral_value():
        raise ValueError("PDF integer expected")
    return int(result)


@dataclass
class Budget:
    deadline: float
    decoded: int = 0
    content: int = 0
    characters: int = 0
    mappings: int = 0

    def check(self) -> None:
        if time.monotonic() > self.deadline:
            protect("time_limit")

    def charge_decoded(self, size: int) -> None:
        self.check()
        self.decoded += size
        if self.decoded > RECIPE["decoded_total_bytes"]:
            protect("decoded_total_limit")

    def charge_mappings(self, count: int) -> None:
        self.check()
        self.mappings += count
        if self.mappings > RECIPE["mapping_count"]:
            protect("mapping_count_limit")


def bounded_stream(stream, compressed_limit: int, decoded_limit: int,
                   budget: Budget, *, category: str) -> bytes:
    """Check /Length before reading, and cap zlib output before allocation.

    Decompress.flush() is intentionally not used: its argument is a buffer
    size, not a hard output cap. Multiple filter chains are unsupported.
    """
    budget.check()
    if not isinstance(stream, pq.Stream):
        raise ValueError("PDF stream expected")
    declared = integer(stream.get("/Length"))
    if declared < 0:
        raise ValueError("negative PDF stream length")
    if declared > compressed_limit:
        protect(category + "_stream_limit")
    filters = stream.get("/Filter")
    if isinstance(filters, pq.Array):
        if len(filters) != 1:
            protect(category + "_filter")
        filters = filters[0]
    if filters not in (None, pq.Name.FlateDecode):
        protect(category + "_filter")
    params = stream.get("/DecodeParms")
    if isinstance(params, pq.Array) and len(params) == 1:
        params = params[0]
    if params is not None:
        # Predictor reversal is left to image decoding, never font/content.
        if category != "image" or not isinstance(params, pq.Dictionary):
            protect(category + "_decode_parameters")
        if set(params.keys()) - {"/Predictor", "/Colors", "/BitsPerComponent", "/Columns"}:
            protect("image_decode_parameters")
    raw = stream.read_raw_bytes()
    if len(raw) != declared:
        raise ValueError("PDF stream length mismatch")
    if filters is None:
        if len(raw) > decoded_limit:
            protect(category + "_decoded_limit")
        decoded = raw
    else:
        inflater = zlib.decompressobj()
        decoded = inflater.decompress(raw, decoded_limit + 1)
        if len(decoded) > decoded_limit or inflater.unconsumed_tail:
            protect(category + "_decoded_limit")
        if not inflater.eof or inflater.unused_data:
            raise ValueError("invalid or trailing Flate data")
    budget.charge_decoded(len(decoded))
    return decoded


_HEX = r"<[0-9a-fA-F]+>"
_TOKEN = re.compile(_HEX + r"|\[|\]")


def cmap_entries(data: bytes, budget: Budget) -> dict[int, int]:
    """Read bounded two-byte ToUnicode bfchar/bfrange maps, including arrays."""
    text = re.sub(r"%[^\r\n]*", "", data.decode("latin-1"))
    if re.search(r"\b(?:usecmap|begincidchar|begincidrange|beginnotdefchar|beginnotdefrange)\b", text):
        protect("tounicode_complex")
    spaces = re.findall(r"(\d+)\s+begincodespacerange(.*?)endcodespacerange", text, re.S)
    if not spaces:
        raise ValueError("missing ToUnicode codespace")
    ranges = []
    for count, body in spaces:
        tokens = _TOKEN.findall(body)
        if re.sub(_TOKEN, "", body).strip() or len(tokens) != int(count) * 2:
            raise ValueError("malformed ToUnicode codespace")
        for lo, hi in zip(tokens[::2], tokens[1::2]):
            if not re.fullmatch(r"<[0-9a-fA-F]{4}>", lo) or not re.fullmatch(r"<[0-9a-fA-F]{4}>", hi):
                protect("tounicode_codespace")
            start, end = int(lo[1:-1], 16), int(hi[1:-1], 16)
            if start > end:
                raise ValueError("reversed ToUnicode codespace")
            ranges.append((start, end))
    result: dict[int, int] = {}

    def put(code: int, token: str) -> None:
        if not re.fullmatch(_HEX, token) or len(token[1:-1]) % 2:
            raise ValueError("malformed ToUnicode destination")
        try:
            value = bytes.fromhex(token[1:-1]).decode("utf-16-be")
        except UnicodeDecodeError as exc:
            raise ValueError("invalid ToUnicode UTF-16") from exc
        if len(value) != 1 or ord(value) > 0xFFFF:
            protect("tounicode_multichar_or_nonbmp")
        if ord(value) in {0, 0xFFFD}:
            protect("unknown_unicode")
        if not any(lo <= code <= hi for lo, hi in ranges):
            raise ValueError("ToUnicode code outside codespace")
        if code in result and result[code] != ord(value):
            raise ValueError("conflicting ToUnicode mapping")
        if code not in result:
            budget.charge_mappings(1)
        result[code] = ord(value)

    blocks = re.findall(r"(\d+)\s+begin(bfchar|bfrange)\b(.*?)end\2\b", text, re.S)
    if not blocks:
        raise ValueError("missing ToUnicode mappings")
    if len(re.findall(r"\bbegin(?:bfchar|bfrange)\b", text)) != len(blocks):
        raise ValueError("unclosed ToUnicode mapping block")
    for count, kind, body in blocks:
        budget.check()
        tokens = _TOKEN.findall(body)
        if re.sub(_TOKEN, "", body).strip():
            raise ValueError("malformed ToUnicode mapping operands")
        pos = 0
        try:
            for _ in range(int(count)):
                budget.check()
                lo = tokens[pos]
                if not re.fullmatch(r"<[0-9a-fA-F]{4}>", lo):
                    protect("tounicode_codespace")
                start = int(lo[1:-1], 16)
                if kind == "bfchar":
                    put(start, tokens[pos + 1])
                    pos += 2
                    continue
                hi = tokens[pos + 1]
                if not re.fullmatch(r"<[0-9a-fA-F]{4}>", hi):
                    protect("tounicode_codespace")
                end = int(hi[1:-1], 16)
                if end < start:
                    raise ValueError("reversed ToUnicode range")
                pos += 2
                if tokens[pos] == "[":
                    pos += 1
                    for cid in range(start, end + 1):
                        put(cid, tokens[pos])
                        pos += 1
                    if tokens[pos] != "]":
                        raise ValueError("ToUnicode array count mismatch")
                    pos += 1
                else:
                    base = tokens[pos]
                    if not re.fullmatch(r"<[0-9a-fA-F]{4}>", base):
                        protect("tounicode_multichar_or_nonbmp")
                    value = int(base[1:-1], 16)
                    if value + end - start > 0xFFFF:
                        raise ValueError("ToUnicode range overflow")
                    for cid in range(start, end + 1):
                        put(cid, f"<{value + cid - start:04X}>")
                    pos += 1
        except IndexError as exc:
            raise ValueError("truncated ToUnicode mapping") from exc
        if pos != len(tokens):
            raise ValueError("ToUnicode mapping count mismatch")
    return result


def width_map(desc) -> tuple[Decimal, dict[int, Decimal]]:
    default = number(desc.get("/DW", 1000))
    values = desc.get("/W", pq.Array())
    if not isinstance(values, pq.Array):
        raise ValueError("CID widths array expected")
    result: dict[int, Decimal] = {}
    pos = 0
    while pos < len(values):
        try:
            first, second = integer(values[pos]), values[pos + 1]
            if isinstance(second, pq.Array):
                last = first + len(second) - 1
                widths = list(second)
                pos += 2
            else:
                last = integer(second)
                if not 0 <= first <= last <= 65535:
                    raise ValueError("invalid CID widths range")
                widths = [values[pos + 2]] * (last - first + 1)
                pos += 3
            if not 0 <= first <= last <= 65535:
                raise ValueError("invalid CID widths range")
            for code, value in zip(range(first, last + 1), widths):
                width = number(value)
                if code in result and result[code] != width:
                    raise ValueError("conflicting CID widths")
                result[code] = width
        except IndexError as exc:
            raise ValueError("truncated CID widths") from exc
    return default, result


def inherited(page, key: str):
    obj = page.obj
    seen = set()
    for _ in range(64):
        if key in obj:
            return obj[key]
        parent = obj.get("/Parent")
        if parent is None:
            return None
        identity = parent.objgen
        if identity in seen:
            raise ValueError("cyclic page inheritance")
        seen.add(identity)
        obj = parent
    protect("page_inheritance_limit")


def font_key(font) -> tuple[int, int]:
    if not isinstance(font, pq.Dictionary):
        raise ValueError("font dictionary expected")
    if font.objgen == (0, 0):
        protect("direct_font_dictionary")
    return font.objgen


@dataclass
class FontRecord:
    font: object
    byte_count: int
    mapping: dict[int, int]
    widths: dict[int, Decimal]
    encoding: object
    tounicode: object | None
    embedded: bool
    glyph_count: int | None = None
    used: set[int] = field(default_factory=set)
    preserve: bool = False


@dataclass
class PageRecord:
    page: object
    resources: object
    instructions: list


@dataclass
class Analysis:
    fonts: dict[tuple[int, int], FontRecord]
    pages: list[PageRecord]
    unicode: set[int]


def _font_record(font, budget: Budget, stream_cache: dict) -> FontRecord:
    subtype = font.get("/Subtype")
    if subtype == pq.Name.Type0:
        if font.get("/Encoding") != pq.Name("/Identity-H"):
            protect("font_encoding")
        descendants = font.get("/DescendantFonts")
        if not isinstance(descendants, pq.Array) or len(descendants) != 1:
            raise ValueError("one descendant font expected")
        desc = descendants[0]
        if desc.get("/Subtype") != pq.Name.CIDFontType2:
            protect("font_subtype")
        if "/W2" in desc or "/DW2" in desc:
            protect("vertical_font")
        if desc.get("/CIDToGIDMap", pq.Name.Identity) != pq.Name.Identity:
            protect("source_cid_to_gid_map")
        to_unicode = font.get("/ToUnicode")
        if not isinstance(to_unicode, pq.Stream):
            protect("missing_tounicode")
        mapping = cmap_entries(bounded_stream(to_unicode, RECIPE["content_bytes"], RECIPE["content_bytes"],
                                             budget, category="tounicode"), budget)
        default, declared_widths = width_map(desc)
        widths = {code: declared_widths.get(code, default) for code in mapping}
        encoding, byte_count = font.Encoding, 2
    elif subtype == pq.Name.TrueType:
        if font.get("/Encoding") != pq.Name.WinAnsiEncoding or "/ToUnicode" in font:
            protect("simple_font_encoding")
        first, last = integer(font.get("/FirstChar")), integer(font.get("/LastChar"))
        if not 32 <= first <= last <= 126:
            protect("simple_font_nonascii")
        values = font.get("/Widths")
        if not isinstance(values, pq.Array) or len(values) != last - first + 1:
            raise ValueError("simple font widths count mismatch")
        declared_widths = {first + i: number(width) for i, width in enumerate(values)}
        mapping = {code: code for code, width in declared_widths.items() if width > 0}
        budget.charge_mappings(len(mapping))
        widths = {code: declared_widths[code] for code in mapping}
        desc, to_unicode, encoding, byte_count = font, None, None, 1
    else:
        protect("font_subtype")
    if not mapping:
        protect("empty_font_mapping")
    if any(width <= 0 or width >= 65536 for width in widths.values()):
        protect("font_width")
    descriptor = desc.get("/FontDescriptor")
    if not isinstance(descriptor, pq.Dictionary):
        raise ValueError("missing font descriptor")
    if "/FontFile" in descriptor or "/FontFile3" in descriptor:
        protect("font_program_type")
    stream = descriptor.get("/FontFile2")
    glyph_count = None
    if stream is not None:
        if not isinstance(stream, pq.Stream):
            raise ValueError("font program stream expected")
        length1 = stream.get("/Length1")
        if length1 is not None and integer(length1) > RECIPE["decoded_font_bytes"]:
            protect("font_decoded_limit")
        key = stream.objgen
        if key not in stream_cache:
            data = bounded_stream(stream, RECIPE["font_stream_bytes"], RECIPE["decoded_font_bytes"],
                                  budget, category="font")
            if length1 is not None and integer(length1) != len(data):
                raise ValueError("font Length1 mismatch")
            with TTFont(io.BytesIO(data), lazy=True) as program:
                if "glyf" not in program or "hmtx" not in program:
                    protect("font_program_type")
                glyph_count = program["maxp"].numGlyphs
                # Parse required tables now: corrupted font programs remain errors.
                program["head"], program["hmtx"]
            stream_cache[key] = glyph_count
        glyph_count = stream_cache[key]
    return FontRecord(font, byte_count, mapping, widths, encoding, to_unicode,
                      stream is not None, glyph_count)


def _jpeg_dimensions(data: bytes) -> tuple[int, int, int, int]:
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("invalid JPEG image stream")
    pos = 2
    while pos < len(data):
        if data[pos] != 255:
            raise ValueError("invalid JPEG marker")
        while pos < len(data) and data[pos] == 255:
            pos += 1
        if pos >= len(data):
            raise ValueError("truncated JPEG marker")
        marker = data[pos]
        pos += 1
        if marker in {0xDA, 0xD9}:
            break
        if pos + 2 > len(data):
            raise ValueError("truncated JPEG header")
        length = int.from_bytes(data[pos:pos + 2], "big")
        if length < 2 or pos + length > len(data):
            raise ValueError("invalid JPEG segment length")
        if marker in {0xC0, 0xC1, 0xC2}:
            if length < 8:
                raise ValueError("truncated JPEG dimensions")
            if length != 8 + data[pos + 7] * 3:
                raise ValueError("invalid JPEG component header")
            return (int.from_bytes(data[pos + 5:pos + 7], "big"),
                    int.from_bytes(data[pos + 3:pos + 5], "big"), data[pos + 2], data[pos + 7])
        if 0xC0 <= marker <= 0xCF and marker not in {0xC4, 0xC8, 0xCC}:
            protect("image_jpeg_process")
        pos += length
    raise ValueError("missing JPEG dimensions")


def _check_image(image, budget: Budget) -> None:
    width, height = integer(image.get("/Width")), integer(image.get("/Height"))
    bits = integer(image.get("/BitsPerComponent"))
    if width <= 0 or height <= 0:
        raise ValueError("invalid image dimensions")
    if width * height > RECIPE["image_pixels"]:
        protect("image_pixel_limit")
    color = image.get("/ColorSpace")
    if bits not in {1, 8} or color not in {pq.Name.DeviceRGB, pq.Name.DeviceGray}:
        protect("image_structure")
    if any(image.get(key) is not None for key in ("/Mask", "/Decode")) or image.get("/ImageMask", False):
        protect("image_structure")
    mask = image.get("/SMask")
    if mask is not None:
        if (not isinstance(mask, pq.Stream) or mask.get('/Subtype') != pq.Name.Image
                or mask.get('/ColorSpace') != pq.Name.DeviceGray
                or mask.get('/Width') != width or mask.get('/Height') != height
                or mask.get('/BitsPerComponent') != 8 or mask.get('/SMask') is not None):
            protect("image_soft_mask")
        _check_image(mask, budget)
    channels = 3 if color == pq.Name.DeviceRGB else 1
    expected = ((width * channels * bits + 7) // 8) * height
    if expected > RECIPE["decoded_image_bytes"]:
        protect("image_decoded_limit")
    filt = image.get("/Filter")
    if isinstance(filt, pq.Array) and len(filt) == 1:
        filt = filt[0]
    if filt == pq.Name.DCTDecode:
        if image.get("/DecodeParms") is not None:
            protect("image_decode_parameters")
        length = integer(image.get("/Length"))
        if length < 0:
            raise ValueError("invalid image stream length")
        if length > RECIPE["image_stream_bytes"]:
            protect("image_stream_limit")
        data = image.read_raw_bytes()
        if len(data) != length or _jpeg_dimensions(data) != (width, height, bits, channels):
            raise ValueError("JPEG dimensions or length disagree with PDF")
        budget.charge_decoded(expected)
    else:
        params = image.get("/DecodeParms")
        if isinstance(params, pq.Array) and len(params) == 1:
            params = params[0]
        predictor = 1
        if params is not None:
            if not isinstance(params, pq.Dictionary):
                protect("image_decode_parameters")
            predictor = integer(params.get("/Predictor", 1))
            if predictor not in {1, 2, 10, 11, 12, 13, 14, 15}:
                protect("image_decode_parameters")
            if (integer(params.get("/Colors", 1)) != channels
                    or integer(params.get("/BitsPerComponent", 8)) != bits
                    or integer(params.get("/Columns", 1)) != width):
                protect("image_decode_parameters")
        decoded = bounded_stream(image, RECIPE["image_stream_bytes"], RECIPE["decoded_image_bytes"],
                                 budget, category="image")
        if len(decoded) != expected + (height if predictor >= 10 else 0):
            raise ValueError("image decoded length disagrees with geometry")


def _check_gstate(resources, name) -> None:
    states = resources.get("/ExtGState", pq.Dictionary())
    state = states.get(name)
    if not isinstance(state, pq.Dictionary):
        raise ValueError("missing ExtGState")
    allowed = {"/Type", "/LW", "/LC", "/LJ", "/ML", "/D", "/RI", "/CA", "/ca", "/BM"}
    if set(state.keys()) - allowed:
        protect("graphics_state")
    if state.get("/BM", pq.Name.Normal) != pq.Name.Normal:
        protect("graphics_state")
    for key in ("/CA", "/ca"):
        if number(state.get(key, 1)) != 1:
            protect("graphics_state")


def _marked_content(op: str, args: list) -> None:
    if len(args) != (1 if op == "BMC" else 2) or not isinstance(args[0], pq.Name):
        raise ValueError("invalid marked-content operands")
    if args[0] == pq.Name.OC:
        protect("optional_content")
    if op == "BMC":
        return
    props = args[1]
    if not isinstance(props, pq.Dictionary):
        protect("marked_content_properties")
    if set(props.keys()) - {"/MCID", "/Lang", "/Type", "/Subtype", "/Attached", "/BBox"}:
        protect("marked_content_properties")
    if "/MCID" in props and integer(props.MCID) < 0:
        raise ValueError("negative marked-content identifier")
    if "/Lang" in props and not isinstance(props.Lang, pq.String):
        raise ValueError("invalid marked-content language")
    for key in ("/Type", "/Subtype"):
        if key in props and not isinstance(props[key], pq.Name):
            raise ValueError("invalid artifact category")
    if "/Attached" in props:
        if not isinstance(props.Attached, pq.Array) or any(
                value not in {pq.Name.Top, pq.Name.Bottom, pq.Name.Left, pq.Name.Right}
                for value in props.Attached):
            raise ValueError("invalid artifact attachment")
    if "/BBox" in props:
        if not isinstance(props.BBox, pq.Array) or len(props.BBox) != 4:
            raise ValueError("invalid artifact bounding box")
        for value in props.BBox:
            number(value)


def _page_instructions(pdf, page, budget: Budget) -> list:
    contents = page.obj.get("/Contents")
    if contents is None:
        return []
    streams = list(contents) if isinstance(contents, pq.Array) else [contents]
    safe = []
    for stream in streams:
        data = bounded_stream(stream, RECIPE["content_bytes"], RECIPE["content_bytes"],
                              budget, category="content")
        budget.content += len(data)
        if budget.content > RECIPE["content_bytes"]:
            protect("content_total_limit")
        safe.append(pdf.make_stream(data))
    # Let pikepdf implement array-of-content-stream parsing semantics, but only
    # after every stream has already passed our bounded decompressor.
    page.obj.Contents = pq.Array(safe)
    try:
        instructions = pq.parse_content_stream(page)
    finally:
        page.obj.Contents = contents
    return instructions


def analyze(pdf, source: Path, budget: Budget) -> Analysis:
    budget.check()
    if source.stat().st_size > RECIPE["source_bytes"]:
        protect("source_size_limit")
    if pdf.is_encrypted:
        protect("encrypted")
    if not 0 < len(pdf.pages) <= RECIPE["pages"]:
        protect("page_limit")
    root = pdf.Root
    form = root.get("/AcroForm")
    if form is not None:
        if not isinstance(form, pq.Dictionary):
            raise ValueError("AcroForm dictionary expected")
        fields = form.get("/Fields", pq.Array())
        if not isinstance(fields, pq.Array):
            raise ValueError("AcroForm Fields array expected")
        if len(fields) or set(form.keys()) - {"/Fields", "/DR", "/DA", "/NeedAppearances"}:
            protect("forms_or_signatures")
    if root.get("/Perms") is not None:
        protect("forms_or_signatures")
    if root.get("/OCProperties") is not None:
        protect("optional_content")
    if any(root.get(key) is not None for key in
           ("/AA", "/AF", "/Collection", "/Threads")):
        protect("catalog_structure")
    names = root.get("/Names", pq.Dictionary())
    if names.get("/EmbeddedFiles") is not None:
        protect("attachments")
    fonts: dict[tuple[int, int], FontRecord] = {}
    pages: list[PageRecord] = []
    font_streams: dict = {}
    image_seen = set()
    predicted_pixels = 0
    for page in pdf.pages:
        budget.check()
        if page.obj.get("/Annots"):
            protect("annotations")
        if page.obj.get("/AA") is not None or page.obj.get("/Group") is not None:
            # Simple isolated Normal transparency groups are common Word output.
            group = page.obj.get("/Group")
            if page.obj.get("/AA") is not None or not isinstance(group, pq.Dictionary):
                protect("page_state")
            if set(group.keys()) - {"/S", "/CS", "/I", "/K", "/Type"} or group.get("/S") != pq.Name.Transparency:
                protect("page_state")
            if group.get("/K", False) or group.get("/CS") not in {None, pq.Name.DeviceRGB, pq.Name.DeviceGray}:
                protect("page_state")
        box = inherited(page, "/CropBox") or inherited(page, "/MediaBox")
        if not isinstance(box, pq.Array) or len(box) != 4:
            raise ValueError("page box expected")
        x0, y0, x1, y1 = map(number, box)
        if x1 <= x0 or y1 <= y0:
            raise ValueError("invalid page box")
        if number(page.obj.get("/UserUnit", 1)) != 1:
            protect("page_user_unit")
        scale = Decimal(RECIPE["render_dpi"]) / 72
        pixels = math.ceil((x1 - x0) * scale) * math.ceil((y1 - y0) * scale)
        if pixels > RECIPE["page_render_pixels"]:
            protect("page_render_limit")
        predicted_pixels += pixels * 2
        if predicted_pixels > RECIPE["validation_pixels_per_candidate"]:
            protect("validation_pixel_limit")
        resources = inherited(page, "/Resources")
        if not isinstance(resources, pq.Dictionary):
            raise ValueError("page resources expected")
        if any(resources.get(key) for key in ("/Pattern", "/Shading", "/Properties")):
            protect("complex_resources")
        graphics_states = resources.get("/ExtGState", pq.Dictionary())
        if not isinstance(graphics_states, pq.Dictionary):
            raise ValueError("graphics-state resources dictionary expected")
        for name in graphics_states.keys():
            _check_gstate(resources, name)
        for xobject in resources.get("/XObject", pq.Dictionary()).values():
            subtype = xobject.get("/Subtype")
            if subtype != pq.Name.Image:
                protect("form_or_nonimage_xobject")
            if xobject.objgen not in image_seen:
                _check_image(xobject, budget)
                image_seen.add(xobject.objgen)
        page_fonts = resources.get("/Font", pq.Dictionary())
        if not isinstance(page_fonts, pq.Dictionary):
            raise ValueError("font resources dictionary expected")
        for font in page_fonts.values():
            key = font_key(font)
            if key not in fonts:
                if len(fonts) >= RECIPE["font_count"]:
                    protect("font_count_limit")
                fonts[key] = _font_record(font, budget, font_streams)
        instructions = _page_instructions(pdf, page, budget)
        current = None
        stack = []
        in_text = False
        marked_depth = 0
        for instruction in instructions:
            budget.check()
            if not isinstance(instruction, pq.ContentStreamInstruction):
                protect("inline_image")
            op, args = str(instruction.operator), list(instruction.operands)
            numeric_counts = {"cm": 6, "w": 1, "J": 1, "j": 1, "M": 1,
                              "i": 1, "m": 2, "l": 2, "c": 6, "v": 4, "y": 4,
                              "re": 4, "G": 1, "g": 1, "RG": 3, "rg": 3,
                              "K": 4, "k": 4, "Tc": 1, "Tw": 1, "TL": 1,
                              "Ts": 1, "Td": 2, "TD": 2}
            no_operands = {"q", "Q", "BT", "ET", "T*", "h", "S", "s", "f", "F",
                           "f*", "B", "B*", "b", "b*", "n", "W", "W*"}
            special = {"Tf", "Tr", "Tz", "Tm", "gs", "Tj", "TJ", "d", "ri", "Do", "BDC", "BMC", "EMC",
                       "CS", "cs", "SC", "sc", "SCN", "scn"}
            unsupported_ops = {"'", '"', "DP", "MP", "BX", "EX", "sh"}
            if op in unsupported_ops:
                protect("complex_content")
            if op not in numeric_counts and op not in no_operands and op not in special:
                raise ValueError("unknown content operator")
            if op in numeric_counts:
                if len(args) != numeric_counts[op]:
                    raise ValueError("invalid content operator arity")
                for arg in args:
                    number(arg)
            if op in no_operands and args:
                raise ValueError("unexpected content operator operands")
            if op in {"CS", "cs"} and (len(args) != 1 or args[0] not in
                    {pq.Name.DeviceRGB, pq.Name.DeviceGray, pq.Name.DeviceCMYK}):
                protect("content_colorspace")
            if op in {"SC", "sc", "SCN", "scn"}:
                for arg in args:
                    if not isinstance(arg, (int, float, Decimal)):
                        protect("content_colorspace")
                    number(arg)
            if op == "Do" and (len(args) != 1 or resources.get("/XObject", pq.Dictionary()).get(args[0]) is None):
                raise ValueError("unknown image resource")
            if op == "d":
                if len(args) != 2 or not isinstance(args[0], pq.Array):
                    raise ValueError("invalid dash pattern")
                for arg in list(args[0]) + args[1:]:
                    number(arg)
            if op == "ri" and (len(args) != 1 or not isinstance(args[0], pq.Name)):
                raise ValueError("invalid rendering intent")
            if op in {"BMC", "BDC"}:
                _marked_content(op, args)
                marked_depth += 1
                if marked_depth > 64:
                    protect("marked_content_nesting_limit")
            elif op == "EMC":
                if args or not marked_depth:
                    raise ValueError("unbalanced marked content")
                marked_depth -= 1
            if op == "q":
                stack.append(current)
            elif op == "Q":
                if not stack:
                    raise ValueError("unbalanced graphics state")
                current = stack.pop()
            elif op == "BT":
                if in_text:
                    raise ValueError("nested text object")
                in_text = True
            elif op == "ET":
                if not in_text:
                    raise ValueError("unbalanced text object")
                in_text = False
            elif op == "Tf":
                if len(args) != 2 or number(args[1]) <= 0:
                    raise ValueError("invalid font selection")
                font = page_fonts.get(args[0])
                if font is None:
                    raise ValueError("unknown font resource")
                current = font_key(font)
            elif op == "Tr":
                if len(args) != 1 or not 0 <= integer(args[0]) <= 7:
                    raise ValueError("invalid text rendering mode")
                if integer(args[0]) >= 4:
                    protect("text_clipping")
            elif op == "Tz":
                if len(args) != 1 or number(args[0]) <= 0:
                    protect("horizontal_scale")
            elif op == "Tm":
                if len(args) != 6:
                    raise ValueError("invalid text matrix")
                a, b, c, d, _, _ = map(number, args)
                determinant = a * d - b * c
                axis_product = ((a * a + b * b) * (c * c + d * d)).sqrt()
                if determinant <= 0 or abs(a * c + b * d) > Decimal("1e-10") * axis_product:
                    protect("transformed_text")
            elif op == "gs":
                if len(args) != 1:
                    raise ValueError("invalid graphics state selection")
                _check_gstate(resources, args[0])
            if op not in {"Tj", "TJ"}:
                continue
            if not in_text or current is None or len(args) != 1:
                raise ValueError("text show outside valid text/font state")
            record = fonts[current]
            values = args[0] if op == "TJ" else [args[0]]
            if op == "TJ" and not isinstance(values, pq.Array):
                raise ValueError("TJ array expected")
            for value in values:
                if not isinstance(value, pq.String):
                    number(value)
                    if op == "Tj":
                        raise ValueError("Tj string expected")
                    continue
                data = bytes(value)
                if len(data) % record.byte_count:
                    raise ValueError("truncated font character code")
                budget.characters += len(data) // record.byte_count
                if budget.characters > RECIPE["char_count"]:
                    protect("character_limit")
                record.used.update(int.from_bytes(data[i:i + record.byte_count], "big")
                                   for i in range(0, len(data), record.byte_count))
        if in_text or stack or marked_depth:
            raise ValueError("unbalanced page graphics/text state")
        pages.append(PageRecord(page, resources, instructions))
    unicode = set()
    for record in fonts.values():
        if not record.used <= record.mapping.keys():
            protect("unmapped_character")
        if not record.embedded:
            if record.byte_count == 1 and record.used <= {32}:
                record.preserve = True
                continue
            protect("unembedded_font")
        if record.byte_count == 2 and any(code >= record.glyph_count for code in record.used):
            raise ValueError("CID outside source font glyph table")
        unicode.update(record.mapping.values())
    if not unicode or not budget.characters:
        protect("no_text")
    budget.check()
    warnings = pdf.get_warnings()
    if warnings:
        raise ValueError("PDF structural warnings during font analysis")
    return Analysis(fonts, pages, unicode)
