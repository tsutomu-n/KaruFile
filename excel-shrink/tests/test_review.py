"""Independent failure-path review regressions for the XLSX boundary."""
from __future__ import annotations

from io import BytesIO
import os
import struct
import xml.etree.ElementTree as ET
import zipfile
import zlib

from PIL import Image, PngImagePlugin
import pytest

from excel_shrink import core, package
from excel_shrink.core import ImagePlan, process_workbook
from fixtures import A, XDR, S, R, REL, image_bytes, picture_anchor, write_workbook, workbook_parts


def _chunk(kind, payload):
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


def _jpeg_marker(kind, payload):
    return bytes((255, kind)) + struct.pack(">H", len(payload) + 2) + payload


@pytest.mark.parametrize("location", ["anchor", "clientData"])
def test_unknown_anchor_content_protects_image(tmp_path, location):
    anchor = picture_anchor()
    parent = anchor if location == "anchor" else anchor.find(f"{{{XDR}}}clientData")
    ET.SubElement(parent, "{urn:unknown-excel-extension}positionOverride", width="91440000")
    source, output = tmp_path / "source.xlsx", tmp_path / "candidate.xlsx"
    write_workbook(source, anchors=[anchor])
    before = source.read_bytes()
    result = process_workbook(source, output)
    assert result.status == "PRESERVED_ORIGINAL"
    assert "unknown_or_complex_anchor" in result.reason
    assert not output.exists()
    assert source.read_bytes() == before


def test_unknown_zero_fill_rectangle_attribute_is_not_assumed_default(tmp_path):
    anchor = picture_anchor()
    fill = anchor.find(f".//{{{A}}}fillRect")
    fill.set("{urn:extension}customViewport", "0")
    source, output = tmp_path / "source.xlsx", tmp_path / "candidate.xlsx"
    write_workbook(source, anchors=[anchor])
    result = process_workbook(source, output)
    assert result.status == "PRESERVED_ORIGINAL"
    assert "nondefault_fill_rectangle" in result.reason


@pytest.mark.parametrize("reference_form", ["attribute", "qualified_attribute", "text"])
def test_shared_image_reference_in_unknown_graphic_is_protected(tmp_path, reference_form):
    unsupported = ET.Element(f"{{{XDR}}}oneCellAnchor")
    graphic = ET.SubElement(unsupported, f"{{{XDR}}}graphicFrame")
    extension = ET.SubElement(graphic, "{urn:unknown}imageCache")
    if reference_form == "text":
        extension.text = "rIdImage1"
    else:
        key = "relationship" if reference_form == "attribute" else "{urn:unknown}relationship"
        extension.set(key, "rIdImage1")
    source, output = tmp_path / "source.xlsx", tmp_path / "candidate.xlsx"
    write_workbook(source, anchors=[picture_anchor(), unsupported])
    result = process_workbook(source, output)
    assert result.status == "PRESERVED_ORIGINAL"
    assert "shared_with_unsupported_image_use" in result.reason
    assert not output.exists()


def test_nul_in_zip_part_name_is_rejected_before_name_truncation(tmp_path):
    source = tmp_path / "source.xlsx"
    write_workbook(source)
    data = source.read_bytes()
    name = b"xl/media/image1.jpeg"
    malformed = name[:-1] + b"\0"
    assert data.count(name) == 2  # Local and central directory names.
    source.write_bytes(data.replace(name, malformed))
    with pytest.raises(ValueError, match="NUL-containing"):
        process_workbook(source, tmp_path / "out.xlsx")


@pytest.mark.parametrize("shared", [False, True])
def test_multicell_anchor_never_uses_cached_shape_extent(tmp_path, shared):
    anchors = [picture_anchor(kind="twoCellAnchor", same_cell=False, shape_extent=(914400, 457200))]
    if shared:
        anchors.insert(0, picture_anchor())
    source, output = tmp_path / "source.xlsx", tmp_path / "candidate.xlsx"
    write_workbook(source, anchors=anchors)
    result = process_workbook(source, output)
    assert result.status == "PRESERVED_ORIGINAL"
    assert "two_cell_display_size_uncertain" in result.reason
    assert not output.exists()


