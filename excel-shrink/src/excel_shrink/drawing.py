"""Resolve every image relationship before allowing a floating picture to shrink."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from fractions import Fraction
import re
import xml.etree.ElementTree as ET

from .package import Budget, Package, Protected, R, S
from .grid import GridResolver
from .drawing_extensions import check_extension_list, check_nonvisual


A = "http://schemas.openxmlformats.org/drawingml/2006/main"
XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
A14 = "http://schemas.microsoft.com/office/drawing/2010/main"
EMU_PER_INCH = 914400


def integer(value: str | None, label: str, *, minimum: int = 0, maximum: int = 10**12) -> int:
    if value is None or not re.fullmatch(r"-?[0-9]{1,15}", value):
        raise ValueError(f"invalid integer in {label}")
    number = int(value)
    if not minimum <= number <= maximum:
        raise ValueError(f"out-of-range integer in {label}")
    return number


def single(parent: ET.Element, tag: str, *, optional: bool = False) -> ET.Element | None:
    matches = parent.findall(tag)
    if len(matches) > 1 or (not matches and not optional):
        raise ValueError(f"missing/duplicate drawing element {tag}")
    return matches[0] if matches else None


def extent(element: ET.Element) -> tuple[int, int]:
    return (integer(element.get("cx"), "extent.cx", minimum=1),
            integer(element.get("cy"), "extent.cy", minimum=1))


def marker(element: ET.Element) -> tuple[int, int, int, int]:
    values = []
    for name, limit in (("col", 16383), ("row", 1048575), ("colOff", 10**12), ("rowOff", 10**12)):
        child = single(element, f"{{{XDR}}}{name}")
        assert child is not None
        values.append(integer(child.text, f"marker.{name}", maximum=limit))
    return tuple(values)  # type: ignore[return-value]


@dataclass(frozen=True)
class Placement:
    width_emu: int
    height_emu: int
    visible_x: Fraction
    visible_y: Fraction
    geometry_basis: str = "validated_anchor"

    def required_pixels(self, dpi: int) -> tuple[int, int]:
        def ceiling(value: Fraction) -> int:
            return (value.numerator + value.denominator - 1) // value.denominator
        return (ceiling(Fraction(self.width_emu * dpi, EMU_PER_INCH) / self.visible_x),
                ceiling(Fraction(self.height_emu * dpi, EMU_PER_INCH) / self.visible_y))


@dataclass
class DrawingPlan:
    placements: dict[str, list[Placement]]
    protected: dict[str, str]
    uses: dict[str, int] = field(default_factory=dict)


def _picture_placement(anchor: ET.Element, picture: ET.Element, blip: ET.Element,
                       *, grid: GridResolver | None = None, owners: tuple[str, ...] = ()) -> Placement:
    geometry_basis = "validated_anchor"
    anchor_members = {
        f"{{{XDR}}}oneCellAnchor": {"from", "ext", "pic", "clientData"},
        f"{{{XDR}}}absoluteAnchor": {"pos", "ext", "pic", "clientData"},
        f"{{{XDR}}}twoCellAnchor": {"from", "to", "pic", "clientData"},
    }.get(anchor.tag)
    if anchor_members is None or any(child.tag not in {f"{{{XDR}}}{name}" for name in anchor_members} for child in anchor):
        raise Protected("unknown_or_complex_anchor_child")
    client_data = single(anchor, f"{{{XDR}}}clientData")
    assert client_data is not None
    if (len(client_data) or set(client_data.attrib) - {"fLocksWithSheet", "fPrintsWithSheet"}
            or any(value not in {"0", "1", "true", "false"} for value in client_data.attrib.values())):
        raise Protected("unknown_or_complex_anchor_client_data")
    if set(picture.attrib) - {"macro", "fPublished"} or picture.get("macro"):
        raise Protected("picture_macro_or_unknown_attributes")
    if any(child.tag not in {f"{{{XDR}}}nvPicPr", f"{{{XDR}}}blipFill", f"{{{XDR}}}spPr"} for child in picture):
        raise Protected("complex_picture_structure")
    if blip.get(f"{{{R}}}link") or set(blip.attrib) - {f"{{{R}}}embed", "cstate"}:
        raise Protected("linked_or_complex_blip")
    # useLocalDpi is retained verbatim. It is not used to infer display size.
    if len(blip) > 1:
        raise Protected("image_effect_or_extension")
    for child in blip:
        check_extension_list(child, creation=False)
    fill = single(picture, f"{{{XDR}}}blipFill")
    shape = single(picture, f"{{{XDR}}}spPr")
    nv = single(picture, f"{{{XDR}}}nvPicPr")
    assert fill is not None and shape is not None and nv is not None
    if single(fill, f"{{{A}}}blip") is not blip:
        raise Protected("ambiguous_image_placement")
    if set(fill.attrib) - {"dpi", "rotWithShape"} or fill.get("dpi", "0") != "0":
        raise Protected("explicit_blip_fill_dpi")
    if any(c.tag not in {f"{{{A}}}blip", f"{{{A}}}srcRect", f"{{{A}}}stretch"} for c in fill):
        raise Protected("tiled_or_complex_fill")
    stretch = single(fill, f"{{{A}}}stretch")
    assert stretch is not None
    fill_rect = single(stretch, f"{{{A}}}fillRect", optional=True)
    if fill_rect is None:
        raise Protected("implicit_fill_rectangle")
    if (stretch.attrib or len(stretch) != 1 or len(fill_rect)
            or set(fill_rect.attrib) - {"l", "r", "t", "b"}
            or any(v != "0" for v in fill_rect.attrib.values())):
        raise Protected("nondefault_fill_rectangle")
    crop = single(fill, f"{{{A}}}srcRect", optional=True)
    sides = {key: 0 for key in ("l", "r", "t", "b")}
    if crop is not None:
        if set(crop.attrib) - set(sides) or len(crop):
            raise Protected("complex_crop")
        for key in sides:
            value = crop.get(key, "0")
            # OOXML Strict percentage strings require separate namespace handling.
            sides[key] = integer(value, f"crop.{key}", minimum=-100000, maximum=100000)
        if min(sides.values()) < 0:
            raise Protected("outward_crop")
    visible_x = Fraction(100000 - sides["l"] - sides["r"], 100000)
    visible_y = Fraction(100000 - sides["t"] - sides["b"], 100000)
    if visible_x <= 0 or visible_y <= 0:
        raise ValueError("empty or inverted crop rectangle")
    if set(shape.attrib) - {"bwMode"} or shape.get("bwMode", "auto") not in {"auto", "clr"}:
        raise Protected("shape_black_white_mode")
    allowed_shape = {f"{{{A}}}xfrm", f"{{{A}}}prstGeom", f"{{{A}}}noFill", f"{{{A}}}ln"}
    if any(child.tag not in allowed_shape for child in shape):
        raise Protected("complex_shape_effect")
    geometry = single(shape, f"{{{A}}}prstGeom", optional=True)
    if geometry is not None:
        if geometry.get("prst") != "rect" or any(c.tag != f"{{{A}}}avLst" or len(c) for c in geometry):
            raise Protected("nonrectangular_geometry")
    # Unknown nonvisual extensions can include camera links or image edit data.
    check_nonvisual(nv)
    if anchor.tag in {f"{{{XDR}}}oneCellAnchor", f"{{{XDR}}}absoluteAnchor"}:
        if anchor.attrib:
            raise Protected("unknown_anchor_attributes")
        size = single(anchor, f"{{{XDR}}}ext")
        assert size is not None
        width, height = extent(size)
        if anchor.tag == f"{{{XDR}}}oneCellAnchor":
            start = single(anchor, f"{{{XDR}}}from")
            assert start is not None
            marker(start)
        else:
            pos = single(anchor, f"{{{XDR}}}pos")
            assert pos is not None
            integer(pos.get("x"), "anchor.x", minimum=-10**12)
            integer(pos.get("y"), "anchor.y", minimum=-10**12)
    elif anchor.tag == f"{{{XDR}}}twoCellAnchor":
        if set(anchor.attrib) - {"editAs"} or anchor.get("editAs", "twoCell") not in {"oneCell", "twoCell", "absolute"}:
            raise Protected("unknown_anchor_attributes")
        start = single(anchor, f"{{{XDR}}}from")
        end = single(anchor, f"{{{XDR}}}to")
        assert start is not None and end is not None
        c1, r1, x1, y1 = marker(start)
        c2, r2, x2, y2 = marker(end)
        if c1 != c2 or r1 != r2:
            if grid is None:
                raise Protected("two_cell_display_size_uncertain")
            try:
                width, height = grid.extent(owners, (c1, r1, x1, y1), (c2, r2, x2, y2))
                assert grid.metrics is not None
                geometry_basis = "grid_" + grid.metrics.basis + (":" + grid.metrics.sha256 if grid.metrics.sha256 else "")
            except Protected as exc:
                raise Protected(f"two_cell_display_size_uncertain:{exc}") from exc
        else:
            width, height = x2 - x1, y2 - y1
        if width <= 0 or height <= 0:
            raise ValueError("inverted two-cell anchor")
    else:
        raise Protected("unsupported_anchor")
    transform = single(shape, f"{{{A}}}xfrm", optional=True)
    if transform is not None:
        if set(transform.attrib) - {"rot", "flipH", "flipV"} or transform.get("rot", "0") != "0":
            raise Protected("rotated_or_complex_transform")
        if any(transform.get(k, "0") not in {"0", "1", "true", "false"} for k in ("flipH", "flipV")):
            raise ValueError("invalid transform boolean")
        if any(c.tag not in {f"{{{A}}}off", f"{{{A}}}ext"} for c in transform):
            raise Protected("group_transform")
        shape_extent = single(transform, f"{{{A}}}ext", optional=True)
        if shape_extent is not None and extent(shape_extent) != (width, height):
            raise Protected("anchor_shape_extent_disagreement")
    return Placement(width, height, visible_x, visible_y, geometry_basis)


def inspect_drawings(package: Package, budget: Budget) -> DrawingPlan:
    images = set(package.images)
    placements: dict[str, list[Placement]] = defaultdict(list)
    protected: dict[str, str] = {}
    recognized_drawings: set[str] = set()
    drawing_owners: dict[str, set[str]] = defaultdict(set)
    grid = GridResolver(package, budget)
    uses: dict[str, int] = defaultdict(int)
    for source, entries in package.relationships.items():
        root = package.xml.get(source)
        if root is None or root.tag != f"{{{S}}}worksheet":
            continue
        for drawing in root.findall(f"{{{S}}}drawing"):
            rid = drawing.get(f"{{{R}}}id")
            rel = entries.get(rid or "")
            if rel is None or rel.external or rel.type != f"{R}/drawing":
                raise ValueError("invalid worksheet drawing relationship")
            recognized_drawings.add(rel.target)
            drawing_owners[rel.target].add(source)
    consumed: set[tuple[str, int, str]] = set()
    handled_rels: set[tuple[str, str]] = set()
    for source in recognized_drawings:
        budget.check()
        root = package.xml.get(source)
        entries = package.relationships.get(source, {})
        if root is None or root.tag != f"{{{XDR}}}wsDr":
            continue
        allowed_anchors = {f"{{{XDR}}}oneCellAnchor", f"{{{XDR}}}twoCellAnchor", f"{{{XDR}}}absoluteAnchor"}
        if any(child.tag not in allowed_anchors for child in root):
            for rel in entries.values():
                if not rel.external and rel.target in images:
                    protected[rel.target] = "drawing_extension_or_alternate_content"
            continue
        for anchor in root:
            pictures = anchor.findall(f"{{{XDR}}}pic")
            for picture in pictures:
                blips = list(picture.iter(f"{{{A}}}blip"))
                targets = {
                    rel.target for el in picture.iter() for attr, rid in el.attrib.items()
                    if attr.startswith(f"{{{R}}}") and (rel := entries.get(rid)) is not None
                    and not rel.external and rel.target in images
                }
                if len(pictures) != 1 or len(blips) != 1:
                    protected.update((name, "ambiguous_picture") for name in targets)
                    continue
                blip = blips[0]
                rid = blip.get(f"{{{R}}}embed", "")
                rel = entries.get(rid)
                if rel is None:
                    if blip.get(f"{{{R}}}link"):
                        continue
                    raise ValueError("missing embedded image relationship")
                if rel.external or rel.type != f"{R}/image" or rel.target not in images:
                    raise ValueError("invalid embedded image relationship")
                uses[rel.target] += 1
                try:
                    placement = _picture_placement(anchor, picture, blip, grid=grid,
                                                   owners=tuple(sorted(drawing_owners[source])))
                except Protected as exc:
                    protected.update((name, str(exc)) for name in targets)
                    continue
                placements[rel.target].append(placement)
                consumed.add((source, id(blip), f"{{{R}}}embed"))
                handled_rels.add((source, rid))
    # Every inbound relationship, including unknown owners and unused aliases, must
    # be explained. A supported use never overrides an unsupported shared use.
    for source, entries in package.relationships.items():
        budget.check()
        image_rels = {rid: rel for rid, rel in entries.items() if not rel.external and rel.target in images}
        root = package.xml.get(source)
        for rid, rel in image_rels.items():
            if (source, rid) not in handled_rels:
                protected.setdefault(rel.target, "unknown_or_unused_image_relationship")
            if root is None:
                protected.setdefault(rel.target, "opaque_image_reference_owner")
        if root is None or not image_rels:
            continue
        # Visit the owner once, even when many image relationships share it.
        # Unknown extensions may store relationship IDs in their own namespace,
        # plain attributes or text. Do not assume only r:* attributes can refer
        # to the same image already consumed by a supported floating picture.
        for element in root.iter():
            budget.check()
            for attr, value in element.attrib.items():
                rel = image_rels.get(value)
                if rel is not None and (source, id(element), attr) not in consumed:
                    protected.setdefault(rel.target, "shared_with_unsupported_image_use")
            rel = image_rels.get((element.text or "").strip())
            if rel is not None:
                protected.setdefault(rel.target, "shared_with_unsupported_image_use")
    for name in images:
        if name not in placements:
            protected.setdefault(name, "no_supported_floating_placement")
    return DrawingPlan(dict(placements), protected, dict(uses))
