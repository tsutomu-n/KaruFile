from __future__ import annotations

from pathlib import Path

import pymupdf as fitz
import pytest

from dataclasses import replace

from pdf_shrink import config, discovery, inspect_pdf, qpdf, transform, validate, worker
from pdf_shrink.models import OptimizationMode, ProcessStatus


def _max_effective_dpi(path: Path) -> float:
    document = fitz.open(path)
    try:
        return max(
            (
                inspect_pdf._effective_image_dpi(info)
                for page in document
                for info in inspect_pdf._page_image_infos(page)
            ),
            default=0.0,
        )
    finally:
        document.close()


def _effective_dpis(path: Path) -> list[tuple[float, float]]:
    with fitz.open(path) as document:
        return [
            inspect_pdf._effective_image_dpis(info)
            for page in document
            for info in inspect_pdf._page_image_infos(page)
        ]


def _write_jpeg_page(
    path: Path,
    *,
    page_size: float = 144,
    pixel_size: int,
    quality: int = 80,
    text: str | None = None,
) -> None:
    pixmap = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, pixel_size, pixel_size), 0)
    pixmap.clear_with(80)
    for offset in range(0, pixel_size, 17):
        pixmap.set_rect(fitz.IRect(offset, 0, offset + 3, pixel_size), (20,))
    jpeg = pixmap.tobytes("jpeg", jpg_quality=quality)
    document = fitz.open()
    page = document.new_page(width=page_size, height=page_size)
    page.insert_image(page.rect, stream=jpeg)
    if text is not None:
        page.insert_text((8, 24), text, fontsize=8)
    document.save(path)
    document.close()


def _write_anisotropic_reused_jpeg_page(path: Path) -> None:
    """Place one xref stretched on one axis, then reuse it rotated."""
    width, height = 1200, 601
    pixmap = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, width, height), 0)
    pixmap.clear_with(80)
    for offset in range(0, width, 19):
        pixmap.set_rect(fitz.IRect(offset, 0, offset + 2, height), (20,))
    jpeg = pixmap.tobytes("jpeg", jpg_quality=90)

    document = fitz.open()
    page = document.new_page(width=600, height=500)
    xref = page.insert_image(
        fitz.Rect(0, 0, 288, 143.99),
        stream=jpeg,
        keep_proportion=False,
    )
    page.insert_image(
        fitz.Rect(350, 0, 550, 400),
        xref=xref,
        rotate=90,
        keep_proportion=False,
    )
    document.save(path)
    document.close()


def _first_image(path: Path) -> tuple[int, int, str, bytes]:
    document = fitz.open(path)
    try:
        image = document[0].get_images(full=True)[0]
        return (
            int(image[2]),
            int(image[3]),
            str(image[8]),
            document.xref_stream_raw(int(image[0])),
        )
    finally:
        document.close()


def _write_decoded_rgb_jpeg_page(path: Path, *, pixel_size: int = 600) -> None:
    samples = bytes(
        (
            x * 37
            + y * 17
            + channel * 71
            + (x * y) % 251
        ) % 256
        for y in range(pixel_size)
        for x in range(pixel_size)
        for channel in range(3)
    )
    pixmap = fitz.Pixmap(
        fitz.csRGB,
        pixel_size,
        pixel_size,
        samples,
        False,
    )
    jpeg = pixmap.tobytes("jpeg", jpg_quality=95)
    document = fitz.open()
    page = document.new_page(width=72, height=72)
    xref = page.insert_image(page.rect, stream=jpeg)
    document.xref_set_key(xref, "Decode", "[1 0 1 0 1 0]")
    document.save(path)
    document.close()


def _write_soft_mask_page(path: Path, *, pixel_size: int = 1200) -> None:
    samples = bytes((40, 120, 200, 128)) * (pixel_size * pixel_size)
    pixmap = fitz.Pixmap(
        fitz.csRGB,
        pixel_size,
        pixel_size,
        samples,
        True,
    )
    document = fitz.open()
    page = document.new_page(width=144, height=144)
    page.insert_image(page.rect, stream=pixmap.tobytes("png"))
    document.save(path)
    document.close()


