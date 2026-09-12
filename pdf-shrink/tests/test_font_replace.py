"""Synthetic engine coverage independent of machine-installed fonts."""
from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
import time
import zlib

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
import pikepdf as pq
import pymupdf as fitz
import pytest

from pdf_shrink import font_replace as engine
from pdf_shrink.font_replace_parse import Budget, RECIPE, Unsupported, bounded_stream, cmap_entries
from pdf_shrink.lossless_jpeg import CandidateRejected


def font_data(*, fs_type=8, family="Yu Gothic"):
    builder = FontBuilder(2048, isTTF=True)
    order = [".notdef", "space", "A", "B", "uni5C71"]
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({32: "space", 65: "A", 66: "B", 0x5C71: "uni5C71"})
    glyphs = {}
    for name in order:
        pen = TTGlyphPen(None)
        if name != "space":
            pen.moveTo((40, 0)); pen.lineTo((450, 0)); pen.lineTo((450, 800))
            pen.lineTo((40, 800)); pen.closePath()
        glyphs[name] = pen.glyph()
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({name: (1139 if name in {"A", "B"} else 1024, 0) for name in order})
    builder.setupHorizontalHeader(ascent=1800, descent=-400)
    builder.setupNameTable({"familyName": family, "styleName": "Regular", "uniqueFontIdentifier": "synthetic",
                           "fullName": family + " Regular", "psName": family.replace(" ", "") + "-Regular"})
    builder.setupOS2(sTypoAscender=1800, sTypoDescender=-400, usWinAscent=1800,
                    usWinDescent=400, sCapHeight=800, fsType=fs_type)
    builder.setupPost()
    builder.setupMaxp()
    result = BytesIO()
    builder.save(result)
    return result.getvalue()


def make_pdf(path, *, extra=b"", text=b"<000200030004> Tj", mode=2,
             matrix=b"1 0 0 1 40 160", embedded=True, simple=False, unicode=0x5C71,
             mutate=None):
    with pq.new() as pdf:
        page = pdf.add_blank_page(page_size=(220, 220))
        descriptor = pq.Dictionary(Type=pq.Name.FontDescriptor, FontName=pq.Name.SourceArbitrary,
            Flags=4, FontBBox=pq.Array([0, -200, 1000, 900]), Ascent=900, Descent=-200,
            CapHeight=800, ItalicAngle=0, StemV=80)
        if embedded:
            program = font_data(family="Arbitrary Source")
            descriptor.FontFile2 = pdf.make_stream(program)
            descriptor.FontFile2.Length1 = len(program)
        descriptor = pdf.make_indirect(descriptor)
        if simple:
            widths = [500 if code in {32, 65, 66} else 0 for code in range(32, 67)]
            font = pq.Dictionary(Type=pq.Name.Font, Subtype=pq.Name.TrueType,
                BaseFont=pq.Name.UnlistedSource, Encoding=pq.Name.WinAnsiEncoding,
                FontDescriptor=descriptor, FirstChar=32, LastChar=66, Widths=pq.Array(widths))
        else:
            descendant = pdf.make_indirect(pq.Dictionary(Type=pq.Name.Font,
                Subtype=pq.Name.CIDFontType2, BaseFont=pq.Name.UnlistedSource,
                CIDSystemInfo=pq.Dictionary(Registry=pq.String("Adobe"), Ordering=pq.String("Identity"), Supplement=0),
                FontDescriptor=descriptor, CIDToGIDMap=pq.Name.Identity,
                DW=500, W=pq.Array([1, pq.Array([500, 500, 500, 500])])) )
            cmap = ("1 begincodespacerange <0000> <ffff> endcodespacerange\n"
                    f"4 beginbfchar <0001> <0020> <0002> <0041> <0003> <0042> <0004> <{unicode:04x}> endbfchar").encode()
            font = pq.Dictionary(Type=pq.Name.Font, Subtype=pq.Name.Type0,
                BaseFont=pq.Name.UnlistedSource, Encoding=pq.Name('/Identity-H'),
                DescendantFonts=pq.Array([descendant]), ToUnicode=pdf.make_stream(cmap))
        page.Resources = pq.Dictionary(Font=pq.Dictionary(F1=pdf.make_indirect(font)))
        page.Contents = pdf.make_stream(extra + b"\nq BT /F1 12 Tf 1 Tc 2 Tw 100 Tz "
            + str(mode).encode() + b" Tr " + matrix + b" Tm " + text + b" ET Q\n")
        if mutate:
            mutate(pdf, page, page.Resources.Font.F1)
        pdf.save(path)


@pytest.fixture
def inputs(tmp_path):
    font = tmp_path / "test-font.ttf"
    font.write_bytes(font_data())
    source = tmp_path / "source.pdf"
    make_pdf(source)
    return source, font, hashlib.sha256(font.read_bytes()).hexdigest()


