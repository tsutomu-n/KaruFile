"""End-to-end video runner."""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

from . import discovery, report, state
from .config import VideoConfig, report_path, state_dir
from .ffmpeg import ToolError, prepare_probe_tool, prepare_tools
from .models import (
    Eligibility,
    FileIdentity,
    MediaInfo,
    Preset,
    ProcessResult,
    ProcessStatus,
    SourceSnapshot,
    ToolInfo,
)
from .output import (
    atomic_copy,
    publish_staged,
    staged_destination,
    validate_auxiliary_path,
    validate_destination,
)
from .probe import inspect_eligibility, probe_media
from .transform import encode_candidate, output_recipe
from .utils import (
    PathValidationError,
    stable_sha256_file,
    stat_file_identity,
    validate_input_output,
)
from .validate import validate_candidate


logger = logging.getLogger("video_shrink")


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    state_dir: Path
    temp_dir: Path
    database: Path
    report: Path
    normal_report: Path
    dry_report: Path

    @classmethod
    def from_config(cls, config: VideoConfig) -> WorkspacePaths:
        root = state_dir(config.output_dir)
        return cls(
            state_dir=root,
            temp_dir=root / "temp",
            database=root / "state.sqlite3",
            report=report_path(config.output_dir, dry_run=config.dry_run),
            normal_report=report_path(config.output_dir, dry_run=False),
            dry_report=report_path(config.output_dir, dry_run=True),
        )


@dataclass(frozen=True, slots=True)
class RunOutcome:
    exit_code: int
    results: tuple[ProcessResult, ...]
    report_path: Path | None


def _validate_plan_collisions(sources: Sequence[SourceSnapshot]) -> None:
    planned = [tuple(part.casefold() for part in source.relative_path.parts) for source in sources]
    for index, parts in enumerate(planned):
        for other in planned[index + 1 :]:
            common = min(len(parts), len(other))
            if parts[:common] == other[:common]:
                raise PathValidationError("video output paths collide case-insensitively")


def _validate_workspace(
    config: VideoConfig,
    paths: WorkspacePaths,
    sources: Sequence[SourceSnapshot],
    protected_sources: Sequence[Path],
) -> None:
    _validate_plan_collisions(sources)
    for source in sources:
        validate_destination(
            source.output_path(config.output_dir),
            input_root=config.input_dir,
            output_root=config.output_dir,
            protected_sources=protected_sources,
        )
    auxiliaries = (
        paths.state_dir,
        paths.temp_dir,
        paths.database,
        Path(f"{paths.database}-journal"),
        Path(f"{paths.database}-wal"),
        Path(f"{paths.database}-shm"),
        paths.normal_report,
        paths.dry_report,
    )
    for candidate in auxiliaries:
        validate_auxiliary_path(
            candidate,
            input_root=config.input_dir,
            output_root=config.output_dir,
            protected_sources=protected_sources,
        )
    for directory in (paths.state_dir, paths.temp_dir):
        if directory.exists() and not directory.is_dir():
            raise PathValidationError(f"video workspace path is not a directory: {directory}")
    if paths.database.exists() and not paths.database.is_file():
        raise PathValidationError(f"video state database is not a file: {paths.database}")


def _base_result(
    source: SourceSnapshot,
    destination: Path,
    config: VideoConfig,
    status: ProcessStatus,
    *,
    reason: str,
    error: str = "",
    output_size: int | None = None,
    output_sha256: str = "",
    eligibility: Eligibility | None = None,
    source_info: MediaInfo | None = None,
    tools: ToolInfo | None = None,
    vmaf_mean: float | None = None,
    vmaf_p5: float | None = None,
    output_identity: FileIdentity | None = None,
) -> ProcessResult:
    video = source_info.video_streams[0] if source_info and source_info.video_streams else None
    audio = source_info.audio_streams[0] if source_info and source_info.audio_streams else None
    if status is ProcessStatus.ADOPTED:
        video_codec = "av1"
        try:
            _muxer, _encoder, audio_codec = output_recipe(destination)
        except ToolError:
            audio_codec = ""
        if eligibility is not None and eligibility.audio is None:
            audio_codec = ""
    else:
        video_codec = video.codec_name if video else ""
        audio_codec = audio.codec_name if audio else ""
    saved = source.size - output_size if output_size is not None else 0
    percent = saved / source.size * 100 if output_size is not None and source.size else 0.0
    width = eligibility.target_width if status is ProcessStatus.ADOPTED and eligibility else None
    height = eligibility.target_height if status is ProcessStatus.ADOPTED and eligibility else None
    fps = (
        float(eligibility.target_fps)
        if status is ProcessStatus.ADOPTED and eligibility and eligibility.target_fps
        else float(video.avg_frame_rate)
        if video and video.avg_frame_rate
        else None
    )
    return ProcessResult(
        source_path=str(source.path),
        source_size=source.size,
        output_path=str(destination),
        output_size=output_size,
        saved_bytes=saved,
        saved_percent=percent,
        status=status,
        error_message=error,
        preset=config.preset,
        source_sha256=source.sha256,
        output_sha256=output_sha256,
        reason=reason,
        video_codec=video_codec,
        audio_codec=audio_codec,
        width=width if width is not None else video.width if video else None,
        height=height if height is not None else video.height if video else None,
        fps=fps,
        duration=source_info.duration if source_info else None,
        vmaf_mean=vmaf_mean,
        vmaf_p5=vmaf_p5,
        ffmpeg_version=tools.ffmpeg_version if tools else "",
        output_identity=output_identity,
        safe=config.safe,
        remove_audio=config.remove_audio,
    )


