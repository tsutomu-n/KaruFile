"""Optional, offline visual evidence; never participates in PDF adoption/state."""
from __future__ import annotations

import json
import math
import os
import stat
import tempfile
import time
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import pymupdf as fitz

from . import discovery, output, worker
from .config import RunConfig, config_for_path, photo_lossy_options, profile_for_path
from .policy import Decision, classify
from .inspect_pdf import inspect_file
from .models import OptimizationMode, ProcessStatus, SourceSnapshot
from .state import Record
from .utils import logger, sha256_file

MAX_PAGES = 100
MAX_REGIONS = 500
MAX_RENDER_PIXELS = 32_000_000
MAX_DOCUMENT_PIXELS = 600_000_000
DOCUMENT_SECONDS = 300


class PreviewLimitError(RuntimeError):
    pass


@dataclass
class Budget:
    deadline: float
    pixels: int = 0

    def check(self) -> None:
        if time.monotonic() > self.deadline:
            raise PreviewLimitError("preview_time_limit")

    def render(self, pixels: int) -> None:
        self.check()
        if pixels <= 0 or pixels > MAX_RENDER_PIXELS:
            raise PreviewLimitError("preview_render_pixel_limit")
        if self.pixels + pixels > MAX_DOCUMENT_PIXELS:
            raise PreviewLimitError("preview_document_pixel_limit")
        self.pixels += pixels


def _safe(path: Path, cfg: RunConfig, protected: tuple[Path, ...], *, work_directory: bool = False) -> None:
    root = Path(os.path.abspath(cfg.output_dir.parent))
    lexical = Path(os.path.abspath(path))
    if not output._is_within(lexical, root) or output._has_link_component(root, lexical):
        raise ValueError(f"unsafe preview path: {path}")
    resolved = path.resolve(strict=False)
    if not output._is_within(resolved, root.resolve(strict=False)):
        raise ValueError(f"preview escapes work root: {path}")
    for tree in (cfg.input_dir.resolve(strict=True), cfg.output_dir.resolve(strict=False)):
        if output._is_within(resolved, tree) or (
            output._is_within(tree, resolved) and not (work_directory and lexical == root)
        ):
            raise ValueError(f"preview overlaps input or PDF output: {path}")
    if path.exists():
        info = path.stat()
        if not info.st_mode & stat.S_IWRITE:
            raise ValueError(f"read-only preview destination: {path}")
        if not path.is_dir() and info.st_nlink > 1:
            raise ValueError(f"hard-linked preview destination: {path}")
        if any(p.exists() and os.path.samefile(path, p) for p in protected):
            raise ValueError(f"preview aliases a protected file: {path}")


def _mkdir(path: Path, cfg: RunConfig, protected: tuple[Path, ...], *, exclusive: bool = False) -> None:
    _safe(path, cfg, protected, work_directory=True)
    path.mkdir(parents=True, exist_ok=not exclusive)
    _safe(path, cfg, protected, work_directory=True)


def _publish_text(path: Path, text: str, cfg: RunConfig, protected: tuple[Path, ...]) -> None:
    _safe(path, cfg, protected)
    _mkdir(path.parent, cfg, protected)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        expected = sha256_file(temporary)
        _safe(path, cfg, protected)
        _safe(temporary, cfg, protected)
        if sha256_file(temporary) != expected:
            raise RuntimeError("preview staging changed")
        os.replace(temporary, path)
        if sha256_file(path) != expected:
            raise RuntimeError("preview publication changed")
    finally:
        temporary.unlink(missing_ok=True)


def _json(value: object) -> str:
    # Safe even when a filename contains </script>, quotes or Unicode separators.
    result = json.dumps(value, ensure_ascii=False, indent=2)
    for char in "<>&\u2028\u2029":
        result = result.replace(char, f"\\u{ord(char):04x}")
    return result


def _check_completed(source: SourceSnapshot, record: Record, cfg: RunConfig, protected: tuple[Path, ...]) -> None:
    discovery.assert_source_unchanged(source, cfg.input_dir)
    destination = source.output_path(cfg.output_dir)
    others = tuple(path for path in protected if path != destination)
    output.validate_destination(destination, input_root=cfg.input_dir, output_root=cfg.output_dir, protected_sources=others)
    before = destination.stat()
    digest = sha256_file(destination)
    after = destination.stat()
    signature = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
    if (signature(before) != signature(after) or digest != record.output_sha256
            or after.st_size != record.output_size):
        raise RuntimeError("completed PDF changed before preview publication")
    output.validate_destination(destination, input_root=cfg.input_dir, output_root=cfg.output_dir, protected_sources=others)
    discovery.assert_source_unchanged(source, cfg.input_dir)