def preflight(inputs):
    return engine.preflight(*inputs, time.monotonic() + 30)


def trace(path):
    with fitz.open(path) as document:
        return [[(char[0], char[2], span["type"], span["dir"], span["color"])
                 for span in page.get_texttrace() for char in span["chars"]] for page in document]


@pytest.mark.parametrize("simple,text,matrix", [
    (False, b"[<00020003> 50 <0004>] TJ", b"1 0 0 1 40 160"),
    (True, b"(A B) Tj", b"0.000000012 -1 1 0.000000012 40 160"),
])
def test_generate_preserves_atomic_stroke_order_origins_and_native_metrics(inputs, tmp_path, simple, text, matrix):
    source, font, sha = inputs
    make_pdf(source, simple=simple, text=text, matrix=matrix,
             extra=b"/Artifact << /Type /Pagination /Subtype /Header /Attached [/Top] >> BDC EMC\n/Span << /MCID 1 /Lang (ja-JP) >> BDC EMC")
    baseline = source.read_bytes()
    assert preflight(inputs) == ""
    target = tmp_path / "candidate.pdf"
    engine.generate(source, target, font, sha, time.monotonic() + 30)
    assert source.read_bytes() == baseline
    old, new = trace(source)[0], trace(target)[0]
    assert [item[0] for item in old] == [item[0] for item in new]
    assert [item[2:] for item in old] == [item[2:] for item in new]
    for a, b in zip(old, new):
        assert a[1] == pytest.approx(b[1], abs=0.02)
    with pq.open(source) as original, pq.open(target) as result:
        source_ops = list(pq.parse_content_stream(original.pages[0]))
        candidate_ops = list(pq.parse_content_stream(result.pages[0]))
        assert len(candidate_ops) == len(source_ops)
        assert [str(i.operator) for i in candidate_ops].count("TJ") == 1
        assert all(pq.unparse_content_stream([a]) == pq.unparse_content_stream([b])
                   for a, b in zip(source_ops, candidate_ops) if str(a.operator) not in {"Tj", "TJ"})
        descendant = result.pages[0].Resources.Font.F1.DescendantFonts[0]
        widths = list(descendant.W)
        assert all(isinstance(value[0], int) for value in widths[1::2])
        program = descendant.FontDescriptor.FontFile2.read_bytes()
        with TTFont(BytesIO(program)) as subset, TTFont(font) as installed:
            assert subset['OS/2'].fsType == installed['OS/2'].fsType == 8
            for unicode, glyph in subset.getBestCmap().items():
                original_glyph = installed.getBestCmap()[unicode]
                assert subset['hmtx'][glyph] == installed['hmtx'][original_glyph]
                assert subset['glyf'][glyph].getCoordinates(subset['glyf'])[0] == installed['glyf'][original_glyph].getCoordinates(installed['glyf'])[0]


@pytest.mark.parametrize("extra,reason", [
    (b"/Span << /ActualText (replacement) >> BDC EMC", "marked_content_properties"),
    (b"/OC BMC EMC", "optional_content"),
    (b"/Span /Props BDC EMC", "marked_content_properties"),
])
def test_sensitive_marked_content_protected(inputs, extra, reason):
    make_pdf(inputs[0], extra=extra)
    assert preflight(inputs) == "font_replace_" + reason


@pytest.mark.parametrize("extra", [b"EMC", b"/Span BMC", b"m", b"unknownoperator"])
def test_malformed_content_is_error_not_protection(inputs, extra):
    make_pdf(inputs[0], extra=extra)
    with pytest.raises(ValueError):
        preflight(inputs)


@pytest.mark.parametrize("mode,matrix,reason", [(4, b"1 0 0 1 0 0", "text_clipping"),
    (0, b"1 0.1 0 1 0 0", "transformed_text"), (0, b"-1 0 0 1 0 0", "transformed_text")])
def test_complex_text_protected(inputs, mode, matrix, reason):
    make_pdf(inputs[0], mode=mode, matrix=matrix)
    assert preflight(inputs) == "font_replace_" + reason


def test_missing_glyph_and_vertical_protected(inputs):
    make_pdf(inputs[0], unicode=0x5CB8)
    assert preflight(inputs) == "font_replace_missing_target_glyph"
    make_pdf(inputs[0], mutate=lambda pdf, page, font: setattr(font, "Encoding", pq.Name('/Identity-V')))
    assert preflight(inputs) == "font_replace_font_encoding"


