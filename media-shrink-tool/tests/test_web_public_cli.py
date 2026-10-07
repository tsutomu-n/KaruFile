import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from PIL import Image

from media_shrink import web_public as wp
from media_shrink import web_public_batch as batch


@pytest.fixture
def inputs(tmp_path):
    root = tmp_path / "案件 写真"
    root.mkdir()
    for folder in ("前", "後"):
        (root / folder).mkdir()
        Image.new("RGB", (30, 40), "red").save(root / folder / "private.png")
    (root / "ignore.pdf").write_bytes(b"not a PDF")
    return root, tmp_path / "掲載 用"


def cli(root, out, *args):
    return subprocess.run([sys.executable, "-m", "media_shrink", "web-public",
        "-i", str(root), "-o", str(out), *args], capture_output=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def snapshot(root):
    return {str(p.relative_to(root)): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
            for p in root.rglob("*")}


def test_cli_selected_and_reuse(inputs, monkeypatch):
    root, out = inputs
    first = cli(root, out, "--file", "前/private.png")
    assert first.returncode == 0, first.stderr
    manifest = json.loads((out / "manifest.web-public.json").read_text("utf-8"))
    assert len(manifest["results"]) == 1
    before = (out / manifest["results"][0]["output_path"]).read_bytes()
    def fail(*args):
        raise AssertionError("encoder called during reuse")
    monkeypatch.setattr(wp, "_save_public", fail)
    second = wp.run_web_public(root, out, wp.WebPublicConfig(), selected_files=["前/private.png"])
    assert second.exit_code == 0
    assert second.results[0]["action"] == "SKIPPED_COMPLETE"
    assert (out / second.results[0]["output_path"]).read_bytes() == before
    assert second.run_id != manifest["run_id"]


def test_dry_run_no_writes(inputs):
    root, out = inputs
    before = snapshot(root.parent)
    result = cli(root, out, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert snapshot(root.parent) == before
    assert cli(root, out).returncode == 0
    before = snapshot(root.parent)
    assert cli(root, out, "--dry-run").returncode == 0
    assert snapshot(root.parent) == before


def test_mixed_results_and_neutral_names(inputs):
    root, out = inputs
    (root / "broken.jpg").write_bytes(b"bad")
    result = wp.run_web_public(root, out, wp.WebPublicConfig())
    assert result.exit_code == 1
    assert result.success_count == 2 and result.error_count == 1
    assert len(list(result.files_dir.iterdir())) == 2
    assert all(p.name.startswith("img-") and "private" not in p.name for p in result.files_dir.iterdir())
    assert next(r for r in result.results if r["action"] == "ERROR")["output_path"] is None
    assert cli(root, out).returncode == 1


@pytest.mark.parametrize("extra", [("--file", "../escape.png"), ("--file", "missing.png"),
    ("--file", "C:\\secret.png"), ("--file", "/tmp/secret.png"), ("--file", "ignore.pdf"),
    ("--workers", "0"), ("--workers", "5"), ("--format", "png"), ("--preset", "compact")])
def test_argument_errors(inputs, extra):
    root, out = inputs
    assert cli(root, out, *extra).returncode == 2
    assert not out.exists()


def test_empty_and_overlapping_inputs(inputs, tmp_path):
    root, out = inputs
    assert cli(root, root).returncode == 2
    assert cli(root, root / "child").returncode == 2
    assert cli(root, root.parent).returncode == 2
    empty = tmp_path / "empty"
    empty.mkdir()
    assert cli(empty, out).returncode == 2


def test_manifest_failure_keeps_previous(inputs, monkeypatch):
    root, out = inputs
    first = wp.run_web_public(root, out, wp.WebPublicConfig())
    path = out / "manifest.web-public.json"
    before = path.read_bytes()
    original = batch.os.replace
    def fail(src, dest):
        if Path(dest) == path:
            raise OSError("simulated NAS disconnect")
        return original(src, dest)
    monkeypatch.setattr(batch.os, "replace", fail)
    second = wp.run_web_public(root, out, wp.WebPublicConfig())
    assert second.exit_code == 1 and second.manifest_error
    assert path.read_bytes() == before
    assert len(list(first.files_dir.iterdir())) == 2


def test_corrupt_manifest_and_tampered_output_regenerate(inputs):
    root, out = inputs
    first = wp.run_web_public(root, out, wp.WebPublicConfig())
    (out / first.results[0]["output_path"]).write_bytes(b"tampered")
    second = wp.run_web_public(root, out, wp.WebPublicConfig())
    assert second.exit_code == 0
    assert second.results[0]["action"] == "CONVERTED"
    (out / "manifest.web-public.json").write_bytes(b"invalid json")
    third = wp.run_web_public(root, out, wp.WebPublicConfig())
    assert all(r["action"] == "CONVERTED" for r in third.results)


def test_source_same_size_mtime_and_engine_change(inputs, monkeypatch):
    root, out = inputs
    source = root / "plain.bmp"
    Image.new("RGB", (10,10), "red").save(source)
    kwargs = dict(selected_files=["plain.bmp"])
    wp.run_web_public(root, out, wp.WebPublicConfig(), **kwargs)
    st = source.stat()
    Image.new("RGB", (10,10), "blue").save(source)
    assert source.stat().st_size == st.st_size
    os.utime(source, ns=(st.st_atime_ns, st.st_mtime_ns))
    changed = wp.run_web_public(root, out, wp.WebPublicConfig(), **kwargs)
    assert changed.results[0]["action"] == "CONVERTED"
    monkeypatch.setattr(batch, "engine_versions", lambda: {"test": "different"})
    assert wp.run_web_public(root, out, wp.WebPublicConfig(), **kwargs).results[0]["action"] == "CONVERTED"


def test_manifest_path_escape_is_not_read(inputs, monkeypatch):
    root, out = inputs
    wp.run_web_public(root, out, wp.WebPublicConfig())
    path = out / "manifest.web-public.json"
    data = json.loads(path.read_text("utf-8"))
    for row in data["results"]:
        row["output_path"] = "../outside.jpg"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = wp.run_web_public(root, out, wp.WebPublicConfig())
    assert result.exit_code == 0
    assert all(r["action"] == "CONVERTED" for r in result.results)


def test_source_changed_during_encoding(inputs, monkeypatch):
    root, out = inputs
    original = wp._save_public
    def change(*args):
        original(*args)
        (root / "前/private.png").write_bytes(b"changed")
    monkeypatch.setattr(wp, "_save_public", change)
    result = wp.run_web_public(root, out, wp.WebPublicConfig(workers=1), selected_files=["前/private.png"])
    assert result.exit_code == 1
    assert result.results[0]["error"]["code"] == "SOURCE_CHANGED"
    assert not list(result.files_dir.iterdir())


def test_manifest_final_sweep_hashes_earlier_source(inputs, monkeypatch):
    root, out = inputs
    for n in (1,2):
        Image.new("RGB", (10,10), "red").save(root/f"{n}.bmp")
    original = batch.verify_public
    count = 0
    source = root/"1.bmp"
    def mutate_earlier(path, *args, **kwargs):
        nonlocal count
        original(path, *args, **kwargs)
        count += 1
        if count == 2:
            st = source.stat()
            Image.new("RGB", (10,10), "blue").save(source)
            os.utime(source, ns=(st.st_atime_ns, st.st_mtime_ns))
    monkeypatch.setattr(batch, "verify_public", mutate_earlier)
    result = wp.run_web_public(root, out, wp.WebPublicConfig(), selected_files=["1.bmp", "2.bmp"])
    assert result.exit_code == 1 and result.manifest_error
    assert not (out / batch.MANIFEST_NAME).exists()


def test_hardlinked_manifest_rejected_without_touching_source(inputs):
    root, out = inputs
    out.mkdir()
    source = root/"前/private.png"
    before = source.read_bytes()
    os.link(source, out/batch.MANIFEST_NAME)
    with pytest.raises(batch.SelectionError):
        wp.run_web_public(root, out, wp.WebPublicConfig())
    assert source.read_bytes() == before


def test_linked_roots_and_selected_path_rejected(inputs, tmp_path):
    root, out = inputs
    link = tmp_path/"linked"
    try:
        link.symlink_to(root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    with pytest.raises(batch.SelectionError):
        wp.run_web_public(link, out, wp.WebPublicConfig())
    out.mkdir()
    output_link = tmp_path/"output-link"
    output_link.symlink_to(out, target_is_directory=True)
    with pytest.raises(batch.SelectionError):
        wp.run_web_public(root, output_link, wp.WebPublicConfig())
    (root/"escape").symlink_to(out, target_is_directory=True)
    Image.new("RGB", (10,10)).save(out/"private.png")
    with pytest.raises(batch.SelectionError):
        wp.run_web_public(root, out, wp.WebPublicConfig(), selected_files=["escape/private.png"])


def test_recipe_change_and_old_marker_regenerate(inputs):
    root, out = inputs
    Image.new("RGB", (10,10)).save(root/"old.jpg", comment=b"karufile:image-v2;recipe=anything")
    first = wp.run_web_public(root, out, wp.WebPublicConfig(), selected_files=["old.jpg"])
    assert first.results[0]["action"] == "CONVERTED"
    second = wp.run_web_public(root, out, wp.WebPublicConfig("graphic"), selected_files=["old.jpg"])
    assert second.results[0]["action"] == "CONVERTED"
    assert second.results[0]["output_format"] == "PNG"


def test_output_creation_io_error_is_exit_one(inputs, monkeypatch):
    root, out = inputs
    def fail(*args):
        raise OSError("NAS unavailable")
    monkeypatch.setattr(batch, "_new_run", fail)
    result = wp.run_web_public(root, out, wp.WebPublicConfig())
    assert result.exit_code == 1 and result.manifest_error


def test_previous_color_recipe_is_not_reused(inputs, monkeypatch):
    import hashlib
    root, out = inputs
    first = wp.run_web_public(root, out, wp.WebPublicConfig())
    assert first.exit_code == 0
    path = out/batch.MANIFEST_NAME
    data = json.loads(path.read_text("utf-8"))
    data["recipe"]["version"] = 1
    data["recipe_hash"] = hashlib.sha256(json.dumps(data["recipe"], sort_keys=True).encode()).hexdigest()
    path.write_text(json.dumps(data), encoding="utf-8")
    calls = []
    save = wp._save_public
    def record(*args):
        calls.append(True)
        return save(*args)
    monkeypatch.setattr(wp, "_save_public", record)
    second = wp.run_web_public(root, out, wp.WebPublicConfig())
    assert second.exit_code == 0 and len(calls) == second.success_count
    assert all(row["action"] == "CONVERTED" for row in second.results)
