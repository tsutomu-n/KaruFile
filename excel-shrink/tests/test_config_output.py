from __future__ import annotations

import os
from pathlib import Path

import pytest

from excel_shrink.config import ExcelConfig
from excel_shrink import output as output_module
from excel_shrink.output import PathGuard, discover_files, fingerprint, staged_file, validate_roots


@pytest.mark.parametrize("pattern", ["", " ", ".", "../x", "foo/../*.xlsx", "/tmp/*", "C:\\work\\*.xlsx", "C:*.xlsx", "\\\\host\\share\\*"])
def test_invalid_selection_is_rejected(tmp_path, pattern):
    with pytest.raises(ValueError):
        ExcelConfig(tmp_path, tmp_path / "out", (pattern,))


@pytest.mark.parametrize("dpi", [149, 301, 220.5, True, "220"])
def test_invalid_dpi_is_rejected(tmp_path, dpi):
    with pytest.raises(ValueError):
        ExcelConfig(tmp_path, tmp_path / "out", ("*.xlsx",), dpi=dpi)


def test_patterns_are_explicit_case_insensitive_and_cross_directories(tmp_path):
    config = ExcelConfig(tmp_path, tmp_path / "out", ("./REPORTS\\*.XLSX", "reports/*.xlsx"))
    assert config.patterns == ("reports/*.xlsx",)
    assert config.selected(Path("Reports/sub/Book.XLSX"))
    assert not config.selected(Path("Reports/~$Book.XLSX"))
    assert not config.selected(Path("else/Book.xlsx"))
    assert not config.selected(Path("Reports/book.xlsm"))


@pytest.mark.parametrize("relationship", ["equal", "child", "parent"])
def test_equal_nested_output_is_rejected(tmp_path, relationship):
    source = tmp_path / "input"
    source.mkdir()
    target = {"equal": source, "child": source / "output", "parent": tmp_path}[relationship]
    with pytest.raises(ValueError, match="non-nested"):
        validate_roots(source, target)


def make_guard(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    unrelated = source / "keep.txt"
    unrelated.write_bytes(b"private source")
    output = tmp_path / "output"
    config = ExcelConfig(source, output, ("*.xlsx",))
    return PathGuard(source, output, config.report_path, config.work_dir, (unrelated,)), unrelated


@pytest.mark.parametrize("destination_type", ["output", "report"])
def test_hardlink_to_nonselected_input_is_rejected(tmp_path, destination_type):
    guard, unrelated = make_guard(tmp_path)
    guard.output_root.mkdir()
    destination = guard.report_path if destination_type == "report" else guard.output_root / "book.xlsx"
    os.link(unrelated, destination)
    with pytest.raises(ValueError, match="hard-linked"):
        guard.preflight((destination,) if destination_type == "output" else ())
    assert unrelated.read_bytes() == b"private source"


def test_symbolic_link_inputs_are_rejected(tmp_path):
    guard, unrelated = make_guard(tmp_path)
    linked = guard.input_root / "link.txt"
    try:
        linked.symlink_to(unrelated)
    except OSError:
        pytest.skip("Windows symlink permission unavailable")
    with pytest.raises(ValueError, match="linked inputs"):
        discover_files(guard.input_root)


def test_fingerprint_detects_replaced_file_even_with_same_contents(tmp_path):
    path = tmp_path / "file"
    path.write_bytes(b"original")
    before = fingerprint(path)
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"original")
    os.replace(replacement, path)
    with pytest.raises(OSError, match="identity changed"):
        fingerprint(path, before)


def test_fingerprint_handles_windows_path_and_handle_ctime_difference(tmp_path, monkeypatch):
    from types import SimpleNamespace

    path = tmp_path / "file"
    path.write_bytes(b"original")
    real_fstat = output_module.os.fstat

    def handle_stat(descriptor):
        result = real_fstat(descriptor)
        return SimpleNamespace(
            st_dev=result.st_dev, st_ino=result.st_ino, st_size=result.st_size,
            st_mtime_ns=result.st_mtime_ns, st_ctime_ns=result.st_ctime_ns + 123456,
        )

    monkeypatch.setattr(output_module.os, "fstat", handle_stat)
    assert fingerprint(path).identity.size == 8


def test_fingerprint_rejects_open_handle_mutation(tmp_path, monkeypatch):
    from types import SimpleNamespace

    path = tmp_path / "file"
    path.write_bytes(b"original")
    real_fstat = output_module.os.fstat
    calls = 0

    def handle_stat(descriptor):
        nonlocal calls
        result = real_fstat(descriptor)
        calls += 1
        return SimpleNamespace(
            st_dev=result.st_dev, st_ino=result.st_ino, st_size=result.st_size,
            st_mtime_ns=result.st_mtime_ns, st_ctime_ns=result.st_ctime_ns + calls,
        )

    monkeypatch.setattr(output_module.os, "fstat", handle_stat)
    with pytest.raises(OSError, match="changed while reading"):
        fingerprint(path)


def test_stage_cleanup_does_not_remove_unrelated_files(tmp_path):
    guard, _ = make_guard(tmp_path)
    guard.work_dir.mkdir()
    keep = guard.work_dir / "unrelated.txt"
    keep.write_bytes(b"keep")
    with staged_file(guard, ".xlsx") as stage:
        stage.write_bytes(b"candidate")
        assert stage.exists()
    assert not stage.exists()
    assert keep.read_bytes() == b"keep"


def test_report_or_work_equal_to_input_is_rejected(tmp_path):
    output = tmp_path / "output"
    source = Path(str(output) + ".excel-work")
    source.mkdir()
    config = ExcelConfig(source, output, ("*.xlsx",))
    guard = PathGuard(source, output, config.report_path, config.work_dir, ())
    with pytest.raises(ValueError, match="unsafe"):
        guard.preflight(())


@pytest.mark.parametrize("names", [("book.xlsx", "BOOK.XLSX"), ("book.xlsx", "BOOK.XLSX/child.xlsx")])
def test_planned_case_or_file_directory_collisions_are_rejected(tmp_path, names):
    guard, _ = make_guard(tmp_path)
    with pytest.raises(ValueError, match="outputs collide"):
        guard.preflight(tuple(guard.output_root / name for name in names))
