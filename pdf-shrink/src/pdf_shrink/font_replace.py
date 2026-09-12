"""Explicit, bounded replacement with an installed Windows regular font subset.

Typeface and natural ink widths change. Text-show boundaries and glyph origins
are preserved by integer PDF widths and matching TJ advance corrections. This
module produces an intermediate; independent validation and qpdf are callers'
responsibility. No image stream is edited.
"""
from __future__ import annotations

from decimal import Decimal, localcontext
import hashlib
import io
import os
from pathlib import Path
import tempfile

from fontTools import subset
from fontTools.ttLib import TTFont
import pikepdf as pq

from .font_replace_parse import (
    RECIPE, Analysis, Budget, Unsupported, analyze, font_key, number, protect,
)
from .lossless_jpeg import CandidateRejected


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _font_bytes(path: Path, expected_sha: str | None = None) -> tuple[bytes, str]:
    if not path.is_file():
        raise FileNotFoundError(f"Windows replacement font is unavailable: {path}")
    if path.stat().st_size > RECIPE["decoded_font_bytes"]:
        raise ValueError("installed font exceeds size limit")
    with path.open("rb") as stream:
        data = stream.read(RECIPE["decoded_font_bytes"] + 1)
    if len(data) > RECIPE["decoded_font_bytes"]:
        raise ValueError("installed font exceeds size limit")
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha is not None and digest != expected_sha:
        raise ValueError("installed Windows font SHA-256 changed")
    return data, digest


def _open_font(data: bytes) -> TTFont:
    font = TTFont(io.BytesIO(data), fontNumber=RECIPE["font_face"], recalcTimestamp=False)
    try:
        if (font["name"].getDebugName(1) not in {"Yu Gothic", "Meiryo"}
                or font["name"].getDebugName(2) != "Regular"):
            raise ValueError("expected Windows Yu Gothic or Meiryo Regular face 0")
        if font["OS/2"].fsType != RECIPE["font_fs_type"]:
            raise ValueError("installed font embedding permissions differ from the recipe")
        if "glyf" not in font or "hmtx" not in font or "fvar" in font:
            raise ValueError("installed font is not a supported static TrueType face")
        if not 16 <= font["head"].unitsPerEm <= 16384:
            raise ValueError("invalid installed font unitsPerEm")
        if not font.getBestCmap():
            raise ValueError("installed font has no Unicode cmap")
        return font
    except BaseException:
        font.close()
        raise


def prepare_font(family: str = "meiryo") -> tuple[Path, str]:
    """Locate and verify the local Windows face; never download a font."""
    filename, expected = {"yu-gothic": ("YuGothR.ttc", "Yu Gothic"),
                          "meiryo": ("meiryo.ttc", "Meiryo")}[family]
    path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filename
    data, digest = _font_bytes(path)
    with _open_font(data) as font:
        if font["name"].getDebugName(1) != expected:
            raise ValueError("installed font does not match the selected family")
    return path, digest


def _check_coverage(analysis: Analysis, font: TTFont) -> None:
    cmap = font.getBestCmap()
    if not analysis.unicode <= cmap.keys():
        protect("missing_target_glyph")
    if any(font.getGlyphID(cmap[u]) == 0 or font["hmtx"][cmap[u]][0] <= 0
           for u in analysis.unicode):
        protect("missing_or_zero_width_target_glyph")


def preflight(source: Path, font_path: Path, expected_sha: str, deadline: float) -> str:
    """Return a protection reason only for documented unsupported boundaries."""
    data, _ = _font_bytes(font_path, expected_sha)
    try:
        budget = Budget(deadline)
        budget.check()
        if source.stat().st_size > RECIPE["source_bytes"]:
            protect("source_size_limit")
        with _open_font(data) as font, pq.open(source, attempt_recovery=False) as pdf:
            analysis = analyze(pdf, source, budget)
            _check_coverage(analysis, font)
            budget.check()
        return ""
    except Unsupported as exc:
        return str(exc)


