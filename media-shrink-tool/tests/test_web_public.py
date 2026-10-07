from pathlib import Path
import struct
import zlib

import pytest
from PIL import Image, ImageCms, ImageOps, PngImagePlugin, JpegImagePlugin

from media_shrink import web_public as wp


def convert(tmp_path, im, kind="photo", **save):
    root = tmp_path / "input"
    root.mkdir(exist_ok=True)
    source = root / "private.png"
    im.save(source, **save)
    out = tmp_path / "output"
    destination = out / ("master.jpg" if kind == "photo" else "master.png")
    result = wp.process_web_public_image(source, destination, wp.WebPublicConfig(kind),
                                         input_root=root, output_root=out)
    return result, destination, source


@pytest.mark.parametrize("size,expected", [((4000,3000),(1400,1050)),
    ((3000,4000),(1400,1867)), ((1200,800),(1200,800)),
    ((800,2400),(800,2400)), ((8000,1000),(1400,175))])
def test_width_cap(tmp_path, size, expected):
    result, dest, _ = convert(tmp_path, Image.new("RGB", size, "red"))
    assert result["action"] == "CONVERTED", result
    with Image.open(dest) as im:
        assert im.size == expected
        assert JpegImagePlugin.get_sampling(im) == 0
        assert im.info["progressive"]


@pytest.mark.parametrize("orientation", range(2, 9))
def test_orientation_exact_once(tmp_path, orientation):
    im = Image.new("RGB", (7, 11))
    im.putdata([(x*3, x*2, x) for x in range(77)])
    exif = Image.Exif()
    exif[274] = orientation
    result, dest, source = convert(tmp_path, im, "graphic", exif=exif)
    assert result["error"] is None, result
    with Image.open(source) as before, Image.open(dest) as after:
        expected = ImageOps.exif_transpose(before)
        assert after.size == expected.size
        assert after.tobytes() == expected.tobytes()


def test_alpha_and_opaque_photo(tmp_path):
    im = Image.new("RGBA", (20, 30), (50, 80, 90, 255))
    result, dest, _ = convert(tmp_path, im)
    assert result["error"] is None
    old = dest.read_bytes()
    im.putpixel((0,0), (5,6,7,100))
    result, dest, _ = convert(tmp_path, im)
    assert result["error"]["code"] == "TRANSPARENT_PHOTO"
    assert dest.read_bytes() == old
    result, dest, _ = convert(tmp_path, im, "graphic")
    assert result["error"] is None
    with Image.open(dest) as after:
        assert after.tobytes() == im.tobytes()


def test_metadata_allowlist(tmp_path):
    exif = Image.Exif()
    exif[270] = "private address"
    exif[34853] = {1: "N", 2: (35.0, 1.0, 2.0)}
    text = PngImagePlugin.PngInfo()
    text.add_text("comment", "karufile:image-v2;secret")
    text.add_itxt("XML:com.adobe.xmp", "private xmp")
    for kind in ("photo", "graphic"):
        result, dest, source = convert(tmp_path, Image.new("RGB", (10,20)), kind,
                                       exif=exif, pnginfo=text, dpi=(300,300))
        assert result["error"] is None, result
        with Image.open(dest) as im:
            assert not im.getexif()
            assert not getattr(im, "text", {})
            assert "SRGB_ASSUMED" in result["warnings"]
            assert "icc_profile" in im.info
            assert "comment" not in im.info
        assert b"private" in source.read_bytes()


def test_icc_conversion_against_lcms(tmp_path):
    # LAB values produce substantially different RGB; tagging without conversion cannot pass.
    root = tmp_path / "input"
    root.mkdir()
    source = root / "color.tiff"
    lab = Image.new("LAB", (16, 16), (150, 175, 90))
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB"))
    lab.save(source, icc_profile=profile.tobytes())
    dest = tmp_path / "out" / "color.png"
    result = wp.process_web_public_image(source, dest, wp.WebPublicConfig("graphic"),
                                         input_root=root, output_root=dest.parent)
    assert result["error"] is None, result
    expected = ImageCms.profileToProfile(lab, profile, ImageCms.createProfile("sRGB"),
                                        renderingIntent=0, outputMode="RGB")
    with Image.open(dest) as actual:
        assert actual.tobytes() == expected.tobytes()