def _views(path: Path, budget: Budget) -> list[dict]:
    views: list[dict] = []
    count = 0
    with fitz.open(path) as doc:
        if doc.page_count > MAX_PAGES:
            raise PreviewLimitError("preview_page_limit")
        for page in doc:
            budget.check()
            infos = page.get_image_info()
            count += len(infos)
            if count > MAX_REGIONS:
                raise PreviewLimitError("preview_region_limit")
            regions = [("ページ全体", page.rect, 144)]
            regions += [(f"画像領域 {i}", fitz.Rect(info["bbox"]) * page.rotation_matrix & page.rect, 300)
                        for i, info in enumerate(infos, 1)]
            for region, (label, rect, dpi) in enumerate(regions):
                # Fully off-page placements have no visible comparison region.
                if rect.is_empty:
                    continue
                if rect.is_infinite or not all(math.isfinite(v) for v in rect):
                    raise ValueError("invalid preview region")
                dimensions = (rect * fitz.Matrix(dpi / 72, dpi / 72)).irect
                if dimensions.width * dimensions.height > MAX_RENDER_PIXELS:
                    raise PreviewLimitError("preview_render_pixel_limit")
                views.append({"page": page.number + 1, "label": label, "region": region,
                              "rect": list(rect), "render_dpi": dpi,
                              "css_width": rect.width * 96 / 72, "images": {}})
    return views


def _render(paths: dict[str, Path], views: list[dict], folder: Path, run_dir: Path,
            cfg: RunConfig, protected: tuple[Path, ...], budget: Budget) -> None:
    assets = folder / "assets"
    _mkdir(assets, cfg, protected)
    with fitz.open(paths["original"]) as source:
        geometry = [(p.rotation, tuple(p.mediabox), tuple(p.cropbox), tuple(p.rect)) for p in source]
    for kind, path in paths.items():
        with fitz.open(path) as doc:
            if doc.page_count != len(geometry):
                raise RuntimeError("preview page count mismatch")
            for page, expected in zip(doc, geometry):
                if (page.rotation, tuple(page.mediabox), tuple(page.cropbox), tuple(page.rect)) != expected:
                    raise RuntimeError("preview page geometry mismatch")
            for view in views:
                rect = fitz.Rect(view["rect"])
                dpi = view["render_dpi"]
                dimensions = (rect * fitz.Matrix(dpi / 72, dpi / 72)).irect
                budget.render(dimensions.width * dimensions.height)
                pix = doc[view["page"] - 1].get_pixmap(dpi=dpi, clip=rect, colorspace=fitz.csRGB, alpha=False)
                if pix.width * pix.height > MAX_RENDER_PIXELS:
                    raise PreviewLimitError("preview_render_pixel_limit")
                if "pixel_width" in view and (view["pixel_width"], view["pixel_height"]) != (pix.width, pix.height):
                    raise RuntimeError("preview render dimensions mismatch")
                target = assets / f"{kind}-p{view['page']}-r{view['region']}.png"
                _safe(target, cfg, protected)
                pix.save(target)
                budget.check()
                _safe(target, cfg, protected)
                view["pixel_width"], view["pixel_height"] = pix.width, pix.height
                view["images"][kind] = target.relative_to(run_dir).as_posix()


def _font_preview_decision(source: SourceSnapshot, record: Record, cfg: RunConfig) -> Decision:
    """Use verified processing state; the ordinary text classifier cannot classify font PDFs."""
    protected = record.status == ProcessStatus.PRESERVED_ORIGINAL
    if (
        record.profile != "font_replace" or record.requested_policy != "font_replace"
        or record.processing_schema != 6 or record.source_sha256 != source.sha256
        or record.permission_basis != "explicit_font_replace"
        or record.font_replacement_requested is not True
        or record.replacement_font != cfg.replacement_font
        or not cfg.font_replace_sha256 or record.replacement_font_sha256 != cfg.font_replace_sha256
        or type(record.text_extraction_changed) is not bool
        or (record.text_extraction_changed and record.status != ProcessStatus.ADOPTED_LOSSY)
        or protected != bool(record.preservation_reason)
        or record.classification != ("protected" if protected else "font_replace")
    ):
        raise RuntimeError("font preview processing state mismatch")
    return Decision(record.classification, record.permission_basis, record.preservation_reason)


