"""Bounded, read-only OPC inspection and byte-preserving ZIP reconstruction.

This module never extracts archive paths onto the filesystem and never rewrites XML.
"""
from __future__ import annotations

import copy
import posixpath
import re
import stat
import struct
import time
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit


MAX_SOURCE = 128 * 1024 * 1024
MAX_ENTRIES = 4096
MAX_DIRECTORY = 4 * 1024 * 1024
MAX_PART = 64 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_XML = 8 * 1024 * 1024
MAX_IMAGES = 1000
MAX_XML_TOTAL = 32 * 1024 * 1024
MAX_XML_NODES = 1_000_000
MAX_PIXELS = 32_000_000
MAX_DECODE_PIXELS = 200_000_000
SECONDS = 300
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
SHEET_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"


class Protected(ValueError):
    """An unsupported structure or preflight limit; retain the whole workbook."""

    def __init__(self, reason: str, *, images_total: int | None = None):
        super().__init__(reason)
        self.images_total = images_total


@dataclass
class Budget:
    deadline: float
    decoded_pixels: int = 0

    @classmethod
    def start(cls) -> Budget:
        return cls(time.monotonic() + SECONDS)

    def check(self) -> None:
        if time.monotonic() > self.deadline:
            raise TimeoutError("Excel cooperative processing budget exceeded")

    def decode(self, pixels: int) -> None:
        self.check()
        self.decoded_pixels += pixels
        if self.decoded_pixels > MAX_DECODE_PIXELS:
            raise ValueError("Excel cumulative image decode budget exceeded")


@dataclass(frozen=True)
class Relationship:
    id: str
    type: str
    target: str
    external: bool


@dataclass
class Package:
    infos: list[zipfile.ZipInfo]
    parts: dict[str, bytes]
    types: dict[str, str]
    xml: dict[str, ET.Element]
    relationships: dict[str, dict[str, Relationship]]
    images: tuple[str, ...]
    comment: bytes


def safe_name(name: str, *, directory: bool = False) -> str:
    value = name[:-1] if directory and name.endswith("/") else name
    if (not value or value.startswith("/") or "\\" in value or ":" in value
            or "%" in value or any(ord(c) < 32 for c in value)
            or any(p in {"", ".", ".."} for p in value.split("/"))):
        raise ValueError(f"unsafe or ambiguous ZIP part name: {name!r}")
    return value


@dataclass
class XmlLimits:
    size: int = 0
    nodes: int = 0


def parse_xml(data: bytes, limits: XmlLimits | None = None) -> ET.Element:
    limits = limits if limits is not None else XmlLimits()
    limits.size += len(data)
    if limits.size > MAX_XML_TOTAL:
        raise Protected("cumulative_xml_size_limit")
    if len(data) > MAX_XML:
        raise Protected("xml_size_limit")
    try:
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = data.decode("utf-16")
        else:
            text = data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise Protected("unsupported_xml_encoding") from exc
    if "\x00" in text:
        raise Protected("unsupported_xml_encoding")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.I):
        raise ValueError("DTD/entity declarations are not accepted")
    declaration = re.match(r"\s*<\?xml[^?]*encoding\s*=\s*['\"]([^'\"]+)", text, re.I)
    if declaration and declaration[1].lower() not in {"utf-8", "utf-16", "utf-16le", "utf-16be", "us-ascii"}:
        raise Protected("unsupported_xml_encoding")
    parser = ET.XMLPullParser(events=("start", "end"))
    root = None
    depth = 0
    nodes = 0
    for offset in range(0, len(text), 16384):
        parser.feed(text[offset:offset + 16384])
        for event, element in parser.read_events():
            if event == "start":
                if root is None:
                    root = element
                depth += 1
                nodes += 1
                limits.nodes += 1
                if depth > 64 or nodes > 250_000:
                    raise Protected("xml_structure_limit")
                if limits.nodes > MAX_XML_NODES:
                    raise Protected("cumulative_xml_node_limit")
            else:
                depth -= 1
    parser.close()
    if root is None:
        raise ValueError("empty XML")
    return root


def relationship_source(name: str) -> str:
    if name == "_rels/.rels":
        return ""
    parent, filename = posixpath.split(name)
    if not parent.endswith("/_rels") or not filename.endswith(".rels"):
        raise ValueError(f"invalid relationships part: {name}")
    return parent[:-6] + "/" + filename[:-5]


def resolve_target(source: str, target: str) -> str:
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or "\\" in target:
        raise ValueError("invalid internal relationship URI")
    decoded = unquote(parsed.path, errors="strict")
    if "%" in decoded or ":" in decoded or "\\" in decoded:
        raise ValueError("ambiguous internal relationship URI")
    if decoded.startswith("/"):
        result = posixpath.normpath(decoded[1:])
    else:
        result = posixpath.normpath(posixpath.join(posixpath.dirname(source), decoded))
    return safe_name(result)


