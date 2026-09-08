from __future__ import annotations

from pathlib import Path

import pymupdf as fitz
import pytest

from pdf_shrink import config, inspect_pdf, transform, validate
from pdf_shrink.models import OptimizationMode


def _photo_options() -> config.LossyOptions:
    return config.LossyOptions(
        photo_mode=True, dpi_target=200, quality=80,
        recompress_existing_jpeg=False, lossless=False,
    )


def _make_image_pdf(
    path: Path,
    *,
    width: int = 568,
    height: int | None = None,
    placements: tuple[tuple[float, float, float, float], ...] = ((0, 0, 144, 144),),
    image_format: str = "jpeg",
    special_key: tuple[str, str] | None = None,
    patch: bool = False,
    rotation: int = 0,
) -> None:
    height = height if height is not None else width
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height), 0)
    pixmap.clear_with(255)
    if patch:
        pixmap.set_rect(fitz.IRect(20, 20, 60, 60), (0, 0, 0))
    with fitz.open() as document:
        page = document.new_page(
            width=max(rect[2] for rect in placements),
            height=max(rect[3] for rect in placements),
        )
        xref = page.insert_image(
            fitz.Rect(placements[0]), stream=pixmap.tobytes(image_format),
            keep_proportion=False,
        )
        # PyMuPDF inserts its own sRGB ICC profile. This fixture deliberately
        # models the simple DeviceRGB JPEGs supported by the opt-in photo path.
        document.xref_set_key(xref, "ColorSpace", "/DeviceRGB")
        if special_key:
            document.xref_set_key(xref, *special_key)
        for placement in placements[1:]:
            page.insert_image(fitz.Rect(placement), xref=xref, keep_proportion=False)
        page.insert_text((12, 110), "Vector caption 123", fontsize=9)
        page.draw_line((5, 115), (130, 115), color=(1, 0, 0), width=0.5)
        page.set_rotation(rotation)
        document.save(path)


def _images(path: Path) -> list[tuple[int, int, bytes]]:
    with fitz.open(path) as document:
        return [
            (int(image[2]), int(image[3]), document.xref_stream(int(image[0])))
            for image in document[0].get_images(full=True)
        ]


def _inspect(path: Path) -> OptimizationMode:
    result = inspect_pdf.inspect_file(
        path, config.ScanOptions(), safe=False, lossy_options=_photo_options(),
    )
    assert result.ok, result.skip_reason
    return result.mode


def test_photo_resizes_284_dpi_jpeg_and_preserves_text_and_paths(tmp_path: Path) -> None:
    source, candidate = tmp_path / "source.pdf", tmp_path / "candidate.pdf"
    _make_image_pdf(source)
    assert _inspect(source) is OptimizationMode.LOSSY

    assert transform.optimize_lossy(source, candidate, _photo_options()) == 1

    assert _images(candidate)[0][:2] == (400, 400)
    with fitz.open(source) as original, fitz.open(candidate) as optimized:
        assert original[0].get_text() == optimized[0].get_text()
        assert original[0].get_drawings() == optimized[0].get_drawings()


@pytest.mark.parametrize("pixel_size", [238, 400])
def test_photo_preserves_jpeg_at_or_below_200_dpi(
    tmp_path: Path, pixel_size: int,
) -> None:
    source, candidate = tmp_path / "source.pdf", tmp_path / "candidate.pdf"
    _make_image_pdf(source, width=pixel_size)
    assert _inspect(source) is OptimizationMode.LOSSLESS
    assert transform.optimize_lossy(source, candidate, _photo_options()) == 0
    assert _images(candidate) == _images(source)


@pytest.mark.parametrize(
    "special_key",
    [
        ("Mask", "[0 0 0 0 0 0]"),
        ("Decode", "[1 0 1 0 1 0]"),
        ("DecodeParms", "<</ColorTransform 0>>"),
        ("ColorSpace", "/DeviceCMYK"),
    ],
)
def test_photo_keeps_masked_or_special_jpeg(
    tmp_path: Path, special_key: tuple[str, str],
) -> None:
    source, candidate = tmp_path / "source.pdf", tmp_path / "candidate.pdf"
    _make_image_pdf(source, special_key=special_key)
    assert _inspect(source) is OptimizationMode.LOSSLESS
    assert transform.optimize_lossy(source, candidate, _photo_options()) == 0
    assert _images(candidate) == _images(source)


def test_photo_keeps_non_jpeg_image(tmp_path: Path) -> None:
    source, candidate = tmp_path / "source.pdf", tmp_path / "candidate.pdf"
    _make_image_pdf(source, image_format="png")
    assert _inspect(source) is OptimizationMode.LOSSLESS
    assert transform.optimize_lossy(source, candidate, _photo_options()) == 0
    assert _images(candidate) == _images(source)


