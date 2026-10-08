"""公開用画像の選択・実行別出力・ローカルmanifest。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import uuid

from .file_identity import capture_source_fingerprint
from .image import IMAGE_EXTENSIONS, collect_images, _validate_replaceable_file
from .utils import (PathValidationError, has_link_component, staged_path,
                    validate_input_output, validate_source_path, validate_output_destination)
from .web_public import (WebPublicConfig, process_web_public_image, engine_versions,
                         verify_public)

MANIFEST_NAME = "manifest.web-public.json"
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
logger = logging.getLogger(__name__)


class SelectionError(ValueError):
    """CLI終了2となる入力・選択の不正。"""


def safe_relative(value):
    if not isinstance(value, str) or not value or "\0" in value:
        raise SelectionError("相対ファイル名を指定してください")
    win = PureWindowsPath(value)
    rel = PurePosixPath(value.replace("\\", "/"))
    if win.drive or win.root or rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise SelectionError("絶対パス・親フォルダーの指定は使用できません")
    if any(":" in p for p in rel.parts):
        raise SelectionError("ドライブや代替ストリームは指定できません")
    return Path(*rel.parts)


def _no_links(path):
    if has_link_component(Path(path.anchor), path):
        raise PathValidationError("リンク・ジャンクションを含むパスは使用できません")


def select_images(input_dir, selected_files=None):
    root = Path(os.path.abspath(input_dir))
    try:
        _no_links(root)
        root = root.resolve(strict=True)
        if not root.is_dir():
            raise SelectionError("入力フォルダーを指定してください")
        if selected_files is None:
            sources = collect_images(root)
        else:
            sources = []
            for value in selected_files:
                source = root / safe_relative(value)
                _no_links(source)
                source = validate_source_path(root, source)
                if source.suffix.lower() not in IMAGE_EXTENSIONS:
                    raise SelectionError("対応する画像ファイルを選択してください")
                sources.append(source)
        sources = sorted(set(sources), key=lambda p: (p.relative_to(root).as_posix().casefold(),
                                                     p.relative_to(root).as_posix()))
        if not sources:
            raise SelectionError("対象画像がありません。1枚以上選択してください")
        return root, sources
    except (ValueError, OSError, RuntimeError) as exc:
        if isinstance(exc, SelectionError):
            raise
        raise SelectionError("入力フォルダー・選択画像を確認してください: " + str(exc)) from exc


def default_output(input_dir):
    root = Path(os.path.abspath(input_dir))
    return root.with_name(root.name + "_HP掲載用")


@dataclass
class BatchResult:
    results: list[dict] = field(default_factory=list)
    run_id: str | None = None
    files_dir: Path | None = None
    manifest_error: str | None = None
    dry_run: bool = False

    @property
    def success_count(self):
        return sum(r["action"] != "ERROR" for r in self.results)

    @property
    def error_count(self):
        return sum(r["action"] == "ERROR" for r in self.results)

    @property
    def warning_count(self):
        return sum(r["action"] != "ERROR" and bool(r["warnings"]) for r in self.results)

    @property
    def exit_code(self):
        return int(bool(self.error_count or self.manifest_error))

    @property
    def source_bytes(self):
        return sum(r["source_size"] or 0 for r in self.results if r["action"] != "ERROR")

    @property
    def output_bytes(self):
        return sum(r["output_size"] or 0 for r in self.results if r["action"] != "ERROR")


def _checked_output(root, out, path):
    _no_links(out)
    validate_output_destination(root, out, path)
    if path.exists() and (not path.is_file() or path.stat().st_nlink > 1):
        raise PathValidationError("通常の単独ファイル以外は使用できません")


def _previous(root, out, config, engines):
    path = out / MANIFEST_NAME
    try:
        _checked_output(root, out, path)
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or type(data.get("schema_version")) is not int
                or data["schema_version"] != 1 or data.get("recipe") != config.recipe
                or data.get("recipe_hash") != config.recipe_hash or data.get("engine_versions") != engines
                or data.get("input_root") != str(root) or data.get("output_root") != str(out)
                or not isinstance(data.get("results"), list)):
            return {}
        rows = {}
        for row in data["results"]:
            if not isinstance(row, dict) or row.get("action") not in ("CONVERTED", "SKIPPED_COMPLETE"):
                continue
            key = row.get("source_path")
            if not isinstance(key, str) or key in rows:
                return {}
            rows[key] = row
        return rows
    except (OSError, ValueError, RecursionError, TypeError):
        return {}


def _reuser(root, out, config, row):
    def copy(temporary, source_fp, clean):
        if row is None or row.get("source_sha256") != source_fp.sha256 or row.get("source_size") != source_fp.stat.st_size:
            return False
        try:
            rel = safe_relative(row.get("output_path"))
            # Only previous completed run files, never arbitrary files under the output root.
            if len(rel.parts) != 4 or rel.parts[0] != "runs" or rel.parts[2] != "files":
                return False
            previous = out / rel
            _checked_output(root, out, previous)
            before = capture_source_fingerprint(previous)
            if (before.sha256 != row.get("output_sha256") or before.stat.st_size != row.get("output_size")
                    or row.get("output_width") != clean.width or row.get("output_height") != clean.height
                    or row.get("output_format") != config.output_format):
                return False
            verify_public(previous, config, clean.size, clean)
            shutil.copyfile(previous, temporary)
            _checked_output(root, out, previous)
            after = capture_source_fingerprint(previous)
            copied = capture_source_fingerprint(temporary)
            if (before.stat_signature != after.stat_signature
                    or before.sha256 != after.sha256 or copied.sha256 != before.sha256):
                return False
            return True
        except (OSError, ValueError, TypeError, KeyError, IndexError):
            return False
    return copy


def _new_run(root, out):
    _no_links(out)
    out.mkdir(parents=True, exist_ok=True)
    runs = out / "runs"
    validate_output_destination(root, out, runs)
    runs.mkdir(exist_ok=True)
    for _ in range(10):
        run_id = uuid.uuid4().hex
        directory = runs / run_id
        validate_output_destination(root, out, directory)
        try:
            directory.mkdir()  # exclusive creation: never overwrite an existing run
        except FileExistsError:
            continue
        files = directory / "files"
        validate_output_destination(root, out, files)
        files.mkdir()
        return run_id, files
    raise OSError("新しい実行フォルダーを作成できません")


def _write_manifest(root, out, config, engines, result):
    manifest = out / MANIFEST_NAME
    _checked_output(root, out, manifest)
    _validate_replaceable_file(manifest, label="web-public manifest")
    snapshots = []
    for row in result.results:
        if row["action"] == "ERROR":
            continue
        source = root / safe_relative(row["source_path"])
        output = out / safe_relative(row["output_path"])
        try:
            _no_links(source)
            validate_source_path(root, source)
            _checked_output(root, out, output)
            src = capture_source_fingerprint(source)
            dst = capture_source_fingerprint(output)
            if ((src.sha256, src.stat.st_size, src.stat.st_mtime_ns) !=
                    (row["source_sha256"], row["source_size"], row["source_mtime_ns"])
                    or (dst.sha256, dst.stat.st_size) != (row["output_sha256"], row["output_size"])):
                raise ValueError("処理後に原本または出力が変更されました")
            verify_public(output, config, (row["output_width"], row["output_height"]))
            snapshots.extend(((source, src), (output, dst)))
        except (OSError, ValueError):
            # Only this run's own invalid result is removed from its upload folder.
            _checked_output(root, out, output)
            if output.parent == result.files_dir:
                output.unlink(missing_ok=True)
            row.update(action="ERROR", output_path=None, output_sha256=None, output_size=None,
                       output_width=None, output_height=None, output_format=None,
                       error={"code": "RESULT_CHANGED", "message": "処理後に原本または出力が変更されました。再実行してください"})
    data = {"schema_version": 1, "run_id": result.run_id, "input_root": str(root),
            "output_root": str(out), "recipe": config.recipe, "recipe_hash": config.recipe_hash,
            "engine_versions": engines, "results": result.results}
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    if len(payload) > MAX_MANIFEST_BYTES:
        raise ValueError("manifestが16 MiBの上限を超えました。選択画像を分けてください")
    with staged_path(manifest, input_root=root, output_root=out) as temporary:
        temporary.write_bytes(payload)
        if json.loads(temporary.read_text("utf-8")) != data:
            raise ValueError("manifestの再読検査に失敗しました")
        # The final sweep also covers changes while later rows were being inspected.
        for path, fingerprint in snapshots:
            _no_links(path)
            observed = capture_source_fingerprint(path)
            if observed.sha256 != fingerprint.sha256 or observed.stat_signature != fingerprint.stat_signature:
                raise ValueError("manifest検証中にファイルが変更されました")
        _checked_output(root, out, manifest)
        _validate_replaceable_file(manifest, label="web-public manifest")
        os.replace(temporary, manifest)


def run_batch(input_dir, output_dir, config, *, selected_files=None, dry_run=False, on_result=None):
    root, sources = select_images(input_dir, selected_files)
    requested_output = Path(os.path.abspath(output_dir if output_dir is not None else default_output(root)))
    try:
        _no_links(requested_output)
        root, out = validate_input_output(root, requested_output)
        _checked_output(root, out, out / MANIFEST_NAME)
        validate_output_destination(root, out, out / "runs")
    except (ValueError, OSError) as exc:
        raise SelectionError("出力フォルダーを確認してください: " + str(exc)) from exc
    result = BatchResult(dry_run=dry_run)
    engines = engine_versions()
    previous = {} if dry_run else _previous(root, out, config, engines)
    if dry_run:
        files = out / "dry-run-files"  # planning only; never created
    else:
        try:
            result.run_id, files = _new_run(root, out)
            result.files_dir = files
        except OSError as exc:
            logger.warning("web-public failure stage=create_run exception=%s", type(exc).__name__)
            result.manifest_error = "出力フォルダーを作成できません。接続と書込み権限を確認してください"
            return result
    rows = [None] * len(sources)
    with ThreadPoolExecutor(max_workers=config.workers) as pool:
        futures = {}
        for index, source in enumerate(sources):
            relative = source.relative_to(root).as_posix()
            destination = files / f"img-{result.run_id or 'dry-run'}-{index+1:04d}{config.suffix}"
            future = pool.submit(process_web_public_image, source, destination, config,
                input_root=root, output_root=out, dry_run=dry_run,
                reuse=_reuser(root, out, config, previous.get(relative)))
            futures[future] = index
        for future in as_completed(futures):
            row = future.result()
            rows[futures[future]] = row
            if on_result is not None:
                on_result(dict(row))
    result.results = rows
    if not dry_run:
        try:
            _write_manifest(root, out, config, engines, result)
        except (OSError, ValueError, RuntimeError) as exc:
            logger.warning("web-public failure stage=manifest exception=%s", type(exc).__name__)
            result.manifest_error = "manifestを確定できませんでした。前回の記録は保持されています。接続・ファイル変更を確認して再実行してください"
    return result
