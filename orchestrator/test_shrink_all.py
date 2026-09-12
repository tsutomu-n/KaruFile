from __future__ import annotations

import csv
import hashlib
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

import shrink_all
from shrink_all import (
    JPEG_EXTENSIONS,
    build_parser,
    collect_files,
    human_size,
    image_errors_match_manifest,
    image_manifest_matches_inputs,
    parse_image_manifest,
    parse_image_summary,
    parse_pdf_report,
    validate_directories,
)


IMAGE_MANIFEST_FIELDS = (
    "source_path",
    "source_size",
    "source_sha256",
    "output_path",
    "output_size",
    "output_sha256",
    "action",
    "error",
    "preset",
    "recipe_hash",
    "orig_width",
    "orig_height",
    "new_width",
    "new_height",
)


def _write_image_manifest(path: Path, rows: list[dict[str, object]] | None = None) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=IMAGE_MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows or [])


def _image_manifest_row(
    source: Path,
    output: Path,
    *,
    preset: str = "standard",
    action: str = "COPIED_ORIGINAL",
    error: str = "",
    dry_run: bool = False,
) -> dict[str, object]:
    source_bytes = source.read_bytes()
    output_bytes = output.read_bytes() if output.is_file() and not dry_run else None
    has_dimensions = action != "ERROR"
    return {
        "source_path": str(source.resolve()),
        "source_size": len(source_bytes),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "output_path": str(output.resolve()),
        "output_size": len(output_bytes) if output_bytes is not None else "",
        "output_sha256": hashlib.sha256(output_bytes).hexdigest() if output_bytes is not None else "",
        "action": action,
        "error": error,
        "preset": preset,
        "recipe_hash": shrink_all.IMAGE_RECIPE_HASHES[preset],
        "orig_width": 1 if has_dimensions else "",
        "orig_height": 1 if has_dimensions else "",
        "new_width": 1 if has_dimensions else "",
        "new_height": 1 if has_dimensions else "",
    }


PDF_REPORT_FIELDS = (
    "requested_policy", "classification", "permission_basis", "preservation_reason", "processing_schema",
    "lossless_jpeg_requested",
    "font_replacement_requested", "replacement_font", "replacement_font_sha256", "text_extraction_changed",
    "photo_dpi",
    "source_path",
    "source_size",
    "source_sha256",
    "output_path",
    "output_size",
    "output_sha256",
    "saved_bytes",
    "saved_percent",
    "status",
    "preset",
    "profile",
    "decision_reason",
    "candidate_size",
    "candidate_saved_bytes",
    "candidate_saved_percent",
    "images_changed",
    "candidate_details",
)


def _write_pdf_report(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=PDF_REPORT_FIELDS)
        writer.writeheader()
        writer.writerows({
            "processing_schema": 6,
            "requested_policy": row.get("profile", row.get("preset")),
            "classification": {"standard": "text", "compact": "text", "photo": "photo", "text": "text_table", "text_scan": "text_scan", "text_scan_bilevel": "text_scan", "font_replace": "font_replace", "preserve": "protected"}.get(row.get("profile", row.get("preset")), "text"),
            "permission_basis": "automatic_text_only" if row.get("profile", row.get("preset")) in {"standard", "compact"} else "explicit_" + str(row.get("profile")),
            "preservation_reason": "",
            "profile": row.get("preset"),
            "lossless_jpeg_requested": "false",
            "font_replacement_requested": "true" if row.get("profile") == "font_replace" else "false",
            "replacement_font": "Yu Gothic Regular" if row.get("profile") == "font_replace" else "",
            "replacement_font_sha256": "a" * 64 if row.get("profile") == "font_replace" else "",
            "text_extraction_changed": "false",
            "photo_dpi": 200 if row.get("profile") == "photo" else "",
            **row,
        } for row in rows)


VIDEO_REPORT_FIELDNAMES = (
    "safe",
    "remove_audio",
    "source_path",
    "source_size",
    "output_path",
    "output_size",
    "saved_bytes",
    "saved_percent",
    "status",
    "error_message",
    "preset",
    "source_sha256",
    "output_sha256",
    "reason",
    "video_codec",
    "audio_codec",
    "width",
    "height",
    "fps",
    "duration",
    "vmaf_mean",
    "vmaf_p5",
    "ffmpeg_version",
)


def _video_metadata(*, adopted: bool = False, audio_codec: str = "aac") -> dict[str, object]:
    if adopted:
        return {
            "safe": False,
            "remove_audio": False,
            "reason": "adopted test candidate",
            "video_codec": "av1",
            "audio_codec": audio_codec,
            "width": 1280,
            "height": 720,
            "fps": 30.0,
            "duration": 10.0,
            "vmaf_mean": 85.0,
            "vmaf_p5": 70.0,
            "ffmpeg_version": "ffmpeg test",
        }
    return {
        "reason": "copied original",
        "safe": False,
        "remove_audio": False,
        "video_codec": "",
        "audio_codec": "",
        "width": None,
        "height": None,
        "fps": None,
        "duration": None,
        "vmaf_mean": None,
        "vmaf_p5": None,
        "ffmpeg_version": "",
    }


def _write_video_report(
    path: Path,
    row: dict[str, object],
    *,
    fieldnames: tuple[str, ...] = VIDEO_REPORT_FIELDNAMES,
) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        serialized = dict(row)
        for flag in ("safe", "remove_audio"):
            if isinstance(serialized.get(flag), bool):
                serialized[flag] = str(serialized[flag]).lower()
        writer.writerow(serialized)


def _make_directory_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            pytest.skip(f"could not create test junction: {completed.stderr}")
    else:
        link.symlink_to(target, target_is_directory=True)


def test_human_size_formats_units():
    assert human_size(500) == "500.00 B"
    assert human_size(1536) == "1.50 KB"


def test_source_baseline_detects_replacement_after_earlier_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.pdf"
    later_source = tmp_path / "later.pdf"
    source.write_bytes(b"first")
    later_source.write_bytes(b"later")
    baseline = shrink_all._capture_source_baseline([source, later_source])
    previous = source.stat()
    replacement = tmp_path / "replacement.pdf"
    replacement.write_bytes(b"other")
    os.utime(replacement, ns=(previous.st_atime_ns, previous.st_mtime_ns))

    original_hash = shrink_all._stable_file_size_and_sha256

    def replace_earlier_source_after_later_hash(path: Path) -> tuple[int, str]:
        result = original_hash(path)
        if path == later_source.resolve():
            os.replace(replacement, source)
        return result

    monkeypatch.setattr(
        shrink_all,
        "_stable_file_size_and_sha256",
        replace_earlier_source_after_later_hash,
    )

    assert not shrink_all._source_baseline_matches(baseline)