def bmp_v5(path, color_space, profile=b"", header_size=124):
    from io import BytesIO
    stream = BytesIO()
    Image.new("RGB", (3, 2), (160, 80, 40)).save(stream, format="BMP")
    original = stream.getvalue()
    pixels = original[struct.unpack_from("<I", original, 10)[0]:]
    header = bytearray(header_size)
    header[:40] = original[14:54]
    struct.pack_into("<I", header, 0, header_size)
    struct.pack_into("<I", header, 56, color_space)
    if header_size == 124:
        struct.pack_into("<III", header, 108, 4, header_size + len(pixels) if profile else 0, len(profile))
    path.write_bytes(struct.pack("<2sIHHI", b"BM", 14+len(header)+len(pixels)+len(profile),
                                 0, 0, 14+len(header)) + header + pixels + profile)


@pytest.mark.parametrize("color_space,profile,header_size", [
    (0x4D424544, b"broken ICC", 124), (0x4C494E4B, b"C:\\private.icc\0", 124),
    (0, b"", 108), (0, b"", 124), (0xDEADBEEF, b"", 124)])
def test_bmp_explicit_unsupported_color_rejected(tmp_path, color_space, profile, header_size):
    root = tmp_path/"input"; root.mkdir()
    source = root/"color.bmp"; bmp_v5(source, color_space, profile, header_size)
    original = source.read_bytes()
    out = tmp_path/"out"; out.mkdir(); destination = out/"master.png"
    destination.write_bytes(b"existing output")
    result = wp.process_web_public_image(source, destination, wp.WebPublicConfig("graphic"),
                                         input_root=root, output_root=out)
    assert result["action"] == "ERROR"
    assert result["error"]["code"] == "UNSUPPORTED_COLOR"
    assert destination.read_bytes() == b"existing output" and source.read_bytes() == original


def test_bmp_embedded_icc_is_used(tmp_path):
    root = tmp_path/"input"; root.mkdir()
    # A valid RGB profile with a different tone curve proves that BMP pixels are transformed.
    profile = bytearray(wp.SRGB_BYTES)
    for offset in range(132, 132 + 12*struct.unpack_from(">I", profile, 128)[0], 12):
        if profile[offset:offset+4] == b"rTRC":
            curve = struct.unpack_from(">I", profile, offset+4)[0]
            struct.pack_into(">i", profile, curve+12, 2*65536)
            break
    profile = bytes(profile)
    source = root/"color.bmp"; bmp_v5(source, 0x4D424544, profile)
    out = tmp_path/"out"; destination = out/"master.png"
    result = wp.process_web_public_image(source, destination, wp.WebPublicConfig("graphic"),
                                         input_root=root, output_root=out)
    assert result["action"] == "CONVERTED", result
    assert "SRGB_ASSUMED" not in result["warnings"]
    from io import BytesIO
    expected = ImageCms.profileToProfile(Image.new("RGB", (3,2), (160,80,40)),
        ImageCms.ImageCmsProfile(BytesIO(profile)), ImageCms.createProfile("sRGB"),
        renderingIntent=0, outputMode="RGB")
    assert expected.getpixel((0,0)) != (160,80,40)
    with Image.open(destination) as im:
        assert im.tobytes() == expected.tobytes()


@pytest.mark.parametrize("dib_size,color_space", [(108, 0x73524742), (124, 0x57696E20)])
def test_bmp_explicit_srgb_accepted(tmp_path, dib_size, color_space):
    root = tmp_path/"input"; root.mkdir()
    source = root/"color.bmp"; bmp_v5(source, color_space, header_size=dib_size)
    out = tmp_path/"out"
    result = wp.process_web_public_image(source, out/"master.png", wp.WebPublicConfig("graphic"),
                                         input_root=root, output_root=out)
    assert result["action"] == "CONVERTED", result


@pytest.mark.parametrize("offset,length", [(124,128), (0xFFFFFFF0,128), (148,1024*1024+1), (148,10000)])
def test_bmp_profile_bounds_rejected(tmp_path, offset, length):
    root = tmp_path/"input"; root.mkdir()
    source = root/"color.bmp"; bmp_v5(source, 0x4D424544, wp.SRGB_BYTES)
    data = bytearray(source.read_bytes()); struct.pack_into("<II", data, 14+112, offset, length)
    source.write_bytes(data)
    out = tmp_path/"out"
    result = wp.process_web_public_image(source, out/"master.png", wp.WebPublicConfig("graphic"),
                                         input_root=root, output_root=out)
    assert result["error"]["code"] == "UNSUPPORTED_COLOR"


