from __future__ import annotations

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
    parse_image_summary,
    parse_pdf_report,
    validate_directories,
)


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


def test_build_parser_requires_input():
    parser = build_parser()
    args = parser.parse_args(["-i", "C:\\some\\path"])
    assert args.input == "C:\\some\\path"
    assert args.pdf_workers == 2
    assert args.image_workers == 4


@pytest.mark.parametrize("option", ["--pdf-workers", "--image-workers"])
def test_build_parser_rejects_non_positive_workers(option: str):
    parser = build_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["-i", "C:\\some\\path", option, "0"])

    assert exc_info.value.code == 2


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
    report.write_text(
        "source_path,source_size,output_size,saved_bytes,status\n"
        "C:/source.pdf,100,,,ERROR\n",
        encoding="utf-8",
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
    header = "source_path,source_size,output_size,saved_bytes,status\n"

    def fake_run(name, _project_dir, _args):
        if name == "pdf-shrink":
            if report_kind == "header_only":
                contents = header
            elif report_kind == "garbage":
                contents = "garbage,columns\n1,2\n"
            else:
                row = f"{source.resolve()},3,3,0,UNCHANGED\n"
                contents = header + row + row
            report_path.write_text(contents, encoding="utf-8")
            return 0, [], 0.01
        image_report.write_text("source,planned_output,error\n", encoding="utf-8")
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
            report_path.write_text(
                "source_path,source_size,output_size,saved_bytes,status\n"
                f"{source.resolve()},3,,,ERROR\n",
                encoding="utf-8",
            )
            return 0, [], 0.01
        image_report.write_text("source,planned_output,error\n", encoding="utf-8")
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


def test_main_rejects_image_error_report_collision_before_processors(
    tmp_path: Path,
    monkeypatch,
):
    output_dir = tmp_path / "output"
    input_dir = tmp_path / "output.image-errors.csv"
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


@pytest.mark.parametrize(
    ("summary_lines", "expected_images"),
    [
        ([], 1),
        (["Resized 0 images (0 errors)", "0.00 B -> 0.00 B"], 1),
    ],
)
def test_main_rejects_missing_or_mismatched_image_summary_without_stale_fallback(
    tmp_path: Path,
    monkeypatch,
    capsys,
    summary_lines: list[str],
    expected_images: int,
):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    (input_dir / "image.jpg").write_bytes(b"image")
    (output_dir / "stale.jpg").write_bytes(b"stale")
    image_report = Path(f"{output_dir}.image-errors.csv")

    def fake_run(name, _project_dir, _args):
        assert name == "media-shrink"
        image_report.write_text("source,planned_output,error\n", encoding="utf-8")
        return 0, summary_lines, 0.01

    monkeypatch.setattr(shrink_all, "run_command", fake_run)

    assert expected_images == 1
    assert shrink_all.main(["-i", str(input_dir), "-o", str(output_dir)]) == 1
    assert "Image errors : unknown" in capsys.readouterr().out


def test_main_treats_reported_processor_errors_as_failure(tmp_path: Path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "image.jpg").write_bytes(b"image")
    image_report = Path(f"{output_dir}.image-errors.csv")

    def fake_run(_name, _project_dir, _args):
        image_report.write_text("source,planned_output,error\n", encoding="utf-8")
        return 0, ["Resized 0 images (1 errors)", "0.00 B -> 0.00 B"], 0.01

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
