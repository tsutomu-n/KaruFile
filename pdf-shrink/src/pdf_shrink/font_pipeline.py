"""Evaluate explicit font candidates without owning publication or state."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import time

from .config import RunConfig
from .lossless_jpeg import CandidateRejected
from .models import CandidateResult, SourceSnapshot
from .qpdf import qpdf_check, qpdf_optimize


def evaluate(source: SourceSnapshot, target: Path, kind: str, cfg: RunConfig,
             qpdf: Path, deadline: float) -> CandidateResult:
    from . import font_replace, font_validate

    detail = CandidateResult(kind=kind)
    def check_deadline() -> None:
        if time.monotonic() > deadline:
            raise CandidateRejected("font_replace_time_limit")
    try:
        check_deadline()
        if cfg.font_replace_path is None or not cfg.font_replace_sha256:
            raise RuntimeError("Windows replacement font was not prepared")
        if kind == "lossless":
            qpdf_optimize(qpdf, source.path, target, cfg.qpdf, reject_warnings=True)
        elif kind == "font_replace":
            with TemporaryDirectory(prefix="font-", dir=target.parent) as folder:
                intermediate = Path(folder) / "prepared.pdf"
                font_replace.generate(source.path, intermediate, cfg.font_replace_path,
                                      cfg.font_replace_sha256, deadline)
                check_deadline()
                qpdf_optimize(qpdf, intermediate, target, cfg.qpdf, reject_warnings=True)
        else:
            raise ValueError(f"unknown font candidate: {kind}")
        detail = replace(detail, size=target.stat().st_size)
        check_deadline()
        rc = qpdf_check(qpdf, target)
        if rc:
            raise RuntimeError(f"qpdf check failed (rc={rc})")
        summary = font_validate.validate_candidate(
            source.path, target, font_path=cfg.font_replace_path,
            expected_font_sha256=cfg.font_replace_sha256, deadline=deadline,
            lossless=kind == "lossless",
        )
        return replace(detail, reason="eligible" if detail.size < source.size else "candidate_not_smaller",
                       text_extraction_changed=summary.extraction_whitespace_changed if kind == "font_replace" else False)
    except CandidateRejected as exc:
        return replace(detail, reason="quality_rejected", validation_reason=str(exc))
    except Exception as exc:
        return replace(detail, reason="processing_error", validation_reason=str(exc))
