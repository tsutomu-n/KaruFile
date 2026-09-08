from __future__ import annotations

import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from video_shrink import discovery, output, report, runner, state, utils
from video_shrink.config import CompactRecipe, VideoConfig
from video_shrink.models import Preset, ProcessStatus, QualityResult, ToolInfo


def _replace_with_same_content_and_basic_stat(path: Path) -> None:
    """Atomically replace a path without changing its size, mtime, or digest."""

    before = utils.stat_file_identity(path)
    path_stat = path.stat()
    replacement = path.with_name(f".{path.name}.replacement")
    replacement.write_bytes(path.read_bytes())
    os.utime(replacement, ns=(path_stat.st_atime_ns, path_stat.st_mtime_ns))
    os.replace(replacement, path)
    after = utils.stat_file_identity(path)
    assert after.size == before.size
    assert after.mtime_ns == before.mtime_ns
    assert after != before


def _replace_once_during_hash(
    monkeypatch: pytest.MonkeyPatch,
    target: Path,
) -> dict[str, bool]:
    real_sha256_file = utils.sha256_file
    state = {"armed": True, "replaced": False}

    def racing_sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
        if state["armed"] and Path(path) == target:
            state["armed"] = False
            _replace_with_same_content_and_basic_stat(target)
            state["replaced"] = True
        return real_sha256_file(path, chunk_size=chunk_size)

    monkeypatch.setattr(utils, "sha256_file", racing_sha256_file)
    return state


def test_snapshot_rejects_same_stat_atomic_replacement_during_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    source = (input_dir / "clip.mp4").resolve()
    source.write_bytes(b"unchanged-payload")
    race = _replace_once_during_hash(monkeypatch, source)

    with pytest.raises(utils.UnstableFileError):
        discovery.snapshot(source, input_dir)

    assert race["replaced"]


def test_source_is_unchanged_rejects_same_stat_same_digest_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    source = (input_dir / "clip.mp4").resolve()
    source.write_bytes(b"unchanged-payload")
    source_snapshot = discovery.snapshot(source, input_dir)
    race = _replace_once_during_hash(monkeypatch, source)

    assert not discovery.source_is_unchanged(source_snapshot)
    assert race["replaced"]


def test_state_reuse_rejects_output_replaced_during_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    source = (input_dir / "clip.mp4").resolve()
    source.write_bytes(b"unchanged-payload")
    config = VideoConfig(input_dir, output_dir, preset=Preset.STANDARD)
    assert runner.run(config).exit_code == 0

    source_snapshot = discovery.snapshot(source, input_dir)
    connection = state.init_db(Path(f"{output_dir}.video-state") / "state.sqlite3")
    try:
        record = state.get_record(connection, str(source_snapshot.path))
    finally:
        connection.close()
    assert record is not None
    destination = (output_dir / "clip.mp4").resolve()
    race = _replace_once_during_hash(monkeypatch, destination)

    reused = state.reusable_result(
        record,
        source_snapshot,
        config.processing_hash(None),
        expected_destination=destination,
        expected_preset=Preset.STANDARD,
        recipe=config.recipe,
        dry_run=False,
    )

    assert reused is None
    assert race["replaced"]


def test_atomic_copy_rechecks_source_identity_immediately_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source = (input_dir / "clip.mp4").resolve()
    destination = output_dir / "clip.mp4"
    source.write_bytes(b"unchanged-payload")
    destination.write_bytes(b"healthy-existing-output")
    expected_sha256, expected_identity = utils.stable_sha256_file(source)
    real_stable_sha256_file = output.stable_sha256_file
    calls: list[str] = []

    def racing_stable_sha256_file(path: Path, **kwargs):
        if Path(path) == source:
            assert calls == ["temporary"]
            calls.append("source")
            _replace_with_same_content_and_basic_stat(source)
        else:
            calls.append("temporary")
        return real_stable_sha256_file(path, **kwargs)

    monkeypatch.setattr(output, "stable_sha256_file", racing_stable_sha256_file)

    with pytest.raises(utils.UnstableFileError):
        output.atomic_copy(
            source,
            destination,
            input_root=input_dir,
            output_root=output_dir,
            protected_sources=(source,),
            expected_sha256=expected_sha256,
            expected_identity=expected_identity,
        )

    assert calls == ["temporary", "source"]
    assert destination.read_bytes() == b"healthy-existing-output"
    assert not list(output_dir.glob(".*.tmp.mp4"))


