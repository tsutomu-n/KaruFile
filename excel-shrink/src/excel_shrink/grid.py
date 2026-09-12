"""Exact, deliberately narrow cell-grid sizing for two-cell image anchors.

Explicit dimensions and confirmed defaults use regular Calibri/Yu Gothic 11
metrics. Automatic content-dependent row heights remain protected.
See Microsoft Open XML Column remarks, ISO/IEC 29500-1 section 18.3.1.13.
"""
from __future__ import annotations

from fractions import Fraction
import re
import xml.etree.ElementTree as ET

from .package import Budget, Package, Protected, R, S
from .font_metrics import FontMetrics, measure_font

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
X14AC = "http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac"
PIXEL_EMU = 9525
MAX_GRID_SPAN = 1024


def _one(parent: ET.Element, name: str) -> ET.Element:
    found = parent.findall(name)
    if len(found) != 1:
        raise Protected("missing_or_ambiguous_grid_metadata")
    return found[0]


def _number(value: str | None) -> Fraction:
    if value is None or not re.fullmatch(r"[0-9]{1,6}(?:\.[0-9]{1,8})?", value):
        raise Protected("unsupported_grid_number")
    return Fraction(value)


def _index(value: str | None, maximum: int) -> int:
    if value is None or not re.fullmatch(r"[0-9]{1,8}", value):
        raise Protected("missing_or_ambiguous_grid_index")
    result = int(value)
    if not 0 <= result <= maximum:
        raise ValueError("grid index outside allowed range")
    return result


def _disabled(element: ET.Element, names: tuple[str, ...]) -> bool:
    return all(element.get(name, "0") in {"0", "false"} for name in names)