def _copy_result(
    source: SourceSnapshot,
    destination: Path,
    config: VideoConfig,
    status: ProcessStatus,
    reason: str,
    protected_sources: Sequence[Path],
    *,
    eligibility: Eligibility | None = None,
    source_info: MediaInfo | None = None,
    tools: ToolInfo | None = None,
    vmaf_mean: float | None = None,
    vmaf_p5: float | None = None,
) -> ProcessResult:
    if config.remove_audio:
        raise ToolError(f"audio removal could not be completed: {reason}")
    size, digest = atomic_copy(
        source.path,
        destination,
        input_root=config.input_dir,
        output_root=config.output_dir,
        protected_sources=protected_sources,
        expected_sha256=source.sha256,
        expected_identity=source.identity,
    )
    output_identity = stat_file_identity(destination)
    return _base_result(
        source,
        destination,
        config,
        status,
        reason=reason,
        output_size=size,
        output_sha256=digest,
        eligibility=eligibility,
        source_info=source_info,
        tools=tools,
        vmaf_mean=vmaf_mean,
        vmaf_p5=vmaf_p5,
        output_identity=output_identity,
    )


def _error_result(
    source: SourceSnapshot,
    destination: Path,
    config: VideoConfig,
    protected_sources: Sequence[Path],
    exc: BaseException,
    *,
    tools: ToolInfo | None,
) -> ProcessResult:
    message = f"{type(exc).__name__}: {exc}"[-4096:]
    output_size: int | None = None
    output_hash = ""
    output_identity = None
    if not config.remove_audio and not config.dry_run and not destination.exists() and discovery.source_is_unchanged(source):
        try:
            output_size, output_hash = atomic_copy(
                source.path,
                destination,
                input_root=config.input_dir,
                output_root=config.output_dir,
                protected_sources=protected_sources,
                expected_sha256=source.sha256,
                expected_identity=source.identity,
            )
            output_identity = stat_file_identity(destination)
            message += "; original copied as recovery"
        except Exception as copy_exc:
            message += f"; recovery copy failed: {type(copy_exc).__name__}: {copy_exc}"
    return _base_result(
        source,
        destination,
        config,
        ProcessStatus.ERROR,
        reason="video processing failed",
        error=message[-4096:],
        output_size=output_size,
        output_sha256=output_hash,
        tools=tools,
        output_identity=output_identity,
    )