def test_compact_publication_rejects_source_replaced_during_final_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    media_factory,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source = (input_dir / "clip.mp4").resolve()
    destination = output_dir / "clip.mp4"
    source.write_bytes(b"S" * 1000)
    destination.write_bytes(b"healthy-existing-output")
    source_info = media_factory(source)
    tools = ToolInfo(Path("ffmpeg"), Path("ffprobe"), "ffmpeg test", "ffprobe test")
    monkeypatch.setattr(runner, "prepare_tools", lambda *args: tools)
    monkeypatch.setattr(runner, "probe_media", lambda *args: source_info)
    monkeypatch.setattr(
        runner,
        "encode_candidate",
        lambda _tools, _source, candidate, *_args, **_kwargs: candidate.write_bytes(b"C" * 400),
    )
    race = _replace_once_during_hash(monkeypatch, source)
    race["armed"] = False

    def validate_then_arm(*args):
        race["armed"] = True
        candidate_info = replace(source_info, path=args[1])
        return candidate_info, QualityResult(95.0, 90.0, 60)

    monkeypatch.setattr(runner, "validate_candidate", validate_then_arm)
    recipe = CompactRecipe(crf_ladder=(38,), min_saved_bytes=1, min_saved_percent=0.10)

    outcome = runner.run(
        VideoConfig(input_dir, output_dir, preset=Preset.COMPACT, recipe=recipe)
    )

    assert outcome.exit_code == 1
    assert outcome.results[0].status is ProcessStatus.ERROR
    assert "source changed before candidate publication" in outcome.results[0].error_message
    assert race["replaced"]
    assert destination.read_bytes() == b"healthy-existing-output"
    assert not list(output_dir.glob(".*.tmp.mp4"))


@pytest.mark.parametrize("race_target", ["source", "output"])
def test_finalization_rejects_reused_file_replaced_while_later_file_is_processed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    race_target: str,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    first_source = (input_dir / "a.mp4").resolve()
    later_source = (input_dir / "b.mp4").resolve()
    first_source.write_bytes(b"first-video")
    later_source.write_bytes(b"later-old")
    config = VideoConfig(input_dir, output_dir, preset=Preset.STANDARD)
    first_outcome = runner.run(config)
    assert first_outcome.exit_code == 0
    assert first_outcome.report_path is not None
    old_report = first_outcome.report_path.read_bytes()

    database = Path(f"{output_dir}.video-state") / "state.sqlite3"
    connection = state.init_db(database)
    try:
        old_later_record = state.get_record(connection, str(later_source))
    finally:
        connection.close()
    assert old_later_record is not None
    later_source.write_bytes(b"later-new")

    real_process_one = runner._process_one
    raced = False

    def process_later_then_race(*args, **kwargs):
        nonlocal raced
        source_snapshot = args[0]
        if source_snapshot.path == later_source:
            target = (
                first_source
                if race_target == "source"
                else (output_dir / "a.mp4").resolve()
            )
            _replace_with_same_content_and_basic_stat(target)
            raced = True
        return real_process_one(*args, **kwargs)

    monkeypatch.setattr(runner, "_process_one", process_later_then_race)
    second_outcome = runner.run(config)

    assert raced
    assert second_outcome.exit_code == 1
    assert second_outcome.report_path is None
    assert first_outcome.report_path.read_bytes() == old_report
    connection = state.init_db(database)
    try:
        current_later_record = state.get_record(connection, str(later_source))
    finally:
        connection.close()
    assert current_later_record is not None
    assert current_later_record.source_sha256 == old_later_record.source_sha256


