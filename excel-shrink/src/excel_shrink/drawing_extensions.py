"""Exact allowlist for inert picture identifiers and retained compression hints."""
import re
import xml.etree.ElementTree as ET
from .package import Protected

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
A14 = "http://schemas.microsoft.com/office/drawing/2010/main"
A16 = "http://schemas.microsoft.com/office/drawing/2014/main"
XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"


def check_extension_list(element: ET.Element, *, creation: bool) -> None:
    reason = "nonvisual_picture_extension" if creation else "image_effect_or_extension"
    if element.tag != f"{{{A}}}extLst" or element.attrib or len(element) != 1:
        raise Protected(reason)
    extension = element[0]
    uri = ("{FF2B5EF4-FFF2-40B4-BE49-F238E27FC236}" if creation
           else "{28A0092B-C50C-407E-A947-70E740481C1C}")
    if (extension.tag != f"{{{A}}}ext" or set(extension.attrib) != {"uri"}
            or extension.get("uri", "").upper() != uri or len(extension) != 1):
        raise Protected(reason)
    child = extension[0]
    if any((node.text or "").strip() or (node.tail or "").strip() for node in element.iter()):
        raise Protected(reason)
    if creation:
        if (child.tag != f"{{{A16}}}creationId" or set(child.attrib) - {"id"} or len(child)
                or ("id" in child.attrib and not re.fullmatch(
                    r"\{[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\}", child.get("id", "")))):
            raise Protected(reason)
    elif (child.tag != f"{{{A14}}}useLocalDpi" or set(child.attrib) - {"val"} or len(child)
          or child.get("val", "true") not in {"0", "1", "true", "false"}):
        raise Protected(reason)


def check_nonvisual(nv: ET.Element) -> None:
    lists = [el for el in nv.iter() if el.tag.endswith("}extLst")]
    if not lists:
        return
    properties = nv.findall(f"{{{XDR}}}cNvPr")
    if len(properties) != 1 or len(lists) != 1 or lists[0] not in list(properties[0]):
        raise Protected("nonvisual_picture_extension")
    check_extension_list(lists[0], creation=True)