def test_space_only_unembedded_is_preserved_with_embedded_text(inputs, tmp_path):
    def add_font(pdf, page, font):
        other = pdf.make_indirect(pq.Dictionary(Type=pq.Name.Font, Subtype=pq.Name.TrueType,
            BaseFont=pq.Name.AnotherUnlistedName, Encoding=pq.Name.WinAnsiEncoding,
            FirstChar=32, LastChar=32, Widths=pq.Array([250]),
            FontDescriptor=font.DescendantFonts[0].FontDescriptor))
        descriptor = pq.Dictionary(other.FontDescriptor)
        del descriptor.FontFile2
        other.FontDescriptor = pdf.make_indirect(descriptor)
        page.Resources.Font.F2 = other
        page.Contents = pdf.make_stream(page.Contents.read_bytes() + b"BT /F2 12 Tf ( ) Tj ET")
    make_pdf(inputs[0], mutate=add_font)
    assert preflight(inputs) == ""
    target = tmp_path / 'out.pdf'
    engine.generate(inputs[0], target, inputs[1], inputs[2], time.monotonic()+30)
    with pq.open(target) as result:
        assert result.pages[0].Resources.Font.F2.Subtype == pq.Name.TrueType


def test_corrupt_width_array_is_error(inputs):
    make_pdf(inputs[0], mutate=lambda pdf, page, font: setattr(font.DescendantFonts[0], "W", pq.Array([2])))
    with pytest.raises(ValueError, match="truncated CID widths"):
        preflight(inputs)


def test_limits_before_unbounded_decompression(tmp_path):
    with pq.new() as pdf:
        stream = pdf.make_stream(zlib.compress(b'x' * 100_000))
        stream.Filter = pq.Name.FlateDecode
        with pytest.raises(Unsupported, match="font_decoded_limit"):
            bounded_stream(stream, 4096, 1024, Budget(time.monotonic()+5), category='font')
        with pytest.raises(Unsupported, match="font_stream_limit"):
            bounded_stream(stream, 2, 200_000, Budget(time.monotonic()+5), category='font')
        broken = pdf.make_stream(b'not-zlib')
        broken.Filter = pq.Name.FlateDecode
        with pytest.raises(zlib.error):
            bounded_stream(broken, 100, 100, Budget(time.monotonic()+5), category='font')


def test_cmap_ranges_arrays_and_invalid_utf16():
    prefix = b'2 begincodespacerange <0000> <00ff> <0100> <ffff> endcodespacerange\n'
    mapping = cmap_entries(prefix + b'2 beginbfrange <0001> <0002> <0041> <0100> <0101> [<0020> <5c71>] endbfrange', Budget(time.monotonic()+5))
    assert mapping == {1:65, 2:66, 256:32, 257:0x5C71}
    with pytest.raises(ValueError, match='UTF-16'):
        cmap_entries(prefix + b'1 beginbfchar <0001> <d800> endbfchar', Budget(time.monotonic()+5))


def test_source_and_font_identity_failure_preserve_files(inputs, tmp_path, monkeypatch):
    source, font, sha = inputs
    baseline = source.read_bytes()
    with pytest.raises(ValueError, match='overwrite'):
        engine.generate(source, source, font, sha, time.monotonic()+30)
    with pytest.raises(ValueError, match='SHA-256'):
        engine.preflight(source, font, '0'*64, time.monotonic()+30)
    target = tmp_path/'out.pdf'
    target.write_bytes(b'keep')
    with pytest.raises(FileExistsError):
        engine.generate(source, target, font, sha, time.monotonic()+30)
    assert target.read_bytes() == b'keep' and source.read_bytes() == baseline
    assert engine.preflight(source, font, sha, time.monotonic()-1) == 'font_replace_time_limit'
    with pytest.raises(CandidateRejected):
        engine.generate(source, tmp_path/'late.pdf', font, sha, time.monotonic()-1)
    assert not list(tmp_path.glob('.font-replace-*'))


def test_embedding_permission_mismatch_is_error(inputs):
    source, font, _ = inputs
    font.write_bytes(font_data(fs_type=2))
    sha = hashlib.sha256(font.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='embedding permissions'):
        engine.preflight(source, font, sha, time.monotonic()+30)


@pytest.mark.parametrize('feature,reason', [('annotation', 'annotations'), ('ocg', 'optional_content'),
    ('action', 'catalog_structure'), ('form', 'form_or_nonimage_xobject')])
def test_protected_document_features(inputs, feature, reason):
    def change(pdf, page, font):
        if feature == 'annotation':
            page.Annots = pq.Array([pdf.make_indirect(pq.Dictionary(Type=pq.Name.Annot, Subtype=pq.Name.Text,
                Rect=pq.Array([0,0,10,10])))])
        elif feature == 'ocg':
            pdf.Root.OCProperties = pq.Dictionary()
        elif feature == 'action':
            pdf.Root.AA = pq.Dictionary()
        else:
            form = pdf.make_stream(b'')
            form.Subtype = pq.Name.Form
            form.BBox = pq.Array([0, 0, 10, 10])
            page.Resources.XObject = pq.Dictionary(X1=form)
    make_pdf(inputs[0], mutate=change)
    assert preflight(inputs) == 'font_replace_' + reason


