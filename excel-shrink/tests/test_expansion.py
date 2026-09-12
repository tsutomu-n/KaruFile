"""Acceptance and failure paths for the real-workbook support expansion."""
from copy import deepcopy
import json
import sys
import xml.etree.ElementTree as ET
import pytest

from excel_shrink import package as pkg
from excel_shrink.core import process_workbook
from excel_shrink.diagnostics import Analysis
from excel_shrink.drawing_extensions import A, A16, check_extension_list
from excel_shrink.font_metrics import FontMetrics, measure_font
from excel_shrink.grid import GridResolver
from fixtures import S, XDR, image_bytes, picture_anchor, workbook_parts, write_workbook
from test_review import _explicit_grid_parts


def creation():
    element = ET.Element(f"{{{A}}}extLst")
    ext = ET.SubElement(element, f"{{{A}}}ext", uri="{FF2B5EF4-FFF2-40B4-BE49-F238E27FC236}")
    ET.SubElement(ext, f"{{{A16}}}creationId", id="{12345678-ABCD-ABCD-ABCD-1234567890AB}")
    return element


@pytest.mark.parametrize("mutation", ["uri", "namespace", "attribute", "wrapper", "text", "duplicate", "guid", "child"])
def test_creation_extension_rejects_unknown_structure(mutation):
    e = creation()
    if mutation == "uri": e[0].set("uri", "unknown")
    elif mutation == "namespace": e[0][0].tag = "{unknown}creationId"
    elif mutation == "attribute": e[0][0].set("relationship", "rId1")
    elif mutation == "wrapper": e.set("x", "1")
    elif mutation == "text": e[0][0].text = "hidden reference"
    elif mutation == "duplicate": e.append(deepcopy(e[0]))
    elif mutation == "guid": e[0][0].set("id", "not-a-guid")
    else: ET.SubElement(e[0][0], "unknown")
    with pytest.raises(pkg.Protected): check_extension_list(e, creation=True)


@pytest.mark.parametrize("omit_id", [False, True])
def test_creation_extension_allows_resizing_without_xml_changes(tmp_path, omit_id):
    anchor = picture_anchor()
    e = creation()
    if omit_id: e[0][0].attrib.clear()
    anchor.find(f"{{{XDR}}}pic/{{{XDR}}}nvPicPr/{{{XDR}}}cNvPr").append(e)
    source, output = tmp_path / "in.xlsx", tmp_path / "out.xlsx"
    original = write_workbook(source, anchors=[anchor])
    result = process_workbook(source, output)
    assert result.status == "ADOPTED_LOSSY"
    candidate = pkg.read_package(output, pkg.Budget.start())
    assert all(candidate.parts[n] == b for n, b in original.items() if n not in result.changed_parts)


@pytest.mark.parametrize("count", [500, 501, 685, 1000, 1001])
def test_inventory_limit_reports_actual_count(tmp_path, count):
    data = image_bytes(size=(8, 4))
    parts = workbook_parts(images={f"xl/media/image{i}.jpeg": data for i in range(1, count + 1)}, anchors=[])
    source = tmp_path / "in.xlsx"
    write_workbook(source, parts=parts)
    analysis = Analysis()
    result = process_workbook(source, None, dry_run=True, analysis=analysis)
    assert result.images_total == count
    assert (result.reason == "image_count_limit") == (count == 1001)
    assert analysis.complete == (count <= 1000)


def test_unknown_image_count_is_distinct_from_zero(tmp_path):
    unknown, empty = tmp_path / "unknown.xlsx", tmp_path / "empty.xlsx"
    unknown.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    write_workbook(empty, images={}, anchors=[])
    assert process_workbook(unknown, None, dry_run=True).images_total is None
    assert process_workbook(empty, None, dry_run=True).images_total == 0


def test_cumulative_xml_limits_before_unbounded_tree(monkeypatch):
    limits = pkg.XmlLimits()
    monkeypatch.setattr(pkg, "MAX_XML_NODES", 5)
    pkg.parse_xml(b"<r><a/><b/></r>", limits)
    with pytest.raises(pkg.Protected, match="cumulative_xml_node_limit"):
        pkg.parse_xml(b"<r><a/><b/></r>", limits)
    monkeypatch.setattr(pkg, "MAX_XML_TOTAL", 12)
    limits = pkg.XmlLimits()
    pkg.parse_xml(b"<root/>", limits)
    with pytest.raises(pkg.Protected, match="cumulative_xml_size_limit"):
        pkg.parse_xml(b"<root/>", limits)