def test_run_command_streams_but_returns_only_bounded_tail(capsys) -> None:
    code = (
        "import sys; "
        "sys.stdout.write('x' * (3 * 1024 * 1024)); "
        "sys.stdout.write('\\nResized 0 images (0 errors)\\n'); "
        "sys.stdout.flush()"
    )

    exit_code, lines, _elapsed = shrink_all.run_command(
        "bounded-output",
        shrink_all.PDF_SHRINK_DIR,
        ["python", "-c", code],
    )

    assert exit_code == 0
    assert len(lines) <= shrink_all.PROCESSOR_OUTPUT_TAIL_LINES
    assert all(
        len(line) <= shrink_all.PROCESSOR_MAX_RETURNED_LINE_CHARS for line in lines
    )
    assert lines[-1] == "Resized 0 images (0 errors)"
    assert len(capsys.readouterr().out) > 3 * 1024 * 1024


def test_run_command_uses_utf8_with_a_legacy_parent_console(monkeypatch) -> None:
    encoded = io.BytesIO()
    legacy_stdout = io.TextIOWrapper(encoded, encoding="cp932")
    with monkeypatch.context() as patch:
        patch.setenv("PYTHONIOENCODING", "cp932")
        patch.setattr(shrink_all.sys, "stdout", legacy_stdout)
        shrink_all._configure_console_output()
        exit_code, lines, _elapsed = shrink_all.run_command(
            "unicode-output",
            shrink_all.PDF_SHRINK_DIR,
            ["python", "-c", "print('\\u21d2\\U0001f9ea')"],
        )
    legacy_stdout.flush()

    assert exit_code == 0
    assert lines == ["\u21d2\U0001f9ea"]
    assert encoded.getvalue().decode("cp932").strip() == "\u21d2\\U0001f9ea"


def test_run_command_times_out_and_terminates_child_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shrink_all, "PROCESSOR_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(shrink_all, "PROCESSOR_TERMINATE_GRACE_SECONDS", 1.0)

    exit_code, _lines, elapsed = shrink_all.run_command(
        "timeout",
        shrink_all.PDF_SHRINK_DIR,
        ["python", "-c", "import time; time.sleep(60)"],
    )

    assert exit_code != 0
    assert elapsed < 5.0


def test_parse_image_summary_extracts_count_and_sizes():
    lines = [
        "some log line",
        "Resized 12 images (1 errors)",
        "  3.00 MB -> 1.20 MB",
    ]
    result = parse_image_summary(lines)
    assert result == {
        "count": 12,
        "errors": 1,
        "orig_size": 3 * 1024 * 1024,
        "new_size": int(1.2 * 1024 * 1024),
    }


def test_parse_image_summary_returns_none_without_summary_line():
    assert parse_image_summary(["no summary here"]) is None


def test_image_manifest_validates_exact_files_totals_and_error_mapping(tmp_path: Path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source = input_dir / "photo.jpg"
    output = output_dir / "photo.jpg"
    source.write_bytes(b"image-bytes")
    output.write_bytes(source.read_bytes())
    manifest_path = Path(f"{output_dir}.image-manifest.csv")
    error_report = Path(f"{output_dir}.image-errors.csv")
    _write_image_manifest(manifest_path, [_image_manifest_row(source, output)])
    error_report.write_text("source,planned_output,error\n", encoding="utf-8")

    result = parse_image_manifest(manifest_path)

    assert result["count"] == 1
    assert result["errors"] == 0
    assert result["orig_size"] == result["new_size"] == len(source.read_bytes())
    assert image_manifest_matches_inputs(
        result,
        [source],
        input_dir=input_dir,
        output_dir=output_dir,
        preset="standard",
        dry_run=False,
    )
    assert image_errors_match_manifest(error_report, result)
    error_report.write_text(
        "source,planned_output,error\nforged,forged,forged\n",
        encoding="utf-8",
    )
    assert not image_errors_match_manifest(error_report, result)


def test_image_manifest_rejects_malformed_and_raced_output(tmp_path: Path, monkeypatch):
    malformed = tmp_path / "malformed.csv"
    malformed.write_text("source_path,action\na,CONVERTED\n", encoding="utf-8")
    assert parse_image_manifest(malformed) == {}

    zero_source = tmp_path / "zero-source.jpg"
    zero_output = tmp_path / "zero-output.jpg"
    zero_source.write_bytes(b"source")
    zero_output.write_bytes(b"")
    zero_manifest = tmp_path / "zero-output.csv"
    _write_image_manifest(
        zero_manifest,
        [_image_manifest_row(zero_source, zero_output, action="CONVERTED")],
    )
    assert parse_image_manifest(zero_manifest) == {}

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source = input_dir / "photo.jpg"
    output = output_dir / "photo.jpg"
    source.write_bytes(b"source")
    output.write_bytes(source.read_bytes())
    report = tmp_path / "manifest.csv"
    _write_image_manifest(report, [_image_manifest_row(source, output)])
    parsed = parse_image_manifest(report)
    original_fingerprint = shrink_all._stable_file_size_and_sha256
    raced = False

    def fingerprint_then_replace(path: Path) -> tuple[int, str]:
        nonlocal raced
        fingerprint = original_fingerprint(path)
        if not raced and Path(path) == output:
            raced = True
            before = output.stat()
            replacement = output.with_name("replacement.jpg")
            replacement.write_bytes(b"forged")
            os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
            os.replace(replacement, output)
        return fingerprint

    monkeypatch.setattr(
        shrink_all,
        "_stable_file_size_and_sha256",
        fingerprint_then_replace,
    )
    assert not image_manifest_matches_inputs(
        parsed,
        [source],
        input_dir=input_dir,
        output_dir=output_dir,
        preset="standard",
        dry_run=False,
    )


def test_build_parser_requires_input():
    parser = build_parser()
    args = parser.parse_args(["-i", "C:\\some\\path"])
    assert args.input == "C:\\some\\path"
    assert args.pdf_workers == 2
    assert args.image_workers == 4
    assert args.video_workers == 1
    assert args.preset == "standard"
    assert args.pdf_photo_pattern == []


def test_build_parser_normalizes_repeated_photo_patterns():
    args = build_parser().parse_args(
        [
            "-i", "input",
            "--pdf-photo-pattern", r"./Photos\*.PDF",
            "--pdf-photo-pattern=-photo.pdf",
        ]
    )

    assert args.pdf_photo_pattern == ["Photos/*.PDF", "-photo.pdf"]


@pytest.mark.parametrize("pattern", ["", " ", ".", "/a.pdf", r"C:\a.pdf", "C:a.pdf", "../a.pdf", "a/../b.pdf"])
def test_build_parser_rejects_nonrelative_photo_patterns(pattern: str):
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["-i", "input", f"--pdf-photo-pattern={pattern}"])

    assert exc_info.value.code == 2


@pytest.mark.parametrize("option", ["--pdf-workers", "--image-workers", "--video-workers"])
def test_build_parser_rejects_non_positive_workers(option: str):
    parser = build_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["-i", "C:\\some\\path", option, "0"])

    assert exc_info.value.code == 2


def test_build_parser_accepts_compact_and_rejects_unknown_preset():
    parser = build_parser()

    assert parser.parse_args(["-i", "input", "--preset", "compact"]).preset == "compact"
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["-i", "input", "--preset", "tiny"])
    assert exc_info.value.code == 2