def _document(source: SourceSnapshot, record: Record, item: dict, cfg: RunConfig,
              run_dir: Path, qpdf_exe: Path | None, protected: tuple[Path, ...]) -> None:
    started = time.monotonic()
    budget = Budget(started + DOCUMENT_SECONDS)
    _check_completed(source, record, cfg, protected)
    views = _views(source.path, budget)
    options = config_for_path(cfg, source.relative_path)
    profile = profile_for_path(cfg, source.relative_path)
    # The source/output SHA checks above and below bind the font classification
    # to the actual completed result. No extra font candidates are generated.
    decision = (_font_preview_decision(source, record, cfg) if profile == "font_replace"
                else classify(source.path, profile, safe=True) if cfg.safe else classify(source.path, profile))
    if decision.protected and record.output_sha256 != source.sha256:
        raise RuntimeError("protected preview output must equal original")
    budget.check()
    # A fresh opaque directory prevents filenames and reruns from colliding.
    folder = run_dir / uuid.uuid4().hex
    _mkdir(folder, cfg, protected, exclusive=True)
    original, completed = folder / "original.pdf", folder / "output.pdf"
    output.copy_original(source, original, input_root=cfg.input_dir, output_root=run_dir)
    output.adopt_candidate(source, source.output_path(cfg.output_dir), completed,
                           candidate_sha256=record.output_sha256,
                           input_root=cfg.input_dir, output_root=run_dir)
    paths = {"original": original, "output": completed}
    item["variants"] = [
        {"key": "original", "label": "原本", "status": "READY", "reason": "original",
         "size": source.size, "href": original.relative_to(run_dir).as_posix()},
        {"key": "output", "label": "実際の出力", "status": "READY", "reason": record.decision_reason,
         "size": record.output_size, "href": completed.relative_to(run_dir).as_posix()},
    ]
    budget.check()
    original_snapshot = discovery.snapshot(original, folder)
    for dpi in (cfg.preview_dpis if decision.classification == "photo" and not decision.protected else ()):
        budget.check()
        key = f"dpi{dpi}"
        variant = {"key": key, "label": f"{dpi} DPI", "status": "REJECTED",
                   "reason": "", "size": None, "href": None}
        item["variants"].append(variant)
        candidate_cfg = replace(options, photo_dpi=dpi, lossy=photo_lossy_options(dpi))
        inspection = inspect_file(original, cfg.scan, safe=False, lossy_options=candidate_cfg.lossy)
        if not inspection.ok:
            raise RuntimeError(f"preview inspection failed at {dpi} DPI: {inspection.skip_reason}")
        if inspection.mode != OptimizationMode.LOSSY:
            variant.update(status="READY", reason="no_image_savings", size=source.size,
                           href=original.relative_to(run_dir).as_posix())
            paths[key] = original
            continue
        if qpdf_exe is None:
            raise RuntimeError("qpdf is required for preview candidates")
        temporary = folder / f".candidate-{dpi}.pdf"
        _safe(temporary, cfg, protected)
        try:
            detail = worker._evaluate_candidate(original_snapshot, candidate_cfg, temporary,
                                                 OptimizationMode.LOSSY, "photo", qpdf_exe)
            budget.check()
            variant.update(reason=detail.validation_reason or detail.reason, size=detail.size)
            if detail.reason == "processing_error":
                variant["status"] = "ERROR"
                item.setdefault("preview_errors", []).append(f"{dpi} DPI: {variant['reason']}")
            elif detail.reason == "no_image_savings":
                variant.update(status="READY", href=original.relative_to(run_dir).as_posix(), size=source.size)
                paths[key] = original
            elif detail.reason in {"eligible", "candidate_not_smaller", "reduction_below_threshold"}:
                candidate = folder / f"{key}.pdf"
                output.adopt_candidate(source, temporary, candidate, candidate_sha256=sha256_file(temporary),
                                       input_root=cfg.input_dir, output_root=run_dir)
                variant.update(status="READY", href=candidate.relative_to(run_dir).as_posix())
                paths[key] = candidate
            elif detail.reason != "quality_rejected":
                raise RuntimeError(f"unexpected preview validation result: {detail.reason}")
        finally:
            # Only this invocation's temporary candidate is removed.
            _safe(temporary, cfg, protected)
            temporary.unlink(missing_ok=True)
    _render(paths, views, folder, run_dir, cfg, protected, budget)
    _check_completed(source, record, cfg, protected)
    budget.check()
    item["views"] = views
    item["status"] = "ERROR" if item.get("preview_errors") else "READY"
    item["reason"] = "; ".join(item.get("preview_errors", [])) or record.preservation_reason or "complete"
    item["elapsed_seconds"] = round(time.monotonic() - started, 3)
    item["rendered_pixels"] = budget.pixels


