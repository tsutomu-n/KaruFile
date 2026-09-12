"""Bound actual central-directory allocations and preserve ambiguous ZIP comments."""
import struct
import zipfile

import pytest

from excel_shrink import package
from excel_shrink.core import process_workbook


def end_record(*, entries=0, directory_size=0, directory_offset=0):
    return struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, entries, entries,
                       directory_size, directory_offset, 0)


@pytest.mark.parametrize("claimed", [0, 1, 4096])
def test_actual_directory_count_is_checked_before_zipinfo_objects(tmp_path, monkeypatch, claimed):
    entry = b"PK\x01\x02" + b"\0" * 24 + struct.pack("<3H", 1, 0, 0) + b"\0" * 12 + b"x"
    directory = entry * 4097
    source = tmp_path / "source.xlsx"
    source.write_bytes(directory + end_record(entries=claimed, directory_size=len(directory)))
    monkeypatch.setattr(package.zipfile, "ZipFile", lambda *_a, **_k: pytest.fail("unbounded ZipInfo allocation"))
    with pytest.raises(ValueError, match="entry count/size mismatch"):
        process_workbook(source, None, dry_run=True)


def test_zip64_locator_is_protected_even_with_nonsentinel_eocd_values(tmp_path, monkeypatch):
    source = tmp_path / "source.xlsx"
    source.write_bytes(b"PK\x06\x07" + b"\0" * 16 + end_record(directory_size=20))
    monkeypatch.setattr(package.zipfile, "ZipFile", lambda *_a, **_k: pytest.fail("ZIP64 parser reached"))
    result = process_workbook(source, None, dry_run=True)
    assert result.status == "DRY_RUN_PRESERVED" and result.reason == "zip64_directory"


def test_comment_with_false_eocd_signature_is_protected_not_error(tmp_path, monkeypatch):
    source = tmp_path / "source.xlsx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("part.xml", "<part/>")
        archive.comment = b"A legitimate comment with PK\x05\x06 inside"
    original = source.read_bytes()
    monkeypatch.setattr(package.zipfile, "ZipFile", lambda *_a, **_k: pytest.fail("ambiguous ZipFile parser reached"))
    result = process_workbook(source, None, dry_run=True)
    assert result.status == "DRY_RUN_PRESERVED"
    assert result.reason == "ambiguous_zip_comment_end_record"
    assert source.read_bytes() == original


@pytest.mark.parametrize("extra", [b"", b"comment without ambiguous signatures"])
def test_regular_directories_and_comments_pass_preflight(tmp_path, extra):
    source = tmp_path / "source.xlsx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("part.xml", "<part/>")
        archive.comment = extra
    package._preflight_directory(source)