@pytest.mark.parametrize("race_target", ["source", "output"])
def test_save_result_revalidates_source_and_output_identity(
    tmp_path: Path,
    race_target: str,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    source_path = (input_dir / "clip.mp4").resolve()
    source_path.write_bytes(b"video")
    config = VideoConfig(input_dir, output_dir, preset=Preset.STANDARD)
    assert runner.run(config).exit_code == 0
    source_snapshot = discovery.snapshot(source_path, input_dir)
    database = Path(f"{output_dir}.video-state") / "state.sqlite3"
    connection = state.init_db(database)
    try:
        record = state.get_record(connection, str(source_path))
        reused = state.reusable_result(
            record,
            source_snapshot,
            config.processing_hash(None),
            expected_destination=(output_dir / "clip.mp4").resolve(),
            expected_preset=Preset.STANDARD,
            recipe=config.recipe,
            dry_run=False,
        )
        assert reused is not None
        target = source_path if race_target == "source" else Path(reused.output_path)
        _replace_with_same_content_and_basic_stat(target)
        with pytest.raises(utils.UnstableFileError):
            state.save_result(connection, source_snapshot, reused, config.processing_hash(None))
    finally:
        connection.close()


def test_commit_failure_rolls_back_state_and_restores_previous_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    source_path = (input_dir / "clip.mp4").resolve()
    source_path.write_bytes(b"old-content")
    config = VideoConfig(input_dir, output_dir, preset=Preset.STANDARD)
    first_outcome = runner.run(config)
    assert first_outcome.exit_code == 0
    assert first_outcome.report_path is not None
    old_report = first_outcome.report_path.read_bytes()
    database = Path(f"{output_dir}.video-state") / "state.sqlite3"
    real_init_db = state.init_db
    connection = real_init_db(database)
    try:
        old_record = state.get_record(connection, str(source_path))
    finally:
        connection.close()
    assert old_record is not None
    source_path.write_bytes(b"new-content")

    class CommitFailingConnection:
        def __init__(self, connection):
            self._connection = connection

        def __getattr__(self, name):
            return getattr(self._connection, name)

        def commit(self) -> None:
            raise RuntimeError("commit failed")

    monkeypatch.setattr(
        state,
        "init_db",
        lambda path: CommitFailingConnection(real_init_db(path)),
    )
    outcome = runner.run(config)

    assert outcome.exit_code == 1
    assert outcome.report_path is None
    assert first_outcome.report_path.read_bytes() == old_report
    connection = real_init_db(database)
    try:
        current_record = state.get_record(connection, str(source_path))
    finally:
        connection.close()
    assert current_record is not None
    assert current_record.source_sha256 == old_record.source_sha256


@pytest.mark.parametrize("path_kind", ["output", "report"])
def test_publication_does_not_chmod_a_hardlink_injected_formal_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path_kind: str,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source = (input_dir / "source.mp4").resolve()
    source.write_bytes(b"protected-source")
    source.chmod(stat.S_IREAD)
    source_mode = stat.S_IMODE(source.stat().st_mode)
    if path_kind == "output":
        destination = output_dir / "clip.mp4"
        validator_name = "validate_destination"
        publisher = output.publish_staged
    else:
        destination = Path(f"{output_dir}.video-report.csv")
        validator_name = "validate_auxiliary_path"
        publisher = output.publish_auxiliary
    destination.write_bytes(b"old-destination")
    temporary = destination.with_name(f".{destination.name}.staged")
    temporary.write_bytes(b"new-destination")
    real_validator = getattr(output, validator_name)
    validation_count = 0

    def inject_after_validation(*args, **kwargs):
        nonlocal validation_count
        real_validator(*args, **kwargs)
        validation_count += 1
        if validation_count == 1:
            destination.unlink()
            os.link(source, destination)

    monkeypatch.setattr(output, validator_name, inject_after_validation)
    try:
        with pytest.raises(utils.PathValidationError):
            publisher(
                temporary,
                destination,
                input_root=input_dir,
                output_root=output_dir,
                protected_sources=(source,),
            )
        assert os.path.samefile(source, destination)
        assert source.read_bytes() == b"protected-source"
        assert stat.S_IMODE(source.stat().st_mode) == source_mode
    finally:
        source.chmod(source_mode | stat.S_IWRITE)


@pytest.mark.skipif(os.name != "nt", reason="read-only replacement semantics are Windows-specific")
@pytest.mark.parametrize("path_kind", ["output", "report"])
def test_readonly_formal_destination_fails_closed(
    tmp_path: Path,
    path_kind: str,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source = (input_dir / "source.mp4").resolve()
    source.write_bytes(b"protected-source")
    if path_kind == "output":
        destination = output_dir / "clip.mp4"
        publisher = output.publish_staged
    else:
        destination = Path(f"{output_dir}.video-report.csv")
        publisher = output.publish_auxiliary
    destination.write_bytes(b"readonly-existing")
    destination.chmod(stat.S_IREAD)
    readonly_mode = stat.S_IMODE(destination.stat().st_mode)
    temporary = destination.with_name(f".{destination.name}.staged")
    temporary.write_bytes(b"new-destination")
    try:
        with pytest.raises(OSError):
            publisher(
                temporary,
                destination,
                input_root=input_dir,
                output_root=output_dir,
                protected_sources=(source,),
            )
        assert destination.read_bytes() == b"readonly-existing"
        assert stat.S_IMODE(destination.stat().st_mode) == readonly_mode
    finally:
        destination.chmod(readonly_mode | stat.S_IWRITE)


def test_report_rollback_does_not_chmod_or_unlink_an_injected_source_hardlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source = (input_dir / "source.mp4").resolve()
    source.write_bytes(b"protected-source")
    source.chmod(stat.S_IREAD)
    source_mode = stat.S_IMODE(source.stat().st_mode)
    report_path = Path(f"{output_dir}.video-report.csv")
    real_validator = report.validate_auxiliary_path
    rollback_armed = False

    def inject_during_rollback(*args, **kwargs):
        real_validator(*args, **kwargs)
        if rollback_armed and Path(args[0]) == report_path:
            report_path.unlink()
            os.link(source, report_path)

    monkeypatch.setattr(report, "validate_auxiliary_path", inject_during_rollback)
    try:
        with output.staged_auxiliary(
            report_path,
            input_root=input_dir,
            output_root=output_dir,
            protected_sources=(source,),
        ) as temporary:
            temporary.write_bytes(b"new-report")
            with pytest.raises(RuntimeError, match="video report rollback failed"):
                with report.published_staged_csv(
                    temporary,
                    report_path,
                    input_root=input_dir,
                    output_root=output_dir,
                    protected_sources=(source,),
                ):
                    rollback_armed = True
                    raise RuntimeError("peer commit failed")
        assert os.path.samefile(source, report_path)
        assert source.read_bytes() == b"protected-source"
        assert stat.S_IMODE(source.stat().st_mode) == source_mode
    finally:
        source.chmod(source_mode | stat.S_IWRITE)


def test_report_does_not_overwrite_concurrent_update_before_publish(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    report_path = Path(f"{output_dir}.video-report.csv")
    report_path.write_bytes(b"previous-report")

    with output.staged_auxiliary(
        report_path,
        input_root=input_dir,
        output_root=output_dir,
        protected_sources=(),
    ) as temporary:
        temporary.write_bytes(b"our-new-report")

        def concurrent_update() -> None:
            report_path.write_bytes(b"concurrent-report")

        with pytest.raises(OSError, match="changed before (?:publish|hashing)"):
            with report.published_staged_csv(
                temporary,
                report_path,
                input_root=input_dir,
                output_root=output_dir,
                protected_sources=(),
                before_publish=concurrent_update,
            ):
                pass

    assert report_path.read_bytes() == b"concurrent-report"