def test_parse_video_report_requires_known_status_and_preset(tmp_path: Path):
    report = tmp_path / "video.csv"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    source = tmp_path / "clip.mp4"
    source_bytes = b"v" * (shrink_all.VIDEO_MIN_SAVED_BYTES + 100)
    source.write_bytes(source_bytes)
    output = output_dir / "clip.mp4"
    output.write_bytes(b"tiny")
    saved = len(source_bytes) - 4
    saved_percent = saved / len(source_bytes) * 100
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    output_hash = hashlib.sha256(output.read_bytes()).hexdigest()
    row = {
        "source_path": str(source),
        "source_size": len(source_bytes),
        "output_path": str(output),
        "output_size": 4,
        "saved_bytes": saved,
        "saved_percent": saved_percent,
        "status": "ADOPTED",
        "error_message": "",
        "preset": "compact",
        "source_sha256": source_hash,
        "output_sha256": output_hash,
        **_video_metadata(adopted=True),
    }
    _write_video_report(
        report,
        row,
    )

    result = shrink_all.parse_video_report(report)

    assert result["count"] == 1
    assert result["errors"] == 0
    assert result["orig_size"] == len(source_bytes)
    assert result["new_size"] == 4
    assert shrink_all.video_report_matches_inputs(
        result,
        [source],
        input_dir=tmp_path,
        output_dir=output_dir,
        preset="compact",
        dry_run=False,
    )
    assert not shrink_all.video_report_matches_inputs(
        result,
        [source],
        input_dir=tmp_path,
        output_dir=output_dir,
        preset="standard",
        dry_run=False,
    )

    _write_video_report(report, {**row, "status": "UNKNOWN"})
    assert shrink_all.parse_video_report(report) == {}


