"""JPEG candidate safety, optional tools, selection, and reduction boundaries."""
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import time

import pymupdf as fitz
import pytest

from pdf_shrink import cli, config, discovery, lossless_jpeg as jpeg, qpdf, runner, worker
from pdf_shrink.models import InspectionResult, OptimizationMode as Mode, ProcessStatus as Status


@pytest.fixture
def jpeg_tool():
    path = os.environ.get("KARUFILE_TEST_JPEGTRAN")
    if not path:
        pytest.skip("set KARUFILE_TEST_JPEGTRAN to a manually prepared jpegtran 3.2.0")
    return jpeg.prepare_tool(Path(path))


def image_pdf(tmp_path, *, shared=False, gray=False):
    width = height = 160
    channels = 1 if gray else 3
    samples = bytes((x // 8 * 17 + y // 8 * 31 + c * 50) % 256 for y in range(height) for x in range(width) for c in range(channels))
    pix = fitz.Pixmap(fitz.csGRAY if gray else fitz.csRGB, width, height, samples, False)
    raw = pix.tobytes("jpeg", jpg_quality=88)
    source = tmp_path / "source.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=144, height=144)
        xref = page.insert_image(page.rect, stream=raw)  # 80 DPI: independent of photo/downsample selection.
        doc.xref_set_key(xref, "ColorSpace", "/DeviceGray" if gray else "/DeviceRGB")
        if shared:
            doc.new_page(width=144, height=144).insert_image(fitz.Rect(0, 0, 144, 144), xref=xref)
        doc.save(source)
    return source, xref, raw


@pytest.mark.parametrize("progressive", [False, True])
@pytest.mark.parametrize("gray", [False, True])
def test_real_jpeg_preserves_low_dpi_pixels_dictionary_and_shared_xref(tmp_path, monkeypatch, jpeg_tool, progressive, gray):
    source, xref, raw = image_pdf(tmp_path, shared=True, gray=gray)
    exe, version, digest = jpeg_tool
    cfg = replace(config.default_config(input_dir=tmp_path, output_dir=tmp_path / "out"), lossless_jpeg=True, jpegtran_path=exe, jpegtran_version=version, jpegtran_sha256=digest)
    calls = []
    real_run = jpeg.subprocess.run

    def record(cmd, **kwargs):
        if str(cmd[0]) == str(exe):
            calls.append(cmd)
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(jpeg.subprocess, "run", record)
    candidate = tmp_path / "candidate.pdf"
    deadline = time.monotonic() + 300
    changed = jpeg.optimize(source, candidate, cfg, qpdf.ensure_qpdf(), progressive=progressive, deadline=deadline)
    if gray and progressive:
        # This tiny gray fixture grows with progressive scan overhead.
        assert changed == 0 and not candidate.exists()
        encoded = real_run([str(exe), "-copy", "all", "-optimize", "-progressive"], input=raw, capture_output=True, check=True).stdout
        assert len(encoded) >= len(raw)
        assert jpeg.jpeg_header(raw) == jpeg.jpeg_header(encoded)
        assert jpeg.same_pixels(raw, encoded)
        return
    assert changed == 1
    assert len(calls) == 1
    assert ("-progressive" in calls[0]) is progressive
    jpeg.validate_exact(source, candidate, deadline)
    assert qpdf.qpdf_check(qpdf.ensure_qpdf(), candidate) == 0
    with fitz.open(source) as doc:
        assert doc.xref_stream_raw(xref) == raw
    with fitz.open(candidate) as doc:
        candidate_xref = doc[0].get_images()[0][0]
        optimized = doc.xref_stream_raw(candidate_xref)
        assert jpeg.jpeg_header(raw) == jpeg.jpeg_header(optimized)
        assert jpeg.same_pixels(raw, optimized)
        assert len(optimized) < len(raw)


@pytest.mark.parametrize(("key", "value"), [("BitsPerComponent", "1"), ("ColorSpace", "/DeviceCMYK"), ("Decode", "[0 1 0 1 0 1]"), ("DecodeParms", "<< /ColorTransform 1 >>"), ("Mask", "[0 0]"), ("SMask", "99 0 R"), ("Filter", "[/DCTDecode]"), ("ImageMask", "true"), ("Width", "20000000")])
def test_unsupported_images_are_untouched(tmp_path, key, value):
    source, xref, _ = image_pdf(tmp_path)
    with fitz.open(source) as doc:
        doc.xref_set_key(xref, key, value)
        assert not jpeg.eligible(doc, xref)


@pytest.mark.parametrize("raw", [b"", b"not jpeg", b"\xff\xd8\xff", b"\xff\xd8\xff\xdb\x00\x03\xff"])
def test_corrupt_jpeg_is_an_error(raw):
    with pytest.raises(ValueError):
        jpeg.jpeg_header(raw)


def test_tool_path_version_missing_and_no_implicit_enable(tmp_path, monkeypatch):
    args = cli.build_parser().parse_args(["run", "--input", str(tmp_path), "--jpegtran-path", str(tmp_path / "absent"), "--safe"])
    assert not config.build_config(args).lossless_jpeg
    monkeypatch.setattr(jpeg.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="not found"):
        jpeg.prepare_tool(None)
    exe = tmp_path / "tool.exe"
    exe.write_bytes(b"fake")
    monkeypatch.setattr(jpeg.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, b"libjpeg-turbo version 3.1.0", b""))
    with pytest.raises(RuntimeError, match="unsupported"):
        jpeg.prepare_tool(exe)


def test_path_lookup_and_explicit_precedence(tmp_path, monkeypatch):
    exe = tmp_path / "tool"
    exe.write_bytes(b"versioned")
    monkeypatch.setattr(jpeg.shutil, "which", lambda _: str(exe))
    monkeypatch.setattr(jpeg.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, b"", b"libjpeg-turbo version 3.2.0 (build test)\n"))
    assert jpeg.prepare_tool(None)[0] == exe.resolve()
    with pytest.raises(RuntimeError, match="not found"):
        jpeg.prepare_tool(tmp_path / "missing")