def _preflight_directory(path: Path) -> None:
    """Bound directory bytes and actual entry count before ZipInfo allocation."""
    with path.open("rb") as stream:
        stream.seek(0, 2)
        size = stream.tell()
        tail_size = min(size, 65535 + 22 + 20)
        stream.seek(size - tail_size)
        tail = stream.read(tail_size)
        last_signature = position = tail.rfind(b"PK\x05\x06")
        while position >= 0:
            if (len(tail) - position >= 22
                    and position + 22 + struct.unpack_from("<H", tail, position + 20)[0] == len(tail)):
                break
            position = tail.rfind(b"PK\x05\x06", 0, position)
        if position < 0:
            raise ValueError("missing ZIP end-of-directory record")
        if position != last_signature:
            # ZipFile itself selects the final signature. Preserve a valid ZIP
            # whose comment would make that parser choose a different record.
            raise Protected("ambiguous_zip_comment_end_record")
        _, disk, directory_disk, disk_entries, total_entries, directory_size, directory_offset, comment_size = struct.unpack_from("<4s4H2LH", tail, position)
        if position + 22 + comment_size != len(tail):
            raise ValueError("invalid ZIP comment/end record")
        if disk or directory_disk or disk_entries != total_entries:
            raise Protected("multi_disk_zip")
        if (total_entries == 65535 or directory_size == 0xFFFFFFFF or directory_offset == 0xFFFFFFFF
                or (position >= 20 and tail[position - 20:position - 16] == b"PK\x06\x07")):
            raise Protected("zip64_directory")
        if total_entries > MAX_ENTRIES:
            raise Protected("zip_entry_limit")
        if directory_size > MAX_DIRECTORY:
            raise Protected("zip_directory_size_limit")
        absolute_end = size - tail_size + position
        if directory_offset + directory_size != absolute_end:
            raise Protected("nonstandard_zip_directory_layout")
        stream.seek(directory_offset)
        directory = stream.read(directory_size)
        if len(directory) != directory_size:
            raise ValueError("truncated ZIP central directory")
    cursor = 0
    entries = 0
    while cursor < len(directory):
        if len(directory) - cursor < 46 or directory[cursor:cursor + 4] != b"PK\x01\x02":
            raise ValueError("invalid ZIP central-directory record")
        name_size, extra_size, entry_comment_size = struct.unpack_from("<3H", directory, cursor + 28)
        cursor += 46 + name_size + extra_size + entry_comment_size
        entries += 1
        if cursor > len(directory) or entries > total_entries:
            raise ValueError("ZIP central-directory entry count/size mismatch")
        if entries > MAX_ENTRIES:
            raise Protected("zip_entry_limit")
    if entries != total_entries:
        raise ValueError("ZIP central-directory entry count mismatch")