@pytest.mark.parametrize("alias", ["same", "hardlink", "symlink"])
def test_core_rejects_candidate_alias_before_writing(tmp_path, alias):
    source, candidate = tmp_path / "source.xlsx", tmp_path / "candidate.xlsx"
    write_workbook(source)
    original = source.read_bytes()
    if alias == "same":
        candidate = source
    elif alias == "hardlink":
        os.link(source, candidate)
    else:
        try:
            candidate.symlink_to(source)
        except OSError:
            pytest.skip("symlink privilege unavailable")
    with pytest.raises(ValueError, match="candidate"):
        process_workbook(source, candidate)
    assert source.read_bytes() == original


@pytest.mark.parametrize("marker", [0xE3, 0xED, 0xEE])
def test_unknown_jpeg_application_data_is_protected(tmp_path, marker):
    jpeg = image_bytes(size=(800, 400))
    jpeg = jpeg[:2] + _jpeg_marker(marker, b"application editing metadata") + jpeg[2:]
    source, output = tmp_path / "source.xlsx", tmp_path / "candidate.xlsx"
    write_workbook(source, images={"xl/media/image1.jpeg": jpeg})
    result = process_workbook(source, output)
    assert result.status == "PRESERVED_ORIGINAL"
    assert "jpeg_extended_metadata" in result.reason
    assert not output.exists()


def test_jpeg_metadata_after_first_scan_is_protected():
    jpeg = image_bytes(size=(80, 40))
    jpeg = jpeg[:-2] + _jpeg_marker(0xFE, b"late metadata") + jpeg[-2:]
    with pytest.raises(package.Protected, match="metadata_after_image_scan"):
        core._inspect_image(jpeg, "image/jpeg", "xl/media/image1.jpeg")


def test_jpeg_trailing_edit_data_is_protected():
    jpeg = image_bytes(size=(80, 40)) + b"original edit image"
    with pytest.raises(package.Protected, match="trailing_jpeg_data"):
        core._inspect_image(jpeg, "image/jpeg", "xl/media/image1.jpeg")


def test_jpeg_without_end_marker_is_structural_error():
    jpeg = image_bytes(size=(80, 40))[:-2]
    with pytest.raises(ValueError, match="end marker") as caught:
        core._inspect_image(jpeg, "image/jpeg", "xl/media/image1.jpeg")
    assert not isinstance(caught.value, package.Protected)


def test_jpeg_progressive_scans_and_exif_comment_survive_resize():
    source_data = image_bytes(size=(800, 400))
    exif = Image.Exif()
    exif[274] = 1
    exif[315] = "Metadata test"
    with Image.open(BytesIO(source_data)) as source:
        original_buffer = BytesIO()
        source.save(original_buffer, format="JPEG", quality=97, subsampling=0, progressive=True,
                    exif=exif, comment=b"caption")
    original = original_buffer.getvalue()
    assert core._inspect_image(original, "image/jpeg", "xl/media/image1.jpeg") == ("JPEG", (800, 400))
    changed = core._encode_image(original, ImagePlan("xl/media/image1.jpeg", "JPEG", (800, 400), (220, 110)), package.Budget.start())
    assert changed is not None
    with Image.open(BytesIO(original)) as before, Image.open(BytesIO(changed)) as after:
        assert after.info["exif"] == before.info["exif"]
        assert after.info["comment"] == b"caption"


def test_duplicate_png_header_is_structural_error():
    png = image_bytes("PNG", size=(40, 20))
    header = png[8:33]
    png = png[:33] + header + png[33:]
    with pytest.raises(ValueError, match="duplicate or misplaced PNG header") as caught:
        core._png_chunks(png)
    assert not isinstance(caught.value, package.Protected)


def test_png_chunk_count_limit_is_checked_before_unbounded_list_growth():
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header)
    png += _chunk(b"tEXt", b"") * 100_000 + _chunk(b"IEND", b"")
    with pytest.raises(package.Protected, match="png_chunk_count_limit"):
        core._png_chunks(png)