@pytest.mark.parametrize("kind", ["soft_mask", "bitonal", "icc"])
def test_photo_excludes_transparency_bitonal_and_icc_images(
    tmp_path: Path, kind: str,
) -> None:
    source, candidate = tmp_path / "source.pdf", tmp_path / "candidate.pdf"
    with fitz.open() as document:
        page = document.new_page(width=144, height=144)
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 600, 600), 0)
        pixmap.clear_with(100)
        if kind == "bitonal":
            pbm = b"P4\n600 600\n" + b"\xaa" * (600 * 600 // 8)
            xref = page.insert_image(page.rect, stream=pbm)
        elif kind == "soft_mask":
            mask = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 600, 600), 0)
            mask.clear_with(128)
            xref = page.insert_image(
                page.rect, stream=pixmap.tobytes("jpeg"), mask=mask.tobytes("png"),
            )
            document.xref_set_key(xref, "ColorSpace", "/DeviceRGB")
        else:
            xref = page.insert_image(page.rect, stream=pixmap.tobytes("jpeg"))
        document.save(source)
    assert _inspect(source) is OptimizationMode.LOSSLESS
    assert transform.optimize_lossy(source, candidate, _photo_options()) == 0
    assert _images(candidate) == _images(source)


def test_photo_preserves_low_dpi_placement_of_shared_xref(tmp_path: Path) -> None:
    source, candidate = tmp_path / "source.pdf", tmp_path / "candidate.pdf"
    _make_image_pdf(
        source, width=1200, placements=((0, 0, 144, 144), (0, 0, 576, 576)),
    )
    assert _inspect(source) is OptimizationMode.LOSSLESS
    assert transform.optimize_lossy(source, candidate, _photo_options()) == 0
    assert _images(candidate) == _images(source)


def test_photo_excludes_ambiguous_xrefs_including_unpainted_resources(tmp_path: Path) -> None:
    source, candidate = tmp_path / "source.pdf", tmp_path / "candidate.pdf"
    with fitz.open() as document:
        page = document.new_page(width=576, height=576)
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 1200, 1200), 0)
        pixmap.clear_with(128)
        original = page.insert_image(page.rect, stream=pixmap.tobytes("jpeg"))
        document.xref_set_key(original, "ColorSpace", "/DeviceRGB")
        duplicate = document.get_new_xref()
        document.update_object(duplicate, "<<>>")
        document.xref_copy(original, duplicate)
        resources = int(document.xref_get_key(page.xref, "Resources")[1].split()[0])
        document.xref_set_key(resources, "XObject/Duplicate", f"{duplicate} 0 R")
        # The first page paints original at 150 DPI; this unused resource makes
        # PyMuPDF attribute that placement to duplicate through the pixel digest.
        page = document.new_page(width=144, height=144)
        page.insert_image(page.rect, xref=original)
        document.save(source)

    with fitz.open(source) as document:
        assert document[0].get_image_info(xrefs=True)[0]["xref"] == duplicate
        assert document[1].get_image_info(xrefs=True)[0]["xref"] == original
        assert inspect_pdf._photo_xref_min_effective_dpis(document) == {}

    assert _inspect(source) is OptimizationMode.LOSSLESS
    assert transform.optimize_lossy(source, candidate, _photo_options()) == 0
    with fitz.open(candidate) as document:
        for page, expected_dpi in zip(document, (150, 600)):
            info = page.get_image_info()[0]
            assert (info["width"], info["height"]) == (1200, 1200)
            assert inspect_pdf._effective_image_dpis(info) == pytest.approx(
                (expected_dpi, expected_dpi),
            )


def test_photo_preserves_low_dpi_axis_but_can_resize_other_axis(tmp_path: Path) -> None:
    source, candidate = tmp_path / "source.pdf", tmp_path / "candidate.pdf"
    _make_image_pdf(
        source, width=1200, height=600,
        placements=((0, 0, 144, 144), (0, 0, 576, 144)),
    )
    assert _inspect(source) is OptimizationMode.LOSSY
    assert transform.optimize_lossy(source, candidate, _photo_options()) == 1
    assert _images(candidate)[0][:2] == (1200, 400)
    with fitz.open(candidate) as document:
        dpis = [inspect_pdf._effective_image_dpis(i) for i in document[0].get_image_info()]
    assert dpis == pytest.approx([(600, 200), (150, 200)])


def test_photo_dpi_rounding_never_crosses_below_target(tmp_path: Path) -> None:
    source, candidate = tmp_path / "source.pdf", tmp_path / "candidate.pdf"
    _make_image_pdf(source, width=569, placements=((0, 0, 144.1, 144.1),))
    assert transform.optimize_lossy(source, candidate, _photo_options()) == 1
    with fitz.open(candidate) as document:
        dpi_x, dpi_y = inspect_pdf._effective_image_dpis(document[0].get_image_info()[0])
    assert dpi_x >= 200
    assert dpi_y >= 200
    assert _images(candidate)[0][:2] == (401, 401)


