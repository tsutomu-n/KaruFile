"""Atomic CSV reporting for the current input set."""
from __future__ import annotations

import csv
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Sequence

from .models import ProcessResult
from .output import (
    publish_auxiliary,
    staged_auxiliary,
    validate_auxiliary_path,
)
from .utils import stable_sha256_file


FIELDNAMES = (
    "source_path",
    "source_size",
    "output_path",
    "output_size",
    "saved_bytes",
    "saved_percent",
    "status",
    "error_message",
    "preset",
    "source_sha256",
    "output_sha256",
    "reason",
    "video_codec",
    "audio_codec",
    "width",
    "height",
    "fps",
    "duration",
    "vmaf_mean",
    "vmaf_p5",
    "ffmpeg_version",
)


@contextmanager
def staged_csv(
    path: Path,
    results: Sequence[ProcessResult],
    *,
    input_root: Path,
    output_root: Path,
    protected_sources: Sequence[Path],
) -> Iterator[Path]:
    with staged_auxiliary(
        path,
        input_root=input_root,
        output_root=output_root,
        protected_sources=protected_sources,
    ) as temporary:
        with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDNAMES)
            writer.writeheader()
            for result in sorted(results, key=lambda item: item.source_path.casefold()):
                writer.writerow(result.as_csv_row())
            stream.flush()
        yield temporary


@contextmanager
def published_staged_csv(
    temporary: Path,
    path: Path,
    *,
    input_root: Path,
    output_root: Path,
    protected_sources: Sequence[Path],
    before_publish: Callable[[], None] | None = None,
) -> Iterator[None]:
    """Publish a staged report and restore the previous report if its peer commit fails."""

    validate_auxiliary_path(
        path,
        input_root=input_root,
        output_root=output_root,
        protected_sources=protected_sources,
    )
    had_previous = path.is_file()
    new_sha256, new_identity = stable_sha256_file(temporary)
    with staged_auxiliary(
        path,
        input_root=input_root,
        output_root=output_root,
        protected_sources=protected_sources,
    ) as backup:
        previous_sha256 = ""
        previous_identity = None
        if had_previous:
            previous_sha256, previous_identity = stable_sha256_file(path)
            shutil.copy2(path, backup)
            backup_sha256, _backup_identity = stable_sha256_file(backup)
            current_sha256, _current_identity = stable_sha256_file(
                path,
                expected_identity=previous_identity,
            )
            if backup_sha256 != previous_sha256 or current_sha256 != previous_sha256:
                raise OSError(f"existing video report changed while backing it up: {path}")

        published = False
        published_identity = None
        try:
            if before_publish is not None:
                before_publish()
            # A concurrent run may have updated the formal report while the
            # final source/output validation was hashing large files. Never
            # overwrite that newer report, and never publish a changed stage.
            validate_auxiliary_path(
                path,
                input_root=input_root,
                output_root=output_root,
                protected_sources=protected_sources,
            )
            if had_previous:
                current_sha256, _current_identity = stable_sha256_file(
                    path,
                    expected_identity=previous_identity,
                )
                if current_sha256 != previous_sha256:
                    raise OSError(f"existing video report changed before publish: {path}")
            elif path.exists():
                raise OSError(f"video report appeared before publish: {path}")
            staged_sha256, _staged_identity = stable_sha256_file(
                temporary,
                expected_identity=new_identity,
            )
            if staged_sha256 != new_sha256:
                raise OSError(f"staged video report changed before publish: {temporary}")
            publish_auxiliary(
                temporary,
                path,
                input_root=input_root,
                output_root=output_root,
                protected_sources=protected_sources,
            )
            published = True
            published_sha256, published_identity = stable_sha256_file(path)
            if published_sha256 != new_sha256:
                raise OSError(f"published video report verification failed: {path}")
            yield
        except BaseException as exc:
            if published:
                try:
                    current_sha256, _current_identity = stable_sha256_file(
                        path,
                        expected_identity=published_identity,
                    )
                    if current_sha256 != new_sha256:
                        raise OSError("published video report changed before rollback")
                    if had_previous:
                        backup_sha256, _backup_identity = stable_sha256_file(backup)
                        if backup_sha256 != previous_sha256:
                            raise OSError("video report rollback backup changed")
                        publish_auxiliary(
                            backup,
                            path,
                            input_root=input_root,
                            output_root=output_root,
                            protected_sources=protected_sources,
                        )
                        restored_sha256, _restored_identity = stable_sha256_file(path)
                        if restored_sha256 != previous_sha256:
                            raise OSError("video report rollback verification failed")
                    else:
                        validate_auxiliary_path(
                            path,
                            input_root=input_root,
                            output_root=output_root,
                            protected_sources=protected_sources,
                        )
                        current_sha256, _current_identity = stable_sha256_file(
                            path,
                            expected_identity=published_identity,
                        )
                        if current_sha256 != new_sha256:
                            raise OSError("published video report changed before removal")
                        path.unlink()
                except BaseException as rollback_exc:
                    raise RuntimeError(
                        f"video report rollback failed after {type(exc).__name__}: {exc}"
                    ) from rollback_exc
            raise


def write_csv(
    path: Path,
    results: Sequence[ProcessResult],
    *,
    input_root: Path,
    output_root: Path,
    protected_sources: Sequence[Path],
) -> None:
    with staged_csv(
        path,
        results,
        input_root=input_root,
        output_root=output_root,
        protected_sources=protected_sources,
    ) as temporary:
        with published_staged_csv(
            temporary,
            path,
            input_root=input_root,
            output_root=output_root,
            protected_sources=protected_sources,
        ):
            pass