def test_rgb_color_key_transparency_and_png_color_metadata_survive():
    with Image.new("RGB", (800, 400), (255, 0, 0)) as image:
        image.paste((0, 0, 255), (200, 100, 600, 300))
        metadata = PngImagePlugin.PngInfo()
        metadata.add(b"gAMA", struct.pack(">I", 45455))
        metadata.add_text("Caption", "Keep text")
        stream = BytesIO()
        image.save(stream, format="PNG", compress_level=0, transparency=(255, 0, 0), pnginfo=metadata, dpi=(96, 96))
    original = stream.getvalue()
    result = core._encode_image(original, ImagePlan("xl/media/image1.png", "PNG", (800, 400), (220, 110)), package.Budget.start())
    assert result is not None
    with Image.open(BytesIO(result)) as decoded:
        assert decoded.mode == "RGBA"
        assert decoded.getpixel((0, 0))[3] == 0
        assert decoded.getpixel((110, 55))[3] == 255
        assert decoded.info["Caption"] == "Keep text"
        assert decoded.info["gamma"] == 0.45455
        assert decoded.info["dpi"] == (96.012, 96.012)
    original_chunks = dict(core._png_chunks(original))
    result_chunks = dict(core._png_chunks(result))
    assert all(result_chunks[kind] == original_chunks[kind] for kind in (b"gAMA", b"pHYs", b"tEXt"))


def test_duplicate_jpeg_comments_are_protected():
    jpeg = image_bytes(size=(80, 40))
    metadata = _jpeg_marker(0xFE, b"first") + _jpeg_marker(0xFE, b"second")
    with pytest.raises(package.Protected, match="duplicate_jpeg_metadata"):
        core._inspect_image(jpeg[:2] + metadata + jpeg[2:], "image/jpeg", "xl/media/image1.jpeg")


def _explicit_grid_parts(*, shape_extent=True):
    width, height = 183 * 9525, 80 * 9525
    anchor = picture_anchor(kind="twoCellAnchor", same_cell=False,
                            shape_extent=(width, height) if shape_extent else None)
    end = anchor.find(f"{{{XDR}}}to")
    end.find(f"{{{XDR}}}colOff").text = "0"
    end.find(f"{{{XDR}}}rowOff").text = "0"
    parts = workbook_parts(anchors=[anchor])
    sheet = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
    cols = ET.Element(f"{{{S}}}cols")
    ET.SubElement(cols, f"{{{S}}}col", min="1", max="4", width="8.7109375", customWidth="1")
    sheet.insert(0, cols)
    data = sheet.find(f"{{{S}}}sheetData")
    data[0].set("ht", "15")
    data[0].set("customHeight", "1")
    for index in range(2, 6):
        ET.SubElement(data, f"{{{S}}}row", r=str(index), ht="15", customHeight="1")
    parts["xl/worksheets/sheet1.xml"] = ET.tostring(sheet)
    styles = ET.fromstring(parts["xl/styles.xml"])
    styles.find(f"{{{S}}}cellStyleXfs/{{{S}}}xf").set("fontId", "0")
    parts["xl/styles.xml"] = ET.tostring(styles)
    return parts


@pytest.mark.parametrize("shape_extent", [True, False])
def test_explicit_calibri_grid_allows_multicell_anchor(tmp_path, shape_extent):
    source, output = tmp_path / "source.xlsx", tmp_path / "candidate.xlsx"
    parts = _explicit_grid_parts(shape_extent=shape_extent)
    write_workbook(source, parts=parts)
    result = process_workbook(source, output, dpi=220)
    assert result.status == "ADOPTED_LOSSY"
    with zipfile.ZipFile(output) as generated:
        with Image.open(BytesIO(generated.read("xl/media/image1.jpeg"))) as image:
            assert image.size == (420, 210)
        assert all(generated.read(name) == content for name, content in parts.items() if name not in result.changed_parts)


