"""Independent, bounded validation of explicitly requested font candidates.

The generator is deliberately not imported. PDF text bytes, drawing order,
resources, font programs and rendering are checked against the actual files.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import io
import math
from pathlib import Path
import re
import time
import zlib

import pikepdf as pdf
import pymupdf as fitz
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont

from .lossless_jpeg import CandidateRejected

MAX_PAGES = 200
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_STREAM_BYTES = 64 * 1024 * 1024
MAX_COMPRESSED_BYTES = 32 * 1024 * 1024
MAX_CONTENT_BYTES = 32 * 1024 * 1024
MAX_DECODED_BYTES = 256 * 1024 * 1024
MAX_IMAGE_PIXELS = 32_000_000
MAX_RENDER_PIXELS = 32_000_000
MAX_TOTAL_RENDER_PIXELS = 600_000_000
MAX_OBJECTS = 100_000
MAX_MAPPINGS = 1_000_000
MAX_DEPTH = 64
RENDER_DPI = 144
ORIGIN_TOLERANCE = 0.02


@dataclass(frozen=True)
class ValidationSummary:
    extraction_whitespace_changed: bool
    page_count: int
    rendered_pixels: int
    validated_glyph_count: int = 0


@dataclass
class _Budget:
    deadline: float
    rendered_pixels: int = 0
    decoded_bytes: int = 0
    mapping_count: int = 0

    def check(self) -> None:
        if time.monotonic() > self.deadline:
            raise CandidateRejected("font_validation_time_limit")

    def decoded(self, count: int) -> None:
        self.check()
        self.decoded_bytes += count
        if self.decoded_bytes > MAX_DECODED_BYTES:
            raise CandidateRejected("font_validation_decoded_byte_limit")

    def mappings(self, count: int) -> None:
        self.check()
        self.mapping_count += count
        _require(self.mapping_count <= MAX_MAPPINGS, 'mapping_count_limit')


def _require(condition, reason: str) -> None:
    if not condition:
        raise CandidateRejected(f"font_validation_{reason}")


def _sha(path: Path, budget: _Budget) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            budget.check()
            h.update(chunk)
    return h.hexdigest()


def _number(value) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("non-finite PDF number")
    return result


def _integer(value) -> int:
    result = _number(value)
    if result != int(result):
        raise ValueError("non-integer PDF value")
    return int(result)


class _Reader:
    """Decode only bounded Flate streams; retain other filters byte-for-byte."""

    def __init__(self, document, budget: _Budget):
        self.document = document
        self.budget = budget
        self.streams = {}
        self.content_bytes = 0
        self.char_count = 0
        self.page_refs = {page.obj.objgen: i for i, page in enumerate(document.pages)}

    def payload(self, stream):
        self.budget.check()
        key = stream.objgen
        if key in self.streams:
            return self.streams[key]
        length = stream.get('/Length')
        if length is None or int(length) != length or int(length) < 0:
            raise ValueError("invalid PDF stream length")
        _require(int(length) <= MAX_COMPRESSED_BYTES, 'stream_byte_limit')
        raw = stream.read_raw_bytes()
        if len(raw) != int(length):
            raise ValueError("PDF stream length mismatch")
        filter_value = stream.get('/Filter')
        if isinstance(filter_value, pdf.Array):
            _require(len(filter_value) == 1, 'unsupported_stream_filters')
            filter_value = filter_value[0]
        params = stream.get('/DecodeParms')
        if isinstance(params, pdf.Array):
            _require(len(params) == 1, 'unsupported_stream_parameters')
            params = params[0]
        if filter_value is None or filter_value == pdf.Name('/FlateDecode'):
            if filter_value is None:
                decoded = raw
            else:
                inflater = zlib.decompressobj()
                decoded = inflater.decompress(raw, MAX_STREAM_BYTES + 1)
                _require(len(decoded) <= MAX_STREAM_BYTES and not inflater.unconsumed_tail,
                         'stream_decoded_limit')
                if not inflater.eof or inflater.unused_data:
                    raise ValueError("invalid or ambiguous Flate stream")
            self.budget.decoded(len(decoded))
            result = ('decoded', params, decoded)
        else:
            _require(filter_value == pdf.Name('/DCTDecode') and stream.get('/Subtype') == pdf.Name.Image,
                     'unsupported_stream_filter')
            expected = _integer(stream.Width) * _integer(stream.Height) * (3 if stream.ColorSpace == pdf.Name.DeviceRGB else 1)
            _require(expected <= MAX_STREAM_BYTES, 'stream_decoded_limit')
            self.budget.decoded(expected)
            result = (str(filter_value), params, raw)
        self.streams[key] = result
        return result

    def decoded(self, stream) -> bytes:
        kind, params, data = self.payload(stream)
        _require(kind == 'decoded' and params is None, 'unsupported_data_stream')
        return data

    def snapshot(self, value):
        seen = {}

        def visit(obj, depth):
            self.budget.check()
            _require(depth <= MAX_DEPTH and len(seen) <= MAX_OBJECTS, 'object_limit')
            if obj is None or isinstance(obj, bool):
                return obj
            if isinstance(obj, (int, float, Decimal)):
                return ('number', _number(obj))
            if isinstance(obj, pdf.Name):
                # PDF names are byte strings; legacy producers use CP932 names.
                # Do not require them to decode as UTF-8 merely to compare them.
                return ('name', obj.unparse())
            if isinstance(obj, pdf.String):
                return ('string', bytes(obj))
            ref = getattr(obj, 'objgen', (0, 0))
            if ref in self.page_refs:
                return ('page', self.page_refs[ref])
            prefix = None
            if ref != (0, 0):
                if ref in seen:
                    return ('reference', seen[ref])
                prefix = len(seen)
                seen[ref] = prefix
            if isinstance(obj, pdf.Stream):
                kind, params, data = self.payload(obj)
                values = tuple((str(k), visit(v, depth+1)) for k, v in sorted(obj.items())
                               if str(k) not in {'/Length', '/Filter', '/DecodeParms'})
                result = ('stream', values, kind, visit(params, depth+1), hashlib.sha256(data).digest())
            elif isinstance(obj, pdf.Dictionary):
                result = ('dictionary', tuple((str(k), visit(v, depth+1)) for k, v in sorted(obj.items())))
            elif isinstance(obj, pdf.Array):
                result = ('array', tuple(visit(v, depth+1) for v in obj))
            else:
                raise ValueError(f"unsupported PDF object: {type(obj).__name__}")
            return ('object', prefix, result) if prefix is not None else result

        return visit(value, 0)


def _cmap(data: bytes, budget: _Budget) -> dict[int, int]:
    """Parse the supported two-byte BMP ToUnicode subset, rejecting other syntax."""
    source = re.sub(rb'%[^\r\n]*', b'', data).decode('latin1')
    _require(not re.search(r'\b(?:usecmap|begincidchar|begincidrange|beginnotdefchar|beginnotdefrange)\b', source),
             'unsupported_cmap')
    spaces = re.findall(r'(\d+)\s+begincodespacerange(.*?)endcodespacerange', source, re.S)
    _require(bool(spaces), 'unsupported_cmap_codespace')
    ranges = []
    for count, body in spaces:
        pairs = re.findall(r'<([0-9A-Fa-f]{4})>\s*<([0-9A-Fa-f]{4})>', body)
        _require(len(pairs) == int(count) and not re.sub(r'<[0-9A-Fa-f]{4}>|\s+', '', body),
                 'unsupported_cmap_codespace')
        for low, high in pairs:
            low, high = int(low, 16), int(high, 16)
            if high < low:
                raise ValueError("reversed CMap codespace")
            ranges.append((low, high))
    result = {}

    def add(code, value):
        budget.check()
        _require(re.fullmatch(r'<[0-9A-Fa-f]{4}>', value) is not None, 'unsupported_cmap_unicode')
        unicode = int(value[1:-1], 16)
        _require(unicode not in {0, 0xFFFD} and not 0xD800 <= unicode <= 0xDFFF, 'unsupported_cmap_unicode')
        if not any(lo <= code <= hi for lo, hi in ranges):
            raise ValueError("ToUnicode outside codespace")
        if code in result and result[code] != unicode:
            raise ValueError("ambiguous ToUnicode mapping")
        if code not in result:
            budget.mappings(1)
        result[code] = unicode

    blocks = re.findall(r'(\d+)\s+begin(bfchar|bfrange)\b(.*?)end\2\b', source, re.S)
    _require(bool(blocks), 'unsupported_cmap')
    for count, kind, body in blocks:
        tokens = re.findall(r'<[0-9A-Fa-f]+>|\[|\]', body)
        _require(not re.sub(r'<[0-9A-Fa-f]+>|\[|\]|\s+', '', body), 'unsupported_cmap_syntax')
        pos = 0
        for _ in range(int(count)):
            if pos >= len(tokens):
                raise ValueError("truncated ToUnicode mapping")
            low = tokens[pos]
            _require(re.fullmatch(r'<[0-9A-Fa-f]{4}>', low) is not None, 'unsupported_cmap_code')
            first = int(low[1:-1], 16)
            if kind == 'bfchar':
                add(first, tokens[pos+1]); pos += 2
                continue
            high = tokens[pos+1]
            _require(re.fullmatch(r'<[0-9A-Fa-f]{4}>', high) is not None, 'unsupported_cmap_code')
            last = int(high[1:-1], 16)
            if last < first:
                raise ValueError("reversed ToUnicode range")
            pos += 2
            if tokens[pos] == '[':
                pos += 1
                for code in range(first, last+1):
                    add(code, tokens[pos]); pos += 1
                if tokens[pos] != ']':
                    raise ValueError("invalid ToUnicode range array")
                pos += 1
            else:
                value = tokens[pos]
                _require(re.fullmatch(r'<[0-9A-Fa-f]{4}>', value) is not None, 'unsupported_cmap_unicode')
                base = int(value[1:-1], 16)
                _require(base+last-first <= 0xFFFF, 'unsupported_cmap_unicode')
                for code in range(first, last+1):
                    add(code, f'<{base+code-first:04X}>')
                pos += 1
        if pos != len(tokens):
            raise ValueError("extra ToUnicode operands")
    return result


def _widths(desc):
    values = list(desc.get('/W', []))
    found = {}
    pos = 0
    while pos < len(values):
        first = int(values[pos])
        _require(0 <= first <= 65535, 'unsupported_cid')
        second = values[pos+1]
        if isinstance(second, pdf.Array):
            for i, width in enumerate(second):
                found[first+i] = _number(width)
            pos += 2
        else:
            last = int(second)
            _require(first <= last <= 65535, 'unsupported_cid_range')
            for code in range(first, last+1):
                found[code] = _number(values[pos+2])
            pos += 3
    return _number(desc.get('/DW', 1000)), found


@dataclass
class _FontInfo:
    width: int
    unicode: dict[int, int]
    widths: dict[int, Decimal]
    default: Decimal
    preserve: bool = False


def _source_font(font, reader: _Reader) -> _FontInfo:
    subtype = font.get('/Subtype')
    if subtype == pdf.Name('/Type0'):
        _require(font.get('/Encoding') == pdf.Name('/Identity-H'), 'unsupported_font_encoding')
        descendants = font.get('/DescendantFonts', [])
        _require(len(descendants) == 1, 'unsupported_descendant_fonts')
        desc = descendants[0]
        _require(desc.get('/Subtype') == pdf.Name('/CIDFontType2') and '/W2' not in desc and '/DW2' not in desc,
                 'unsupported_cidfont')
        _require(desc.get('/CIDToGIDMap', pdf.Name('/Identity')) == pdf.Name('/Identity'),
                 'unsupported_source_gidmap')
        default, widths = _widths(desc)
        descriptor = desc.get('/FontDescriptor')
        _require(descriptor is not None and '/FontFile2' in descriptor and '/FontFile3' not in descriptor
                 and '/FontFile' not in descriptor, 'unsupported_source_font_program')
        reader.decoded(descriptor.FontFile2)
        return _FontInfo(2, _cmap(reader.decoded(font.ToUnicode), reader.budget), widths, default)
    descriptor = font.get('/FontDescriptor')
    embedded = descriptor is not None and any(k in descriptor for k in ('/FontFile', '/FontFile2', '/FontFile3'))
    if not embedded:
        _require(subtype == pdf.Name.TrueType and font.get('/Encoding') == pdf.Name.WinAnsiEncoding
                 and '/ToUnicode' not in font, 'unsupported_unembedded_font')
        return _FontInfo(1, {32: 32}, {}, Decimal(0), True)
    _require(subtype == pdf.Name('/TrueType') and font.get('/Encoding') == pdf.Name('/WinAnsiEncoding')
             and '/ToUnicode' not in font, 'unsupported_simple_font')
    first, last = int(font.FirstChar), int(font.LastChar)
    _require(32 <= first <= last <= 126, 'unsupported_simple_font_range')
    _require('/FontFile2' in descriptor and '/FontFile3' not in descriptor and '/FontFile' not in descriptor,
             'unsupported_source_font_program')
    reader.decoded(descriptor.FontFile2)
    widths = {first+i: _number(w) for i, w in enumerate(font.Widths)}
    if len(widths) != last-first+1:
        raise ValueError("invalid simple font width array")
    mapping = {c: c for c, width in widths.items() if width > 0}
    reader.budget.mappings(len(mapping))
    return _FontInfo(1, mapping, widths, Decimal(0))


def _jpeg_geometry(data: bytes):
    """Read the SOF before allowing a native decoder to allocate image pixels."""
    if data[:2] != b'\xff\xd8':
        raise ValueError("invalid JPEG header")
    offset = 2
    while offset < len(data):
        if data[offset] != 255:
            raise ValueError("invalid JPEG marker")
        while offset < len(data) and data[offset] == 255:
            offset += 1
        if offset + 3 > len(data):
            raise ValueError("truncated JPEG marker")
        marker = data[offset]
        offset += 1
        length = int.from_bytes(data[offset:offset+2], 'big')
        if length < 2 or offset + length > len(data):
            raise ValueError("invalid JPEG segment")
        if marker in {0xC0, 0xC1, 0xC2}:
            if length < 8 or length != 8 + 3*data[offset+7]:
                raise ValueError("invalid JPEG frame")
            return (int.from_bytes(data[offset+5:offset+7], 'big'),
                    int.from_bytes(data[offset+3:offset+5], 'big'), data[offset+2], data[offset+7])
        _require(not (0xC0 <= marker <= 0xCF and marker not in {0xC4, 0xC8, 0xCC}),
                 'unsupported_jpeg_process')
        if marker in {0xDA, 0xD9}:
            break
        offset += length
    raise ValueError("missing JPEG frame")


def _guard_resources(page, reader: _Reader) -> None:
    _require(not page.get('/Annots', []), 'unsupported_annotations')
    _require(page.get('/AA') is None and _number(page.get('/UserUnit', 1)) == 1,
             'unsupported_page_state')
    group = page.get('/Group')
    if group is not None:
        _require(isinstance(group, pdf.Dictionary) and
                 set(group.keys()) <= {'/S', '/CS', '/I', '/K', '/Type'} and
                 group.get('/S') == pdf.Name.Transparency and not group.get('/K', False) and
                 group.get('/CS') in {None, pdf.Name.DeviceRGB, pdf.Name.DeviceGray}, 'unsupported_page_group')
    images = list(page.Resources.get('/XObject', {}).values())
    for obj in list(images):
        mask = obj.get('/SMask')
        if mask is not None:
            _require(isinstance(mask, pdf.Stream) and mask.get('/Subtype') == pdf.Name.Image
                     and mask.get('/ColorSpace') == pdf.Name.DeviceGray
                     and mask.get('/Width') == obj.get('/Width') and mask.get('/Height') == obj.get('/Height')
                     and mask.get('/BitsPerComponent') == 8 and mask.get('/SMask') is None,
                     'unsupported_image_soft_mask')
            images.append(mask)
    for obj in images:
        _require(obj.get('/Subtype') == pdf.Name('/Image'), 'unsupported_xobject')
        width, height, bits = _integer(obj.Width), _integer(obj.Height), _integer(obj.BitsPerComponent)
        if width <= 0 or height <= 0:
            raise ValueError("invalid image dimensions")
        _require(width*height <= MAX_IMAGE_PIXELS, 'image_pixel_limit')
        _require(bits in {1, 8} and obj.get('/ColorSpace') in {pdf.Name.DeviceRGB, pdf.Name.DeviceGray}
                 and not any(obj.get(k) is not None for k in ('/Mask', '/Decode'))
                 and not obj.get('/ImageMask', False), 'unsupported_image_structure')
        channels = 3 if obj.ColorSpace == pdf.Name.DeviceRGB else 1
        expected = ((width*channels*bits+7)//8)*height
        _require(expected <= MAX_STREAM_BYTES, 'image_decoded_limit')
        kind, params, data = reader.payload(obj)
        if kind == '/DCTDecode':
            _require(params is None, 'unsupported_image_parameters')
            if _jpeg_geometry(data) != (width, height, bits, channels):
                raise ValueError("JPEG frame disagrees with PDF image dimensions")
        else:
            predictor = 1
            if params is not None:
                _require(isinstance(params, pdf.Dictionary) and
                         set(params.keys()) <= {'/Predictor', '/Colors', '/BitsPerComponent', '/Columns'},
                         'unsupported_image_parameters')
                predictor = _integer(params.get('/Predictor', 1))
                _require(predictor in {1, 2, 10, 11, 12, 13, 14, 15} and
                         _integer(params.get('/Colors', 1)) == channels and
                         _integer(params.get('/BitsPerComponent', 8)) == bits and
                         _integer(params.get('/Columns', 1)) == width, 'unsupported_image_parameters')
            if len(data) != expected + (height if predictor >= 10 else 0):
                raise ValueError("decoded image length disagrees with PDF geometry")
    _require(not any(page.Resources.get(k) for k in ('/Pattern', '/Shading', '/Properties')),
             'unsupported_complex_resources')
    allowed_gs = {'/Type', '/CA', '/ca', '/BM', '/LW', '/LC', '/LJ', '/ML', '/D', '/RI'}
    for obj in page.Resources.get('/ExtGState', {}).values():
        _require(set(map(str, obj.keys())) <= allowed_gs and obj.get('/BM', pdf.Name.Normal) == pdf.Name.Normal
                 and all(_number(obj.get(k, 1)) == 1 for k in ('/CA', '/ca')), 'unsupported_graphics_state')


def _marked_content(op, args):
    if len(args) != (1 if op == 'BMC' else 2) or not isinstance(args[0], pdf.Name):
        raise ValueError("invalid marked-content operands")
    _require(args[0] != pdf.Name.OC, 'unsupported_optional_content')
    if op == 'BMC':
        return
    props = args[1]
    _require(isinstance(props, pdf.Dictionary) and
             set(props.keys()) <= {'/MCID', '/Lang', '/Type', '/Subtype', '/Attached', '/BBox'},
             'unsupported_marked_content')
    if '/MCID' in props and _integer(props.MCID) < 0:
        raise ValueError("negative marked-content identifier")
    if '/Lang' in props and not isinstance(props.Lang, pdf.String):
        raise ValueError("invalid marked-content language")
    if any(k in props and not isinstance(props[k], pdf.Name) for k in ('/Type', '/Subtype')):
        raise ValueError("invalid artifact category")
    if '/Attached' in props and (not isinstance(props.Attached, pdf.Array) or
            any(v not in {pdf.Name.Top, pdf.Name.Bottom, pdf.Name.Left, pdf.Name.Right} for v in props.Attached)):
        raise ValueError("invalid artifact attachment")
    if '/BBox' in props:
        if not isinstance(props.BBox, pdf.Array) or len(props.BBox) != 4:
            raise ValueError("invalid artifact bounding box")
        for value in props.BBox:
            _number(value)


def _content(page, reader: _Reader, infos=None):
    contents = page.get('/Contents')
    if contents is None:
        return [], {}
    streams = contents if isinstance(contents, pdf.Array) else [contents]
    for stream in streams:
        data = reader.decoded(stream)
        reader.content_bytes += len(data)
        _require(reader.content_bytes <= MAX_CONTENT_BYTES, 'content_total_limit')
    result, used = [], {}
    current = None
    stack = []
    in_text, marked_depth = False, 0
    for instruction in pdf.parse_content_stream(page):
        reader.budget.check()
        _require(isinstance(instruction, pdf.ContentStreamInstruction), 'unsupported_inline_image')
        op, args = str(instruction.operator), instruction.operands
        _require(op not in {"'", '"', 'DP', 'MP', 'BX', 'EX', 'sh'}, 'unsupported_complex_content')
        numeric = {'cm': 6, 'w': 1, 'J': 1, 'j': 1, 'M': 1, 'i': 1, 'm': 2, 'l': 2,
                   'c': 6, 'v': 4, 'y': 4, 're': 4, 'G': 1, 'g': 1, 'RG': 3, 'rg': 3,
                   'K': 4, 'k': 4, 'Tc': 1, 'Tw': 1, 'TL': 1, 'Ts': 1, 'Td': 2, 'TD': 2}
        empty = {'q', 'Q', 'BT', 'ET', 'T*', 'h', 'S', 's', 'f', 'F', 'f*', 'B', 'B*',
                 'b', 'b*', 'n', 'W', 'W*', 'EMC'}
        special = {'Tf', 'Tr', 'Tz', 'Tm', 'gs', 'Tj', 'TJ', 'd', 'ri', 'Do', 'BDC', 'BMC',
                   'CS', 'cs', 'SC', 'sc', 'SCN', 'scn'}
        if op not in numeric and op not in empty and op not in special:
            raise ValueError("unknown PDF content operator")
        if op in numeric:
            if len(args) != numeric[op]:
                raise ValueError("invalid content operator arity")
            for arg in args:
                _number(arg)
        if op in empty and args:
            raise ValueError("unexpected content operator operands")
        if op in {'CS', 'cs'}:
            _require(len(args) == 1 and args[0] in {pdf.Name.DeviceRGB, pdf.Name.DeviceGray,
                                                   pdf.Name.DeviceCMYK}, 'unsupported_content_colorspace')
        if op in {'SC', 'sc', 'SCN', 'scn'}:
            for arg in args:
                _require(isinstance(arg, (int, float, Decimal)), 'unsupported_content_colorspace')
                _number(arg)
        if op in {'Do', 'gs'}:
            resources = page.Resources.get('/XObject' if op == 'Do' else '/ExtGState', {})
            if len(args) != 1 or args[0] not in resources:
                raise ValueError("unknown drawing resource")
        if op == 'd':
            if len(args) != 2 or not isinstance(args[0], pdf.Array):
                raise ValueError("invalid dash pattern")
            for arg in list(args[0]) + list(args[1:]):
                _number(arg)
        if op == 'ri' and (len(args) != 1 or not isinstance(args[0], pdf.Name)):
            raise ValueError("invalid rendering intent")
        if op in {'BMC', 'BDC'}:
            _marked_content(op, args)
            marked_depth += 1
            _require(marked_depth <= MAX_DEPTH, 'marked_content_depth_limit')
        elif op == 'EMC':
            if args or not marked_depth:
                raise ValueError("unbalanced marked content")
            marked_depth -= 1
        if op == 'q':
            stack.append(current)
        elif op == 'Q':
            if not stack:
                raise ValueError("unbalanced graphics state")
            current = stack.pop()
        elif op == 'BT':
            if in_text:
                raise ValueError("nested text object")
            in_text = True
        elif op == 'ET':
            if not in_text:
                raise ValueError("unbalanced text object")
            in_text = False
        elif op == 'Tf':
            if len(args) != 2 or args[0] not in page.Resources.get('/Font', {}):
                raise ValueError("unknown font resource")
            current = str(args[0])
            _require(_number(args[1]) > 0, 'unsupported_font_size')
        elif op == 'Tr':
            _require(len(args) == 1 and _integer(args[0]) in {0, 1, 2, 3}, 'unsupported_text_clipping')
        elif op == 'Tz':
            _require(len(args) == 1 and _number(args[0]) > 0, 'unsupported_text_scale')
        elif op == 'Tm':
            if len(args) != 6:
                raise ValueError("invalid text matrix")
            a, b, c, d, _, _ = map(_number, args)
            axis_product = ((a*a+b*b)*(c*c+d*d)).sqrt()
            _require(a*d-b*c > 0 and abs(a*c+b*d) <= Decimal('1e-10')*axis_product,
                     'unsupported_text_transform')
        if op in {'Tj', 'TJ'} and (not in_text or len(args) != 1 or
                not isinstance(args[0], pdf.Array if op == 'TJ' else pdf.String)):
            raise ValueError("invalid text-show operation")
        if op not in {'Tj', 'TJ'} or infos is None:
            result.append((op, tuple(reader.snapshot(v) for v in args)))
            continue
        if current not in infos:
            raise ValueError("text references an unknown font")
        info = infos[current]
        values = args[0] if op == 'TJ' else [args[0]]
        raw_text, advance = bytearray(), Decimal(0)
        codes = used.setdefault(current, set())
        for value in values:
            if not isinstance(value, pdf.String):
                advance -= _number(value)
                continue
            data = bytes(value)
            if len(data) % info.width:
                raise ValueError("truncated PDF character code")
            raw_text.extend(data)
            reader.char_count += len(data)//info.width
            _require(reader.char_count <= 1_000_000, 'character_count_limit')
            for i in range(0, len(data), info.width):
                code = int.from_bytes(data[i:i+info.width], 'big')
                _require(code in info.unicode, 'missing_unicode_mapping')
                if info.preserve:
                    _require(code == 32, 'unsupported_unembedded_font')
                codes.add(code)
                advance += info.widths.get(code, info.default)
        result.append(('text_show', current, bytes(raw_text), advance))
    if stack or in_text or marked_depth:
        raise ValueError("unbalanced content state")
    return result, used


def _outline(glyphs, name):
    pen = DecomposingRecordingPen(glyphs)
    glyphs[name].draw(pen)
    return pen.value


class _Fonts:
    def __init__(self, path: Path, budget: _Budget):
        self.budget = budget
        self.original = TTFont(path, fontNumber=0)
        self.cmap = self.original.getBestCmap()
        self.glyphs = self.original.getGlyphSet()
        self.loaded = {}
        self.verified = set()
        self.target_gids = {}

    def validate(self, source_font, target_font, source_info, sr, tr):
        self.budget.check()
        if source_info.preserve:
            _require(sr.snapshot(source_font) == tr.snapshot(target_font), 'preserved_font_mismatch')
            return source_info
        _require(target_font.get('/Subtype') == pdf.Name('/Type0') and len(target_font.DescendantFonts) == 1,
                 'replacement_font_type_mismatch')
        desc = target_font.DescendantFonts[0]
        _require(desc.get('/Subtype') == pdf.Name('/CIDFontType2') and '/W2' not in desc,
                 'replacement_cidfont_mismatch')
        if source_info.width == 2:
            _require(target_font.Encoding == pdf.Name('/Identity-H'), 'replacement_encoding_mismatch')
            _require(sr.decoded(source_font.ToUnicode) == tr.decoded(target_font.ToUnicode),
                     'tounicode_mismatch')
        else:
            encoding = tr.decoded(target_font.Encoding)
            _require(re.search(rb'/WMode\s+0\b', encoding) and
                     re.search(rb'1\s+begincodespacerange\s*<00>\s*<[fF][fF]>\s*endcodespacerange', encoding) and
                     re.search(rb'1\s+begincidrange\s*<00>\s*<[fF][fF]>\s+0\s*endcidrange', encoding),
                     'replacement_byte_encoding_mismatch')
            # Re-express the generated one-byte map as the supported two-byte map
            # for independent Unicode validation; only source ASCII codes are allowed.
            data = tr.decoded(target_font.ToUnicode)
            entries = {}
            for block in re.findall(rb'beginbfchar(.*?)endbfchar', data, re.S):
                for code, value in re.findall(rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', block):
                    entries[int(code, 16)] = bytes.fromhex(value.decode()).decode('utf-16-be')
            _require(all(entries.get(c) == chr(u) for c, u in source_info.unicode.items()
                         if source_info.widths.get(c, 0) > 0), 'replacement_ascii_unicode_mismatch')
        descriptor = desc.FontDescriptor
        stream = tr.decoded(descriptor.FontFile2)
        digest = hashlib.sha256(stream).digest()
        _require(int(descriptor.FontFile2.Length1) == len(stream), 'font_stream_length_mismatch')
        if digest not in self.loaded:
            _require(stream[:4] in {b'\x00\x01\x00\x00', b'true'}, 'font_program_type_mismatch')
            target = TTFont(io.BytesIO(stream))
            self.loaded[digest] = target
            _require('glyf' in target and 'fvar' not in target, 'font_program_type_mismatch')
            _require(target['head'].unitsPerEm == self.original['head'].unitsPerEm,
                     'font_units_mismatch')
            _require(target['OS/2'].fsType == self.original['OS/2'].fsType,
                     'font_embedding_flags_mismatch')
            _require(target['OS/2'].usWeightClass == self.original['OS/2'].usWeightClass,
                     'font_weight_mismatch')
            _require(all(getattr(target['hhea'], k) == getattr(self.original['hhea'], k)
                         for k in ('ascent', 'descent', 'lineGap')), 'font_vertical_metrics_mismatch')
        target = self.loaded[digest]
        name = target['name'].getDebugName(6)
        _require(all(re.sub(r'^/[A-Z]{6}\+', '', str(value)).lstrip('/') == name
                     for value in (target_font.BaseFont, desc.BaseFont, descriptor.FontName)),
                 'font_name_mismatch')
        mapping = tr.decoded(desc.CIDToGIDMap)
        if len(mapping) % 2:
            raise ValueError("invalid CIDToGIDMap length")
        default, widths = _widths(desc)
        target_order = target.getGlyphOrder()
        target_cmap = target.getBestCmap()
        target_glyphs = target.getGlyphSet()
        for code, unicode in source_info.unicode.items():
            if source_info.widths.get(code, source_info.default) <= 0:
                continue
            self.budget.check()
            _require(2*code+2 <= len(mapping), 'missing_gid_mapping')
            gid = int.from_bytes(mapping[2*code:2*code+2], 'big')
            _require(0 < gid < len(target_order), 'missing_glyph')
            _require(unicode in self.cmap and unicode in target_cmap, 'missing_font_unicode')
            glyph_name = target_order[gid]
            _require(glyph_name == target_cmap[unicode], 'glyph_unicode_mismatch')
            expected = math.floor(1000*target['hmtx'][glyph_name][0]/target['head'].unitsPerEm + 0.5)
            _require(widths.get(code, default) == expected, 'font_width_mismatch')
            marker = (digest, unicode)
            if marker not in self.verified:
                original_name = self.cmap[unicode]
                _require(target['hmtx'][glyph_name] == self.original['hmtx'][original_name],
                         'font_hmtx_mismatch')
                _require(_outline(target_glyphs, glyph_name) == _outline(self.glyphs, original_name),
                         'font_outline_mismatch')
                self.verified.add(marker)
            self.target_gids[gid] = unicode
        return _FontInfo(source_info.width, source_info.unicode, widths, default)

    def close(self):
        self.original.close()
        for font in self.loaded.values():
            font.close()


def _stable(value):
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items() if k not in {'xref', 'id'}}
    if isinstance(value, (list, tuple)):
        return tuple(_stable(v) for v in value)
    return value


def _traces(page):
    rows = []
    for span in page.get_texttrace():
        style = tuple(_stable(span.get(k)) for k in
                      ('dir', 'size', 'wmode', 'color', 'opacity', 'type', 'linewidth', 'seqno'))
        for char in span['chars']:
            rows.append((char[0], char[1], tuple(char[2]), style))
    return rows


def _render_pair(source, target, budget, lossless):
    scale = RENDER_DPI / 72
    for page in (source, target):
        expected = (page.rect * fitz.Matrix(scale, scale)).irect
        _require(expected.width*expected.height <= MAX_RENDER_PIXELS, 'render_pixel_limit')
    predicted = sum((p.rect * fitz.Matrix(scale, scale)).irect.width *
                    (p.rect * fitz.Matrix(scale, scale)).irect.height for p in (source, target))
    _require(budget.rendered_pixels+predicted <= MAX_TOTAL_RENDER_PIXELS, 'render_total_pixel_limit')
    budget.check()
    a = source.get_pixmap(dpi=RENDER_DPI, colorspace=fitz.csRGB, alpha=False)
    budget.check()
    b = target.get_pixmap(dpi=RENDER_DPI, colorspace=fitz.csRGB, alpha=False)
    budget.rendered_pixels += a.width*a.height + b.width*b.height
    _require(budget.rendered_pixels <= MAX_TOTAL_RENDER_PIXELS, 'render_total_pixel_limit')
    _require((a.width, a.height, a.n, a.stride) == (b.width, b.height, b.n, b.stride),
             'render_geometry_mismatch')
    if lossless:
        _require(a.samples == b.samples, 'lossless_render_mismatch')
    budget.check()


def validate_candidate(source: Path, candidate: Path, *, font_path: Path,
                       expected_font_sha256: str, deadline: float,
                       lossless: bool = False) -> ValidationSummary:
    """Validate one candidate; syntax/I/O failures deliberately propagate as errors."""
    budget = _Budget(min(deadline, time.monotonic()+300))
    budget.check()
    _require(source.stat().st_size <= MAX_FILE_BYTES and candidate.stat().st_size <= MAX_FILE_BYTES,
             'file_byte_limit')
    _require(font_path.stat().st_size <= MAX_FILE_BYTES, 'font_file_limit')
    if _sha(font_path, budget) != expected_font_sha256:
        raise RuntimeError("font input SHA-256 changed")
    fonts = None
    whitespace_changed = False
    try:
        with fitz.open(source) as sm, fitz.open(candidate) as tm, pdf.open(source) as sp, pdf.open(candidate) as tp:
            for doc in (sm, tm):
                if doc.is_repaired:
                    raise RuntimeError("font validation required PDF repair")
                _require(not doc.is_encrypted and not doc.needs_pass and doc.get_sigflags() <= 0,
                         'unsupported_protected_document')
                _require(not doc.get_ocgs() and not doc.is_form_pdf and not doc.embfile_names(),
                         'unsupported_document_features')
                _require(0 < doc.page_count <= MAX_PAGES, 'page_limit')
            _require(len(sm) == len(tm) == len(sp.pages) == len(tp.pages), 'page_count_mismatch')
            sr, tr = _Reader(sp, budget), _Reader(tp, budget)
            for obj in (sp.Root, tp.Root):
                _require(not any(k in obj for k in ('/Perms', '/AA', '/AF', '/Collection', '/Threads')),
                         'unsupported_catalog_features')
                form = obj.get('/AcroForm')
                if form is not None:
                    _require(isinstance(form, pdf.Dictionary), 'invalid_form')
                    fields = form.get('/Fields', pdf.Array())
                    _require(isinstance(fields, pdf.Array) and len(fields) == 0
                             and not (set(form.keys()) - {'/Fields', '/DR', '/DA', '/NeedAppearances'}),
                             'unsupported_form')
            sc = pdf.Dictionary({str(k): v for k, v in sp.Root.items() if str(k) != '/Pages'})
            tc = pdf.Dictionary({str(k): v for k, v in tp.Root.items() if str(k) != '/Pages'})
            _require(sr.snapshot(sc) == tr.snapshot(tc), 'catalog_mismatch')
            _require(sr.snapshot(sp.docinfo) == tr.snapshot(tp.docinfo), 'document_info_mismatch')
            # Object-stream compression can legitimately raise the PDF version.
            # MuPDF's format label describes that container, not document Info/XMP.
            metadata = lambda doc: {k: v for k, v in doc.metadata.items() if k != 'format'}
            _require(metadata(sm) == metadata(tm) and sm.get_xml_metadata() == tm.get_xml_metadata()
                     and _stable(sm.get_toc(simple=False)) == _stable(tm.get_toc(simple=False))
                     and _stable(sm.resolve_names()) == _stable(tm.resolve_names()), 'document_metadata_mismatch')
            if not lossless:
                fonts = _Fonts(font_path, budget)
            compared_fonts, compared_images = {}, set()
            for s, t, ms, mt in zip(sp.pages, tp.pages, sm, tm):
                budget.check()
                _guard_resources(s, sr); _guard_resources(t, tr)
                omitted = {'/Parent', '/Contents', '/Resources'}
                sprops = pdf.Dictionary({str(k): v for k, v in s.obj.items() if str(k) not in omitted})
                tprops = pdf.Dictionary({str(k): v for k, v in t.obj.items() if str(k) not in omitted})
                _require(sr.snapshot(sprops) == tr.snapshot(tprops), 'page_properties_mismatch')
                _require((ms.rotation, ms.mediabox, ms.cropbox, ms.rect) ==
                         (mt.rotation, mt.mediabox, mt.cropbox, mt.rect), 'page_geometry_mismatch')
                sresources = pdf.Dictionary({str(k): v for k, v in s.Resources.items()
                                            if lossless or str(k) != '/Font'})
                tresources = pdf.Dictionary({str(k): v for k, v in t.Resources.items()
                                            if lossless or str(k) != '/Font'})
                _require(sr.snapshot(sresources) == tr.snapshot(tresources), 'page_resources_mismatch')
                sf, tf = s.Resources.get('/Font', {}), t.Resources.get('/Font', {})
                _require(set(sf.keys()) == set(tf.keys()), 'font_resources_mismatch')
                si, ti = {}, {}
                for key, source_font in sf.items():
                    marker = (source_font.objgen, tf[key].objgen)
                    if marker not in compared_fonts:
                        _require(len(compared_fonts) < 256, 'font_count_limit')
                        old = _source_font(source_font, sr)
                        new = fonts.validate(source_font, tf[key], old, sr, tr) if fonts else old
                        compared_fonts[marker] = old, new
                    si[str(key)], ti[str(key)] = compared_fonts[marker]
                se, used = _content(s, sr, si)
                te, target_used = _content(t, tr, ti)
                _require(se == te and used == target_used, 'text_bytes_advance_or_operators_mismatch')
                for key, source_image in s.Resources.get('/XObject', {}).items():
                    target_image = t.Resources.XObject[key]
                    pair = (source_image.objgen[0], target_image.objgen[0])
                    if pair not in compared_images:
                        budget.check()
                        a, b = fitz.Pixmap(sm, pair[0]), fitz.Pixmap(tm, pair[1])
                        _require((a.width, a.height, a.n, a.alpha, a.stride) ==
                                 (b.width, b.height, b.n, b.alpha, b.stride) and a.samples == b.samples,
                                 'image_pixels_mismatch')
                        compared_images.add(pair)
                _require(_stable(ms.get_links()) == _stable(mt.get_links()), 'links_mismatch')
                _require(ms.get_drawings(extended=True) == mt.get_drawings(extended=True), 'paths_mismatch')
                placements = lambda page: [(i['bbox'], i['transform']) for i in page.get_image_info(xrefs=True)]
                _require(placements(ms) == placements(mt), 'image_placements_mismatch')
                a, b = _traces(ms), _traces(mt)
                _require(len(a) == len(b), 'glyph_count_mismatch')
                for old, new in zip(a, b):
                    _require(old[0] == new[0], 'glyph_unicode_mismatch')
                    _require(old[3] == new[3], 'glyph_style_or_order_mismatch')
                    _require(max(abs(x-y) for x, y in zip(old[2], new[2])) <= ORIGIN_TOLERANCE,
                             'glyph_origin_mismatch')
                    if fonts is not None and new[0] != 32:
                        _require(fonts.target_gids.get(new[1]) == new[0], 'rendered_gid_mismatch')
                original_text, new_text = ms.get_text(), mt.get_text()
                if original_text != new_text:
                    _require(''.join(original_text.split()) == ''.join(new_text.split()),
                             'extracted_nonwhitespace_mismatch')
                    whitespace_changed = True
                _render_pair(ms, mt, budget, lossless)
            if fonts is not None:
                _require(len(fonts.loaded) == 1, 'shared_font_count_mismatch')
            if _sha(font_path, budget) != expected_font_sha256:
                raise RuntimeError("font input SHA-256 changed during validation")
            budget.check()
            return ValidationSummary(whitespace_changed, len(sm), budget.rendered_pixels,
                                     len(fonts.verified) if fonts else 0)
    finally:
        if fonts is not None:
            fonts.close()
