from io import BytesIO
from pathlib import Path
import hashlib
import struct
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image, PngImagePlugin
import pytest

from excel_shrink import core, package
from excel_shrink.core import process_workbook
from fixtures import A, XDR, R, S, REL, CT, image_bytes, picture_anchor, relationships, workbook_parts, write_workbook


def read_parts(path):
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def dimensions(data):
    with Image.open(BytesIO(data)) as image:
        return image.size


@pytest.mark.parametrize("kind", ["oneCellAnchor", "absoluteAnchor", "twoCellAnchor"])
def test_resize_preserves_every_other_part_and_original(tmp_path, kind):
    source, output = tmp_path / "source.xlsx", tmp_path / "candidate.xlsx"
    originals = write_workbook(source, anchors=[picture_anchor(kind=kind)])
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    result = process_workbook(source, output, dpi=220)
    assert result.status == "ADOPTED_LOSSY"
    assert result.images_total == result.images_changed == 1
    assert result.changed_parts == ("xl/media/image1.jpeg",)
    generated = read_parts(output)
    assert generated.keys() == originals.keys()
    assert all(generated[key] == value for key, value in originals.items() if key not in result.changed_parts)
    assert dimensions(generated["xl/media/image1.jpeg"]) == (220, 110)
    assert output.stat().st_size < source.stat().st_size
    assert hashlib.sha256(source.read_bytes()).hexdigest() == sha
    with zipfile.ZipFile(output) as archive:
        assert archive.comment == b"fixture package comment"
        assert archive.testzip() is None


def test_shared_image_uses_largest_placement(tmp_path):
    source, output = tmp_path / "source.xlsx", tmp_path / "candidate.xlsx"
    write_workbook(source, anchors=[picture_anchor(), picture_anchor(width=1828800, height=914400)])
    result = process_workbook(source, output, dpi=220)
    assert result.status == "ADOPTED_LOSSY"
    assert result.images_changed == 1
    assert dimensions(read_parts(output)["xl/media/image1.jpeg"]) == (440, 220)


def test_crop_keeps_original_region_and_required_pixels(tmp_path):
    source, output = tmp_path / "source.xlsx", tmp_path / "candidate.xlsx"
    parts = write_workbook(source, anchors=[picture_anchor(crop={"l": 25000, "r": 25000})])
    assert process_workbook(source, output, dpi=220).status == "ADOPTED_LOSSY"
    result = read_parts(output)
    assert dimensions(result["xl/media/image1.jpeg"]) == (440, 220)
    assert result["xl/drawings/drawing1.xml"] == parts["xl/drawings/drawing1.xml"]


def test_png_preserves_alpha_color_and_gamma(tmp_path):
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add(b"gAMA", struct.pack(">I", 45455))
    pnginfo.add_text("Author", "Sample author")
    png = image_bytes("PNG", mode="RGBA", pnginfo=pnginfo)
    source, output = tmp_path / "source.xlsx", tmp_path / "candidate.xlsx"
    write_workbook(source, images={"xl/media/image1.png": png})
    assert process_workbook(source, output, dpi=220).status == "ADOPTED_LOSSY"
    with Image.open(BytesIO(read_parts(output)["xl/media/image1.png"])) as image:
        assert image.size == (220, 110)
        assert image.mode == "RGBA"
        assert image.getpixel((0, 0))[3] == 0
        assert image.getpixel((110, 55)) == (220, 20, 100, 255)
        assert image.info["gamma"] == pytest.approx(0.45455)
        assert image.info["Author"] == "Sample author"


def test_dry_run_inspects_without_encoding_or_output(tmp_path, monkeypatch):
    source = tmp_path / "source.xlsx"
    write_workbook(source)
    monkeypatch.setattr(core, "_encode_image", lambda *a: pytest.fail("dry-run encoded image"))
    result = process_workbook(source, None, dry_run=True)
    assert result.status == "DRY_RUN"
    assert result.changed_parts == () and result.images_changed == 0
    assert list(tmp_path.iterdir()) == [source]


@pytest.mark.parametrize("dpi,expected", [(150, (150, 75)), (300, (300, 150))])
def test_explicit_dpi(tmp_path, dpi, expected):
    source, output = tmp_path / "source.xlsx", tmp_path / "candidate.xlsx"
    write_workbook(source)
    assert process_workbook(source, output, dpi=dpi).status == "ADOPTED_LOSSY"
    assert dimensions(read_parts(output)["xl/media/image1.jpeg"]) == expected


def test_dpi_mode_does_not_upscale_or_recompress_small_image(tmp_path):
    source, output = tmp_path / "source.xlsx", tmp_path / "candidate.xlsx"
    write_workbook(source, images={"xl/media/image1.jpeg": image_bytes(size=(100, 50))})
    result = process_workbook(source, output, dpi=220)
    assert result.status == "PRESERVED_ORIGINAL"
    assert "already_within_resolution" in result.reason
    assert not output.exists()