def _process_one(
    source: SourceSnapshot,
    config: VideoConfig,
    paths: WorkspacePaths,
    protected_sources: Sequence[Path],
    tools: ToolInfo | None,
) -> ProcessResult:
    destination = source.output_path(config.output_dir)
    try:
        if not discovery.source_is_unchanged(source):
            raise OSError("source changed before processing")
        if config.preset is Preset.STANDARD:
            if config.dry_run:
                return _base_result(
                    source,
                    destination,
                    config,
                    ProcessStatus.DRY_RUN,
                    reason="standard would copy the original without transcoding",
                )
            return _copy_result(
                source,
                destination,
                config,
                ProcessStatus.SKIPPED_STANDARD,
                "standard copies the original without transcoding",
                protected_sources,
            )
        if tools is None:
            raise ToolError("FFmpeg tools are unavailable")
        source_info = probe_media(tools, source.path, config.recipe)
        if not discovery.source_is_unchanged(source):
            raise OSError("source changed during inspection")
        eligibility = inspect_eligibility(
            source_info, config.recipe, safe=config.safe, remove_audio=config.remove_audio,
        )
        if not eligibility.eligible:
            if config.dry_run:
                planned_status = (
                    "ERROR (audio removal unavailable)" if config.remove_audio
                    else eligibility.status.value if eligibility.status else "skip"
                )
                return _base_result(
                    source,
                    destination,
                    config,
                    ProcessStatus.DRY_RUN,
                    reason=f"would {planned_status}: {eligibility.reason}",
                    eligibility=eligibility,
                    source_info=source_info,
                    tools=tools,
                )
            return _copy_result(
                source,
                destination,
                config,
                eligibility.status or ProcessStatus.SKIPPED_COMPLEX,
                eligibility.reason,
                protected_sources,
                eligibility=eligibility,
                source_info=source_info,
                tools=tools,
            )
        if config.dry_run:
            return _base_result(
                source,
                destination,
                config,
                ProcessStatus.DRY_RUN,
                reason=(
                    f"would try CRF ladder {config.recipe.crf_ladder} at "
                    f"{eligibility.target_width}x{eligibility.target_height}"
                    f"; safe={config.safe}; remove_audio={config.remove_audio}"
                ),
                eligibility=eligibility,
                source_info=source_info,
                tools=tools,
            )

        last_quality = None
        for crf in config.recipe.crf_ladder:
            with staged_destination(
                destination,
                input_root=config.input_dir,
                output_root=config.output_dir,
                protected_sources=protected_sources,
            ) as candidate:
                encode_candidate(tools, source.path, candidate, eligibility, config, crf=crf)
                if not discovery.source_is_unchanged(source):
                    raise OSError("source changed during encoding")
                candidate_info, quality = validate_candidate(
                    tools,
                    candidate,
                    source_info,
                    source.path,
                    eligibility,
                    paths.temp_dir,
                    config,
                )
                last_quality = quality
                quality_ok = (
                    quality.mean >= config.recipe.vmaf_min_mean
                    and quality.p5 >= config.recipe.vmaf_min_p5
                )
                candidate_size = candidate.stat().st_size
                saved = source.size - candidate_size
                saved_ratio = saved / source.size if source.size else 0.0
                savings_ok = (
                    saved >= config.recipe.min_saved_bytes
                    and saved_ratio >= config.recipe.min_saved_percent
                )
                if quality_ok and savings_ok:
                    digest, _candidate_identity = stable_sha256_file(candidate)
                    if not discovery.source_is_unchanged(source):
                        raise OSError("source changed before candidate publication")
                    publish_staged(
                        candidate,
                        destination,
                        input_root=config.input_dir,
                        output_root=config.output_dir,
                        protected_sources=protected_sources,
                    )
                    output_identity = stat_file_identity(destination)
                    return _base_result(
                        source,
                        destination,
                        config,
                        ProcessStatus.ADOPTED,
                        reason=f"adopted CRF {crf}",
                        output_size=candidate_size,
                        output_sha256=digest,
                        eligibility=eligibility,
                        source_info=source_info,
                        tools=tools,
                        vmaf_mean=quality.mean,
                        vmaf_p5=quality.p5,
                        output_identity=output_identity,
                    )
                if quality_ok and not savings_ok:
                    return _copy_result(
                        source,
                        destination,
                        config,
                        ProcessStatus.UNCHANGED,
                        f"CRF {crf} did not meet both savings thresholds",
                        protected_sources,
                        eligibility=eligibility,
                        source_info=source_info,
                        tools=tools,
                        vmaf_mean=quality.mean,
                        vmaf_p5=quality.p5,
                    )

        quality_text = (
            f"VMAF mean={last_quality.mean:.3f}, p5={last_quality.p5:.3f} did not meet thresholds"
            if last_quality
            else "no CRF candidate passed validation"
        )
        return _copy_result(
            source,
            destination,
            config,
            ProcessStatus.UNCHANGED,
            quality_text,
            protected_sources,
            eligibility=eligibility,
            source_info=source_info,
            tools=tools,
            vmaf_mean=last_quality.mean if last_quality else None,
            vmaf_p5=last_quality.p5 if last_quality else None,
        )
    except Exception as exc:
        logger.error("Video processing failed for %s: %s", source.path, exc)
        return _error_result(
            source,
            destination,
            config,
            protected_sources,
            exc,
            tools=tools,
        )