class GridResolver:
    def __init__(self, package: Package, budget: Budget):
        self.package = package
        self.budget = budget
        self.font_checked = False
        self.metrics: FontMetrics | None = None
        self.grids: dict[str, tuple[list[ET.Element], dict[int, ET.Element]]] = {}

    def _normal_font(self) -> None:
        if self.font_checked:
            return
        relationships = self.package.relationships.get("xl/workbook.xml", {})
        styles = [rel for rel in relationships.values() if rel.type == f"{R}/styles"]
        if len(styles) != 1 or styles[0].external:
            raise Protected("normal_font_not_explicit")
        root = self.package.xml.get(styles[0].target)
        if root is None or root.tag != f"{{{S}}}styleSheet":
            raise Protected("normal_font_not_explicit")
        normal = [style for style in _one(root, f"{{{S}}}cellStyles")
                  if style.tag == f"{{{S}}}cellStyle" and style.get("builtinId") == "0"]
        if len(normal) != 1:
            raise Protected("normal_font_not_explicit")
        formats = _one(root, f"{{{S}}}cellStyleXfs")
        format_index = _index(normal[0].get("xfId"), 65535)
        if format_index >= len(formats):
            raise ValueError("Normal style references missing cell style format")
        format_record = formats[format_index]
        if (format_record.tag != f"{{{S}}}xf" or format_record.get("applyFont", "1") not in {"1", "true"}
                or "xfId" in format_record.attrib or format_record.find(f"{{{S}}}extLst") is not None):
            raise Protected("normal_font_inheritance_or_extension")
        font_index = _index(format_record.get("fontId"), 65535)
        fonts = _one(root, f"{{{S}}}fonts")
        if font_index >= len(fonts):
            raise ValueError("Normal style references missing font")
        font = fonts[font_index]
        allowed = {"name", "sz", "family", "charset", "scheme", "color", "b", "i", "strike", "outline", "shadow", "condense", "extend", "vertAlign", "u"}
        if font.tag != f"{{{S}}}font" or font.attrib or any(child.tag not in {f"{{{S}}}{name}" for name in allowed} for child in font):
            raise Protected("unsupported_normal_font_structure")
        for child in font:
            attrs = {"auto", "indexed", "rgb", "theme", "tint"} if child.tag == f"{{{S}}}color" else {"val"}
            if set(child.attrib) - attrs or len(child):
                raise Protected("unsupported_normal_font_structure")
        face_name = _one(font, f"{{{S}}}name").get("val")
        if (face_name not in {"Calibri", "游ゴシック", "Yu Gothic"}
                or _number(_one(font, f"{{{S}}}sz").get("val")) != 11):
            raise Protected("normal_font_not_verified_regular_11")
        for name in ("b", "i", "strike", "outline", "shadow", "condense", "extend"):
            if any(child.get("val", "1") not in {"0", "false"} for child in font.findall(f"{{{S}}}{name}")):
                raise Protected("normal_font_not_regular")
        if any(child.get("val", "superscript") != "baseline" for child in font.findall(f"{{{S}}}vertAlign")):
            raise Protected("normal_font_not_regular")
        if any(child.get("val", "single") != "none" for child in font.findall(f"{{{S}}}u")):
            raise Protected("normal_font_not_regular")
        schemes = font.findall(f"{{{S}}}scheme")
        if len(schemes) > 1:
            raise Protected("ambiguous_normal_font_scheme")
        if schemes and schemes[0].get("val") != "none":
            scheme = schemes[0].get("val")
            themes = [rel for rel in relationships.values() if rel.type == f"{R}/theme"]
            if scheme not in {"major", "minor"} or len(themes) != 1 or themes[0].external:
                raise Protected("normal_theme_font_not_explicit")
            theme = self.package.xml.get(themes[0].target)
            if theme is None or theme.tag != f"{{{A}}}theme":
                raise Protected("normal_theme_font_not_explicit")
            elements = _one(theme, f"{{{A}}}themeElements")
            scheme_root = _one(elements, f"{{{A}}}fontScheme")
            theme_fonts = _one(scheme_root, f"{{{A}}}{scheme}Font")
            if face_name == "Calibri":
                if _one(theme_fonts, f"{{{A}}}latin").get("typeface") != face_name:
                    raise Protected("normal_theme_font_mismatch")
            else:
                east_asian = _one(theme_fonts, f"{{{A}}}ea").get("typeface")
                japanese = [child.get("typeface") for child in theme_fonts
                            if child.tag == f"{{{A}}}font" and child.get("script") == "Jpan"]
                resolved = east_asian if east_asian else (japanese[0] if len(japanese) == 1 else None)
                if resolved not in {"游ゴシック", "Yu Gothic"}:
                    raise Protected("normal_theme_font_mismatch")
        charsets = font.findall(f"{{{S}}}charset")
        if len(charsets) > 1:
            raise Protected("ambiguous_normal_font_charset")
        charset = _index(charsets[0].get("val"), 255) if charsets else 0
        self.metrics = measure_font(face_name, charset)
        self.font_checked = True

    def _sheet(self, name: str) -> tuple[list[ET.Element], dict[int, ET.Element]]:
        if name in self.grids:
            return self.grids[name]
        root = self.package.xml[name]
        if root.find(f"{{{S}}}customSheetViews") is not None or root.find(f"{{{S}}}extLst") is not None:
            raise Protected("custom_or_extended_sheet_dimensions")
        for view in root.findall(f"{{{S}}}sheetViews/{{{S}}}sheetView"):
            if not _disabled(view, ("showFormulas", "rightToLeft")):
                raise Protected("formula_or_rtl_sheet_view")
        for format_properties in root.findall(f"{{{S}}}sheetFormatPr"):
            if not _disabled(format_properties, ("zeroHeight", "thickTop", "thickBottom")):
                raise Protected("hidden_or_border_adjusted_sheet_dimensions")
        found_cols = root.findall(f"{{{S}}}cols")
        if len(found_cols) > 1:
            raise Protected("ambiguous_column_structure")
        cols = found_cols[0] if found_cols else ET.Element(f"{{{S}}}cols")
        if cols.attrib or any(col.tag != f"{{{S}}}col" for col in cols):
            raise Protected("unsupported_column_structure")
        rows: dict[int, ET.Element] = {}
        for row in _one(root, f"{{{S}}}sheetData"):
            self.budget.check()
            if row.tag != f"{{{S}}}row":
                raise Protected("unsupported_row_structure")
            index = _index(row.get("r"), 1048576)
            if index < 1 or index in rows:
                raise ValueError("invalid or duplicate worksheet row")
            rows[index] = row
        result = (list(cols), rows)
        self.grids[name] = result
        return result

    def extent(self, owners: tuple[str, ...], start: tuple[int, int, int, int], end: tuple[int, int, int, int]) -> tuple[int, int]:
        c1, r1, x1, y1 = start
        c2, r2, x2, y2 = end
        if len(owners) != 1:
            raise Protected("two_cell_shared_drawing_owner")
        if c2 < c1 or r2 < r1:
            raise ValueError("inverted two-cell cell indices")
        if c2 - c1 >= MAX_GRID_SPAN or r2 - r1 >= MAX_GRID_SPAN:
            raise Protected("two_cell_grid_span_limit")
        self._normal_font()
        assert self.metrics is not None
        mdw = self.metrics.mdw
        cols, rows = self._sheet(owners[0])
        format_items = self.package.xml[owners[0]].findall(f"{{{S}}}sheetFormatPr")
        if len(format_items) > 1:
            raise Protected("ambiguous_sheet_format")
        properties = format_items[0] if format_items else None
        if properties is not None and (len(properties) or set(properties.attrib) - {
            "baseColWidth", "defaultColWidth", "defaultRowHeight", "customHeight", "zeroHeight",
            "thickTop", "thickBottom", "outlineLevelRow", "outlineLevelCol", f"{{{X14AC}}}dyDescent"
        }):
            raise Protected("unsupported_sheet_format")
        widths: dict[int, int] = {}
        for col in cols:
            self.budget.check()
            first, last = _index(col.get("min"), 16384), _index(col.get("max"), 16384)
            if first < 1 or last < first:
                raise ValueError("invalid worksheet column range")
            if last < c1 + 1 or first > c2 + 1:
                continue
            allowed = {"min", "max", "width", "style", "bestFit", "customWidth", "hidden", "collapsed", "outlineLevel", "phonetic"}
            if (set(col.attrib) - allowed or len(col) or not _disabled(col, ("hidden", "collapsed"))
                    or col.get("bestFit", "0") not in {"0", "1", "true", "false"}
                    or (col.get("bestFit") in {"1", "true"} and col.get("customWidth") not in {"1", "true"})):
                raise Protected("unsupported_explicit_column")
            width = _number(col.get("width"))
            if not 0 < width <= 255:
                raise Protected("unsupported_explicit_column_width")
            pixels = ((256 * width + 128 // mdw) * mdw) // 256
            if pixels < 1:
                raise Protected("zero_pixel_column")
            for index in range(max(first, c1 + 1), min(last, c2 + 1) + 1):
                if index in widths:
                    raise Protected("overlapping_column_definitions")
                widths[index] = int(pixels) * PIXEL_EMU
        heights: dict[int, int] = {}
        for index in range(r1 + 1, r2 + 2):
            self.budget.check()
            row = rows.get(index)
            allowed = {"r", "spans", "s", "customFormat", "ht", "hidden", "customHeight", "outlineLevel", "collapsed", "thickTop", "thickBot", "ph", f"{{{X14AC}}}dyDescent"}
            if row is not None and set(row.attrib) - allowed:
                raise Protected("unsupported_explicit_row")
            if row is None or row.get("customHeight") not in {"1", "true"}:
                # Default height is usable for structurally empty, unstyled rows.
                # A row with cells or an explicit non-custom ht can be autoFit.
                if (properties is None or (row is not None and (len(row) or "ht" in row.attrib
                        or row.get("s", "0") != "0"))
                        or any(col.get("style", "0") != "0" for col in cols)):
                    raise Protected("row_height_not_explicit")
                if row is not None and not _disabled(row, ("hidden", "collapsed", "thickTop", "thickBot")):
                    raise Protected("unsupported_explicit_row")
                row = ET.Element(f"{{{S}}}row", r=str(index), customHeight="1",
                                 ht=properties.get("defaultRowHeight", ""))
            allowed = {"r", "spans", "s", "customFormat", "ht", "hidden", "customHeight", "outlineLevel", "collapsed", "thickTop", "thickBot", "ph"}
            allowed.add(f"{{{X14AC}}}dyDescent")
            if (set(row.attrib) - allowed or not _disabled(row, ("hidden", "collapsed", "thickTop", "thickBot"))
                    or any(child.tag != f"{{{S}}}c" for child in row)):
                raise Protected("unsupported_explicit_row")
            height = _number(row.get("ht"))
            pixels = height * Fraction(4, 3)
            if not 0 < height <= 409 or pixels.denominator != 1:
                raise Protected("row_height_not_integral_pixels")
            descent = row.get(f"{{{X14AC}}}dyDescent")
            # MS-XLSX 2.5.3 describes a baseline offset; its only height-related
            # side effect sets customHeight=true, which was already required.
            if descent is not None and not 0 <= _number(descent) <= pixels:
                raise Protected("unsupported_row_descent")
            heights[index] = int(pixels) * PIXEL_EMU
        if any(index not in widths for index in range(c1 + 1, c2 + 2)):
            if properties is None:
                raise Protected("column_width_not_explicit")
            if properties.get("defaultColWidth") is not None:
                default = _number(properties.get("defaultColWidth"))
                if not 0 < default <= 255:
                    raise Protected("unsupported_default_column_width")
                pixels = ((256 * default + 128 // mdw) * mdw) // 256
            else:
                base = _index(properties.get("baseColWidth", "8"), 255)
                # Excel's default columns round up to an 8-pixel boundary.
                # Limit the implicit recipe to the independently checked base=8.
                if base != 8:
                    raise Protected("unverified_base_column_width")
                pixels = ((base * mdw + 5 + 7) // 8) * 8
            if pixels < 1:
                raise Protected("zero_pixel_column")
            for index in range(c1 + 1, c2 + 2):
                widths.setdefault(index, int(pixels) * PIXEL_EMU)
        if x1 > widths[c1 + 1] or x2 > widths[c2 + 1] or y1 > heights[r1 + 1] or y2 > heights[r2 + 1]:
            raise Protected("two_cell_offset_outside_explicit_cell")
        return (sum(widths[index] for index in range(c1 + 1, c2 + 1)) + x2 - x1,
                sum(heights[index] for index in range(r1 + 1, r2 + 1)) + y2 - y1)