def test_detail_detects_small_image_loss_missed_at_72_dpi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, candidate = tmp_path / "source.pdf", tmp_path / "candidate.pdf"
    _make_image_pdf(source, width=600, patch=True)
    _make_image_pdf(candidate, width=600, patch=False)
    monkeypatch.setattr(validate, "qpdf_check", lambda *_: 0)

    assert validate.validate(source, candidate, tmp_path / "qpdf.exe", enhanced=True)[0]
    ok, reason = validate.validate(source, candidate, tmp_path / "qpdf.exe", detail=True)
    assert not ok
    assert reason.startswith("render_detail_local_diff_too_large")


@pytest.mark.parametrize("rotation", [0, 90])
def test_detail_uses_bounded_tiles_and_accepts_safe_photo_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rotation: int,
) -> None:
    source, candidate = tmp_path / "source.pdf", tmp_path / "candidate.pdf"
    _make_image_pdf(source, rotation=rotation)
    transform.optimize_lossy(source, candidate, _photo_options())
    monkeypatch.setattr(validate, "qpdf_check", lambda *_: 0)
    original_render = fitz.Page.get_pixmap
    rendered_sizes: list[tuple[int, int]] = []

    def render(page, *args, **kwargs):
        if kwargs.get("dpi") == 300:
            assert kwargs.get("clip") is not None
        pixmap = original_render(page, *args, **kwargs)
        if kwargs.get("dpi") == 300:
            rendered_sizes.append((pixmap.width, pixmap.height))
        return pixmap

    monkeypatch.setattr(fitz.Page, "get_pixmap", render)
    ok, reason = validate.validate(source, candidate, tmp_path / "qpdf.exe", detail=True)
    assert ok, reason
    assert rendered_sizes
    assert all(max(size) <= 258 for size in rendered_sizes)


@pytest.mark.parametrize(
    ("limit", "value", "reason"),
    [
        ("_DETAIL_RENDER_MAX_PIXELS", 1, "render_detail_pixel_limit"),
        ("_DETAIL_RENDER_MAX_SECONDS", -1, "render_detail_time_limit"),
        ("_DETAIL_RENDER_MAX_REGIONS", 0, "render_detail_region_limit"),
    ],
)
def test_detail_rejects_incomplete_validation_when_budget_exceeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str, value: int, reason: str,
) -> None:
    source, candidate = tmp_path / "source.pdf", tmp_path / "candidate.pdf"
    _make_image_pdf(source)
    transform.optimize_lossy(source, candidate, _photo_options())
    monkeypatch.setattr(validate, limit, value)
    assert validate._compare_render_detail(source, candidate) == (False, reason)


def test_detail_rejects_page_geometry_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, candidate = tmp_path / "source.pdf", tmp_path / "candidate.pdf"
    _make_image_pdf(source)
    with fitz.open(source) as document:
        document[0].set_cropbox(fitz.Rect(0, 0, 143, 144))
        document.save(candidate)
    monkeypatch.setattr(validate, "qpdf_check", lambda *_: 0)
    assert validate.validate(source, candidate, tmp_path / "qpdf.exe", detail=True) == (
        False, "page_geometry_mismatch",
    )


def test_detail_matches_placements_after_xrefs_are_renumbered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, candidate = tmp_path / "source.pdf", tmp_path / "candidate.pdf"
    with fitz.open() as document:
        page = document.new_page(width=144, height=144)
        orphan = document.get_new_xref()
        document.update_object(orphan, "<</Unused true>>")
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 568, 568), 0)
        pixmap.clear_with(128)
        original_xref = page.insert_image(page.rect, stream=pixmap.tobytes("jpeg"))
        document.xref_set_key(original_xref, "ColorSpace", "/DeviceRGB")
        document.save(source)
    assert transform.optimize_lossy(source, candidate, _photo_options()) == 1
    with fitz.open(candidate) as document:
        assert document[0].get_images(full=True)[0][0] != original_xref
    monkeypatch.setattr(validate, "qpdf_check", lambda *_: 0)
    ok, reason = validate.validate(source, candidate, tmp_path / "qpdf.exe", detail=True)
    assert ok, reason


def test_photo_does_not_silently_ignore_unreadable_shared_placements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.pdf"
    _make_image_pdf(source)

    def unreadable(*_args, **_kwargs):
        raise RuntimeError("placement read failed")

    monkeypatch.setattr(fitz.Page, "get_image_info", unreadable)
    result = inspect_pdf.inspect_file(
        source, config.ScanOptions(), safe=False, lossy_options=_photo_options(),
    )
    assert not result.ok
    assert result.skip_reason.startswith("inspect_error:")