@pytest.mark.parametrize("color_space,interop,icc", [
    (1, "R03", None), (None, "R03", None), (1, "R03", wp.SRGB_BYTES),
    (2, "R98", wp.SRGB_BYTES)], ids=["contradiction", "r03-without-icc", "contradiction-with-icc", "r98-adobe"])
def test_exif_color_contradiction_rejected(tmp_path, color_space, interop, icc):
    root = tmp_path/"input"; root.mkdir()
    exif = Image.Exif(); nested = {40965: {1: interop}}
    if color_space is not None:
        nested[40961] = color_space
    exif[34665] = nested
    source = root/"color.jpg"
    Image.new("RGB", (10,10)).save(source, exif=exif, icc_profile=icc)
    out = tmp_path/"out"; destination = out/"master.png"
    result = wp.process_web_public_image(source, destination, wp.WebPublicConfig("graphic"),
                                         input_root=root, output_root=out)
    assert result["error"]["code"] == "UNSUPPORTED_COLOR"
    assert not destination.exists()


def test_failure_diagnostic_records_stage_and_type(tmp_path, monkeypatch, caplog):
    def fail(*args):
        raise PermissionError("private credential detail")
    monkeypatch.setattr(wp, "_save_public", fail)
    result, destination, _ = convert(tmp_path, Image.new("RGB", (10,10)))
    assert result["action"] == "ERROR" and not destination.exists()
    assert "stage=encode" in caplog.text and "PermissionError" in caplog.text
    assert "private credential detail" not in caplog.text


@pytest.mark.parametrize("profile", [b"broken", b""])
def test_bad_icc_rejected(tmp_path, profile):
    result, dest, _ = convert(tmp_path, Image.new("RGB", (10,10)), icc_profile=profile)
    if profile:  # Pillow omits an empty ICC on save.
        assert result["action"] == "ERROR"
        assert not dest.exists()


def test_candidate_metadata_injection_not_published(tmp_path, monkeypatch):
    original = wp._save_public
    def inject(im, path, config):
        original(im, path, config)
        with Image.open(path) as candidate:
            candidate.load()
            candidate.save(path, format="JPEG", comment=b"private comment")
    monkeypatch.setattr(wp, "_save_public", inject)
    result, dest, _ = convert(tmp_path, Image.new("RGB", (10,10)))
    assert result["action"] == "ERROR"
    assert not dest.exists()


def test_encoder_failure_preserves_existing(tmp_path, monkeypatch):
    result, dest, source = convert(tmp_path, Image.new("RGB", (10,10)))
    original_source, original_output = source.read_bytes(), dest.read_bytes()
    def fail(*args):
        raise OSError("synthetic encode failure")
    monkeypatch.setattr(wp, "_save_public", fail)
    result = wp.process_web_public_image(source, dest, wp.WebPublicConfig(),
                                         input_root=source.parent, output_root=dest.parent)
    assert result["action"] == "ERROR"
    assert source.read_bytes() == original_source
    assert dest.read_bytes() == original_output


def test_pixel_limit_and_animation(tmp_path, monkeypatch):
    monkeypatch.setattr(wp, "MAX_PIXELS", 99)
    result, dest, _ = convert(tmp_path, Image.new("RGB", (10,10)))
    assert result["error"]["code"] == "INPUT_LIMIT"
    assert not dest.exists()
    monkeypatch.setattr(wp, "MAX_PIXELS", 80_000_000)
    root = tmp_path / "input"
    source = root / "animated.gif"
    Image.new("RGB", (10,10), "red").save(source, save_all=True,
        append_images=[Image.new("RGB", (10,10), "blue")])
    result = wp.process_web_public_image(source, dest, wp.WebPublicConfig(),
                                         input_root=root, output_root=dest.parent)
    assert result["error"]["code"] == "MULTIFRAME"


def insert_png_chunk(path, kind, payload):
    data = path.read_bytes()
    chunk = struct.pack(">I", len(payload)) + kind + payload
    chunk += struct.pack(">I", zlib.crc32(kind + payload))
    path.write_bytes(data[:33] + chunk + data[33:])