@pytest.mark.parametrize("uncertainty", ["missing_column", "row_autoheight", "column_hidden", "column_bestfit", "row_hidden", "row_fraction", "row_thickborder", "font_name", "font_bold", "show_formulas", "cached_extent", "span_limit"])
def test_multicell_grid_uncertainty_preserves_image(tmp_path, uncertainty):
    parts = _explicit_grid_parts()
    sheet = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
    styles = ET.fromstring(parts["xl/styles.xml"])
    drawing = ET.fromstring(parts["xl/drawings/drawing1.xml"])
    col = sheet.find(f"{{{S}}}cols/{{{S}}}col")
    row = sheet.find(f"{{{S}}}sheetData/{{{S}}}row")
    if uncertainty == "missing_column":
        col.set("min", "2")
    elif uncertainty == "row_autoheight":
        row.attrib.pop("customHeight")
    elif uncertainty == "column_hidden":
        col.set("hidden", "1")
    elif uncertainty == "column_bestfit":
        col.set("bestFit", "1")
        col.set("customWidth", "0")
    elif uncertainty == "row_hidden":
        row.set("hidden", "1")
    elif uncertainty == "row_fraction":
        row.set("ht", "15.1")
    elif uncertainty == "row_thickborder":
        row.set("thickBot", "1")
    elif uncertainty == "font_name":
        styles.find(f"{{{S}}}fonts/{{{S}}}font/{{{S}}}name").set("val", "Aptos")
    elif uncertainty == "font_bold":
        ET.SubElement(styles.find(f"{{{S}}}fonts/{{{S}}}font"), f"{{{S}}}b")
    elif uncertainty == "show_formulas":
        ET.SubElement(ET.SubElement(sheet, f"{{{S}}}sheetViews"), f"{{{S}}}sheetView", showFormulas="1")
    elif uncertainty == "cached_extent":
        drawing.find(f".//{{{A}}}xfrm/{{{A}}}ext").set("cx", "914400")
    else:
        drawing.find(f".//{{{XDR}}}to/{{{XDR}}}col").text = "1024"
    parts["xl/worksheets/sheet1.xml"] = ET.tostring(sheet)
    parts["xl/styles.xml"] = ET.tostring(styles)
    parts["xl/drawings/drawing1.xml"] = ET.tostring(drawing)
    source, output = tmp_path / "source.xlsx", tmp_path / "candidate.xlsx"
    write_workbook(source, parts=parts)
    result = process_workbook(source, output)
    assert result.status == "PRESERVED_ORIGINAL"
    assert not output.exists()


@pytest.mark.parametrize("theme_font", ["Calibri", "Aptos"])
def test_normal_theme_font_must_match_calibri(tmp_path, theme_font):
    parts = _explicit_grid_parts()
    styles = ET.fromstring(parts["xl/styles.xml"])
    ET.SubElement(styles.find(f"{{{S}}}fonts/{{{S}}}font"), f"{{{S}}}scheme", val="minor")
    parts["xl/styles.xml"] = ET.tostring(styles)
    rels = ET.fromstring(parts["xl/_rels/workbook.xml.rels"])
    ET.SubElement(rels, f"{{{REL}}}Relationship", Id="rTheme", Type=f"{R}/theme", Target="theme/theme1.xml")
    parts["xl/_rels/workbook.xml.rels"] = ET.tostring(rels)
    theme = ET.Element(f"{{{A}}}theme")
    scheme = ET.SubElement(ET.SubElement(theme, f"{{{A}}}themeElements"), f"{{{A}}}fontScheme")
    ET.SubElement(ET.SubElement(scheme, f"{{{A}}}minorFont"), f"{{{A}}}latin", typeface=theme_font)
    parts["xl/theme/theme1.xml"] = ET.tostring(theme)
    source, output = tmp_path / "source.xlsx", tmp_path / "candidate.xlsx"
    write_workbook(source, parts=parts)
    result = process_workbook(source, output)
    assert result.status == ("ADOPTED_LOSSY" if theme_font == "Calibri" else "PRESERVED_ORIGINAL")


def test_explicit_custom_row_height_allows_known_descent_metadata(tmp_path):
    parts = _explicit_grid_parts()
    sheet = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
    for row in sheet.findall(f"{{{S}}}sheetData/{{{S}}}row"):
        row.set("{http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac}dyDescent", "0.25")
    parts["xl/worksheets/sheet1.xml"] = ET.tostring(sheet)
    source, output = tmp_path / "source.xlsx", tmp_path / "candidate.xlsx"
    write_workbook(source, parts=parts)
    assert process_workbook(source, output).status == "ADOPTED_LOSSY"