@pytest.mark.parametrize("mdw,font,height", [(7,"Calibri",15),(8,"游ゴシック",18.75)])
@pytest.mark.parametrize("default_width", [None, "9.625"])
def test_default_grid_matches_independent_excel_oracle(tmp_path, monkeypatch, mdw, font, height, default_width):
    # Excel16 oracle measurements: default 64/72px, explicit 67/77px;
    # row heights 15/18.75pt. Stored cached extents are not consulted here.
    p = _explicit_grid_parts()
    s = ET.fromstring(p["xl/worksheets/sheet1.xml"])
    s.remove(s.find(f"{{{S}}}cols")); s.find(f"{{{S}}}sheetData").clear()
    props = ET.Element(f"{{{S}}}sheetFormatPr", defaultRowHeight=str(height))
    if default_width: props.set("defaultColWidth", default_width)
    s.insert(0,props); p["xl/worksheets/sheet1.xml"] = ET.tostring(s)
    styles = ET.fromstring(p["xl/styles.xml"])
    styles.find(f"{{{S}}}fonts/{{{S}}}font/{{{S}}}name").set("val", font)
    p["xl/styles.xml"] = ET.tostring(styles)
    monkeypatch.setattr("excel_shrink.grid.measure_font", lambda *_: FontMetrics(font,mdw,"","iso_calibri11"))
    file = tmp_path / "grid.xlsx"; write_workbook(file,parts=p)
    grid = GridResolver(pkg.read_package(file,pkg.Budget.start()),pkg.Budget.start())
    pixels = ({7:67,8:77} if default_width else {7:64,8:72})[mdw]
    assert grid.extent(("xl/worksheets/sheet1.xml",),(0,0,0,0),(3,4,0,0)) == (3*pixels*9525,int(4*height*12700))
    row = ET.SubElement(s.find(f"{{{S}}}sheetData"),f"{{{S}}}row",r="2")
    ET.SubElement(row,f"{{{S}}}c",r="A2",s="1")
    p["xl/worksheets/sheet1.xml"] = ET.tostring(s); write_workbook(file,parts=p)
    grid = GridResolver(pkg.read_package(file,pkg.Budget.start()),pkg.Budget.start())
    with pytest.raises(pkg.Protected,match="row_height_not_explicit"):
        grid.extent(("xl/worksheets/sheet1.xml",),(0,0,0,0),(3,4,0,0))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows GDI integration")
def test_installed_font_measurement_and_unknown_font_rejection():
    for font,charset,expected in [("Calibri",0,7),("游ゴシック",128,8)]:
        try: metrics = measure_font(font,charset)
        except pkg.Protected as exc: pytest.skip(f"Required local font unavailable: {exc}")
        assert metrics.mdw == expected and len(metrics.sha256) == 64
    with pytest.raises(pkg.Protected): measure_font("Missing-KaruFile-Font",128)


def test_dry_run_diagnostics_and_post_decode_error(tmp_path, monkeypatch):
    source = tmp_path / "in.xlsx"; write_workbook(source)
    analysis = Analysis()
    result = process_workbook(source,None,dry_run=True,analysis=analysis)
    assert result.images_changed == 0 and result.changed_parts == ()
    assert analysis.complete and analysis.records[0]["outcome"] == "planned"
    monkeypatch.setattr("excel_shrink.core._encode_image", lambda *_, **kwargs: (_ for _ in ()).throw(OSError("disk failure")))
    analysis = Analysis()
    with pytest.raises(OSError): process_workbook(source,tmp_path/"out.xlsx",analysis=analysis)
    assert analysis.images_total == 1 and len(analysis.records) == 1


def test_cumulative_pixel_preflight_is_not_relaxed_for_many_images(tmp_path, monkeypatch):
    source = tmp_path / "in.xlsx"; write_workbook(source)
    monkeypatch.setattr("excel_shrink.core.MAX_DECODE_PIXELS", 1)
    analysis = Analysis()
    result = process_workbook(source, None, dry_run=True, analysis=analysis)
    assert result.status == "DRY_RUN_PRESERVED" and result.reason == "cumulative_image_pixel_limit"
    assert analysis.images_total == 1 and not analysis.complete


def test_known_inventory_survives_later_xml_limit(tmp_path, monkeypatch):
    source = tmp_path / "in.xlsx"; parts = write_workbook(source)
    # Content Types fits; the next XML makes the cumulative bound fail.
    monkeypatch.setattr(pkg, "MAX_XML_TOTAL", len(parts["[Content_Types].xml"]) + 1)
    analysis = Analysis()
    result = process_workbook(source, None, dry_run=True, analysis=analysis)
    assert result.reason == "cumulative_xml_size_limit" and result.images_total == 1


def test_implicit_fill_rectangle_protects_only_its_image(tmp_path):
    anchor = picture_anchor()
    anchor.find(f"{{{XDR}}}pic/{{{XDR}}}blipFill/{{{A}}}stretch").clear()
    source = tmp_path / "in.xlsx"; write_workbook(source, anchors=[anchor])
    result = process_workbook(source,None,dry_run=True)
    assert result.status == "DRY_RUN_PRESERVED" and "implicit_fill_rectangle" in result.reason