def _write_bitonal_page(path: Path, *, pixel_size: int = 1200) -> None:
    row = bytes((0xAA, 0x55)) * (pixel_size // 16)
    pbm = f"P4\n{pixel_size} {pixel_size}\n".encode("ascii") + row * pixel_size
    document = fitz.open()
    page = document.new_page(width=144, height=144)
    page.insert_image(page.rect, stream=pbm)
    document.save(path)
    document.close()


def test_text_only_pdf_stays_lossless(tmp_path: Path) -> None:
    path = tmp_path / "text.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "visible document text " * 8, fontsize=12)
    document.save(path)
    document.close()

    result = inspect_pdf.inspect_file(path, config.default_config().scan, safe=False)
    assert result.mode is OptimizationMode.LOSSLESS


def test_visible_text_with_600_dpi_image_is_lossy(tmp_path: Path) -> None:
    path = tmp_path / "text-and-photo.pdf"
    _write_jpeg_page(path, pixel_size=1200, text="visible body text " * 8)

    result = inspect_pdf.inspect_file(path, config.default_config().scan, safe=False)
    assert result.ok
    assert result.mode is OptimizationMode.LOSSY


def test_lossy_downsamples_placed_600_dpi_even_when_jfif_is_low(tmp_path: Path) -> None:
    source = tmp_path / "scan-jfif.pdf"
    candidate = tmp_path / "scan-jfif-out.pdf"
    _write_jpeg_page(source, pixel_size=1200)

    document = fitz.open(source)
    info = document[0].get_image_info()[0]
    jfif_dpi = min(float(info.get("xres") or 0), float(info.get("yres") or 0))
    document.close()
    assert jfif_dpi < 300
    assert _max_effective_dpi(source) == pytest.approx(600, rel=0.02)

    transform.optimize_lossy(source, candidate, config.LossyOptions())

    assert candidate.exists()
    assert _max_effective_dpi(candidate) == pytest.approx(300, rel=0.05)
    out = fitz.open(candidate)
    images = out[0].get_images(full=True)
    out.close()
    assert len(images) == 1
    image = images[0]
    assert image[2] == pytest.approx(600, rel=0.05)
    assert image[3] == pytest.approx(600, rel=0.05)


def test_lossy_limits_each_axis_for_anisotropic_reused_rotated_image(
    tmp_path: Path,
) -> None:
    source = tmp_path / "anisotropic.pdf"
    candidate = tmp_path / "anisotropic-out.pdf"
    _write_anisotropic_reused_jpeg_page(source)
    cfg = config.default_config()

    source_dpis = _effective_dpis(source)
    assert len(source_dpis) == 2
    # The first placement is exactly 300 DPI horizontally but slightly above
    # it vertically.  A scalar minimum-DPI calculation used to miss this case.
    assert source_dpis[0][0] == pytest.approx(300)
    assert source_dpis[0][1] > 300
    assert inspect_pdf.inspect_file(
        source,
        cfg.scan,
        safe=False,
        lossy_options=cfg.lossy,
    ).mode is OptimizationMode.LOSSY

    transform.optimize_lossy(source, candidate, cfg.lossy)

    width, height, _image_filter, _stream = _first_image(candidate)
    assert width == 1200  # the already-compliant axis is never upscaled
    assert height < 601
    assert all(
        dpi_x <= 300 and dpi_y <= 300
        for dpi_x, dpi_y in _effective_dpis(candidate)
    )


@pytest.mark.parametrize(
    "preset",
    [config.CompressionPreset.STANDARD, config.CompressionPreset.COMPACT],
)
def test_lossy_keeps_vector_text(
    tmp_path: Path,
    preset: config.CompressionPreset,
) -> None:
    source = tmp_path / "captioned.pdf"
    candidate = tmp_path / "captioned-out.pdf"
    text = "Caption text kept"
    _write_jpeg_page(source, pixel_size=1200, text=text)

    source_doc = fitz.open(source)
    source_text = source_doc[0].get_text()
    source_doc.close()
    assert text in source_text

    transform.optimize_lossy(
        source,
        candidate,
        config.default_config(preset=preset).lossy,
    )

    output = fitz.open(candidate)
    extracted = output[0].get_text()
    output.close()
    assert text in extracted
    assert extracted == source_text


def test_worker_adopts_lossy_600_dpi_jpeg(tmp_path: Path) -> None:
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    temp_root = tmp_path / "temp"
    input_dir.mkdir()
    temp_root.mkdir()
    source_path = input_dir / "scan.pdf"
    _write_jpeg_page(source_path, pixel_size=1200)

    cfg = replace(
        config.default_config(input_dir=input_dir, output_dir=output_dir),
        reduction=replace(
            config.ReductionOptions(),
            skip_below_bytes=1,
            lossy_min_bytes=1,
            lossy_min_percent=0.0,
        ),
    )
    source = discovery.snapshot(source_path, input_dir)
    result = worker.process_one_file(source, cfg, temp_root, qpdf.ensure_qpdf())

    assert result.status is ProcessStatus.PRESERVED_ORIGINAL
    assert result.candidate_details == ()
    assert result.output_path.read_bytes() == source_path.read_bytes()
    assert result.error_message is None
    assert _max_effective_dpi(result.output_path) == _max_effective_dpi(source_path)


def test_lossy_does_not_upscale_72_dpi_image(tmp_path: Path) -> None:
    source = tmp_path / "low-dpi.pdf"
    candidate = tmp_path / "low-dpi-out.pdf"
    _write_jpeg_page(source, pixel_size=144)

    assert inspect_pdf.inspect_file(
        source, config.default_config().scan, safe=False
    ).mode is OptimizationMode.LOSSLESS
    source_image = _first_image(source)
    transform.optimize_lossy(source, candidate, config.LossyOptions())
    candidate_image = _first_image(candidate)
    assert candidate_image[:2] == source_image[:2]
    assert candidate_image[3] == source_image[3]
    assert _max_effective_dpi(candidate) == pytest.approx(72, rel=0.05)


def test_compact_recompresses_300_dpi_jpeg_without_resizing(tmp_path: Path) -> None:
    source = tmp_path / "jpeg-300.pdf"
    candidate = tmp_path / "jpeg-300-out.pdf"
    _write_jpeg_page(source, pixel_size=600, quality=95)
    standard = config.default_config()
    compact = config.default_config(preset=config.CompressionPreset.COMPACT)

    assert inspect_pdf.inspect_file(
        source,
        standard.scan,
        safe=False,
        lossy_options=standard.lossy,
    ).mode is OptimizationMode.LOSSLESS
    assert inspect_pdf.inspect_file(
        source,
        compact.scan,
        safe=False,
        lossy_options=compact.lossy,
    ).mode is OptimizationMode.LOSSY

    source_width, source_height, source_filter, source_stream = _first_image(source)
    transform.optimize_lossy(source, candidate, compact.lossy)
    width, height, image_filter, candidate_stream = _first_image(candidate)

    assert (width, height) == (source_width, source_height) == (600, 600)
    assert "DCTDecode" in source_filter
    assert "DCTDecode" in image_filter
    assert candidate_stream != source_stream
    assert _max_effective_dpi(candidate) == pytest.approx(300, rel=0.05)


def test_compact_recompression_does_not_upscale_low_dpi_jpeg(tmp_path: Path) -> None:
    source = tmp_path / "jpeg-72.pdf"
    candidate = tmp_path / "jpeg-72-out.pdf"
    _write_jpeg_page(source, pixel_size=144, quality=95)
    compact = config.default_config(preset=config.CompressionPreset.COMPACT)

    transform.optimize_lossy(source, candidate, compact.lossy)

    assert _first_image(candidate)[:2] == _first_image(source)[:2] == (144, 144)
    assert _max_effective_dpi(candidate) == pytest.approx(72, rel=0.05)


def test_compact_keeps_jpeg_when_same_size_recompression_is_not_smaller(
    tmp_path: Path,
) -> None:
    source = tmp_path / "jpeg-quality-10.pdf"
    candidate = tmp_path / "jpeg-quality-10-out.pdf"
    _write_jpeg_page(source, pixel_size=600, quality=10)
    compact = config.default_config(preset=config.CompressionPreset.COMPACT)
    source_stream = _first_image(source)[3]

    transform.optimize_lossy(source, candidate, compact.lossy)

    assert _first_image(candidate)[3] == source_stream


@pytest.mark.parametrize(
    "preset",
    [config.CompressionPreset.STANDARD, config.CompressionPreset.COMPACT],
)
def test_lossy_clears_decode_after_recompressing_decoded_jpeg(
    tmp_path: Path,
    preset: config.CompressionPreset,
) -> None:
    source = tmp_path / "decoded-rgb.pdf"
    candidate = tmp_path / "decoded-rgb-out.pdf"
    _write_decoded_rgb_jpeg_page(source)
    cfg = config.default_config(preset=preset)

    transform.optimize_lossy(source, candidate, cfg.lossy)

    with fitz.open(candidate) as document:
        xref = int(document[0].get_images(full=True)[0][0])
        assert document.xref_get_key(xref, "Decode")[0] == "null"
    valid, reason = validate.validate(
        source,
        candidate,
        qpdf.ensure_qpdf(),
        enhanced=cfg.lossy.recompress_existing_jpeg,
    )
    assert valid, reason


@pytest.mark.parametrize(
    "image",
    [
        (1, 2, 600, 600, 8, "DeviceRGB", "", "", "DCTDecode"),
        (1, 0, 600, 600, 1, "DeviceGray", "", "", "DCTDecode"),
    ],
)
def test_compact_keeps_soft_masks_and_bitonal_images(image: tuple) -> None:
    compact = config.default_config(preset=config.CompressionPreset.COMPACT)

    assert not inspect_pdf._should_rewrite_image(image, compact.lossy)


def test_compact_keeps_real_soft_mask_image_unchanged(tmp_path: Path) -> None:
    source = tmp_path / "soft-mask.pdf"
    candidate = tmp_path / "soft-mask-out.pdf"
    _write_soft_mask_page(source)
    compact = config.default_config(preset=config.CompressionPreset.COMPACT)
    with fitz.open(source) as document:
        image = document[0].get_images(full=True)[0]
        assert int(image[1]) > 0
        source_streams = {
            xref: document.xref_stream(xref)
            for xref in (int(image[0]), int(image[1]))
        }

    transform.optimize_lossy(source, candidate, compact.lossy)

    with fitz.open(candidate) as document:
        image = document[0].get_images(full=True)[0]
        assert int(image[1]) > 0
        assert document.xref_stream(int(image[0])) == source_streams[int(image[0])]
        assert document.xref_stream(int(image[1])) == source_streams[int(image[1])]
    assert _max_effective_dpi(candidate) == pytest.approx(600, rel=0.05)


def test_compact_keeps_real_bitonal_image_unchanged(tmp_path: Path) -> None:
    source = tmp_path / "bitonal.pdf"
    candidate = tmp_path / "bitonal-out.pdf"
    _write_bitonal_page(source)
    compact = config.default_config(preset=config.CompressionPreset.COMPACT)
    with fitz.open(source) as document:
        image = document[0].get_images(full=True)[0]
        assert int(image[4]) == 1
        source_stream = document.xref_stream(int(image[0]))

    transform.optimize_lossy(source, candidate, compact.lossy)

    with fitz.open(candidate) as document:
        image = document[0].get_images(full=True)[0]
        assert int(image[4]) == 1
        assert document.xref_stream(int(image[0])) == source_stream
    assert _max_effective_dpi(candidate) == pytest.approx(600, rel=0.05)


def test_compact_worker_keeps_original_when_reduction_is_insufficient(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    temp_root = tmp_path / "temp"
    input_dir.mkdir()
    temp_root.mkdir()
    source_path = input_dir / "jpeg-300.pdf"
    _write_jpeg_page(source_path, pixel_size=600, quality=95)
    cfg = config.default_config(
        input_dir=input_dir,
        output_dir=output_dir,
        preset=config.CompressionPreset.COMPACT,
    )
    cfg = replace(
        cfg,
        reduction=replace(
            cfg.reduction,
            skip_below_bytes=1,
            lossy_min_bytes=source_path.stat().st_size + 1,
            lossy_min_percent=0.0,
        ),
    )

    result = worker.process_one_file(
        discovery.snapshot(source_path, input_dir),
        cfg,
        temp_root,
        qpdf.ensure_qpdf(),
    )

    assert result.status is ProcessStatus.PRESERVED_ORIGINAL
    assert result.candidate_details == ()
    assert result.output_path.read_bytes() == source_path.read_bytes()
    assert result.output_path.read_bytes() == source_path.read_bytes()


def test_compact_worker_adopts_300_dpi_jpeg_when_all_gates_pass(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    temp_root = tmp_path / "temp"
    input_dir.mkdir()
    temp_root.mkdir()
    source_path = input_dir / "jpeg-300.pdf"
    _write_jpeg_page(source_path, pixel_size=600, quality=95)
    cfg = config.default_config(
        input_dir=input_dir,
        output_dir=output_dir,
        preset=config.CompressionPreset.COMPACT,
    )
    cfg = replace(
        cfg,
        reduction=replace(
            cfg.reduction,
            skip_below_bytes=1,
            lossy_min_bytes=1,
            lossy_min_percent=0.0,
        ),
    )

    result = worker.process_one_file(
        discovery.snapshot(source_path, input_dir),
        cfg,
        temp_root,
        qpdf.ensure_qpdf(),
    )

    assert result.status is ProcessStatus.PRESERVED_ORIGINAL
    assert result.candidate_details == ()
    assert result.output_path.read_bytes() == source_path.read_bytes()
    assert result.output_size is not None
    assert result.output_size == source_path.stat().st_size
    assert _max_effective_dpi(result.output_path) == _max_effective_dpi(source_path)


def test_compact_worker_recovers_original_when_validation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    temp_root = tmp_path / "temp"
    input_dir.mkdir()
    temp_root.mkdir()
    source_path = input_dir / "jpeg-300.pdf"
    _write_jpeg_page(source_path, pixel_size=600, quality=95)
    cfg = config.default_config(
        input_dir=input_dir,
        output_dir=output_dir,
        preset=config.CompressionPreset.COMPACT,
    )
    cfg = replace(
        cfg,
        reduction=replace(cfg.reduction, skip_below_bytes=1),
    )
    monkeypatch.setattr(
        worker.validate,
        "validate",
        lambda *_args, **_kwargs: (False, "deliberate_validation_failure"),
    )

    result = worker.process_one_file(
        discovery.snapshot(source_path, input_dir),
        cfg,
        temp_root,
        tmp_path / "qpdf.exe",
    )

    assert result.status is ProcessStatus.PRESERVED_ORIGINAL
    assert result.candidate_details == ()
    assert result.output_path.read_bytes() == source_path.read_bytes()
    assert result.error_message is None
    assert result.output_path.read_bytes() == source_path.read_bytes()
    assert list(temp_root.rglob("*.pdf")) == []