@pytest.mark.parametrize("kind,payload", [(b"cICP", bytes((9,16,0,1))),
    (b"cICP", bytes((9,18,0,1))), (b"iCCP", b"bad\0\0not-zlib"),
    (b"mDCv", bytes(24))])
def test_actual_png_hdr_and_broken_profile_rejected(tmp_path, kind, payload):
    root = tmp_path / "in"
    root.mkdir()
    source = root / "color.png"
    Image.new("RGB", (10,10), "red").save(source)
    insert_png_chunk(source, kind, payload)
    dest = tmp_path / "out" / "master.jpg"
    result = wp.process_web_public_image(source, dest, wp.WebPublicConfig(),
                                         input_root=root, output_root=dest.parent)
    assert result["action"] == "ERROR", result
    assert not dest.exists()


def test_heic_orientation_and_color(tmp_path):
    root = tmp_path/"in"
    root.mkdir()
    source = root/"phone.heic"
    im = Image.new("RGB", (100,200), "red")
    exif = Image.Exif()
    exif[274] = 6
    im.save(source, quality=90, exif=exif, icc_profile=wp.SRGB_BYTES)
    with Image.open(source) as opened:
        expected = ImageOps.exif_transpose(opened).size
    dest = tmp_path/"out"/"phone.jpg"
    result = wp.process_web_public_image(source, dest, wp.WebPublicConfig(),
                                         input_root=root, output_root=dest.parent)
    assert result["error"] is None, result
    with Image.open(dest) as after:
        assert after.size == expected


def test_cmyk_without_icc_and_high_depth_rejected(tmp_path):
    root = tmp_path/"in"
    root.mkdir()
    for mode, suffix in (("CMYK", ".jpg"), ("I;16", ".png")):
        source = root/('bad'+suffix)
        Image.new(mode, (10,10)).save(source)
        dest = tmp_path/"out"/"bad.jpg"
        result = wp.process_web_public_image(source, dest, wp.WebPublicConfig(),
                                             input_root=root, output_root=dest.parent)
        assert result["action"] == "ERROR"
        assert not dest.exists()


def test_jpeg_private_segments_removed_and_post_scan_rejected(tmp_path, monkeypatch):
    root = tmp_path/"in"
    root.mkdir()
    source = root/"private.jpg"
    Image.new("RGB", (24,24), "red").save(source, comment=b"private")
    data = source.read_bytes()
    def segment(marker, value):
        return bytes((255,marker)) + struct.pack(">H", len(value)+2) + value
    source.write_bytes(data[:2] + segment(0xE1, b"http://ns.adobe.com/xap/1.0/\0private")
                       + segment(0xED, b"Photoshop 3.0\0private IPTC") + data[2:])
    dest = tmp_path/"out"/"photo.jpg"
    result = wp.process_web_public_image(source, dest, wp.WebPublicConfig(),
                                         input_root=root, output_root=dest.parent)
    assert result["error"] is None, result
    old = dest.read_bytes()
    with Image.open(dest) as check:
        assert {name for name,_ in check.applist} == {"APP0", "APP2"}
    original = wp._save_public
    def inject(*args):
        original(*args)
        path = args[1]
        data = path.read_bytes()
        path.write_bytes(data[:-2] + segment(0xFE, b"late private comment") + data[-2:])
    monkeypatch.setattr(wp, "_save_public", inject)
    result = wp.process_web_public_image(source, dest, wp.WebPublicConfig(),
                                         input_root=root, output_root=dest.parent)
    assert result["action"] == "ERROR"
    assert dest.read_bytes() == old


def test_incomplete_jpeg_icc_rejected(tmp_path):
    root = tmp_path/"in"
    root.mkdir()
    source = root/"bad.jpg"
    Image.new("RGB", (10,10)).save(source, icc_profile=wp.SRGB_BYTES)
    data = source.read_bytes().replace(b"ICC_PROFILE\0\x01\x01", b"ICC_PROFILE\0\x01\x02", 1)
    source.write_bytes(data)
    dest = tmp_path/"out"/"photo.jpg"
    result = wp.process_web_public_image(source, dest, wp.WebPublicConfig(),
                                         input_root=root, output_root=dest.parent)
    assert result["action"] == "ERROR"


def test_input_byte_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(wp, "MAX_BYTES", 20)
    result, dest, _ = convert(tmp_path, Image.new("RGB", (10,10)))
    assert result["error"]["code"] == "INPUT_LIMIT"
    assert not dest.exists()
