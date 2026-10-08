"""原本保護と旧image helperの呼出し互換を検証する。"""
import hashlib
import importlib
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def identity():
    return importlib.import_module("media_shrink.file_identity")


def test_identity_import_does_not_load_image_or_gui_dependencies():
    probe = subprocess.run([sys.executable, "-c", """
import sys
from media_shrink.file_identity import capture_source_fingerprint
assert 'media_shrink.image' not in sys.modules
assert not any(name == 'PIL' or name.startswith('PIL.') for name in sys.modules)
assert not any(name == 'nicegui' or name.startswith('nicegui.') for name in sys.modules)
assert not any(name == 'pillow_heif' or name.startswith('pillow_heif.') for name in sys.modules)
"""], capture_output=True, text=True)
    assert probe.returncode == 0, probe.stderr


@pytest.mark.parametrize("payload", [b"", b"abc", b"abcdef" * 400_000],
                         ids=["empty", "abc", "multiple-chunks"])
def test_sha_covers_empty_and_multiple_read_chunks(identity, tmp_path, payload):
    source = tmp_path / "source.bin"
    source.write_bytes(payload)
    assert identity.sha256_file(source) == hashlib.sha256(payload).hexdigest()


def test_capture_and_unchanged_source(identity, tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"abc")
    fingerprint = identity.capture_source_fingerprint(source)
    assert fingerprint.sha256 == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert fingerprint.stat.st_size == 3
    identity.assert_source_unchanged(source, fingerprint, tmp_path)


def test_stat_signature_keeps_identity_and_nanoseconds_but_ignores_atime(identity):
    observed = SimpleNamespace(st_dev=3, st_ino=4, st_size=5,
                               st_mtime_ns=-11, st_ctime_ns=12, st_atime_ns=99)
    assert identity.stat_signature(observed) == (3, 4, 5, -11, 12)
    observed.st_atime_ns = 100
    assert identity.stat_signature(observed) == (3, 4, 5, -11, 12)


def test_same_size_and_restored_mtime_still_reject_changed_bytes(identity, tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"before")
    fingerprint = identity.capture_source_fingerprint(source)
    source.write_bytes(b"after!")
    os.utime(source, ns=(fingerprint.stat.st_atime_ns, fingerprint.stat.st_mtime_ns))
    assert source.stat().st_size == fingerprint.stat.st_size
    assert source.stat().st_mtime_ns == fingerprint.stat.st_mtime_ns
    with pytest.raises(identity.SourceChangedError):
        identity.assert_source_unchanged(source, fingerprint, tmp_path)


def test_same_bytes_replacement_is_rejected_by_file_identity(identity, tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"original")
    fingerprint = identity.capture_source_fingerprint(source)
    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(b"original")
    os.utime(replacement, ns=(fingerprint.stat.st_atime_ns, fingerprint.stat.st_mtime_ns))
    os.replace(replacement, source)
    assert identity.sha256_file(source) == fingerprint.sha256
    assert source.stat().st_ino != fingerprint.stat.st_ino
    with pytest.raises(identity.SourceChangedError):
        identity.assert_source_unchanged(source, fingerprint, tmp_path)


def test_mutation_during_hash_is_rejected(identity, tmp_path, monkeypatch):
    source = tmp_path / "source.bin"
    source.write_bytes(b"original")
    original_hash = identity.sha256_file

    def hash_then_mutate(path):
        digest = original_hash(path)
        path.write_bytes(b"longer replacement")
        return digest

    monkeypatch.setattr(identity, "sha256_file", hash_then_mutate)
    with pytest.raises(identity.SourceChangedError):
        identity.capture_source_fingerprint(source)


def test_removed_source_is_changed_error_with_io_cause(identity, tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"original")
    fingerprint = identity.capture_source_fingerprint(source)
    source.unlink()
    with pytest.raises(identity.SourceChangedError) as error:
        identity.assert_source_unchanged(source, fingerprint, tmp_path)
    assert isinstance(error.value.__cause__, (OSError, ValueError))
    assert isinstance(error.value, OSError)


def test_initial_capture_preserves_missing_file_error(identity, tmp_path):
    with pytest.raises(FileNotFoundError):
        identity.capture_source_fingerprint(tmp_path / "missing.bin")