@pytest.mark.parametrize("kwargs,reason", [
    ({"kind": "twoCellAnchor", "same_cell": False}, "two_cell_display_size_uncertain"),
    ({"crop": {"l": -1}}, "outward_crop"),
    ({"shape_extent": (1828800, 914400)}, "anchor_shape_extent_disagreement"),
])
def test_ambiguous_placements_protect_image(tmp_path, kwargs, reason):
    source, output = tmp_path / "source.xlsx", tmp_path / "candidate.xlsx"
    write_workbook(source, anchors=[picture_anchor(**kwargs)])
    result = process_workbook(source, output)
    assert result.status == "PRESERVED_ORIGINAL" and reason in result.reason
    assert not output.exists()


def test_shared_with_unsupported_placement_protects_entire_image(tmp_path):
    source, output = tmp_path / "source.xlsx", tmp_path / "candidate.xlsx"
    write_workbook(source, anchors=[picture_anchor(), picture_anchor(kind="twoCellAnchor", same_cell=False)])
    result = process_workbook(source, output)
    assert result.status == "PRESERVED_ORIGINAL" and not output.exists()


def test_independent_supported_image_still_shrinks(tmp_path):
    source, output = tmp_path / "source.xlsx", tmp_path / "candidate.xlsx"
    originals = write_workbook(source, images={"xl/media/image1.jpeg": image_bytes(), "xl/media/image2.jpeg": image_bytes()},
        anchors=[picture_anchor(), picture_anchor("rIdImage2", kind="twoCellAnchor", same_cell=False)])
    result = process_workbook(source, output)
    assert result.status == "ADOPTED_LOSSY" and result.changed_parts == ("xl/media/image1.jpeg",)
    assert read_parts(output)["xl/media/image2.jpeg"] == originals["xl/media/image2.jpeg"]


def test_unknown_relationship_owner_blocks_shared_image(tmp_path):
    parts = workbook_parts()
    parts["customXml/item1.xml"] = b"<unknown/>"
    parts["customXml/_rels/item1.xml.rels"] = relationships([{"Id": "rIdMystery", "Type": f"{R}/image", "Target": "../xl/media/image1.jpeg"}])
    source = tmp_path / "source.xlsx"
    write_workbook(source, parts=parts)
    result = process_workbook(source, None, dry_run=True)
    assert result.status == "DRY_RUN_PRESERVED"


@pytest.mark.parametrize("feature", ["signature", "macro", "richdata", "formula", "embedded"])
def test_workbook_level_protection(tmp_path, feature):
    parts = workbook_parts()
    if feature == "formula":
        parts["xl/worksheets/sheet1.xml"] = parts["xl/worksheets/sheet1.xml"].replace(b"SUM(1,2)", b'IMAGE("https://example.invalid/a.png")')
    else:
        names = {"signature": "_xmlsignatures/sig1.xml", "macro": "xl/vbaProject.bin", "richdata": "xl/richData/rdrichvalue.xml", "embedded": "xl/embeddings/oleObject1.bin"}
        parts[names[feature]] = b"<x/>" if names[feature].endswith(".xml") else b"binary"
    source = tmp_path / "source.xlsx"
    write_workbook(source, parts=parts)
    assert process_workbook(source, None, dry_run=True).status == "DRY_RUN_PRESERVED"


def test_ole_container_is_preserved_without_opening_excel(tmp_path):
    source = tmp_path / "source.xlsx"
    source.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"opaque")
    assert process_workbook(source, None, dry_run=True).reason == "encrypted_or_legacy_container"


@pytest.mark.parametrize("part,data", [
    ("../evil.xml", b"<x/>"),
    ("/evil.xml", b"<x/>"),
    ("xl/../evil.xml", b"<x/>"),
    ("xl\\evil.xml", b"<x/>"),
    ("evil%2f.xml", b"<x/>"),
    ("xl/worksheets/sheet1.xml", b'<!DOCTYPE a [<!ENTITY x "value">]><a>&x;</a>'),
    ("xl/worksheets/sheet1.xml", '<!DOCTYPE a [<!ENTITY x "value">]><a>&x;</a>'.encode("utf-16")),
    ("xl/worksheets/sheet1.xml", b"<broken>"),
])
def test_unsafe_or_malformed_packages_fail(tmp_path, part, data):
    parts = workbook_parts()
    parts[part] = data
    source = tmp_path / "source.xlsx"
    write_workbook(source, parts=parts)
    if "\\" in part:
        # Windows ZipInfo normalizes the platform separator when writing. Make
        # the on-disk local and central-directory names actually malformed.
        source.write_bytes(source.read_bytes().replace(part.replace("\\", "/").encode(), part.encode()))
    with pytest.raises((ValueError, ET.ParseError)):
        process_workbook(source, None, dry_run=True)