def test_dry_run_does_not_execute_tools_but_records_requested(tmp_path, monkeypatch):
    source, _, _ = image_pdf(tmp_path)
    cfg = replace(config.default_config(input_dir=tmp_path, output_dir=tmp_path / "out"), lossless_jpeg=True, dry_run=True, safe=True)
    monkeypatch.setattr(jpeg.subprocess, "run", lambda *a, **k: pytest.fail("dry run executed external tool"))
    prepared, tool = runner._prepare_tools(cfg)
    assert tool is None and prepared.lossless_jpeg
    result = worker.process_one_file(discovery.snapshot(source, tmp_path), prepared, tmp_path / "temp", None)
    assert result.lossless_jpeg_requested and result.output_size is None
    assert not result.output_path.exists()


@pytest.mark.parametrize("failure", ["warning", "nonzero", "timeout", "corrupt", "io", "pixels", "budget", "larger"])
def test_generation_failure_classification(tmp_path, monkeypatch, failure):
    source, _, raw = image_pdf(tmp_path)
    exe = tmp_path / "tool"
    exe.write_bytes(b"fake")
    cfg = replace(config.default_config(input_dir=tmp_path, output_dir=tmp_path / "out"), lossless_jpeg=True, jpegtran_path=exe, jpegtran_sha256=jpeg.file_sha256(exe))
    original_header = jpeg.jpeg_header(raw)

    def run(cmd, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(cmd, 30)
        if failure == "io":
            raise OSError("disk failure")
        payload = b"bad" if failure == "corrupt" else raw + (b"padding" if failure == "larger" else b"")
        Path(cmd[cmd.index("-outfile") + 1]).write_bytes(payload)
        return subprocess.CompletedProcess(cmd, 1 if failure == "nonzero" else 0, b"", b"warning" if failure == "warning" else b"\r  \r")

    monkeypatch.setattr(jpeg.subprocess, "run", run)
    if failure == "pixels":
        monkeypatch.setattr(jpeg, "same_pixels", lambda *a: False)
    candidate = tmp_path / "candidate.pdf"
    snapshot = discovery.snapshot(source, tmp_path)
    result = worker._evaluate_candidate(snapshot, cfg, candidate, Mode.LOSSLESS, "standard", Path("qpdf"), jpeg_kind="jpeg_lossless_baseline", deadline=0 if failure == "budget" else time.monotonic() + 300)
    assert result.reason == ("quality_rejected" if failure in {"pixels", "budget"} else "no_image_savings" if failure == "larger" else "processing_error")
    with fitz.open(source) as doc:
        assert jpeg.jpeg_header(doc.xref_stream_raw(doc[0].get_images()[0][0])) == original_header


@pytest.mark.parametrize("saved", [16 * 1024 - 1, 16 * 1024, 16 * 1024 + 1])
def test_lossless_byte_boundaries(saved):
    assert worker._meets_reduction(300_000, 300_000 - saved, Mode.LOSSLESS, config.ReductionOptions()) is (saved >= 16 * 1024)


@pytest.mark.parametrize("saved", [19_999, 20_000, 20_001])
def test_lossless_percent_boundaries(saved):
    assert worker._meets_reduction(1_000_000, 1_000_000 - saved, Mode.LOSSLESS, config.ReductionOptions()) is (saved >= 20_000)


def test_tool_and_reduction_changes_invalidate_state_hash(tmp_path):
    cfg = replace(config.default_config(input_dir=tmp_path), lossless_jpeg=True, jpegtran_version="3.2.0", jpegtran_sha256="a" * 64)
    for changed in [replace(cfg, lossless_jpeg=False), replace(cfg, jpegtran_sha256="b" * 64), replace(cfg, jpegtran_version="different"), replace(cfg, reduction=replace(cfg.reduction, lossless_min_bytes=64 * 1024))]:
        assert config.config_hash(cfg) != config.config_hash(changed)


@pytest.mark.parametrize(("sizes", "winner"), [([300000] * 4, 1), ([300000, 400000, 300000, 300000], 2), ([300000, 400000, 400000, 300000], 3), ([300000, 400000, 400000, 400000], 0)])
def test_candidate_tie_priority_and_primary_diagnostics(tmp_path, monkeypatch, sizes, winner):
    from test_photo_worker import _case
    from pdf_shrink.models import CandidateResult
    source, cfg = _case(tmp_path, monkeypatch)
    cfg = replace(cfg, lossless_jpeg=True)
    calls = []

    def evaluate(src, cfg, path, mode, profile, tool, **kwargs):
        index = len(calls)
        calls.append(src.path)
        path.write_bytes(bytes([index]) * sizes[index])
        return CandidateResult(kwargs.get("jpeg_kind") or ("photo" if mode is Mode.LOSSY else "lossless"), sizes[index], reason="eligible")

    monkeypatch.setattr(worker, "_evaluate_candidate", evaluate)
    result = worker.process_one_file(source, cfg, tmp_path / "temp", Path("qpdf"))
    assert calls == [source.path] * 4
    assert [c.selected for c in result.candidate_details] == [i == winner for i in range(4)]
    assert result.candidate_size == sizes[0]
    assert result.status is (Status.ADOPTED_LOSSY if winner == 0 else Status.ADOPTED_LOSSLESS)
    assert result.lossless_jpeg_requested
    if winner >= 2:
        assert result.decision_reason == "adopted_" + result.candidate_details[winner].kind


def test_exact_render_rejects_pixel_changes(tmp_path):
    source, xref, _ = image_pdf(tmp_path)
    candidate = tmp_path / "changed.pdf"
    with fitz.open(source) as doc:
        doc[0].delete_image(xref)
        doc.save(candidate)
    with pytest.raises(jpeg.CandidateRejected, match="render_mismatch"):
        jpeg.validate_exact(source, candidate, time.monotonic() + 300)


@pytest.mark.parametrize("failure", ["tool", "budget", "pixels"])
def test_jpeg_failure_preserves_primary_diagnostics_and_recovers_or_uses_alternative(tmp_path, monkeypatch, failure):
    from test_photo_worker import _case
    source, cfg = _case(tmp_path, monkeypatch)
    cfg = replace(cfg, lossless_jpeg=True)
    deadlines = []

    def optimize(src, path, cfg, tool, *, progressive, deadline):
        deadlines.append(deadline)
        if not progressive or failure == "tool":
            if failure == "tool":
                raise RuntimeError("tool broke")
            raise jpeg.CandidateRejected("jpeg_document_time_limit" if failure == "budget" else "jpeg_pixel_mismatch")
        path.write_bytes(b"P" * 200_000)
        return 3

    monkeypatch.setattr(jpeg, "optimize", optimize)
    monkeypatch.setattr(jpeg, "validate_exact", lambda *a: None)
    monkeypatch.setattr(worker.validate, "qpdf_check", lambda *a: 0)
    result = worker.process_one_file(source, cfg, tmp_path / "temp", Path("qpdf"))
    assert result.candidate_size == 350_000
    if failure == "tool":
        assert result.status is Status.ERROR
        assert result.output_path.read_bytes() == source.path.read_bytes()
        assert result.candidate_details[-1].reason == "processing_error"
        assert not any(c.selected for c in result.candidate_details)
    else:
        assert result.status is Status.ADOPTED_LOSSLESS
        assert result.candidate_details[2].reason == "quality_rejected"
        assert result.candidate_details[3].selected
        assert len(deadlines) == 2 and deadlines[0] == deadlines[1]


def test_changed_executable_is_error_before_candidate_generation(tmp_path):
    source, _, _ = image_pdf(tmp_path)
    exe = tmp_path / "changed-tool"
    exe.write_bytes(b"new")
    cfg = replace(config.default_config(input_dir=tmp_path), lossless_jpeg=True, jpegtran_path=exe, jpegtran_sha256="old")
    with pytest.raises(RuntimeError, match="changed"):
        jpeg.optimize(source, tmp_path / "candidate.pdf", cfg, Path("qpdf"), progressive=False, deadline=time.monotonic() + 300)


def test_qpdf_warning_is_error_in_jpeg_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(qpdf.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 3, "", "warning"))
    with pytest.raises(RuntimeError, match="rc=3"):
        qpdf.qpdf_optimize(Path("qpdf"), tmp_path / "source", tmp_path / "candidate", config.QpdfOptions(), reject_warnings=True)


def test_expired_budget_never_runs_jpegtran(tmp_path, monkeypatch):
    source, _, _ = image_pdf(tmp_path)
    cfg = config.default_config(input_dir=tmp_path)
    monkeypatch.setattr(jpeg.subprocess, "run", lambda *a, **k: pytest.fail("tool ran after budget expired"))
    with pytest.raises(jpeg.CandidateRejected, match="time_limit"):
        jpeg.optimize(source, tmp_path / "candidate", cfg, Path("qpdf"), progressive=False, deadline=0)