def _path_key(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(str(Path(path).resolve(strict=False)))


def _validate_final_results(
    config: VideoConfig,
    sources: Sequence[SourceSnapshot],
    results: Sequence[ProcessResult],
    protected_sources: Sequence[Path],
) -> None:
    if len(results) != len(sources):
        raise ValueError("video result count does not match the input snapshot count")
    sources_by_path = {_path_key(source.path): source for source in sources}
    if len(sources_by_path) != len(sources):
        raise ValueError("video source snapshots contain duplicate paths")
    validated_identities = []
    seen_sources: set[str] = set()
    for result in results:
        source_key = _path_key(result.source_path)
        source = sources_by_path.get(source_key)
        if source is None or source_key in seen_sources:
            raise ValueError("video result has an unknown or duplicate source_path")
        seen_sources.add(source_key)
        if (
            result.source_size != source.size
            or result.source_sha256.casefold() != source.sha256.casefold()
            or result.preset is not config.preset
            or result.safe is not config.safe
            or result.remove_audio is not config.remove_audio
        ):
            raise ValueError("video result source metadata does not match its snapshot")
        if config.remove_audio and not config.dry_run and result.status is not ProcessStatus.ERROR:
            if result.audio_codec or result.status not in {ProcessStatus.ADOPTED, ProcessStatus.SKIPPED_COMPLETE}:
                raise ValueError("audio removal result is not a silent compressed output")
        source_sha256, source_identity = stable_sha256_file(
            source.path,
            expected_identity=source.identity,
        )
        if source_sha256.casefold() != source.sha256.casefold():
            raise OSError(f"video source changed before report publication: {source.path}")
        validated_identities.append((source.path, source_identity))

        expected_output = source.output_path(config.output_dir)
        if _path_key(result.output_path) != _path_key(expected_output):
            raise ValueError("video result output_path does not match the output plan")
        if config.dry_run:
            if (
                result.status is not ProcessStatus.DRY_RUN
                or result.output_size is not None
                or result.output_sha256
            ):
                raise ValueError("video dry-run result claims a published output")
            continue
        if result.output_size is None:
            if result.status is not ProcessStatus.ERROR or result.output_sha256:
                raise ValueError("video result without output is not an error shape")
            continue
        if (
            not isinstance(result.output_size, int)
            or isinstance(result.output_size, bool)
            or result.output_size < 0
            or not result.output_sha256
            or result.output_identity is None
        ):
            raise ValueError("video result output metadata is invalid")
        validate_destination(
            expected_output,
            input_root=config.input_dir,
            output_root=config.output_dir,
            protected_sources=protected_sources,
        )
        output_sha256, output_identity = stable_sha256_file(
            expected_output,
            expected_identity=result.output_identity,
        )
        if (
            output_identity.size != result.output_size
            or output_sha256.casefold() != result.output_sha256.casefold()
        ):
            raise OSError(f"video output changed before report publication: {expected_output}")
        validated_identities.append((expected_output, output_identity))

    if len(seen_sources) != len(sources_by_path):
        raise ValueError("video results do not cover every input snapshot")
    for path, identity in validated_identities:
        if stat_file_identity(path) != identity:
            raise OSError(f"video file changed during final report validation: {path}")


def run(config: VideoConfig) -> RunOutcome:
    try:
        input_dir, output_dir = validate_input_output(config.input_dir, config.output_dir)
        config = VideoConfig(
            input_dir=input_dir,
            output_dir=output_dir,
            preset=config.preset,
            workers=config.workers,
            dry_run=config.dry_run,
            ffmpeg_path=config.ffmpeg_path,
            ffprobe_path=config.ffprobe_path,
            recipe=config.recipe,
            safe=config.safe,
            remove_audio=config.remove_audio,
        )
        files = discovery.collect_videos(config.input_dir)
        sources = [discovery.snapshot(path, config.input_dir) for path in files]
        protected_sources = tuple(files)
        paths = WorkspacePaths.from_config(config)
        _validate_workspace(config, paths, sources, protected_sources)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.error("Video preflight failed: %s", exc)
        return RunOutcome(1, (), None)

    try:
        paths.state_dir.mkdir(parents=True, exist_ok=True)
        paths.temp_dir.mkdir(parents=True, exist_ok=True)
        if not config.dry_run:
            config.output_dir.mkdir(parents=True, exist_ok=True)
        _validate_workspace(config, paths, sources, protected_sources)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.error("Video workspace creation failed: %s", exc)
        return RunOutcome(1, (), None)

    tools: ToolInfo | None = None
    tool_error: BaseException | None = None
    if config.preset is Preset.COMPACT and sources:
        try:
            tools = (
                prepare_probe_tool(config.ffprobe_path, config.recipe)
                if config.dry_run
                else prepare_tools(config.ffmpeg_path, config.ffprobe_path, config.recipe)
            )
        except Exception as exc:
            tool_error = exc
            logger.error("Video tool preparation failed: %s", exc)
    processing_hash = config.processing_hash(tools)

    try:
        connection = state.init_db(paths.database)
    except Exception as exc:
        logger.error("Video state initialization failed: %s", exc)
        return RunOutcome(1, (), None)

    results: list[ProcessResult] = []
    updates: list[tuple[SourceSnapshot, ProcessResult]] = []
    operation_error: BaseException | None = None
    try:
        pending: list[SourceSnapshot] = []
        for source in sources:
            if config.dry_run:
                pending.append(source)
                continue
            record = state.get_record(connection, str(source.path))
            reused = state.reusable_result(
                record,
                source,
                processing_hash,
                expected_destination=source.output_path(config.output_dir),
                expected_preset=config.preset,
                recipe=config.recipe,
                dry_run=config.dry_run,
            )
            if reused is not None:
                if config.remove_audio and (reused.audio_codec or reused.reason != "reused ADOPTED"):
                    pending.append(source)
                else:
                    results.append(replace(reused, safe=config.safe, remove_audio=config.remove_audio))
            else:
                pending.append(source)

        if tool_error is not None:
            for source in pending:
                result = _error_result(
                    source,
                    source.output_path(config.output_dir),
                    config,
                    protected_sources,
                    tool_error,
                    tools=None,
                )
                results.append(result)
                if not config.dry_run:
                    updates.append((source, result))
        elif config.workers == 1 or len(pending) <= 1:
            for source in pending:
                result = _process_one(source, config, paths, protected_sources, tools)
                results.append(result)
                if not config.dry_run:
                    updates.append((source, result))
        else:
            with ThreadPoolExecutor(max_workers=min(config.workers, len(pending))) as executor:
                futures = {
                    executor.submit(
                        _process_one,
                        source,
                        config,
                        paths,
                        protected_sources,
                        tools,
                    ): source
                    for source in pending
                }
                for future in as_completed(futures):
                    source = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:  # defensive: _process_one normally contains failures
                        result = _error_result(
                            source,
                            source.output_path(config.output_dir),
                            config,
                            protected_sources,
                            exc,
                            tools=tools,
                        )
                    results.append(result)
                    if not config.dry_run:
                        updates.append((source, result))
    except Exception as exc:
        operation_error = exc
        logger.error("Video state operation failed: %s", exc)

    if operation_error is None:
        try:
            with report.staged_csv(
                paths.report,
                results,
                input_root=config.input_dir,
                output_root=config.output_dir,
                protected_sources=protected_sources,
            ) as staged_report:
                if updates:
                    connection.execute("BEGIN IMMEDIATE")
                    for source, result in updates:
                        state.save_result(
                            connection,
                            source,
                            result,
                            processing_hash,
                            commit=False,
                        )
                with report.published_staged_csv(
                    staged_report,
                    paths.report,
                    input_root=config.input_dir,
                    output_root=config.output_dir,
                    protected_sources=protected_sources,
                    before_publish=lambda: _validate_final_results(
                        config,
                        sources,
                        results,
                        protected_sources,
                    ),
                ):
                    if updates:
                        connection.commit()
        except Exception as exc:
            operation_error = exc
            logger.error("Video state/report finalization failed: %s", exc)
            try:
                connection.rollback()
            except Exception as rollback_exc:
                logger.error("Video state rollback failed: %s", rollback_exc)

    try:
        connection.close()
    except Exception as exc:
        if operation_error is None:
            operation_error = exc
            logger.error("Video state close failed: %s", exc)

    if operation_error is not None:
        return RunOutcome(1, tuple(results), None)
    exit_code = 1 if any(result.status is ProcessStatus.ERROR for result in results) else 0
    return RunOutcome(exit_code, tuple(results), paths.report)