def _one_byte_cmap() -> bytes:
    return b"""/CIDInit /ProcSet findresource begin
12 dict begin begincmap
/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> def
/CMapName /KaruFileASCII def /CMapType 1 def /WMode 0 def
1 begincodespacerange <00> <ff> endcodespacerange
1 begincidrange <00> <ff> 0 endcidrange
endcmap CMapName currentdict /CMap defineresource pop end end
"""


def _ascii_tounicode(mapping: dict[int, int]) -> bytes:
    lines = ["/CIDInit /ProcSet findresource begin", "12 dict begin begincmap",
             "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
             "/CMapName /KaruFileASCIIUnicode def /CMapType 2 def",
             "1 begincodespacerange <00> <ff> endcodespacerange"]
    items = sorted(mapping.items())
    for offset in range(0, len(items), 100):
        block = items[offset:offset + 100]
        lines.append(f"{len(block)} beginbfchar")
        lines.extend(f"<{cid:02x}> <{unicode:04x}>" for cid, unicode in block)
        lines.append("endbfchar")
    lines.append("endcmap CMapName currentdict /CMap defineresource pop end end")
    return ("\n".join(lines) + "\n").encode("ascii")


def _subset_font(font: TTFont, unicode: set[int], budget: Budget) -> bytes:
    budget.check()
    options = subset.Options()
    options.hinting = True
    options.layout_features = []
    options.name_IDs = ["*"]
    options.name_legacy = True
    options.name_languages = ["*"]
    options.recalc_timestamp = False
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes=unicode)
    subsetter.subset(font)
    budget.check()
    if font["OS/2"].fsType != RECIPE["font_fs_type"]:
        raise ValueError("subsetting altered font embedding permissions")
    buffer = io.BytesIO()
    font.save(buffer)
    result = buffer.getvalue()
    if len(result) > RECIPE["decoded_font_bytes"]:
        protect("font_decoded_limit")
    return result


def _rewrite_text(pdf, analysis: Analysis, natural: dict[int, int], budget: Budget) -> None:
    total_bytes = 0
    for record in analysis.pages:
        budget.check()
        current = None
        stack = []
        result = []
        for instruction in record.instructions:
            budget.check()
            op, args = str(instruction.operator), list(instruction.operands)
            if op == "q":
                stack.append(current)
            elif op == "Q":
                current = stack.pop()
            elif op == "Tf":
                current = font_key(record.resources.Font[args[0]])
            font = analysis.fonts.get(current)
            if op not in {"Tj", "TJ"} or font is None or font.preserve:
                result.append(instruction)
                continue
            values = args[0] if op == "TJ" else [args[0]]
            adjusted = []
            pending = bytearray()

            def flush() -> None:
                if pending:
                    adjusted.append(pq.String(bytes(pending)))
                    pending.clear()

            for value in values:
                if not isinstance(value, pq.String):
                    flush()
                    adjusted.append(value)
                    continue
                data = bytes(value)
                n = font.byte_count
                for offset in range(0, len(data), n):
                    raw = data[offset:offset + n]
                    cid = int.from_bytes(raw, "big")
                    pending.extend(raw)
                    correction = Decimal(natural[font.mapping[cid]]) - font.widths[cid]
                    if correction:
                        flush()
                        adjusted.append(correction)
            flush()
            result.append(pq.ContentStreamInstruction([pq.Array(adjusted)], pq.Operator("TJ")))
        encoded = pq.unparse_content_stream(result)
        total_bytes += len(encoded)
        if total_bytes > RECIPE["content_bytes"]:
            protect("generated_content_limit")
        record.page.Contents = pdf.make_stream(encoded)


