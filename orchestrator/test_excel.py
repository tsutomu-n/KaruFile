"""Excel opt-in, source protection, and independent report/package verification."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import struct
import zipfile
import zlib

import pytest

import shrink_all
from test_shrink_all import _write_image_manifest


def _png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    pixels = bytes((index * 19 + index // 11) % 256 for index in range(width * height * 3))
    raw = b"".join(b"\0" + pixels[row * width * 3:(row + 1) * width * 3] for row in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _xlsx(path: Path, width: int = 80, height: int = 60, *, extra: dict[str, bytes] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("[Content_Types].xml", b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="png" ContentType="image/png"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="bin" ContentType="application/octet-stream"/></Types>')
        archive.writestr("xl/workbook.xml", b"<workbook><formula>SUM(A1:A3)</formula></workbook>")
        archive.writestr("xl/media/image1.png", _png(width, height))
        for name, data in (extra or {}).items():
            archive.writestr(name, data)


def _row(source: Path, output: Path, status: str = "ADOPTED_LOSSY", *, dpi: int = 220) -> dict:
    original = source.read_bytes()
    completed = output.read_bytes() if status in {"ADOPTED_LOSSY", "PRESERVED_ORIGINAL"} else None
    return {
        "schema_version": "3", "source_path": str(source), "relative_path": source.name,
        "output_path": str(output), "source_size": len(original),
        "output_size": len(completed) if completed is not None else "",
        "source_sha256": hashlib.sha256(original).hexdigest(),
        "output_sha256": hashlib.sha256(completed).hexdigest() if completed is not None else "",
        "status": status, "dpi": dpi, "images_total": 1, "max_side": "", "jpeg_quality": 85,
        "images_changed": int(status == "ADOPTED_LOSSY"),
        "changed_parts": json.dumps(["xl/media/image1.png"] if status == "ADOPTED_LOSSY" else []),
        "reason": "candidate accepted" if status == "ADOPTED_LOSSY" else "protected or failed",
        "recipe_version": "grid2-pixel-jpeg-v2", "analysis_complete": "true", "diagnostics_complete": "true",
        "image_diagnostics": json.dumps([dict(part="xl/media/image1.png", format="PNG", size=[80,60],
            placements=1, required_pixels=[8,6], geometry_basis="validated_anchor", reasons=[],
            outcome="adopted" if status == "ADOPTED_LOSSY" else "preserved")]),
    }


def _report(path: Path, rows: list[dict], *, fields=None) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or sorted(shrink_all.EXCEL_REPORT_COLUMNS), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


@pytest.mark.parametrize("field,value", [
    ("analysis_complete", "1"), ("analysis_complete", "false"),
    ("diagnostics_complete", "False"), ("recipe_version", "stale"),
    ("image_diagnostics", '[{"part":"xl/media/image1.png","part":"xl/media/image1.png"}]'),
    ("image_diagnostics", "["*9+"0"+"]"*9),
    ("image_diagnostics", "[]"), ("images_total", ""),
])
def test_schema2_rejects_false_or_incomplete_adoption_diagnostics(case, field, value):
    report, _, _, row, _ = case
    row[field] = value
    _report(report, [row])
    assert shrink_all.parse_excel_report(report) == {}


def test_schema2_large_diagnostics_are_bounded_without_default_csv_limit(case):
    report, _, _, row, _ = case
    base = json.loads(row["image_diagnostics"])[0]
    records = [dict(base, part=f"xl/media/image{i}.png", outcome="preserved") for i in range(1000)]
    row.update(status="DRY_RUN_PRESERVED", output_size="", output_sha256="", images_total=1000,
               images_changed=0, changed_parts="[]", image_diagnostics=json.dumps(records))
    assert len(row["image_diagnostics"]) > 131072
    before = csv.field_size_limit()
    _report(report, [row])
    assert shrink_all.parse_excel_report(report)["count"] == 1
    assert csv.field_size_limit() == before
    records[0]["part"] = "x" * (2 * 1024 * 1024)
    row["image_diagnostics"] = json.dumps(records)
    _report(report, [row])
    assert shrink_all.parse_excel_report(report) == {}
    assert csv.field_size_limit() == before


def test_schema2_rejects_false_image_inventory(case):
    report, source, _, row, options = case
    row.update(images_total=2, diagnostics_complete="false")
    _report(report, [row])
    assert not shrink_all.excel_report_matches_inputs(shrink_all.parse_excel_report(report), [source], **options)


@pytest.fixture
def case(tmp_path):
    inputs, outputs = tmp_path / "input", tmp_path / "output"
    source, output = inputs / "photo.xlsx", outputs / "photo.xlsx"
    _xlsx(source)
    _xlsx(output, 8, 6)
    report = tmp_path / "output.excel-report.csv"
    options = dict(input_dir=inputs, output_dir=outputs, dpi=220, dry_run=False)
    return report, source, output, _row(source, output), options


def test_excel_default_is_disabled_without_discovery(monkeypatch, tmp_path):
    args = shrink_all.build_parser().parse_args(["-i", str(tmp_path)])
    assert args.excel_pattern == [] and args.excel_dpi is None
    assert args.excel_max_side == 800 and args.excel_jpeg_quality == 72
    monkeypatch.setattr(shrink_all, "collect_files", lambda *_args: pytest.fail("Excel discovery when disabled"))
    assert shrink_all.collect_excel_files(tmp_path, []) == []


def test_excel_selection_is_relative_case_insensitive_and_skips_locks(tmp_path):
    nested = tmp_path / "Reports" / "2026"
    nested.mkdir(parents=True)
    for name in ("A.XLSX", "~$A.xlsx", "B.xlsm", "C.xlsb", "D.xls"):
        (nested / name).write_bytes(b"test")
    (tmp_path / "else.xlsx").write_bytes(b"test")
    args = shrink_all.build_parser().parse_args([
        "-i", str(tmp_path), "--excel-pattern", r".\reports\*.xlsx", "--excel-pattern=-extra.xlsx",
    ])
    assert args.excel_pattern == ["reports/*.xlsx", "-extra.xlsx"]
    assert shrink_all.collect_excel_files(tmp_path, args.excel_pattern) == [nested / "A.XLSX"]


@pytest.mark.parametrize("arguments", [
    ["--excel-dpi", "220"], ["--excel-pattern", "../*.xlsx"], ["--excel-pattern", ""],
    ["--excel-pattern", r"C:\*.xlsx"], ["--excel-pattern", "/a.xlsx"],
    ["--excel-pattern", "*", "--excel-dpi", "149"], ["--excel-pattern", "*", "--excel-dpi", "301"],
    ["--excel-pattern", "*", "--excel-dpi", "220.0"], ["--excel-pattern", "*", "--excel-dpi", "+220"],
])
def test_excel_invalid_options_fail_preflight(arguments):
    with pytest.raises(SystemExit) as caught:
        shrink_all.build_parser().parse_args(["-i", "input", *arguments])
    assert caught.value.code == 2


@pytest.mark.parametrize('options', [
    ['--excel-max-side','800'], ['--excel-jpeg-quality','72'],
    ['--excel-pattern','*','--excel-max-side','99'],
    ['--excel-pattern','*','--excel-max-side','800','--excel-dpi','220'],
    ['--excel-pattern','*','--excel-jpeg-quality','39'],
])
def test_pixel_options_reject_invalid_requests(options):
    with pytest.raises(SystemExit):
        shrink_all.build_parser().parse_args(['-i','input',*options])


def test_pixel_report_requires_exact_requested_cap_and_quality(case):
    report,source,output,row,options=case
    row.update(dpi='',max_side=100,jpeg_quality=72,status='DRY_RUN',output_size='',
               output_sha256='',changed_parts='[]',images_changed=0)
    diagnostics=json.loads(row['image_diagnostics'])
    diagnostics[0].update(required_pixels=[80,60],geometry_basis='pixel_cap',outcome='planned')
    row['image_diagnostics']=json.dumps(diagnostics)
    _report(report,[row])
    request=dict(options,dpi=None,max_side=100,jpeg_quality=72,dry_run=True)
    parsed=shrink_all.parse_excel_report(report)
    assert shrink_all.excel_report_matches_inputs(parsed,[source],**request)
    assert not shrink_all.excel_report_matches_inputs(parsed,[source],**dict(request,max_side=800))
    assert not shrink_all.excel_report_matches_inputs(parsed,[source],**dict(request,jpeg_quality=85))
    diagnostics[0]['required_pixels']=[79,60]
    row['image_diagnostics']=json.dumps(diagnostics)
    _report(report,[row])
    assert shrink_all.parse_excel_report(report) == {}


def test_same_size_jpeg_requires_pixel_mode(tmp_path):
    # Minimal JPEG header exercises only the independent dimensions validator.
    header=b'\xff\xd8\xff\xc0'+struct.pack('>H B H H B',17,8,60,80,3)+b'\x01\x11\x00\x02\x11\x00\x03\x11\x00'
    source,output=tmp_path/'before.xlsx',tmp_path/'after.xlsx'
    types=b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="jpg" ContentType="image/jpeg"/></Types>'
    for path,padding in [(source,100),(output,10)]:
        with zipfile.ZipFile(path,'w') as archive:
            archive.writestr('[Content_Types].xml',types)
            archive.writestr('xl/media/a.jpg',header+b'\xff\xd9'+b'x'*padding)
    assert not shrink_all._excel_adopted_package_matches(source,output,['xl/media/a.jpg'])
    assert shrink_all._excel_adopted_package_matches(source,output,['xl/media/a.jpg'],max_side=800)


@pytest.mark.parametrize("status", ["ADOPTED_LOSSY", "PRESERVED_ORIGINAL", "ERROR", "DRY_RUN", "DRY_RUN_PRESERVED"])
def test_excel_reports_bind_all_supported_statuses_to_current_bytes(case, status):
    report, source, output, _original_row, options = case
    if status == "PRESERVED_ORIGINAL":
        output.write_bytes(source.read_bytes())
    row = _row(source, output, status)
    _report(report, [row])
    options["dry_run"] = status.startswith("DRY_RUN")
    parsed = shrink_all.parse_excel_report(report)
    assert shrink_all.excel_report_matches_inputs(parsed, [source], **options)
    assert parsed["errors"] == int(status == "ERROR")
    if status.startswith("DRY_RUN"):
        assert not shrink_all.excel_report_matches_inputs(parsed, [source], **dict(options, dry_run=False))


@pytest.mark.parametrize(("field", "value"), [
    ("schema_version", "1"), ("schema_version", "01"), ("source_sha256", "A" * 64),
    ("output_sha256", "g" * 64), ("output_size", "-1"), ("source_size", "1.0"),
    ("images_changed", 0), ("images_total", 0), ("changed_parts", "{}"),
    ("changed_parts", '["xl/workbook.xml"]'), ("changed_parts", '["xl/media/../image.png"]'),
    ("changed_parts", '["xl/media/image%2F1.png"]'),
    ("changed_parts", '["xl/media/image1.png", "xl/media/image1.png"]'),
    ("changed_parts", "[]"), ("changed_parts", "[null]"), ("reason", ""),
    ("dpi", 301), ("status", "SKIPPED_COMPLETE"),
])
def test_excel_parser_rejects_malformed_or_inconsistent_rows(case, field, value):
    report, _source, _output, row, _options = case
    row[field] = value
    _report(report, [row])
    assert shrink_all.parse_excel_report(report) == {}


@pytest.mark.parametrize("missing", sorted(shrink_all.EXCEL_REPORT_COLUMNS))
def test_excel_parser_requires_every_column(case, missing):
    report, _source, _output, row, _options = case
    _report(report, [row], fields=sorted(shrink_all.EXCEL_REPORT_COLUMNS - {missing}))
    assert shrink_all.parse_excel_report(report) == {}


@pytest.mark.parametrize(("field", "value"), [
    ("dpi", 150), ("source_sha256", "a" * 64), ("output_sha256", "b" * 64),
    ("source_size", 20_000), ("output_size", 1), ("relative_path", "different.xlsx"),
    ("source_path", "photo.xlsx"), ("output_path", "photo.xlsx"), ("dpi", True),
    ("schema_version", 1), ("images_changed", True), ("images_total", -1),
])
def test_excel_matcher_independently_rejects_forged_metadata(case, field, value):
    report, source, _output, row, options = case
    _report(report, [row])
    parsed = shrink_all.parse_excel_report(report)
    assert shrink_all.excel_report_matches_inputs(parsed, [source], **options)
    parsed["rows"][0][field] = value
    assert not shrink_all.excel_report_matches_inputs(parsed, [source], **options)


def test_excel_report_requires_exact_selected_file_set_and_accurate_totals(case):
    report, source, _output, row, options = case
    _report(report, [row, row])
    parsed = shrink_all.parse_excel_report(report)
    assert not shrink_all.excel_report_matches_inputs(parsed, [source, source], **options)
    _report(report, [row])
    parsed = shrink_all.parse_excel_report(report)
    assert not shrink_all.excel_report_matches_inputs(parsed, [], **options)
    parsed["saved"] += 1
    assert not shrink_all.excel_report_matches_inputs(parsed, [source], **options)


@pytest.mark.parametrize("mutation", ["xml", "added_part", "undeclared_image", "upscale", "same_dimensions", "fake_image", "duplicate", "traversal"])
def test_excel_rejects_package_tampering_even_with_matching_output_hash(case, mutation):
    report, source, output, _row_before, options = case
    if mutation == "upscale":
        _xlsx(output, 81, 1)
    elif mutation == "same_dimensions":
        # A smaller ZIP is not proof that any image was downscaled.
        with zipfile.ZipFile(source) as archive, zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for info in archive.infolist():
                target.writestr(info.filename, archive.read(info))
    else:
        with zipfile.ZipFile(output, "a") as archive:
            if mutation == "xml":
                archive.writestr("xl/new-formula.xml", b"<evil/>")
            elif mutation == "added_part":
                archive.writestr("xl/media/extra.png", _png(1, 1))
            elif mutation == "undeclared_image":
                archive.writestr("xl/media/image2.png", _png(1, 1))
        if mutation in {"fake_image", "duplicate", "traversal"}:
            with zipfile.ZipFile(output, "w") as archive:
                archive.writestr("[Content_Types].xml", b"<Types/>")
                archive.writestr("xl/workbook.xml", b"<workbook><formula>SUM(A1:A3)</formula></workbook>")
                archive.writestr("xl/media/image1.png", b"not an image" if mutation == "fake_image" else _png(1, 1))
                if mutation == "duplicate":
                    with pytest.warns(UserWarning, match="Duplicate name"):
                        archive.writestr("xl/media/image1.png", _png(1, 1))
                if mutation == "traversal":
                    archive.writestr("../outside.xml", b"unsafe")
    _report(report, [_row(source, output)])
    assert not shrink_all.excel_report_matches_inputs(shrink_all.parse_excel_report(report), [source], **options)


def test_excel_rejects_actual_nondeclared_xml_change(case):
    report, source, output, _row_before, options = case
    with zipfile.ZipFile(output) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    parts["xl/workbook.xml"] = b"<workbook>CHANGED</workbook>"
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    _report(report, [_row(source, output)])
    assert not shrink_all.excel_report_matches_inputs(shrink_all.parse_excel_report(report), [source], **options)


def test_excel_rejects_output_and_report_hardlinks(case):
    report, source, output, _row_before, options = case
    linked = output.with_name("linked.xlsx")
    os.link(output, linked)
    _report(report, [_row(source, output)])
    assert not shrink_all.excel_report_matches_inputs(shrink_all.parse_excel_report(report), [source], **options)
    os.link(report, report.with_name("linked.csv"))
    assert shrink_all.parse_excel_report(report) == {}


@pytest.mark.parametrize("derived", ["excel-work", "excel-report.csv", "excel-report.dry-run.csv"])
def test_excel_derived_paths_cannot_overlap_inputs(tmp_path, derived):
    output = tmp_path / "output"
    inputs = Path(f"{output}.{derived}")
    inputs.mkdir()
    source = inputs / "photo.xlsx"
    source.write_bytes(b"source")
    with pytest.raises(ValueError, match="入力"):
        shrink_all.validate_derived_write_paths(inputs, output, [], [], excel_files=[source])


def test_excel_output_hardlink_preflight_protects_other_processor_source(tmp_path):
    inputs, outputs = tmp_path / "input", tmp_path / "output"
    inputs.mkdir()
    outputs.mkdir()
    excel, image = inputs / "book.xlsx", inputs / "photo.jpg"
    excel.write_bytes(b"workbook")
    image.write_bytes(b"image")
    os.link(image, outputs / "book.xlsx")
    with pytest.raises(ValueError, match="hardlink"):
        shrink_all.validate_planned_destinations(inputs, outputs, [], [image], excel_files=[excel])


@pytest.mark.parametrize("preset", ["standard", "compact"])
@pytest.mark.parametrize("status", ["PRESERVED_ORIGINAL", "ERROR", "DRY_RUN", "DRY_RUN_PRESERVED", "stale"])
def test_excel_root_pipeline_and_failure_codes(tmp_path, monkeypatch, preset, status):
    inputs, outputs = tmp_path / "input", tmp_path / "output"
    source, output = inputs / "book.xlsx", outputs / "book.xlsx"
    _xlsx(source)
    dry_run = status.startswith("DRY_RUN")
    calls = []
    excel_report = Path(f"{outputs}.excel-report{'.dry-run' if dry_run else ''}.csv")
    if status == "stale":
        _report(excel_report, [])

    def run(name, project, arguments):
        calls.append(name)
        if name == "media-shrink":
            Path(f"{outputs}.image-errors.csv").write_text("source,planned_output,error\n", encoding="utf-8")
            _write_image_manifest(Path(f"{outputs}.image-manifest{'.dry-run' if dry_run else ''}.csv"))
            return 0, ["Resized 900 images (0 errors)"], 0.01
        assert name == "excel-shrink" and project == shrink_all.EXCEL_SHRINK_DIR
        assert arguments[:2] == ["excel-shrink", "run"]
        assert "--pattern=*.xlsx" in arguments
        assert arguments[arguments.index("--dpi") + 1] == "150"
        assert ("--dry-run" in arguments) is dry_run
        if status == "stale":
            return 0, [], 0.01
        if status == "PRESERVED_ORIGINAL":
            output.write_bytes(source.read_bytes())
        _report(excel_report, [_row(source, output, status, dpi=150)])
        return 0, ["Success: no errors"], 0.01

    monkeypatch.setattr(shrink_all, "run_command", run)
    arguments = ["-i", str(inputs), "-o", str(outputs), "--preset", preset,
                 "--excel-pattern", "*.xlsx", "--excel-dpi", "150"]
    if dry_run:
        arguments.append("--dry-run")
    assert shrink_all.main(arguments) == int(status in {"ERROR", "stale"})
    assert calls == ["media-shrink", "excel-shrink"]


def test_excel_disabled_does_not_launch_component_or_copy_books(tmp_path, monkeypatch):
    inputs, outputs = tmp_path / "input", tmp_path / "output"
    _xlsx(inputs / "book.xlsx")
    calls = []
    def run(name, _project, _arguments):
        calls.append(name)
        Path(f"{outputs}.image-errors.csv").write_text("source,planned_output,error\n", encoding="utf-8")
        _write_image_manifest(Path(f"{outputs}.image-manifest.csv"))
        return 0, [], 0
    monkeypatch.setattr(shrink_all, "run_command", run)
    assert shrink_all.main(["-i", str(inputs), "-o", str(outputs)]) == 0
    assert calls == ["media-shrink"]
    assert not (outputs / "book.xlsx").exists()
    assert not Path(f"{outputs}.excel-work").exists()
    assert not Path(f"{outputs}.excel-report.csv").exists()


@pytest.mark.parametrize("changed_path", ["source", "output"])
def test_excel_detects_file_replacement_during_package_validation(case, monkeypatch, changed_path):
    report, source, output, row, options = case
    _report(report, [row])
    def mutate(*_args):
        target = source if changed_path == "source" else output
        target.write_bytes(target.read_bytes() + b"changed during package verification")
        return True
    monkeypatch.setattr(shrink_all, "_excel_adopted_package_matches", mutate)
    assert not shrink_all.excel_report_matches_inputs(shrink_all.parse_excel_report(report), [source], **options)


def test_excel_zip_entry_and_xml_expansion_budgets(tmp_path):
    path = tmp_path / "large.xlsx"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", b"x" * (8 * 1024 * 1024 + 1))
    with zipfile.ZipFile(path) as archive, pytest.raises(ValueError, match="ZIP entry"):
        shrink_all._excel_zip_index(archive)
    with zipfile.ZipFile(path, "w") as archive:
        for index in range(4097):
            archive.writestr(f"entry{index}", b"")
    with zipfile.ZipFile(path) as archive, pytest.raises(ValueError, match="budget"):
        shrink_all._excel_zip_index(archive)


def test_excel_pipeline_continues_independent_processors_after_errors(tmp_path, monkeypatch):
    inputs, outputs = tmp_path / "input", tmp_path / "output"
    _xlsx(inputs / "book.xlsx")
    (inputs / "book.pdf").write_bytes(b"%PDF-test")
    (inputs / "clip.mp4").write_bytes(b"video")
    calls = []
    def run(name, _project, _arguments):
        calls.append(name)
        if name == "media-shrink":
            Path(f"{outputs}.image-errors.csv").write_text("source,planned_output,error\n", encoding="utf-8")
            _write_image_manifest(Path(f"{outputs}.image-manifest.csv"))
        return 1, ["processor failed"], 0
    monkeypatch.setattr(shrink_all, "run_command", run)
    assert shrink_all.main(["-i", str(inputs), "-o", str(outputs), "--preset", "compact", "--excel-pattern", "*"]) == 1
    assert calls == ["pdf-shrink", "media-shrink", "excel-shrink", "video-shrink"]


def test_excel_root_checks_starting_source_baseline_after_forged_current_report(tmp_path, monkeypatch, caplog):
    inputs, outputs = tmp_path / "input", tmp_path / "output"
    source, output = inputs / "book.xlsx", outputs / "book.xlsx"
    _xlsx(source)
    def run(name, _project, _arguments):
        if name == "media-shrink":
            Path(f"{outputs}.image-errors.csv").write_text("source,planned_output,error\n", encoding="utf-8")
            _write_image_manifest(Path(f"{outputs}.image-manifest.csv"))
        else:
            source.write_bytes(source.read_bytes() + b"source changed")
            output.write_bytes(source.read_bytes())
            _report(Path(f"{outputs}.excel-report.csv"), [_row(source, output, "PRESERVED_ORIGINAL")])
        return 0, [], 0
    monkeypatch.setattr(shrink_all, "run_command", run)
    assert shrink_all.main(["-i", str(inputs), "-o", str(outputs), "--excel-pattern", "*"]) == 1
    assert "Input source files changed" in caplog.text


def test_excel_preservation_is_byte_exact_even_when_source_cannot_be_parsed(case):
    report, source, output, _row_before, options = case
    source.write_bytes(b"encrypted or unsupported workbook")
    output.write_bytes(source.read_bytes())
    row = _row(source, output, "PRESERVED_ORIGINAL")
    row.update(images_total="", analysis_complete="false", diagnostics_complete="false", image_diagnostics="[]")
    _report(report, [row])
    assert shrink_all.excel_report_matches_inputs(shrink_all.parse_excel_report(report), [source], **options)
    output.write_bytes(b"a different byte sequence")
    _report(report, [_row(source, output, "PRESERVED_ORIGINAL")])
    assert shrink_all.parse_excel_report(report) == {}


@pytest.mark.parametrize("header", [b"", b"\xff\xd8", b"\xff\xd8\xff\xc0\x00\x01", b"\x89PNG\r\n\x1a\n"])
def test_excel_rejects_truncated_image_headers(header):
    with pytest.raises(ValueError):
        shrink_all._excel_image_dimensions(header)


def test_excel_jpeg_dimensions_are_parsed_independently():
    header = b"\xff\xd8\xff\xe0\x00\x04JF\xff\xc0\x00\x0b\x08\x00\x3c\x00\x50\x01\x01\x11\x00"
    assert shrink_all._excel_image_dimensions(header) == ("JPEG", 80, 60)


@pytest.mark.parametrize("names", [("xl/media", "xl/media/"), ("xl/media/image%20.png",)])
def test_excel_zip_ambiguous_encoded_or_directory_names_are_rejected(tmp_path, names):
    path = tmp_path / "ambiguous.xlsx"
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, b"")
    with zipfile.ZipFile(path) as archive, pytest.raises(ValueError, match="ZIP entry"):
        shrink_all._excel_zip_index(archive)


def _end_record(*, entries=0, directory_size=0, directory_offset=0, comment=b""):
    return struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, entries, entries,
                       directory_size, directory_offset, len(comment)) + comment


@pytest.mark.parametrize("payload", [
    _end_record(entries=4097),
    _end_record(entries=1, directory_size=4 * 1024 * 1024 + 1),
    _end_record(entries=65535),
    b"PK\x06\x07" + b"\0" * 16 + _end_record(directory_size=20),
])
@pytest.mark.parametrize("malicious_path", ["source", "output"])
def test_excel_report_rejects_directory_budgets_before_zipfile_allocation(case, monkeypatch, payload, malicious_path):
    report, source, output, _old_row, options = case
    if malicious_path == "source":
        source.write_bytes(b"padding" * 1000 + payload)
    else:
        output.write_bytes(payload)
    _report(report, [_row(source, output)])
    parsed = shrink_all.parse_excel_report(report)
    assert parsed  # Hashes and reduction claims alone appear valid.
    monkeypatch.setattr(shrink_all.zipfile, "ZipFile", lambda *_a, **_k: pytest.fail("ZipInfo allocation before directory validation"))
    assert not shrink_all.excel_report_matches_inputs(parsed, [source], **options)


def test_excel_directory_counts_actual_records_before_zipfile_allocation(case, monkeypatch):
    report, source, output, _old_row, options = case
    entry = b"PK\x01\x02" + b"\0" * 24 + struct.pack("<3H", 1, 0, 0) + b"\0" * 12 + b"x"
    directory = entry * 4097
    source.write_bytes(directory + _end_record(entries=1, directory_size=len(directory)))
    _report(report, [_row(source, output)])
    parsed = shrink_all.parse_excel_report(report)
    assert parsed
    monkeypatch.setattr(shrink_all.zipfile, "ZipFile", lambda *_a, **_k: pytest.fail("untrusted central records allocated"))
    assert not shrink_all.excel_report_matches_inputs(parsed, [source], **options)


def test_excel_ambiguous_zip_comment_is_not_adopted(case):
    _report_path, source, _output, _old_row, _options = case
    with zipfile.ZipFile(source, "a") as archive:
        archive.comment = b"a legitimate comment containing PK\x05\x06 bytes"
    with pytest.raises(ValueError, match="ambiguous"):
        shrink_all._excel_preflight_directory(source)


def test_excel_zip_index_rejects_names_zipinfo_silently_truncates():
    from types import SimpleNamespace
    item = zipfile.ZipInfo("xl/media/image.png\0different")
    assert item.filename != item.orig_filename
    with pytest.raises(ValueError, match="ZIP entry"):
        shrink_all._excel_zip_index(SimpleNamespace(infolist=lambda: [item]))