@pytest.mark.parametrize(
    "missing",
    [
        "reason",
        "video_codec",
        "audio_codec",
        "width",
        "height",
        "fps",
        "duration",
        "vmaf_mean",
        "vmaf_p5",
        "ffmpeg_version",
    ],
)
def test_parse_video_report_requires_all_metadata_columns(
    tmp_path: Path,
    missing: str,
) -> None:
    report = tmp_path / "video.csv"
    fieldnames = tuple(field for field in VIDEO_REPORT_FIELDNAMES if field != missing)
    report.write_text(",".join(fieldnames) + "\n", encoding="utf-8")

    assert shrink_all.parse_video_report(report) == {}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reason", " "),
        ("width", "0"),
        ("height", "-1"),
        ("fps", "nan"),
        ("duration", "inf"),
        ("vmaf_mean", "-0.1"),
        ("vmaf_p5", "100.1"),
    ],
)
def test_parse_video_report_rejects_invalid_metadata_values(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    report = tmp_path / "video.csv"
    row = {
        "source_path": str(tmp_path / "clip.mp4"),
        "source_size": 5,
        "output_path": str(tmp_path / "output" / "clip.mp4"),
        "output_size": "",
        "saved_bytes": 0,
        "saved_percent": 0.0,
        "status": "DRY_RUN",
        "error_message": "",
        "preset": "compact",
        "source_sha256": "a" * 64,
        "output_sha256": "",
        **_video_metadata(),
    }
    row[field] = value
    _write_video_report(report, row)

    assert shrink_all.parse_video_report(report) == {}


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("source_size", 999),
        ("saved_bytes", 0),
        ("saved_percent", 0.0),
        ("output_path", "outside.mp4"),
        ("source_sha256", "0" * 64),
        ("output_sha256", "f" * 64),
        ("reason", ""),
        ("video_codec", "h264"),
        ("audio_codec", "opus"),
        ("width", 1282),
        ("width", 1279),
        ("height", 722),
        ("height", 719),
        ("fps", 30.1),
        ("fps", float("nan")),
        ("duration", 0.0),
        ("vmaf_mean", 84.9),
        ("vmaf_p5", 69.9),
        ("ffmpeg_version", ""),
    ],
)
def test_video_report_match_rejects_forged_row(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source = input_dir / "clip.mp4"
    output = output_dir / "clip.mp4"
    source_bytes = b"v" * (shrink_all.VIDEO_MIN_SAVED_BYTES + 100)
    source.write_bytes(source_bytes)
    output.write_bytes(b"tiny")
    saved = len(source_bytes) - 4
    row = {
        "source_path": str(source),
        "source_size": len(source_bytes),
        "output_path": str(output),
        "output_size": 4,
        "saved_bytes": saved,
        "saved_percent": saved / len(source_bytes) * 100,
        "status": "ADOPTED",
        "error_message": "",
        "preset": "compact",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        **_video_metadata(adopted=True),
    }
    row[field] = replacement
    result = {
        "count": 1,
        "source_paths": [str(source)],
        "presets": ["compact"],
        "rows": [row],
    }

    assert not shrink_all.video_report_matches_inputs(
        result,
        [source],
        input_dir=input_dir,
        output_dir=output_dir,
        preset="compact",
        dry_run=False,
    )


@pytest.mark.parametrize(
    ("suffix", "audio_codec", "status", "expected"),
    [
        (".mp4", "aac", "ADOPTED", True),
        (".m4v", "", "ADOPTED", True),
        (".mkv", "opus", "ADOPTED", True),
        (".webm", "", "ADOPTED", True),
        (".mp4", "opus", "ADOPTED", False),
        (".mkv", "aac", "ADOPTED", False),
        (".mp4", "aac", "SKIPPED_COMPLETE", True),
        (".mp4", "opus", "SKIPPED_COMPLETE", False),
    ],
)
def test_video_report_match_validates_adopted_metadata_and_container_audio(
    tmp_path: Path,
    suffix: str,
    audio_codec: str,
    status: str,
    expected: bool,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source = input_dir / f"clip{suffix}"
    output = output_dir / f"clip{suffix}"
    source_bytes = b"v" * (shrink_all.VIDEO_MIN_SAVED_BYTES + 100)
    source.write_bytes(source_bytes)
    output.write_bytes(b"tiny")
    saved = len(source_bytes) - output.stat().st_size
    row = {
        "source_path": str(source),
        "source_size": len(source_bytes),
        "output_path": str(output),
        "output_size": output.stat().st_size,
        "saved_bytes": saved,
        "saved_percent": saved / len(source_bytes) * 100,
        "status": status,
        "error_message": "",
        "preset": "compact",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        **_video_metadata(adopted=True, audio_codec=audio_codec),
    }
    result = {
        "count": 1,
        "source_paths": [str(source)],
        "presets": ["compact"],
        "rows": [row],
    }

    assert shrink_all.video_report_matches_inputs(
        result,
        [source],
        input_dir=input_dir,
        output_dir=output_dir,
        preset="compact",
        dry_run=False,
    ) is expected


def test_video_report_match_accepts_only_dry_run_shape_for_dry_run(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    source = input_dir / "clip.mp4"
    source.write_bytes(b"video")
    row = {
        "source_path": str(source),
        "source_size": 5,
        "output_path": str(output_dir / "clip.mp4"),
        "output_size": None,
        "saved_bytes": 0,
        "saved_percent": 0.0,
        "status": "DRY_RUN",
        "error_message": "",
        "preset": "compact",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "output_sha256": "",
        **_video_metadata(),
    }
    result = {
        "count": 1,
        "source_paths": [str(source)],
        "presets": ["compact"],
        "rows": [row],
    }

    assert shrink_all.video_report_matches_inputs(
        result,
        [source],
        input_dir=input_dir,
        output_dir=output_dir,
        preset="compact",
        dry_run=True,
    )
    assert not shrink_all.video_report_matches_inputs(
        result,
        [source],
        input_dir=input_dir,
        output_dir=output_dir,
        preset="compact",
        dry_run=False,
    )


@pytest.mark.parametrize(
    ("status", "output_bytes", "error_message", "expected"),
    [
        ("SKIPPED_STANDARD", b"video", "", False),
        ("SKIPPED_COMPLEX", b"tiny", "", False),
        ("SKIPPED_UNSUPPORTED", b"video", "", True),
        ("UNCHANGED", b"video", "", True),
        ("SKIPPED_COMPLETE", b"video", "", True),
        ("ADOPTED", b"tiny", "", False),
        ("ERROR", b"video", "processing failed", True),
        ("ERROR", b"video", "", False),
    ],
)
def test_video_report_match_enforces_status_semantics(
    tmp_path: Path,
    status: str,
    output_bytes: bytes,
    error_message: str,
    expected: bool,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source = input_dir / "clip.mp4"
    source.write_bytes(b"video")
    output = output_dir / "clip.mp4"
    output.write_bytes(output_bytes)
    source_size = source.stat().st_size
    output_size = output.stat().st_size
    saved = source_size - output_size
    row = {
        "source_path": str(source),
        "source_size": source_size,
        "output_path": str(output),
        "output_size": output_size,
        "saved_bytes": saved,
        "saved_percent": saved / source_size * 100,
        "status": status,
        "error_message": error_message,
        "preset": "compact",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        **_video_metadata(adopted=status == "ADOPTED"),
    }
    result = {
        "count": 1,
        "source_paths": [str(source)],
        "presets": ["compact"],
        "rows": [row],
    }

    assert shrink_all.video_report_matches_inputs(
        result,
        [source],
        input_dir=input_dir,
        output_dir=output_dir,
        preset="compact",
        dry_run=False,
    ) is expected


@pytest.mark.parametrize("race_target", ["source", "output"])
def test_video_report_match_rejects_atomic_replace_during_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    race_target: str,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source = input_dir / "clip.mp4"
    output = output_dir / "clip.mp4"
    source.write_bytes(b"video")
    output.write_bytes(b"video")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    output_hash = hashlib.sha256(output.read_bytes()).hexdigest()
    row = {
        "source_path": str(source),
        "source_size": 5,
        "output_path": str(output),
        "output_size": 5,
        "saved_bytes": 0,
        "saved_percent": 0.0,
        "status": "UNCHANGED",
        "error_message": "",
        "preset": "compact",
        "source_sha256": source_hash,
        "output_sha256": output_hash,
        **_video_metadata(),
    }
    result = {
        "count": 1,
        "source_paths": [str(source)],
        "presets": ["compact"],
        "rows": [row],
    }
    target = source if race_target == "source" else output
    original_hash = shrink_all._sha256_file
    raced = False

    def hash_then_replace(path: Path) -> str:
        nonlocal raced
        digest = original_hash(path)
        if not raced and Path(path) == target:
            raced = True
            before = target.stat()
            replacement = target.with_name(f"{target.name}.replacement")
            replacement.write_bytes(b"other")
            os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
            os.replace(replacement, target)
            os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
        return digest

    monkeypatch.setattr(shrink_all, "_sha256_file", hash_then_replace)
    assert not shrink_all.video_report_matches_inputs(
        result,
        [source],
        input_dir=input_dir,
        output_dir=output_dir,
        preset="compact",
        dry_run=False,
    )


def test_standard_keeps_v1_behavior_and_does_not_start_video(tmp_path: Path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "clip.mp4").write_bytes(b"video")
    image_report = Path(f"{output_dir}.image-errors.csv")
    calls: list[str] = []

    def fake_run(name, _project_dir, args):
        calls.append(name)
        assert name == "media-shrink"
        assert args[args.index("--preset") + 1] == "standard"
        image_report.write_text("source,planned_output,error\n", encoding="utf-8")
        _write_image_manifest(Path(f"{output_dir}.image-manifest.csv"))
        return 0, ["Resized 0 images (0 errors)", "0.00 B -> 0.00 B"], 0.01

    monkeypatch.setattr(shrink_all, "run_command", fake_run)

    assert shrink_all.main(["-i", str(input_dir), "-o", str(output_dir)]) == 0
    assert calls == ["media-shrink"]


@pytest.mark.parametrize("safe,remove_audio", [(False, False), (True, True)])
def test_compact_runs_video_and_validates_atomic_report(tmp_path: Path, monkeypatch, safe, remove_audio):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    source = input_dir / "clip.mp4"
    source_bytes = b"v" * (shrink_all.VIDEO_MIN_SAVED_BYTES + 100)
    source.write_bytes(source_bytes)
    image_report = Path(f"{output_dir}.image-errors.csv")
    video_report = Path(f"{output_dir}.video-report.csv")
    calls: list[str] = []

    def fake_run(name, _project_dir, args):
        calls.append(name)
        assert args[args.index("--preset") + 1] == "compact"
        if name == "media-shrink":
            image_report.write_text("source,planned_output,error\n", encoding="utf-8")
            _write_image_manifest(Path(f"{output_dir}.image-manifest.csv"))
            return 0, ["Resized 0 images (0 errors)", "0.00 B -> 0.00 B"], 0.01
        assert name == "video-shrink"
        assert ("--safe" in args) is safe
        assert ("--remove-audio" in args) is remove_audio
        output = output_dir / "clip.mp4"
        output.write_bytes(b"tiny")
        saved = len(source_bytes) - 4
        saved_percent = saved / len(source_bytes) * 100
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        output_hash = hashlib.sha256(output.read_bytes()).hexdigest()
        _write_video_report(
            video_report,
            {
                "source_path": str(source.resolve()),
                "source_size": len(source_bytes),
                "output_path": str(output.resolve()),
                "output_size": 4,
                "saved_bytes": saved,
                "saved_percent": saved_percent,
                "status": "ADOPTED",
                "error_message": "",
                "preset": "compact",
                "source_sha256": source_hash,
                "output_sha256": output_hash,
                **_video_metadata(adopted=True, audio_codec="" if remove_audio else "aac"),
                "safe": safe,
                "remove_audio": remove_audio,
            },
        )
        return 0, [], 0.01

    monkeypatch.setattr(shrink_all, "run_command", fake_run)

    assert shrink_all.main(
        ["-i", str(input_dir), "-o", str(output_dir), "--preset", "compact"]
        + (["--video-safe"] if safe else [])
        + (["--video-remove-audio"] if remove_audio else [])
    ) == 0
    assert calls == ["media-shrink", "video-shrink"]
    parsed = shrink_all.parse_video_report(video_report)
    assert not shrink_all.video_report_matches_inputs(
        parsed, [source], input_dir=input_dir, output_dir=output_dir,
        preset="compact", dry_run=False, safe=not safe, remove_audio=remove_audio,
    )
    if remove_audio:
        parsed["rows"][0]["audio_codec"] = "aac"
        assert not shrink_all.video_report_matches_inputs(
            parsed, [source], input_dir=input_dir, output_dir=output_dir,
            preset="compact", dry_run=False, safe=safe, remove_audio=True,
        )


def test_compact_rejects_video_state_hardlink_before_processors(
    tmp_path: Path,
    monkeypatch,
):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    state_dir = Path(f"{output_dir}.video-state")
    input_dir.mkdir()
    state_dir.mkdir()
    source = input_dir / "clip.mp4"
    source.write_bytes(b"video")
    os.link(source, state_dir / "state.sqlite3")
    monkeypatch.setattr(
        shrink_all,
        "run_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("processor must not be started")
        ),
    )

    assert shrink_all.main(
        ["-i", str(input_dir), "-o", str(output_dir), "--preset", "compact"]
    ) == 1
    assert source.read_bytes() == b"video"


@pytest.mark.parametrize("relationship", ["same", "output_below_input", "input_below_output"])
def test_validate_directories_rejects_overlapping_paths(tmp_path: Path, relationship: str):
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    if relationship == "same":
        output_dir = input_dir
    elif relationship == "output_below_input":
        output_dir = input_dir / "output"
    else:
        output_dir = tmp_path

    with pytest.raises(ValueError):
        validate_directories(input_dir.resolve(), output_dir.resolve())


def test_main_rejects_overlapping_paths_before_starting_processors(tmp_path: Path, monkeypatch):
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    def unexpected_run(*_args, **_kwargs):
        raise AssertionError("processor must not be started")

    monkeypatch.setattr(shrink_all, "run_command", unexpected_run)

    assert shrink_all.main(["-i", str(input_dir), "-o", str(input_dir)]) == 1


def test_main_propagates_image_processor_failure(tmp_path: Path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "broken.jpg").write_bytes(b"not a jpeg")

    def failed_image(name, _project_dir, _args):
        assert name == "media-shrink"
        return 1, ["Resized 0 images (1 errors)", "  10.00 B -> 0.00 B"], 0.01

    monkeypatch.setattr(shrink_all, "run_command", failed_image)

    assert shrink_all.main(["-i", str(input_dir), "-o", str(output_dir)]) == 1


def test_main_does_not_report_stale_results_after_start_failure(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    (input_dir / "document.pdf").write_bytes(b"not a pdf")
    (input_dir / "image.jpg").write_bytes(b"not a jpeg")
    (output_dir / "stale.jpg").write_bytes(b"stale")
    (tmp_path / "report.csv").write_text(
        "source_size,output_size,saved_bytes,status\n100,50,50,COPIED\n",
        encoding="utf-8",
    )
    Path(f"{output_dir}.image-errors.csv").write_text(
        "source,planned_output,error\n",
        encoding="utf-8",
    )
    _write_image_manifest(Path(f"{output_dir}.image-manifest.csv"))

    monkeypatch.setattr(
        shrink_all,
        "run_command",
        lambda *_args, **_kwargs: (1, [], 0.01),
    )

    assert shrink_all.main(["-i", str(input_dir), "-o", str(output_dir)]) == 1
    output = capsys.readouterr().out
    assert "PDF errors   : unknown" in output
    assert "Image errors : unknown" in output
    assert "Output size   : unknown" in output
    assert "not updated this run" in output


def test_parse_pdf_report_keeps_missing_output_size_unknown(tmp_path: Path):
    report = tmp_path / "report.csv"
    _write_pdf_report(
        report,
        [
            {
                "source_path": "C:/source.pdf",
                "source_size": 100,
                "source_sha256": "a" * 64,
                "output_path": "C:/output/source.pdf",
                "output_size": "",
                "output_sha256": "",
                "saved_bytes": 0,
                "saved_percent": 0,
                "status": "ERROR",
                "preset": "standard",
            }
        ],
    )

    result = parse_pdf_report(report)

    assert result["orig_size"] == 100
    assert result["new_size"] is None
    assert result["saved"] is None
    assert result["errors"] == 1


def test_parse_pdf_report_rejects_missing_required_columns(tmp_path: Path):
    report = tmp_path / "report.csv"
    report.write_text("garbage,columns\n1,2\n", encoding="utf-8")

    assert parse_pdf_report(report) == {}


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("source_size", 31),
        ("source_sha256", "f" * 64),
        ("output_path", "unexpected.pdf"),
        ("output_size", 31),
        ("output_sha256", "e" * 64),
        ("saved_bytes", 1),
        ("saved_percent", 0.1),
        ("status", "ADOPTED_LOSSLESS"),
        ("preset", "compact"),
        ("profile", "photo"),
        ("profile", ""),
        ("profile", "unknown"),
        ("lossless_jpeg_requested", "true"),
        ("lossless_jpeg_requested", "True"),
        ("lossless_jpeg_requested", ""),
    ],
)
def test_pdf_report_matcher_rejects_forged_row(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source = input_dir / "document.pdf"
    destination = output_dir / "document.pdf"
    source.write_bytes(b"%PDF-1.7\n" + b"A" * 23)
    destination.write_bytes(source.read_bytes())
    row: dict[str, object] = {
        "source_path": str(source.resolve()),
        "source_size": 32,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "output_path": str(destination.resolve()),
        "output_size": 32,
        "output_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "saved_bytes": 0,
        "saved_percent": 0,
        "status": "UNCHANGED",
        "preset": "standard",
    }
    report = tmp_path / "report.csv"
    _write_pdf_report(report, [row])
    parsed = parse_pdf_report(report)
    assert shrink_all.pdf_report_matches_inputs(
        parsed,
        [source],
        input_dir=input_dir,
        output_dir=output_dir,
        preset="standard",
        dry_run=False,
    )

    row[field] = replacement
    _write_pdf_report(report, [row])

    assert not shrink_all.pdf_report_matches_inputs(
        parse_pdf_report(report),
        [source],
        input_dir=input_dir,
        output_dir=output_dir,
        preset="standard",
        dry_run=False,
    )


@pytest.mark.parametrize("saved_bytes", [64 * 1024 - 1, 64 * 1024, 256 * 1024])
def test_pdf_photo_report_requires_selected_profile_and_its_savings_gate(
    tmp_path: Path, saved_bytes: int,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    (input_dir / "Photos").mkdir(parents=True)
    (output_dir / "Photos").mkdir(parents=True)
    source = input_dir / "Photos" / "site.PDF"
    output = output_dir / source.relative_to(input_dir)
    source.write_bytes(b"%PDF-1.7\n" + b"a" * (1024 * 1024 - 9))
    output.write_bytes(source.read_bytes()[:-saved_bytes])
    row = {
        "source_path": str(source.resolve()),
        "source_size": source.stat().st_size,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "output_path": str(output.resolve()),
        "output_size": output.stat().st_size,
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "saved_bytes": saved_bytes,
        "saved_percent": saved_bytes / source.stat().st_size,
        "status": "ADOPTED_LOSSY",
        "preset": "standard",
        "profile": "photo",
        "decision_reason": "ADOPTED",
        "candidate_size": output.stat().st_size,
        "candidate_saved_bytes": saved_bytes,
        "candidate_saved_percent": saved_bytes / source.stat().st_size,
        "images_changed": 1,
        "candidate_details": '[{"kind":"photo","reason":"ADOPTED"}]',
    }
    report = tmp_path / "report.csv"
    _write_pdf_report(report, [row])
    parsed = parse_pdf_report(report)
    match_options = dict(
        input_dir=input_dir, output_dir=output_dir, preset="standard", dry_run=False,
    )

    # A top-level wildcard includes subdirectories and matching ignores case.
    assert shrink_all.pdf_report_matches_inputs(
        parsed, [source], photo_patterns=["*SITE.pdf"], **match_options,
    ) is (saved_bytes >= 64 * 1024)
    assert not shrink_all.pdf_report_matches_inputs(parsed, [source], **match_options)

    row["profile"] = "standard"
    _write_pdf_report(report, [row])
    parsed = parse_pdf_report(report)
    assert not shrink_all.pdf_report_matches_inputs(
        parsed, [source], photo_patterns=["*SITE.pdf"], **match_options,
    )
    assert shrink_all.pdf_report_matches_inputs(
        parsed, [source], **match_options,
    ) is (saved_bytes > 0)


@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("jpeg_requested", [False, True])
def test_main_sends_photo_patterns_only_to_pdf_and_matches_each_profile(
    tmp_path: Path, monkeypatch, selected: bool, jpeg_requested: bool,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    (input_dir / "Photos").mkdir(parents=True)
    sources = [input_dir / "Photos" / "Site.PDF", input_dir / "diagram.pdf"]
    for source in sources:
        source.write_bytes(b"%PDF-1.7\ncontent")
    calls = []

    def fake_run(name, _project_dir, args):
        calls.append(name)
        patterns = [arg for arg in args if arg.startswith("--photo-pattern=")]
        if name == "pdf-shrink":
            assert ("--lossless-jpeg" in args) is jpeg_requested
            assert args[args.index("--jpegtran-path") + 1] == "manually-prepared.exe"
            assert patterns == (["--photo-pattern=photos/*.pdf", "--photo-pattern=-extra.pdf"] if selected else [])
            rows = []
            for index, source in enumerate(sources):
                output = output_dir / source.relative_to(input_dir)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(source.read_bytes())
                digest = hashlib.sha256(source.read_bytes()).hexdigest()
                rows.append({
                    "source_path": str(source.resolve()),
                    "source_size": source.stat().st_size,
                    "source_sha256": digest,
                    "output_path": str(output.resolve()),
                    "output_size": output.stat().st_size,
                    "output_sha256": digest,
                    "saved_bytes": 0,
                    "saved_percent": 0,
                    "status": "UNCHANGED",
                    "preset": "standard",
                    "profile": "photo" if selected and index == 0 else "standard",
                    "lossless_jpeg_requested": "true" if jpeg_requested else "false",
                })
            _write_pdf_report(output_dir.parent / "report.csv", rows)
        else:
            assert name == "media-shrink"
            assert "--lossless-jpeg" not in args and "--jpegtran-path" not in args
            assert patterns == []
            assert args[args.index("--preset") + 1] == "standard"
            Path(f"{output_dir}.image-errors.csv").write_text("source,planned_output,error\n", encoding="utf-8")
            _write_image_manifest(Path(f"{output_dir}.image-manifest.csv"))
        return 0, [], 0.01

    monkeypatch.setattr(shrink_all, "run_command", fake_run)
    cli_args = ["-i", str(input_dir), "-o", str(output_dir)]
    cli_args.extend(["--pdf-jpegtran-path", "manually-prepared.exe"])
    if jpeg_requested:
        cli_args.append("--pdf-lossless-jpeg")
    if selected:
        cli_args.extend(["--pdf-photo-pattern", r"photos\*.pdf", "--pdf-photo-pattern=-extra.pdf"])

    assert shrink_all.main(cli_args) == 0
    assert calls == ["pdf-shrink", "media-shrink"]


@pytest.mark.parametrize("missing", ["profile", "lossless_jpeg_requested", "photo_dpi"])
def test_parse_pdf_report_rejects_legacy_report_without_required_column(tmp_path: Path, missing: str) -> None:
    report = tmp_path / "report.csv"
    report.write_text(
        ",".join(field for field in PDF_REPORT_FIELDS if field != missing) + "\n",
        encoding="utf-8",
    )

    assert parse_pdf_report(report) == {}


def test_pdf_report_matcher_accepts_only_empty_dry_run_output(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    source = input_dir / "document.pdf"
    source.write_bytes(b"source")
    report = tmp_path / "report.csv"
    row: dict[str, object] = {
        "source_path": str(source.resolve()),
        "source_size": source.stat().st_size,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "output_path": str((output_dir / source.name).resolve()),
        "output_size": "",
        "output_sha256": "",
        "saved_bytes": 0,
        "saved_percent": 0,
        "status": "DRY_RUN_LOSSLESS",
        "preset": "standard",
    }
    _write_pdf_report(report, [row])

    assert shrink_all.pdf_report_matches_inputs(
        parse_pdf_report(report),
        [source],
        input_dir=input_dir,
        output_dir=output_dir,
        preset="standard",
        dry_run=True,
    )

    row["output_sha256"] = "f" * 64
    _write_pdf_report(report, [row])
    assert not shrink_all.pdf_report_matches_inputs(
        parse_pdf_report(report),
        [source],
        input_dir=input_dir,
        output_dir=output_dir,
        preset="standard",
        dry_run=True,
    )


def test_pdf_report_matcher_rejects_identical_hardlinked_output(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source = input_dir / "document.pdf"
    external = tmp_path / "external.pdf"
    destination = output_dir / source.name
    source.write_bytes(b"source")
    external.write_bytes(b"source")
    os.link(external, destination)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    report = tmp_path / "report.csv"
    _write_pdf_report(
        report,
        [
            {
                "source_path": str(source.resolve()),
                "source_size": source.stat().st_size,
                "source_sha256": digest,
                "output_path": str(destination.resolve()),
                "output_size": destination.stat().st_size,
                "output_sha256": digest,
                "saved_bytes": 0,
                "saved_percent": 0,
                "status": "UNCHANGED",
                "preset": "standard",
            }
        ],
    )

    assert not shrink_all.pdf_report_matches_inputs(
        parse_pdf_report(report),
        [source],
        input_dir=input_dir,
        output_dir=output_dir,
        preset="standard",
        dry_run=False,
    )


@pytest.mark.parametrize("report_kind", ["header_only", "garbage", "count_mismatch"])
def test_main_rejects_updated_pdf_report_that_does_not_match_current_inputs(
    tmp_path: Path,
    monkeypatch,
    capsys,
    report_kind: str,
):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    source = input_dir / "document.pdf"
    source.write_bytes(b"pdf")
    report_path = tmp_path / "report.csv"
    image_report = Path(f"{output_dir}.image-errors.csv")

    def fake_run(name, _project_dir, _args):
        if name == "pdf-shrink":
            if report_kind == "header_only":
                _write_pdf_report(report_path, [])
            elif report_kind == "garbage":
                report_path.write_text("garbage,columns\n1,2\n", encoding="utf-8")
            else:
                digest = hashlib.sha256(source.read_bytes()).hexdigest()
                row = {
                    "source_path": str(source.resolve()),
                    "source_size": 3,
                    "source_sha256": digest,
                    "output_path": str((output_dir / source.name).resolve()),
                    "output_size": 3,
                    "output_sha256": digest,
                    "saved_bytes": 0,
                    "saved_percent": 0,
                    "status": "UNCHANGED",
                    "preset": "standard",
                }
                _write_pdf_report(report_path, [row, row])
            return 0, [], 0.01
        image_report.write_text("source,planned_output,error\n", encoding="utf-8")
        _write_image_manifest(Path(f"{output_dir}.image-manifest.csv"))
        return 0, ["Resized 0 images (0 errors)", "0.00 B -> 0.00 B"], 0.01

    monkeypatch.setattr(shrink_all, "run_command", fake_run)

    assert shrink_all.main(["-i", str(input_dir), "-o", str(output_dir)]) == 1
    stdout = capsys.readouterr().out
    assert "PDF errors   : unknown" in stdout
    assert "Output size   : unknown" in stdout


def test_main_treats_pdf_report_error_as_failure_even_if_child_exits_zero(
    tmp_path: Path,
    monkeypatch,
):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    source = input_dir / "document.pdf"
    source.write_bytes(b"pdf")
    report_path = tmp_path / "report.csv"
    image_report = Path(f"{output_dir}.image-errors.csv")

    def fake_run(name, _project_dir, _args):
        if name == "pdf-shrink":
            _write_pdf_report(
                report_path,
                [
                    {
                        "source_path": str(source.resolve()),
                        "source_size": 3,
                        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "output_path": str((output_dir / source.name).resolve()),
                        "output_size": "",
                        "output_sha256": "",
                        "saved_bytes": 0,
                        "saved_percent": 0,
                        "status": "ERROR",
                        "preset": "standard",
                    }
                ],
            )
            return 0, [], 0.01
        image_report.write_text("source,planned_output,error\n", encoding="utf-8")
        _write_image_manifest(Path(f"{output_dir}.image-manifest.csv"))
        return 0, ["Resized 0 images (0 errors)", "0.00 B -> 0.00 B"], 0.01

    monkeypatch.setattr(shrink_all, "run_command", fake_run)

    assert shrink_all.main(["-i", str(input_dir), "-o", str(output_dir)]) == 1


def test_main_normalizes_unresolvable_input_to_exit_one():
    assert shrink_all.main(["-i", "\0"]) == 1


def test_jpeg_fallback_includes_both_extensions(tmp_path: Path):
    (tmp_path / "a.jpg").write_bytes(b"a")
    (tmp_path / "b.jpeg").write_bytes(b"b")
    (tmp_path / "ignored.png").write_bytes(b"c")

    assert {path.name for path in collect_files(tmp_path, JPEG_EXTENSIONS)} == {"a.jpg", "b.jpeg"}


def test_collect_files_rejects_linked_input_directory(tmp_path: Path):
    input_dir = tmp_path / "input"
    external = tmp_path / "external"
    input_dir.mkdir()
    external.mkdir()
    (external / "outside.pdf").write_bytes(b"outside")
    _make_directory_link(input_dir / "linked", external)

    with pytest.raises(ValueError, match="junction"):
        collect_files(input_dir, {".pdf"})


@pytest.mark.parametrize("filename", ["document.pdf", "image.png"])
def test_main_rejects_output_junction_into_input_before_processors(
    tmp_path: Path,
    monkeypatch,
    filename: str,
):
    input_dir = tmp_path / "input"
    source_dir = input_dir / "nested"
    output_dir = tmp_path / "output"
    source_dir.mkdir(parents=True)
    output_dir.mkdir()
    source = source_dir / filename
    source.write_bytes(b"source bytes")
    _make_directory_link(output_dir / "nested", source_dir)

    def unexpected_run(*_args, **_kwargs):
        raise AssertionError("processor must not be started")

    monkeypatch.setattr(shrink_all, "run_command", unexpected_run)

    assert shrink_all.main(["-i", str(input_dir), "-o", str(output_dir)]) == 1
    assert source.read_bytes() == b"source bytes"


def test_main_rejects_output_internal_junction_alias_before_processors(
    tmp_path: Path,
    monkeypatch,
):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    first = input_dir / "a" / "same.png"
    second = input_dir / "b" / "same.png"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    (output_dir / "b").mkdir(parents=True)
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    link = output_dir / "a"
    _make_directory_link(link, output_dir / "b")

    monkeypatch.setattr(
        shrink_all,
        "run_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("processor must not be started")
        ),
    )
    try:
        assert shrink_all.main(["-i", str(input_dir), "-o", str(output_dir)]) == 1
        assert first.read_bytes() == b"first"
        assert second.read_bytes() == b"second"
    finally:
        if link.exists():
            link.rmdir()


def test_main_rejects_file_directory_prefix_collision_before_processors(
    tmp_path: Path,
    monkeypatch,
):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "photo.png").write_bytes(b"image")
    pdf_dir = input_dir / "photo.png.jpg"
    pdf_dir.mkdir()
    (pdf_dir / "child.pdf").write_bytes(b"pdf")

    monkeypatch.setattr(
        shrink_all,
        "run_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("processor must not be started")
        ),
    )

    assert shrink_all.main(["-i", str(input_dir), "-o", str(output_dir)]) == 1


def test_image_only_prefix_collision_uses_same_hash_plan_as_media_tool(tmp_path: Path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    first = input_dir / "photo.png"
    nested_dir = input_dir / "photo.png.jpg"
    nested_dir.mkdir()
    second = nested_dir / "child.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    plans = shrink_all._plan_image_destinations(
        input_dir.resolve(),
        output_dir.resolve(),
        [first.resolve(), second.resolve()],
    )

    relative_outputs = [destination.relative_to(output_dir.resolve()) for _, destination in plans]
    assert relative_outputs[0].name.startswith("photo.png~")
    assert relative_outputs[1] == Path("photo.png.jpg") / "child.jpg"
    shrink_all.validate_planned_destinations(
        input_dir.resolve(),
        output_dir.resolve(),
        [],
        [first.resolve(), second.resolve()],
    )


@pytest.mark.parametrize("input_name", [".pdf-shrink", "report.csv", "report.dry-run.csv"])
def test_main_rejects_pdf_workspace_collision_before_processors(
    tmp_path: Path,
    monkeypatch,
    input_name: str,
):
    input_dir = tmp_path / input_name
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "document.pdf").write_bytes(b"pdf")
    monkeypatch.setattr(
        shrink_all,
        "run_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("processor must not be started")
        ),
    )

    assert shrink_all.main(["-i", str(input_dir), "-o", str(output_dir)]) == 1


@pytest.mark.parametrize(
    "suffix",
    [".image-errors.csv", ".image-manifest.csv", ".image-manifest.dry-run.csv"],
)
def test_main_rejects_image_report_collision_before_processors(
    tmp_path: Path,
    monkeypatch,
    suffix: str,
):
    output_dir = tmp_path / "output"
    input_dir = tmp_path / f"output{suffix}"
    input_dir.mkdir()
    (input_dir / "image.jpg").write_bytes(b"image")
    monkeypatch.setattr(
        shrink_all,
        "run_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("processor must not be started")
        ),
    )

    assert shrink_all.main(["-i", str(input_dir), "-o", str(output_dir)]) == 1


def test_main_rejects_pdf_state_junction_into_input_before_processors(
    tmp_path: Path,
    monkeypatch,
):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "document.pdf").write_bytes(b"pdf")
    _make_directory_link(tmp_path / ".pdf-shrink", input_dir)
    monkeypatch.setattr(
        shrink_all,
        "run_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("processor must not be started")
        ),
    )

    assert shrink_all.main(["-i", str(input_dir), "-o", str(output_dir)]) == 1