def test_source_outside_input_root_is_rejected(identity, tmp_path):
    input_root = tmp_path / "input"
    input_root.mkdir()
    source = tmp_path / "outside.bin"
    source.write_bytes(b"outside")
    fingerprint = identity.capture_source_fingerprint(source)
    with pytest.raises(identity.SourceChangedError):
        identity.assert_source_unchanged(source, fingerprint, input_root)


def test_source_symlink_is_rejected(identity, tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"original")
    fingerprint = identity.capture_source_fingerprint(source)
    linked = tmp_path / "linked.bin"
    try:
        linked.symlink_to(source)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")
    with pytest.raises(identity.SourceChangedError):
        identity.assert_source_unchanged(linked, fingerprint, tmp_path)
    assert source.read_bytes() == b"original"


@pytest.mark.skipif(os.name != "nt", reason="Windows junction integration")
def test_source_through_escaping_junction_is_rejected(identity, tmp_path):
    input_root, outside = tmp_path / "input", tmp_path / "outside"
    input_root.mkdir()
    outside.mkdir()
    source = outside / "source.bin"
    source.write_bytes(b"original")
    fingerprint = identity.capture_source_fingerprint(source)
    junction = input_root / "junction"
    created = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                             capture_output=True)
    assert created.returncode == 0, created.stderr
    with pytest.raises(identity.SourceChangedError):
        identity.assert_source_unchanged(junction / source.name, fingerprint, input_root)
    assert source.read_bytes() == b"original"


def test_legacy_hash_hook_and_exception_identity_are_preserved(identity, tmp_path, monkeypatch):
    from media_shrink import image
    source = tmp_path / "source.bin"
    source.write_bytes(b"original")
    original_hash = image._sha256_file

    def hash_then_mutate(path):
        digest = original_hash(path)
        path.write_bytes(b"longer replacement")
        return digest

    assert image.SourceChangedError is identity.SourceChangedError
    assert image.SourceFingerprint is identity.SourceFingerprint
    monkeypatch.setattr(image, "_sha256_file", hash_then_mutate)
    with pytest.raises(identity.SourceChangedError):
        image._capture_source_fingerprint(source)


def test_legacy_capture_hook_is_used_during_source_recheck(identity, tmp_path, monkeypatch):
    from media_shrink import image
    source = tmp_path / "source.bin"
    source.write_bytes(b"original")
    fingerprint = image._capture_source_fingerprint(source)
    original_capture = image._capture_source_fingerprint

    def mutate_then_capture(path):
        path.write_bytes(b"replacement")
        return original_capture(path)

    monkeypatch.setattr(image, "_capture_source_fingerprint", mutate_then_capture)
    with pytest.raises(identity.SourceChangedError):
        image._assert_source_unchanged(source, fingerprint, tmp_path)


@pytest.mark.parametrize("consumer", ["resize", "web-public"])
def test_consumers_preserve_output_when_source_changes_during_hash(
    identity, tmp_path, monkeypatch, consumer,
):
    from PIL import Image
    from media_shrink import image, web_public
    from media_shrink.config import ImageConfig
    source = tmp_path / "input" / "source.png"
    source.parent.mkdir()
    Image.new("RGB", (30, 40), "red").save(source)
    output = tmp_path / "output" / "master.jpg"
    output.parent.mkdir()
    output.write_bytes(b"previous completed output")
    original_hash = identity.sha256_file

    def hash_then_mutate(path):
        digest = original_hash(path)
        if path == source:
            path.write_bytes(path.read_bytes() + b"changed")
        return digest

    if consumer == "resize":
        monkeypatch.setattr(image, "_sha256_file", hash_then_mutate)
        with pytest.raises(identity.SourceChangedError):
            image.process_image(source, output, ImageConfig(),
                                input_root=source.parent, output_root=output.parent)
    else:
        monkeypatch.setattr(identity, "sha256_file", hash_then_mutate)
        result = web_public.process_web_public_image(source, output, web_public.WebPublicConfig(),
                        input_root=source.parent, output_root=output.parent)
        assert result["action"] == "ERROR"
        assert result["error"]["code"] == "SOURCE_CHANGED"
    assert output.read_bytes() == b"previous completed output"