def _install_font(pdf, analysis: Analysis, data: bytes, budget: Budget) -> dict[int, int]:
    with TTFont(io.BytesIO(data), recalcTimestamp=False) as font:
        cmap = font.getBestCmap()
        upem = font["head"].unitsPerEm
        gids = {u: font.getGlyphID(cmap[u]) for u in analysis.unicode}
        natural = {u: (font["hmtx"][cmap[u]][0] * 1000 + upem // 2) // upem
                   for u in analysis.unicode}
        if any(gid <= 0 for gid in gids.values()) or any(w <= 0 for w in natural.values()):
            raise ValueError("subset lost a required glyph or advance")
        name = pq.Name("/KFYUGO+" + font["name"].getDebugName(6))
        stream = pdf.make_stream(data)
        stream.Length1 = len(data)

        def units(value):
            return Decimal(value) * 1000 / upem

        descriptor = pdf.make_indirect(pq.Dictionary(
            Type=pq.Name.FontDescriptor, FontName=name, Flags=4,
            FontBBox=pq.Array([units(getattr(font["head"], key))
                               for key in ("xMin", "yMin", "xMax", "yMax")]),
            ItalicAngle=number(font["post"].italicAngle),
            Ascent=units(font["hhea"].ascent), Descent=units(font["hhea"].descent),
            CapHeight=units(font["OS/2"].sCapHeight), StemV=80,
            FontWeight=font["OS/2"].usWeightClass, FontFile2=stream))
        ascii_encoding = None
        for record in analysis.fonts.values():
            budget.check()
            if record.preserve:
                continue
            mapping = bytearray((max(record.mapping) + 1) * 2)
            widths = pq.Array()
            for cid, unicode in sorted(record.mapping.items()):
                mapping[cid * 2:cid * 2 + 2] = gids[unicode].to_bytes(2, "big")
                widths.extend([cid, pq.Array([natural[unicode]])])
            descendant = pdf.make_indirect(pq.Dictionary(
                Type=pq.Name.Font, Subtype=pq.Name.CIDFontType2, BaseFont=name,
                CIDSystemInfo=pq.Dictionary(Registry=pq.String("Adobe"),
                    Ordering=pq.String("Identity"), Supplement=0),
                FontDescriptor=descriptor, DW=1000, W=widths,
                CIDToGIDMap=pdf.make_stream(bytes(mapping))))
            encoding, tounicode = record.encoding, record.tounicode
            if record.byte_count == 1:
                if ascii_encoding is None:
                    ascii_encoding = pdf.make_stream(_one_byte_cmap())
                encoding = ascii_encoding
                tounicode = pdf.make_stream(_ascii_tounicode(record.mapping))
            for key in list(record.font.keys()):
                del record.font[key]
            record.font.Type = pq.Name.Font
            record.font.Subtype = pq.Name.Type0
            record.font.BaseFont = name
            record.font.DescendantFonts = pq.Array([descendant])
            record.font.Encoding = encoding
            record.font.ToUnicode = tounicode
        return natural


def generate(source: Path, target: Path, font_path: Path, expected_sha: str,
             deadline: float) -> None:
    """Atomically write one intermediate to a new destination, preserving inputs."""
    if source.resolve() == target.resolve() or (target.exists() and os.path.samefile(source, target)):
        raise ValueError("font replacement cannot overwrite its input")
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    data, _ = _font_bytes(font_path, expected_sha)
    temporary: Path | None = None
    try:
        budget = Budget(deadline)
        budget.check()
        if source.stat().st_size > RECIPE["source_bytes"]:
            protect("source_size_limit")
        source_sha = _sha(source)
        with localcontext() as context:
            context.prec = 36
            with _open_font(data) as font, pq.open(source, attempt_recovery=False) as pdf:
                analysis = analyze(pdf, source, budget)
                _check_coverage(analysis, font)
                subset_data = _subset_font(font, analysis.unicode, budget)
                natural = _install_font(pdf, analysis, subset_data, budget)
                _rewrite_text(pdf, analysis, natural, budget)
                budget.check()
                with tempfile.NamedTemporaryFile(prefix=".font-replace-", suffix=".pdf",
                                                 dir=target.parent, delete=False) as temporary_file:
                    temporary = Path(temporary_file.name)
                pdf.save(temporary, object_stream_mode=pq.ObjectStreamMode.generate, fix_metadata_version=False,
                         compress_streams=True, recompress_flate=False)
                if pdf.get_warnings():
                    raise ValueError("PDF structural warnings during font generation")
        budget.check()
        if _sha(source) != source_sha or _sha(font_path) != expected_sha:
            raise ValueError("source PDF or installed font changed during generation")
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        os.replace(temporary, target)
        temporary = None
    except Unsupported as exc:
        raise CandidateRejected(str(exc)) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