def test_main_rejects_planned_output_hardlink_to_cross_type_source(
    tmp_path: Path,
    monkeypatch,
):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    pdf = input_dir / "document.pdf"
    image = input_dir / "image.jpg"
    pdf.write_bytes(b"pdf")
    image.write_bytes(b"image")
    os.link(image, output_dir / "document.pdf")
    monkeypatch.setattr(
        shrink_all,
        "run_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("processor must not be started")
        ),
    )

    assert shrink_all.main(["-i", str(input_dir), "-o", str(output_dir)]) == 1
    assert image.read_bytes() == b"image"


@pytest.mark.parametrize(
    "derived_name",
    ["state.sqlite3", "state.sqlite3-journal", "state.sqlite3-wal", "state.sqlite3-shm"],
)
def test_main_rejects_pdf_state_hardlink_to_input_source(
    tmp_path: Path,
    monkeypatch,
    derived_name: str,
):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    state_dir = tmp_path / ".pdf-shrink"
    input_dir.mkdir()
    state_dir.mkdir()
    source = input_dir / "document.pdf"
    source.write_bytes(b"pdf")
    os.link(source, state_dir / derived_name)
    monkeypatch.setattr(
        shrink_all,
        "run_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("processor must not be started")
        ),
    )

    assert shrink_all.main(["-i", str(input_dir), "-o", str(output_dir)]) == 1
    assert source.read_bytes() == b"pdf"