def test_duplicate_zip_name_fails(tmp_path):
    source = tmp_path / "source.xlsx"
    parts = write_workbook(source)
    with zipfile.ZipFile(source, "a") as archive, pytest.warns(UserWarning):
        archive.writestr("xl/workbook.xml", parts["xl/workbook.xml"])
    with pytest.raises(ValueError, match="duplicate"):
        process_workbook(source, None, dry_run=True)


@pytest.mark.parametrize("limit,value", [("MAX_SOURCE", 1), ("MAX_ENTRIES", 1), ("MAX_PART", 1), ("MAX_TOTAL", 1), ("MAX_XML", 1), ("MAX_IMAGES", 0)])
def test_preflight_limits_protect(tmp_path, monkeypatch, limit, value):
    source = tmp_path / "source.xlsx"
    write_workbook(source)
    monkeypatch.setattr(package, limit, value)
    assert process_workbook(source, None, dry_run=True).status == "DRY_RUN_PRESERVED"


def test_runtime_timeout_is_error_not_preservation(tmp_path, monkeypatch):
    source, output = tmp_path / "source.xlsx", tmp_path / "candidate.xlsx"
    write_workbook(source)
    def expired(*args, **kwargs):
        raise TimeoutError("runtime budget exceeded")
    monkeypatch.setattr(core, "_encode_image", expired)
    with pytest.raises(TimeoutError):
        process_workbook(source, output)


def test_post_write_non_image_tampering_is_detected(tmp_path, monkeypatch):
    source, output = tmp_path / "source.xlsx", tmp_path / "candidate.xlsx"
    write_workbook(source)
    real = core.write_candidate
    def tamper(original, replacements, candidate, budget):
        real(original, replacements, candidate, budget)
        parts = read_parts(candidate)
        parts["xl/worksheets/sheet1.xml"] = parts["xl/worksheets/sheet1.xml"].replace(b"SUM(1,2)", b"SUM(9,9)")
        write_workbook(candidate, parts=parts)
    monkeypatch.setattr(core, "write_candidate", tamper)
    with pytest.raises(ValueError, match="non-target"):
        process_workbook(source, output)


def test_repeated_run_from_original_is_identical(tmp_path):
    source, output, again = tmp_path / "source.xlsx", tmp_path / "candidate.xlsx", tmp_path / "again.xlsx"
    write_workbook(source)
    assert process_workbook(source, output).status == "ADOPTED_LOSSY"
    assert process_workbook(source, again).status == "ADOPTED_LOSSY"
    assert output.read_bytes() == again.read_bytes()


def test_exif_rotation_protects_image(tmp_path):
    exif = Image.Exif()
    exif[274] = 6
    source = tmp_path / "source.xlsx"
    write_workbook(source, images={"xl/media/image1.jpeg": image_bytes(exif=exif)})
    result = process_workbook(source, None, dry_run=True)
    assert result.status == "DRY_RUN_PRESERVED" and "exif_orientation" in result.reason


def test_source_and_candidate_must_be_separate(tmp_path):
    source = tmp_path / "source.xlsx"
    write_workbook(source)
    original = source.read_bytes()
    with pytest.raises(ValueError):
        process_workbook(source, source)
    assert source.read_bytes() == original


def test_jpeg_quality_rejection_retains_original(tmp_path):
    from random import Random
    noisy = Image.frombytes("RGB", (1600, 800), Random(42).randbytes(1600 * 800 * 3))
    buffer = BytesIO()
    noisy.save(buffer, "JPEG", quality=97, subsampling=0)
    noisy.close()
    source, output = tmp_path / "source.xlsx", tmp_path / "candidate.xlsx"
    write_workbook(source, images={"xl/media/image1.jpeg": buffer.getvalue()})
    result = process_workbook(source, output, dpi=300)
    assert result.status == "PRESERVED_ORIGINAL"
    assert "image_savings_or_quality_rejected" in result.reason


def test_directory_limit_is_checked_before_zipfile_allocation(tmp_path, monkeypatch):
    source = tmp_path / "source.xlsx"
    write_workbook(source)
    data = bytearray(source.read_bytes())
    end = data.rfind(b"PK\x05\x06")
    struct.pack_into("<HH", data, end + 8, 5000, 5000)
    source.write_bytes(data)
    monkeypatch.setattr(package.zipfile, "ZipFile", lambda *a, **k: pytest.fail("unbounded ZipFile construction"))
    result = process_workbook(source, None, dry_run=True)
    assert result.status == "DRY_RUN_PRESERVED" and result.reason == "zip_entry_limit"


def test_directory_byte_size_limit_before_zipfile(tmp_path, monkeypatch):
    source = tmp_path / "source.xlsx"
    write_workbook(source)
    monkeypatch.setattr(package, "MAX_DIRECTORY", 1)
    monkeypatch.setattr(package.zipfile, "ZipFile", lambda *a, **k: pytest.fail("unbounded ZipFile construction"))
    assert process_workbook(source, None, dry_run=True).reason == "zip_directory_size_limit"