def test_image_streams_are_preserved_exactly(inputs, tmp_path):
    pixels = bytes(range(27))
    def add_image(pdf, page, font):
        image = pdf.make_stream(zlib.compress(pixels))
        image.Type, image.Subtype = pq.Name.XObject, pq.Name.Image
        image.Filter = pq.Name.FlateDecode
        image.Width, image.Height, image.BitsPerComponent = 3, 3, 8
        image.ColorSpace = pq.Name.DeviceRGB
        page.Resources.XObject = pq.Dictionary(I1=image)
        page.Contents = pdf.make_stream(page.Contents.read_bytes() + b' q 10 0 0 10 0 0 cm /I1 Do Q')
    make_pdf(inputs[0], mutate=add_image)
    assert preflight(inputs) == ''
    candidate = tmp_path / 'images.pdf'
    engine.generate(inputs[0], candidate, inputs[1], inputs[2], time.monotonic()+30)
    with pq.open(inputs[0]) as source, pq.open(candidate) as result:
        a, b = source.pages[0].Resources.XObject.I1, result.pages[0].Resources.XObject.I1
        assert a.read_raw_bytes() == b.read_raw_bytes()
        assert a.read_bytes() == b.read_bytes() == pixels
        assert a.stream_dict == b.stream_dict


def test_source_and_content_limits_protect(inputs, monkeypatch):
    monkeypatch.setitem(RECIPE, 'source_bytes', 1)
    assert preflight(inputs) == 'font_replace_source_size_limit'
    monkeypatch.setitem(RECIPE, 'source_bytes', 128 * 1024**2)
    monkeypatch.setitem(RECIPE, 'content_bytes', 20)
    assert preflight(inputs).endswith('_stream_limit')


def test_failed_publication_does_not_leave_partial_output(inputs, tmp_path, monkeypatch):
    def fail(*args):
        raise OSError('simulated publication failure')
    monkeypatch.setattr(engine.os, 'replace', fail)
    target = tmp_path / 'out.pdf'
    original = inputs[0].read_bytes()
    with pytest.raises(OSError, match='publication'):
        engine.generate(inputs[0], target, inputs[1], inputs[2], time.monotonic()+30)
    assert not target.exists() and not list(tmp_path.glob('.font-replace-*'))
    assert inputs[0].read_bytes() == original


def test_mapping_expansion_budget_is_cumulative_and_checked_during_range(monkeypatch):
    monkeypatch.setitem(RECIPE, 'mapping_count', 4)
    data = b'1 begincodespacerange <0000> <ffff> endcodespacerange 1 beginbfrange <0001> <0003> <0041> endbfrange'
    budget = Budget(time.monotonic()+5)
    assert len(cmap_entries(data, budget)) == 3
    with pytest.raises(Unsupported, match='mapping_count_limit'):
        cmap_entries(data, budget)
    assert budget.mappings == 5


def test_unused_complex_graphics_state_is_preflight_protected(inputs):
    def add_state(pdf, page, font):
        page.Resources.ExtGState = pq.Dictionary(Unused=pq.Dictionary(SMask=pq.Name.None_))
    make_pdf(inputs[0], mutate=add_state)
    assert preflight(inputs) == 'font_replace_graphics_state'


@pytest.mark.parametrize('simple,text,matrix', [
    (False, b'<000200030004> Tj', b'1 0 0 1 40 160'),
    (True, b'(A B) Tj', b'0.000000012 -1 1 0.000000012 40 160'),
])
def test_generated_output_passes_independent_validator(inputs, tmp_path, simple, text, matrix):
    from pdf_shrink.font_validate import validate_candidate

    source, font, sha = inputs
    make_pdf(source, simple=simple, text=text, matrix=matrix,
             extra=b'/Artifact BMC EMC /Span << /MCID 3 /Lang (en-US) >> BDC EMC')
    assert preflight(inputs) == ''
    candidate = tmp_path / 'generated.pdf'
    deadline = time.monotonic() + 30
    engine.generate(source, candidate, font, sha, deadline)
    summary = validate_candidate(source, candidate, font_path=font,
        expected_font_sha256=sha, deadline=deadline)
    assert summary.page_count == 1
    assert summary.validated_glyph_count == (3 if simple else 4)
    assert summary.rendered_pixels == 220 * 220 * 4 * 2