def read_package(path: Path, budget: Budget) -> Package:
    if path.stat().st_size > MAX_SOURCE:
        raise Protected("source_size_limit")
    with path.open("rb") as stream:
        if stream.read(8) == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise Protected("encrypted_or_legacy_container")
    _preflight_directory(path)
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_ENTRIES:
            raise Protected("zip_entry_limit")
        total = 0
        seen: set[str] = set()
        for info in infos:
            budget.check()
            if info.orig_filename != info.filename:
                # ZipInfo silently truncates NUL-containing names. Comparing
                # only .filename could validate a different OPC name from the
                # bytes that Excel or another ZIP reader sees.
                raise ValueError("ambiguous or NUL-containing ZIP entry name")
            name = safe_name(info.filename, directory=info.is_dir())
            key = name.casefold()
            if key in seen:
                raise ValueError("duplicate or case-ambiguous ZIP entry")
            seen.add(key)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("symlink ZIP entries are not accepted")
            if info.flag_bits & 1:
                raise Protected("encrypted_zip")
            if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise Protected("unsupported_zip_compression")
            total += info.file_size
            if info.file_size > MAX_PART or total > MAX_TOTAL:
                raise Protected("zip_expanded_size_limit")
        parts: dict[str, bytes] = {}
        for info in infos:
            budget.check()
            with archive.open(info) as stream:
                data = stream.read(info.file_size + 1)
                if len(data) != info.file_size or stream.read(1):
                    raise ValueError("ZIP entry expanded size mismatch")
            parts[info.filename] = data
        comment = archive.comment
    if "[Content_Types].xml" not in parts or "_rels/.rels" not in parts:
        raise ValueError("not an OPC workbook package")
    xml_limits = XmlLimits()
    type_root = parse_xml(parts["[Content_Types].xml"], xml_limits)
    if type_root.tag != f"{{{CT}}}Types":
        raise ValueError("invalid content types root")
    defaults: dict[str, str] = {}
    overrides: dict[str, str] = {}
    for element in type_root:
        if element.tag == f"{{{CT}}}Default":
            key, content_type = element.get("Extension", "").lower(), element.get("ContentType", "")
            if not key or "/" in key or not content_type or key in defaults:
                raise ValueError("invalid/duplicate default content type")
            defaults[key] = content_type
        elif element.tag == f"{{{CT}}}Override":
            part = element.get("PartName", "")
            if not part.startswith("/"):
                raise ValueError("invalid content type part URI")
            key = safe_name(unquote(part[1:], errors="strict"))
            if key not in parts or key in overrides or not element.get("ContentType"):
                raise ValueError("invalid/duplicate content type override")
            overrides[key] = element.attrib["ContentType"]
        else:
            raise ValueError("unknown content types element")
    types = {
        name: overrides.get(name, defaults.get(name.rsplit(".", 1)[-1].lower(), ""))
        for name in parts if not name.endswith("/") and name != "[Content_Types].xml"
    }
    if any(not value for value in types.values()):
        raise ValueError("part has no content type")
    images = tuple(sorted(name for name, kind in types.items() if kind.startswith("image/")))
    if len(images) > MAX_IMAGES:
        raise Protected("image_count_limit", images_total=len(images))
    xml: dict[str, ET.Element] = {"[Content_Types].xml": type_root}
    for name, content_type in types.items():
        budget.check()
        if name.lower().endswith((".xml", ".rels", ".vml")) or content_type.endswith("+xml"):
            try:
                xml[name] = parse_xml(parts[name], xml_limits)
            except Protected as exc:
                raise Protected(str(exc), images_total=len(images)) from exc
    relationships: dict[str, dict[str, Relationship]] = {}
    for name, root in xml.items():
        if not name.endswith(".rels"):
            continue
        source = relationship_source(name)
        if source and source not in parts:
            raise ValueError("orphan relationships part")
        if root.tag != f"{{{REL}}}Relationships":
            raise ValueError("invalid relationships root")
        entries: dict[str, Relationship] = {}
        for element in root:
            if element.tag != f"{{{REL}}}Relationship":
                raise ValueError("invalid relationship element")
            rid, kind, target = (element.get(k, "") for k in ("Id", "Type", "Target"))
            mode = element.get("TargetMode", "Internal")
            if not rid or rid in entries or not kind or not target or mode not in {"Internal", "External"}:
                raise ValueError("invalid/duplicate relationship")
            external = mode == "External"
            resolved = target if external else resolve_target(source, target)
            if not external and resolved not in parts:
                raise ValueError(f"relationship target is missing: {resolved}")
            entries[rid] = Relationship(rid, kind, resolved, external)
        relationships[source] = entries
    return Package(infos, parts, types, xml, relationships, images, comment)


def check_workbook(package: Package) -> None:
    root_rels = package.relationships.get("", {})
    office = [r for r in root_rels.values() if r.type == f"{R}/officeDocument"]
    if len(office) != 1 or office[0].external:
        raise Protected("unsupported_workbook_relationship")
    workbook_name = office[0].target
    if workbook_name != "xl/workbook.xml" or package.types.get(workbook_name) != SHEET_TYPE:
        raise Protected("unsupported_workbook_type")
    workbook = package.xml.get(workbook_name)
    if workbook is None or workbook.tag != f"{{{S}}}workbook":
        raise Protected("unsupported_workbook_namespace")
    for name, kind in package.types.items():
        lower = (name + " " + kind).lower()
        if any(token in lower for token in ("_xmlsignatures", "digital-signature", "vbaproject", "macroenabled", "richdata", "cellimage", "/embeddings/")):
            raise Protected("signed_macro_embedded_or_cell_image_workbook")
    for source, entries in package.relationships.items():
        for rel in entries.values():
            if any(token in rel.type.lower() for token in ("digital-signature", "vbaproject", "oleobject", "richvalue", "richdata")):
                raise Protected("signed_macro_embedded_or_cell_image_workbook")
    # IMAGE/DISPIMG can have application-maintained caches outside ordinary drawings.
    for root in package.xml.values():
        for formula in root.iter(f"{{{S}}}f"):
            if re.search(r"(?:^|[^A-Z0-9_])(?:_XLFN\.)?(?:IMAGE|DISPIMG)\s*\(", (formula.text or "").upper()):
                raise Protected("cell_image_formula")


def write_candidate(package: Package, replacements: dict[str, bytes], path: Path, budget: Budget) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.comment = package.comment
        for original in package.infos:
            budget.check()
            info = copy.copy(original)
            archive.writestr(info, replacements.get(info.filename, package.parts[info.filename]))


def verify_candidate(original: Package, candidate: Package, replacements: dict[str, bytes]) -> None:
    if list(original.parts) != list(candidate.parts) or original.comment != candidate.comment:
        raise ValueError("candidate ZIP entries/order/comment changed")
    changed = {name for name in original.parts if original.parts[name] != candidate.parts[name]}
    if changed != set(replacements):
        raise ValueError("candidate changed non-target parts or omitted image changes")
    for name in replacements:
        if candidate.parts[name] != replacements[name]:
            raise ValueError("candidate image bytes changed during packaging")