def test_main_rechecks_destinations_after_output_directory_creation(
    tmp_path: Path,
    monkeypatch,
):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    source = input_dir / "image.jpg"
    source.write_bytes(b"image")
    original_validate = shrink_all.validate_planned_destinations
    calls = 0

    def inject_hardlink(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            os.link(source, output_dir / "image.jpg")
        return original_validate(*args, **kwargs)

    monkeypatch.setattr(shrink_all, "validate_planned_destinations", inject_hardlink)
    monkeypatch.setattr(
        shrink_all,
        "run_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("processor must not be started")
        ),
    )

    assert shrink_all.main(["-i", str(input_dir), "-o", str(output_dir)]) == 1
    assert calls == 2
    assert source.read_bytes() == b"image"


def test_main_uses_image_manifest_totals_and_ignores_stdout_summary(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source = input_dir / "image.jpg"
    output = output_dir / "image.jpg"
    source.write_bytes(b"image")
    output.write_bytes(source.read_bytes())
    image_report = Path(f"{output_dir}.image-errors.csv")
    image_manifest = Path(f"{output_dir}.image-manifest.csv")

    def fake_run(name, _project_dir, _args):
        assert name == "media-shrink"
        image_report.write_text("source,planned_output,error\n", encoding="utf-8")
        _write_image_manifest(image_manifest, [_image_manifest_row(source, output)])
        return 0, ["Resized 999 images (999 errors)", "9.00 TB -> 8.00 TB"], 0.01

    monkeypatch.setattr(shrink_all, "run_command", fake_run)

    assert shrink_all.main(["-i", str(input_dir), "-o", str(output_dir)]) == 0
    stdout = capsys.readouterr().out
    assert "Image errors : 0" in stdout
    assert "Original size : 5.00 B" in stdout


def test_main_uses_separate_dry_run_image_manifest(tmp_path: Path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    source = input_dir / "image.jpg"
    planned_output = output_dir / "image.jpg"
    source.write_bytes(b"image")
    error_report = Path(f"{output_dir}.image-errors.csv")
    dry_manifest = Path(f"{output_dir}.image-manifest.dry-run.csv")

    def fake_run(name, _project_dir, args):
        assert name == "media-shrink"
        assert "-n" in args
        error_report.write_text("source,planned_output,error\n", encoding="utf-8")
        _write_image_manifest(
            dry_manifest,
            [
                _image_manifest_row(
                    source,
                    planned_output,
                    action="DRY_RUN",
                    dry_run=True,
                )
            ],
        )
        return 0, [], 0.01

    monkeypatch.setattr(shrink_all, "run_command", fake_run)

    assert shrink_all.main(
        ["-i", str(input_dir), "-o", str(output_dir), "-n"]
    ) == 0
    assert dry_manifest.is_file()
    assert not Path(f"{output_dir}.image-manifest.csv").exists()
    assert not output_dir.exists()


def test_main_treats_reported_processor_errors_as_failure(tmp_path: Path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    source = input_dir / "image.jpg"
    source.write_bytes(b"image")
    planned_output = output_dir / "image.jpg"
    image_report = Path(f"{output_dir}.image-errors.csv")
    image_manifest = Path(f"{output_dir}.image-manifest.csv")
    error = "ValueError: invalid image"

    def fake_run(_name, _project_dir, _args):
        with image_report.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=("source", "planned_output", "error")
            )
            writer.writeheader()
            writer.writerow(
                {
                    "source": str(source.resolve()),
                    "planned_output": str(planned_output.resolve()),
                    "error": error,
                }
            )
        _write_image_manifest(
            image_manifest,
            [
                _image_manifest_row(
                    source,
                    planned_output,
                    action="ERROR",
                    error=error,
                )
            ],
        )
        return 0, ["Resized 999 images (0 errors)"], 0.01

    monkeypatch.setattr(shrink_all, "run_command", fake_run)

    assert shrink_all.main(["-i", str(input_dir), "-o", str(output_dir)]) == 1


def test_root_entry_help_succeeds():
    repo_root = Path(__file__).resolve().parent.parent
    completed = subprocess.run(
        [sys.executable, str(repo_root / "karufile.py"), "--help"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "karufile" in completed.stdout.lower()
    assert "--pdf-photo-pattern" in completed.stdout
