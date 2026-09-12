"""Small deterministic OPC fixtures; no workbook re-save library is used."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from random import Random
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image, ImageFilter

CT = "http://schemas.openxmlformats.org/package/2006/content-types"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"


def image_bytes(fmt="JPEG", size=(1600, 800), *, mode="RGB", exif=None, pnginfo=None):
    if mode == "RGBA":
        image = Image.new(mode, size, (20, 130, 220, 0))
        image.paste((220, 20, 100, 255), (size[0] // 4, size[1] // 4, size[0] * 3 // 4, size[1] * 3 // 4))
    else:
        bands = len(Image.new(mode, (1, 1)).getbands())
        noise = Image.frombytes(mode, size, Random(42).randbytes(size[0] * size[1] * bands))
        image = noise.filter(ImageFilter.GaussianBlur(2))
        noise.close()
    buffer = BytesIO()
    options = {"quality": 97, "subsampling": 0} if fmt == "JPEG" else {"compress_level": 0}
    if exif is not None:
        options["exif"] = exif
    if pnginfo is not None:
        options["pnginfo"] = pnginfo
    image.save(buffer, format=fmt, **options)
    image.close()
    return buffer.getvalue()


def _xml(root):
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def relationships(entries):
    root = ET.Element(f"{{{REL}}}Relationships")
    for entry in entries:
        ET.SubElement(root, f"{{{REL}}}Relationship", entry)
    return _xml(root)


def picture_anchor(rid="rIdImage1", *, width=914400, height=457200, kind="oneCellAnchor", crop=None, same_cell=True, shape_extent=None):
    anchor = ET.Element(f"{{{XDR}}}{kind}")
    if kind == "absoluteAnchor":
        ET.SubElement(anchor, f"{{{XDR}}}pos", x="0", y="0")
    else:
        start = ET.SubElement(anchor, f"{{{XDR}}}from")
        for name in ("col", "colOff", "row", "rowOff"):
            ET.SubElement(start, f"{{{XDR}}}{name}").text = "0"
    if kind == "twoCellAnchor":
        end = ET.SubElement(anchor, f"{{{XDR}}}to")
        values = {"col": 0 if same_cell else 3, "row": 0 if same_cell else 4, "colOff": width, "rowOff": height}
        for name in ("col", "colOff", "row", "rowOff"):
            ET.SubElement(end, f"{{{XDR}}}{name}").text = str(values[name])
    else:
        ET.SubElement(anchor, f"{{{XDR}}}ext", cx=str(width), cy=str(height))
    picture = ET.SubElement(anchor, f"{{{XDR}}}pic")
    nv = ET.SubElement(picture, f"{{{XDR}}}nvPicPr")
    ET.SubElement(nv, f"{{{XDR}}}cNvPr", id="2", name="Photo")
    ET.SubElement(nv, f"{{{XDR}}}cNvPicPr")
    fill = ET.SubElement(picture, f"{{{XDR}}}blipFill")
    ET.SubElement(fill, f"{{{A}}}blip", {f"{{{R}}}embed": rid})
    if crop:
        ET.SubElement(fill, f"{{{A}}}srcRect", {key: str(value) for key, value in crop.items()})
    ET.SubElement(ET.SubElement(fill, f"{{{A}}}stretch"), f"{{{A}}}fillRect")
    props = ET.SubElement(picture, f"{{{XDR}}}spPr")
    if shape_extent:
        transform = ET.SubElement(props, f"{{{A}}}xfrm")
        ET.SubElement(transform, f"{{{A}}}off", x="0", y="0")
        ET.SubElement(transform, f"{{{A}}}ext", cx=str(shape_extent[0]), cy=str(shape_extent[1]))
    ET.SubElement(ET.SubElement(props, f"{{{A}}}prstGeom", prst="rect"), f"{{{A}}}avLst")
    ET.SubElement(anchor, f"{{{XDR}}}clientData")
    return anchor


def workbook_parts(*, images=None, anchors=None):
    if images is None:
        images = {"xl/media/image1.jpeg": image_bytes()}
    if anchors is None:
        anchors = [picture_anchor()]
    types = ET.Element(f"{{{CT}}}Types")
    for extension, kind in {"rels": "application/vnd.openxmlformats-package.relationships+xml", "xml": "application/xml", "jpeg": "image/jpeg", "jpg": "image/jpeg", "png": "image/png", "bin": "application/octet-stream"}.items():
        ET.SubElement(types, f"{{{CT}}}Default", Extension=extension, ContentType=kind)
    for name, kind in {
        "/xl/workbook.xml": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
        "/xl/worksheets/sheet1.xml": "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml",
        "/xl/drawings/drawing1.xml": "application/vnd.openxmlformats-officedocument.drawing+xml",
        "/xl/styles.xml": "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml",
    }.items():
        ET.SubElement(types, f"{{{CT}}}Override", PartName=name, ContentType=kind)
    workbook = ET.Element(f"{{{S}}}workbook")
    sheets = ET.SubElement(workbook, f"{{{S}}}sheets")
    ET.SubElement(sheets, f"{{{S}}}sheet", {"name": "Report", "sheetId": "1", f"{{{R}}}id": "rId1"})
    sheet = ET.Element(f"{{{S}}}worksheet")
    data = ET.SubElement(sheet, f"{{{S}}}sheetData")
    row = ET.SubElement(data, f"{{{S}}}row", r="1")
    cell = ET.SubElement(row, f"{{{S}}}c", r="A1")
    ET.SubElement(cell, f"{{{S}}}f").text = "SUM(1,2)"
    ET.SubElement(cell, f"{{{S}}}v").text = "3"
    ET.SubElement(sheet, f"{{{S}}}drawing", {f"{{{R}}}id": "rIdDrawing"})
    drawing = ET.Element(f"{{{XDR}}}wsDr")
    drawing.extend(anchors)
    parts = {
        "[Content_Types].xml": _xml(types),
        "_rels/.rels": relationships([{"Id": "rId1", "Type": f"{R}/officeDocument", "Target": "xl/workbook.xml"}]),
        "xl/workbook.xml": _xml(workbook),
        "xl/_rels/workbook.xml.rels": relationships([
            {"Id": "rId1", "Type": f"{R}/worksheet", "Target": "worksheets/sheet1.xml"},
            {"Id": "rId2", "Type": f"{R}/styles", "Target": "styles.xml"},
        ]),
        "xl/worksheets/sheet1.xml": _xml(sheet),
        "xl/styles.xml": f'<styleSheet xmlns="{S}"><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="1"><xf/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'.encode(),
        "xl/worksheets/_rels/sheet1.xml.rels": relationships([{"Id": "rIdDrawing", "Type": f"{R}/drawing", "Target": "../drawings/drawing1.xml"}]),
        "xl/drawings/drawing1.xml": _xml(drawing),
        "xl/drawings/_rels/drawing1.xml.rels": relationships([
            {"Id": f"rIdImage{index}", "Type": f"{R}/image", "Target": "../media/" + Path(name).name}
            for index, name in enumerate(images, 1)
        ]),
        **images,
    }
    return parts


def write_workbook(path, *, parts=None, **kwargs):
    parts = parts if parts is not None else workbook_parts(**kwargs)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.comment = b"fixture package comment"
        for name, data in parts.items():
            archive.writestr(name, data)
    return parts
