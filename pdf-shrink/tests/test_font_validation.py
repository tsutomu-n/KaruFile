"""Real font/PDF fixtures exercise independent validation and failure boundaries."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
import time
import zlib

import pikepdf as pdf
import pymupdf as fitz
import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from pdf_shrink import font_validate as validation
from pdf_shrink.lossless_jpeg import CandidateRejected


def _font(path):
    builder = FontBuilder(2048, isTTF=True)
    order = ['.notdef', 'A', 'B', 'space']
    builder.setupGlyphOrder(order)
    glyphs = {}
    for name in order:
        pen = TTGlyphPen(None)
        if name not in {'.notdef', 'space'}:
            pen.moveTo((100, 0)); pen.lineTo((800, 0))
            pen.lineTo((800, 1400 if name == 'A' else 1000))
            pen.lineTo((100, 1400 if name == 'A' else 1000)); pen.closePath()
        glyphs[name] = pen.glyph()
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({'.notdef': (1024, 0), 'A': (1024, 100),
                                    'B': (1536, 100), 'space': (512, 0)})
    builder.setupHorizontalHeader(ascent=1600, descent=-400)
    builder.setupCharacterMap({65: 'A', 66: 'B', 32: 'space'})
    builder.setupNameTable({'familyName': 'Validation Font', 'styleName': 'Regular',
                           'uniqueFontIdentifier': 'ValidationFont', 'fullName': 'Validation Font',
                           'psName': 'ValidationFont', 'version': 'Version 1.000'})
    builder.setupOS2(sTypoAscender=1600, sTypoDescender=-400, usWinAscent=1600,
                    usWinDescent=400, fsType=8, usWeightClass=400, sCapHeight=1400)
    builder.setupPost(); builder.setupMaxp()
    builder.save(path)


def _pdf(path, font):
    with pdf.Pdf.new() as document:
        page = document.add_blank_page(page_size=(180, 120))
        ff = document.make_stream(font.read_bytes())
        ff.Length1 = font.stat().st_size
        descriptor = document.make_indirect(pdf.Dictionary(
            Type=pdf.Name.FontDescriptor, FontName=pdf.Name('/ValidationFont'), Flags=4,
            FontBBox=pdf.Array([0, -200, 1000, 800]), ItalicAngle=0, Ascent=800,
            Descent=-200, CapHeight=700, StemV=80, FontFile2=ff))
        descendant = document.make_indirect(pdf.Dictionary(
            Type=pdf.Name.Font, Subtype=pdf.Name.CIDFontType2, BaseFont=pdf.Name('/ValidationFont'),
            CIDSystemInfo=pdf.Dictionary(Registry=pdf.String('Adobe'), Ordering=pdf.String('Identity'), Supplement=0),
            FontDescriptor=descriptor, DW=1000, W=pdf.Array([1, pdf.Array([500, 750, 250])]),
            CIDToGIDMap=pdf.Name.Identity))
        cmap = document.make_stream(b'''/CIDInit /ProcSet findresource begin
12 dict begin begincmap /CMapType 2 def
1 begincodespacerange <0000> <FFFF> endcodespacerange
3 beginbfchar <0001> <0041> <0002> <0042> <0003> <0020> endbfchar
endcmap end end''')
        font_obj = document.make_indirect(pdf.Dictionary(
            Type=pdf.Name.Font, Subtype=pdf.Name.Type0, BaseFont=pdf.Name('/ValidationFont'),
            Encoding=pdf.Name('/Identity-H'), DescendantFonts=pdf.Array([descendant]), ToUnicode=cmap))
        page.Resources = pdf.Dictionary(Font=pdf.Dictionary(F1=font_obj))
        page.Contents = document.make_stream(b'BT /F1 12 Tf 1 0 0 1 10 80 Tm <0001000200030001> Tj ET')
        document.save(path)


@pytest.fixture
def case(tmp_path):
    font, source, candidate = tmp_path/'font.ttf', tmp_path/'source.pdf', tmp_path/'candidate.pdf'
    _font(font); _pdf(source, font)
    with pdf.open(source) as document:
        descendant = document.pages[0].Resources.Font.F1.DescendantFonts[0]
        descendant.CIDToGIDMap = document.make_stream(b'\0\0\0\1\0\2\0\3')
        document.save(candidate)
    return source, candidate, font


def _validate(case, **kwargs):
    source, candidate, font = case
    return validation.validate_candidate(source, candidate, font_path=font,
                                         expected_font_sha256=hashlib.sha256(font.read_bytes()).hexdigest(),
                                         deadline=time.monotonic()+30, **kwargs)


def _edit(path, callback):
    replacement = path.with_suffix('.edited.pdf')
    with pdf.open(path) as document:
        callback(document)
        document.save(replacement)
    replacement.replace(path)


def test_actual_embedded_font_and_text_pass(case):
    summary = _validate(case)
    assert summary.page_count == 1 and summary.validated_glyph_count == 3
    assert summary.rendered_pixels == 180*120*4*2
    assert summary.extraction_whitespace_changed is False


@pytest.mark.parametrize('mutation,reason', [
    ('glyph', 'glyph_unicode_mismatch'), ('zero', 'missing_glyph'),
    ('width', 'font_width_mismatch'), ('unicode', 'tounicode_mismatch'),
])
def test_glyph_mapping_width_and_unicode_corruption_rejected(case, mutation, reason):
    def change(document):
        font = document.pages[0].Resources.Font.F1
        desc = font.DescendantFonts[0]
        if mutation == 'glyph':
            desc.CIDToGIDMap = document.make_stream(b'\0\0\0\2\0\2\0\3')
        elif mutation == 'zero':
            desc.CIDToGIDMap = document.make_stream(b'\0\0\0\0\0\2\0\3')
        elif mutation == 'width':
            desc.W = pdf.Array([1, pdf.Array([499, 750, 250])])
        else:
            font.ToUnicode = document.make_stream(font.ToUnicode.read_bytes().replace(b'<0041>', b'<0042>'))
    _edit(case[1], change)
    with pytest.raises(CandidateRejected, match=reason):
        _validate(case)


@pytest.mark.parametrize('mutation,reason', [('outline', 'font_outline_mismatch'),
                                           ('hmtx', 'font_hmtx_mismatch'),
                                           ('license', 'font_embedding_flags_mismatch')])
def test_font_program_changes_rejected_even_when_text_mapping_survives(case, mutation, reason):
    def change(document):
        stream = document.pages[0].Resources.Font.F1.DescendantFonts[0].FontDescriptor.FontFile2
        font = TTFont(io.BytesIO(stream.read_bytes()))
        if mutation == 'outline':
            glyph = font['glyf']['A']
            glyph.coordinates[0] = (glyph.coordinates[0][0]+1, glyph.coordinates[0][1])
        elif mutation == 'hmtx':
            advance, bearing = font['hmtx']['A']
            font['hmtx']['A'] = advance, bearing+1
        else:
            font['OS/2'].fsType = 2
        buffer = io.BytesIO(); font.save(buffer)
        stream.write(buffer.getvalue()); stream.Length1 = len(buffer.getvalue())
    _edit(case[1], change)
    with pytest.raises(CandidateRejected, match=reason):
        _validate(case)


@pytest.mark.parametrize('replacement', [
    b'BT /F1 12 Tf 1 0 0 1 10 80 Tm <000100020001> Tj ET',
    b'BT /F1 12 Tf 1 0 0 1 10 80 Tm [<0001000200030001> 1] TJ ET',
    b'BT /F1 12 Tf 1 0 0 1 11 80 Tm <0001000200030001> Tj ET',
    b'0.5 g BT /F1 12 Tf 1 0 0 1 10 80 Tm <0001000200030001> Tj ET',
])
def test_space_loss_advance_position_and_paint_operator_changes_rejected(case, replacement):
    _edit(case[1], lambda d: setattr(d.pages[0], 'Contents', d.make_stream(replacement)))
    with pytest.raises(CandidateRejected, match='text_bytes_advance_or_operators_mismatch'):
        _validate(case)


def test_unsupported_annotation_is_not_silently_ignored(case):
    _edit(case[1], lambda d: setattr(d.pages[0], 'Annots', pdf.Array([
        d.make_indirect(pdf.Dictionary(Type=pdf.Name.Annot, Subtype=pdf.Name.Text,
                                      Rect=pdf.Array([10, 10, 20, 20])))])))
    with pytest.raises(CandidateRejected, match='unsupported_annotations'):
        _validate(case)


def test_unknown_font_input_hash_is_processing_error(case):
    with pytest.raises(RuntimeError, match='SHA-256 changed'):
        validation.validate_candidate(case[0], case[1], font_path=case[2],
                                      expected_font_sha256='0'*64, deadline=time.monotonic()+30)


@pytest.mark.parametrize('lossless', [False, True])
def test_font_input_change_during_validation_is_error_even_for_qpdf_fallback(case, monkeypatch, lossless):
    if lossless:
        case[1].write_bytes(case[0].read_bytes())
    original = validation._render_pair
    def change_font_after_render(*args, **kwargs):
        original(*args, **kwargs)
        case[2].write_bytes(case[2].read_bytes()+b'\0')
    monkeypatch.setattr(validation, '_render_pair', change_font_after_render)
    with pytest.raises(RuntimeError, match='SHA-256 changed during validation'):
        _validate(case, lossless=lossless)


def test_expired_budget_checks_before_reading_files(tmp_path):
    with pytest.raises(CandidateRejected, match='time_limit'):
        validation.validate_candidate(tmp_path/'missing.pdf', tmp_path/'other.pdf',
                                      font_path=tmp_path/'font.ttf', expected_font_sha256='', deadline=0)


def test_lossless_candidate_requires_exact_render(case, monkeypatch):
    source, candidate, font = case
    candidate.write_bytes(source.read_bytes())
    assert _validate(case, lossless=True).validated_glyph_count == 0
    original = fitz.Page.get_pixmap
    def changed_render(page, *args, **kwargs):
        pix = original(page, *args, **kwargs)
        if Path(page.parent.name).resolve() == candidate.resolve():
            pix.clear_with(0)
        return pix
    monkeypatch.setattr(fitz.Page, 'get_pixmap', changed_render)
    with pytest.raises(CandidateRejected, match='lossless_render_mismatch'):
        _validate(case, lossless=True)


def test_render_and_cumulative_pixel_limits_precede_render(case, monkeypatch):
    monkeypatch.setattr(validation, 'MAX_RENDER_PIXELS', 1)
    with pytest.raises(CandidateRejected, match='render_pixel_limit'):
        _validate(case)
    monkeypatch.setattr(validation, 'MAX_RENDER_PIXELS', 1_000_000)
    monkeypatch.setattr(validation, 'MAX_TOTAL_RENDER_PIXELS', 1)
    with pytest.raises(CandidateRejected, match='render_total_pixel_limit'):
        _validate(case)


def test_flate_expansion_is_bounded_before_image_decode(case, monkeypatch):
    monkeypatch.setattr(validation, 'MAX_STREAM_BYTES', 16_384)
    def add_bomb(document):
        stream = document.make_stream(zlib.compress(b'A'*32_768))
        stream.Type = pdf.Name.XObject; stream.Subtype = pdf.Name.Image
        stream.Width = 1; stream.Height = 1; stream.BitsPerComponent = 8
        stream.ColorSpace = pdf.Name.DeviceGray; stream.Filter = pdf.Name.FlateDecode
        document.pages[0].Resources.XObject = pdf.Dictionary(I1=stream)
    _edit(case[0], add_bomb)
    with pytest.raises(CandidateRejected, match='stream_decoded_limit'):
        _validate(case)


def test_invalid_flate_data_is_not_mislabeled_quality_rejection(case):
    def corrupt(document):
        stream = document.make_stream(b'not zlib')
        stream.Filter = pdf.Name.FlateDecode
        document.pages[0].Contents = stream
    _edit(case[1], corrupt)
    with pytest.raises(zlib.error):
        _validate(case)


def test_lossless_legacy_cp932_pdf_font_names_compare_as_bytes(case):
    def rename(document):
        font = document.pages[0].Resources.Font.F1
        legacy = pdf.Object.parse(b'/#82#A0')
        font.BaseFont = legacy
        font.DescendantFonts[0].BaseFont = legacy
        font.DescendantFonts[0].FontDescriptor.FontName = legacy
    _edit(case[0], rename)
    case[1].write_bytes(case[0].read_bytes())
    assert _validate(case, lossless=True).page_count == 1


def test_passive_marked_content_rotated_text_and_multiple_codespaces_pass(case):
    def change(document):
        page = document.pages[0]
        raw = page.Contents.read_bytes().replace(b'1 0 0 1 10 80 Tm', b'0 -1 1 0 10 80 Tm')
        page.Contents = document.make_stream(
            b'/Artifact <</Type/Pagination /Subtype/Header /Attached[/Top]>> BDC '
            b'/Span <</MCID 0 /Lang (ja-JP)>> BDC ' + raw + b' EMC EMC')
        font = page.Resources.Font.F1
        font.ToUnicode = document.make_stream(font.ToUnicode.read_bytes().replace(
            b'1 begincodespacerange <0000> <FFFF>',
            b'2 begincodespacerange <0000> <0002> <0003> <FFFF>'))
    _edit(case[0], change); _edit(case[1], change)
    assert _validate(case).validated_glyph_count == 3


@pytest.mark.parametrize('wrapper,reason', [
    (b'/Span <</ActualText (A)>> BDC %s EMC', 'unsupported_marked_content'),
    (b'/OC BMC %s EMC', 'unsupported_optional_content'),
    (b'/Span BMC %s', 'unbalanced content state'),
])
def test_unexamined_or_unbalanced_marked_content_cannot_pass(case, wrapper, reason):
    def change(document):
        page = document.pages[0]
        page.Contents = document.make_stream(wrapper % page.Contents.read_bytes())
    _edit(case[0], change); _edit(case[1], change)
    with pytest.raises((CandidateRejected, ValueError), match=reason):
        _validate(case)


@pytest.mark.parametrize('matrix', [b'1 1 0 1', b'-1 0 0 1'])
def test_skewed_or_mirrored_text_remains_unsupported(case, matrix):
    def change(document):
        page = document.pages[0]
        page.Contents = document.make_stream(page.Contents.read_bytes().replace(b'1 0 0 1', matrix))
    _edit(case[0], change); _edit(case[1], change)
    with pytest.raises(CandidateRejected, match='unsupported_text_transform'):
        _validate(case)


def test_jpeg_header_dimension_mismatch_rejected_before_native_decode(case, monkeypatch):
    def add_image(document):
        # A complete SOF0 header declaring 100 x 100 grayscale, while PDF says 1 x 1.
        data = bytes.fromhex('ffd8 ffc0 000b 08 0064 0064 01 01 1100 ffd9')
        stream = document.make_stream(data)
        stream.Type = pdf.Name.XObject; stream.Subtype = pdf.Name.Image
        stream.Width = 1; stream.Height = 1; stream.BitsPerComponent = 8
        stream.ColorSpace = pdf.Name.DeviceGray; stream.Filter = pdf.Name.DCTDecode
        document.pages[0].Resources.XObject = pdf.Dictionary(I1=stream)
    _edit(case[0], add_image)
    def forbidden_decode(*args, **kwargs):
        pytest.fail('native decoder called before JPEG header validation')
    monkeypatch.setattr(fitz, 'Pixmap', forbidden_decode)
    with pytest.raises(ValueError, match='JPEG frame disagrees'):
        _validate(case)


@pytest.mark.parametrize('lossless', [False, True])
def test_mapping_count_bound_also_applies_to_lossless_fallback(case, monkeypatch, lossless):
    monkeypatch.setattr(validation, 'MAX_MAPPINGS', 2)
    if lossless:
        case[1].write_bytes(case[0].read_bytes())
    with pytest.raises(CandidateRejected, match='mapping_count_limit'):
        _validate(case, lossless=lossless)