def generate(cfg: RunConfig, sources: list[SourceSnapshot], records: list[Record],
             qpdf_exe: Path | None, protected_sources: tuple[Path, ...]) -> bool:
    """Publish an independent manifest even for empty selections or dry runs."""
    by_source = {record.source_path: record for record in records}
    selected = list(sources)
    data = {"schema": 1, "requested": True, "dry_run": cfg.dry_run, "photo_dpi": cfg.photo_dpi,
            "preview_dpis": list(cfg.preview_dpis), "input_root": str(cfg.input_dir),
            "output_root": str(cfg.output_dir), "status": "DRY_RUN" if cfg.dry_run else "COMPLETE",
            "run_dir": None, "index_path": None, "index_sha256": None, "items": [], "errors": []}
    for source in selected:
        record = by_source[str(source.path)]
        data["items"].append({"source_path": str(source.path), "relative_path": source.relative_path.as_posix(),
                              "source_sha256": source.sha256, "output_path": str(source.output_path(cfg.output_dir)),
                              "output_sha256": record.output_sha256, "pdf_status": str(record.status),
                              "status": "SKIPPED", "reason": "dry_run" if cfg.dry_run else "not_rendered",
                              "source_size": source.size, "output_size": record.output_size,
                              "decision_reason": record.decision_reason,
                              "classification": record.classification,
                              "permission_basis": record.permission_basis,
                              "preservation_reason": record.preservation_reason,
                              "font_replacement_requested": record.font_replacement_requested,
                              "replacement_font": record.replacement_font,
                              "text_extraction_changed": record.text_extraction_changed,
                              "selected_kind": next((d.kind for d in record.candidate_details if d.selected), "original"),
                              "variants": [], "views": []})
    protected = tuple(protected_sources) + tuple(source.output_path(cfg.output_dir) for source in sources
                                                 if by_source[str(source.path)].output_sha256)
    if not cfg.dry_run:
        try:
            root = cfg.output_dir.parent / "pdf-preview"
            _mkdir(root, cfg, protected)
            run_dir = root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12])
            _mkdir(run_dir, cfg, protected, exclusive=True)
            data["run_dir"] = str(run_dir)
            for source, item in zip(selected, data["items"]):
                record = by_source[str(source.path)]
                if record.status == ProcessStatus.ERROR or str(record.status).startswith("SKIPPED_"):
                    item["reason"] = f"pdf_status:{record.status}"
                    continue
                try:
                    _document(source, record, item, cfg, run_dir, qpdf_exe, protected)
                    if item["status"] == "ERROR":
                        data["errors"].append(f"{source.relative_path}: {item['reason']}")
                except Exception as exc:
                    item.update(status="ERROR", reason=str(exc), views=[])
                    data["errors"].append(f"{source.relative_path}: {exc}")
                logger.info("PDF preview %s: %s (%s)", source.relative_path, item["status"], item["reason"])
            # Recheck after all rendering; output/source changes cannot yield READY evidence.
            for source, item in zip(selected, data["items"]):
                if item["status"] == "READY":
                    try:
                        _check_completed(source, by_source[str(source.path)], cfg, protected)
                    except Exception as exc:
                        item.update(status="ERROR", reason=str(exc), views=[])
                        data["errors"].append(f"{source.relative_path}: {exc}")
            data["status"] = "ERROR" if data["errors"] else "COMPLETE"
            template = Path(__file__).with_name("preview.html").read_text(encoding="utf-8")
            if template.count("__PREVIEW_DATA__") != 1:
                raise RuntimeError("invalid preview template")
            index = run_dir / "index.html"
            _publish_text(index, template.replace("__PREVIEW_DATA__", _json(data)), cfg, protected)
            data.update(index_path=str(index), index_sha256=sha256_file(index))
            logger.info("PDF comparison: %s", index)
        except Exception as exc:
            data["errors"].append(str(exc))
            data["status"] = "ERROR"
    manifest = cfg.output_dir.parent / ("pdf-preview.dry-run.json" if cfg.dry_run else "pdf-preview.json")
    _publish_text(manifest, _json(data) + "\n", cfg, protected)
    return data["status"] != "ERROR"
