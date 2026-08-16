# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""KaruFile の PDF・画像オーケストレータ。

サードパーティ依存を持たない単一ファイルスクリプト（PEP 723）。`pdf-shrink` と
`media-shrink-tool` を `uv run --project` 経由でサブプロセス実行し、混在する
PDF + 画像フォルダーをまとめて軽量化する。実行環境には uv と各プロジェクトの
`.venv` が必要。

使用例:
    uv run --script karufile.py -i "C:\\...\\input" [-o "C:\\...\\output"] -n
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# KaruFile/orchestrator/shrink_all.py から見て parent.parent が KaruFile リポジトリのルート。
REPO_ROOT = Path(__file__).resolve().parent.parent

# 呼び出し対象プロジェクト。環境変数で上書き可能。
PDF_SHRINK_DIR = Path(os.environ.get("PDF_SHRINK_ROOT", REPO_ROOT / "pdf-shrink"))
MEDIA_SHRINK_DIR = Path(os.environ.get("MEDIA_SHRINK_ROOT", REPO_ROOT / "media-shrink-tool"))

PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".gif", ".webp", ".heic", ".heif"
}
JPEG_EXTENSIONS = {".jpg", ".jpeg"}

IMAGE_SUMMARY_RE = re.compile(r"Resized\s+(\d+)\s+images\s+\((\d+)\s+errors\)")
IMAGE_SIZE_RE = re.compile(
    r"([\d.]+)\s*(B|KB|MB|GB|TB)\s*->\s+([\d.]+)\s*(B|KB|MB|GB|TB)",
    re.IGNORECASE,
)
PDF_REPORT_REQUIRED_COLUMNS = frozenset(
    {"source_path", "source_size", "output_size", "saved_bytes", "status"}
)
PDF_REPORT_STATUSES = frozenset(
    {
        "ADOPTED_LOSSLESS",
        "ADOPTED_LOSSY",
        "UNCHANGED",
        "SKIPPED_SMALL",
        "SKIPPED_ENCRYPTED",
        "SKIPPED_SIGNED",
        "SKIPPED_COMPLEX",
        "DRY_RUN_LOSSLESS",
        "DRY_RUN_LOSSY",
        "ERROR",
    }
)


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def human_size(num: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:.2f} {unit}"
        num /= 1024.0
    return f"{num:.2f} TB"


def _to_bytes(value: float, unit: str) -> int:
    unit = unit.upper()
    multipliers = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    return int(value * multipliers.get(unit, 1))


def run_command(
    name: str,
    project_dir: Path,
    args: list[str],
) -> tuple[int, list[str], float]:
    """uv run --project <project_dir> <args> をストリームしながら実行する。"""
    cmd = ["uv", "run", "--project", str(project_dir)]
    cmd.extend(args)

    logging.info("[%s] Starting: %s", name, " ".join(cmd))
    start = time.perf_counter()
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=project_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        elapsed = time.perf_counter() - start
        logging.error("[%s] Failed to start: %s", name, exc)
        return 1, [], elapsed
    lines: list[str] = []
    if proc.stdout:
        for line in proc.stdout:
            line = line.rstrip("\n")
            print(line)
            lines.append(line)
    returncode = proc.wait()
    elapsed = time.perf_counter() - start
    logging.info("[%s] Finished in %.2fs (exit code: %d)", name, elapsed, returncode)
    return returncode, lines, elapsed


def _is_link_or_junction(path: Path) -> bool:
    """Return whether *path* is a filesystem link that traversal must not follow."""

    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, FileNotFoundError):
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def collect_files(input_dir: Path, extensions: set[str]) -> list[Path]:
    """Collect regular files without following symlinks or Windows junctions."""

    input_root = input_dir.resolve(strict=True)
    found: list[Path] = []
    pending = [input_root]
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise ValueError(f"入力ディレクトリを探索できません: {directory}: {exc}") from exc

        for entry in entries:
            path = Path(entry.path)
            if _is_link_or_junction(path):
                raise ValueError(f"入力内のシンボリックリンクまたはjunctionは処理できません: {path}")
            try:
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                resolved = path.resolve(strict=True)
            except OSError as exc:
                raise ValueError(f"入力ファイルを確認できません: {path}: {exc}") from exc

            if not _is_within(resolved, input_root):
                raise ValueError(f"入力root外へ解決されるファイルは処理できません: {path}")
            if resolved.suffix.lower() in extensions:
                found.append(resolved)

    return sorted(
        found,
        key=lambda path: (
            path.relative_to(input_root).as_posix().casefold(),
            path.relative_to(input_root).as_posix(),
        ),
    )


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _has_link_component(root: Path, candidate: Path) -> bool:
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return True
    current = root
    if _is_link_or_junction(current):
        return True
    for part in relative.parts:
        current = current / part
        if _is_link_or_junction(current):
            return True
    return False


def validate_directories(input_dir: Path, output_dir: Path) -> None:
    """processor 起動前に危険な入出力関係を拒否する。"""
    if not input_dir.is_dir():
        raise ValueError(f"入力ディレクトリが存在しません: {input_dir}")
    if output_dir.exists() and not output_dir.is_dir():
        raise ValueError(f"出力先がディレクトリではありません: {output_dir}")
    if input_dir == output_dir:
        raise ValueError("入力と出力に同じディレクトリは指定できません")
    if _is_within(output_dir, input_dir):
        raise ValueError("出力ディレクトリを入力ディレクトリ配下には置けません")
    if _is_within(input_dir, output_dir):
        raise ValueError("入力ディレクトリを出力ディレクトリ配下には置けません")


def _plan_image_destinations(
    input_root: Path,
    output_dir: Path,
    image_files: list[Path],
) -> list[tuple[Path, Path]]:
    """media_shrink.image.plan_outputs と同じstable naming/collision規則を適用する。"""

    base: list[tuple[Path, Path, Path]] = []
    groups: dict[str, list[int]] = {}
    for source in image_files:
        relative_source = source.resolve(strict=True).relative_to(input_root)
        relative_output = relative_source
        if relative_output.suffix.lower() not in JPEG_EXTENSIONS:
            relative_output = relative_output.with_name(f"{relative_output.name}.jpg")
        index = len(base)
        base.append((source, relative_source, relative_output))
        groups.setdefault(relative_output.as_posix().casefold(), []).append(index)

    hashed_indexes = {
        index
        for indexes in groups.values()
        if len(indexes) > 1
        for index in indexes
    }
    while True:
        planned_relative: list[Path] = []
        for index, (_source, relative_source, relative_output) in enumerate(base):
            if index in hashed_indexes:
                digest = hashlib.sha256(
                    relative_source.as_posix().encode("utf-8")
                ).hexdigest()[:8]
                relative_output = relative_output.with_name(
                    f"{relative_output.stem}~{digest}{relative_output.suffix}"
                )
            planned_relative.append(relative_output)

        final_groups: dict[str, list[int]] = {}
        for index, relative_output in enumerate(planned_relative):
            final_groups.setdefault(relative_output.as_posix().casefold(), []).append(index)
        remaining = [indexes for indexes in final_groups.values() if len(indexes) > 1]

        path_parts = [
            tuple(part.casefold() for part in relative_output.parts)
            for relative_output in planned_relative
        ]
        prefix_indexes = {
            left_index
            for left_index, left in enumerate(path_parts)
            for right_index, right in enumerate(path_parts)
            if left_index != right_index
            and len(left) < len(right)
            and right[:len(left)] == left
        }
        if not remaining and not prefix_indexes:
            return [
                (base[index][0], output_dir / relative_output)
                for index, relative_output in enumerate(planned_relative)
            ]

        newly_hashed = {
            index
            for indexes in remaining
            for index in indexes
            if index not in hashed_indexes
        }
        newly_hashed.update(index for index in prefix_indexes if index not in hashed_indexes)
        if newly_hashed:
            hashed_indexes.update(newly_hashed)
            continue

        conflicting = sorted(
            {index for indexes in remaining for index in indexes} | prefix_indexes
        )
        sources_text = ", ".join(str(base[index][1]) for index in conflicting)
        raise ValueError(
            "8桁hashでも画像出力の同名・file/directory衝突を解消できません: "
            f"{sources_text}"
        )


def validate_planned_destinations(
    input_dir: Path,
    output_dir: Path,
    pdf_files: list[Path],
    image_files: list[Path],
) -> None:
    """全processorの予定出力が、link解決後も安全な出力root内か確認する。"""

    input_root = input_dir.resolve(strict=True)
    output_root = output_dir.resolve(strict=False)
    planned: list[tuple[str, Path, Path]] = []
    for source in pdf_files:
        relative = source.resolve(strict=True).relative_to(input_root)
        planned.append(("pdf", source, output_dir / relative))

    planned.extend(
        ("image", source, destination)
        for source, destination in _plan_image_destinations(
            input_root,
            output_dir,
            image_files,
        )
    )
    protected_sources = tuple([*pdf_files, *image_files])

    for _processor, source, destination in planned:
        resolved_source = source.resolve(strict=True)
        if not _is_within(resolved_source, input_root):
            raise ValueError(f"入力root外へ解決されるファイルは処理できません: {source}")
        resolved_destination = destination.resolve(strict=False)
        if not _is_within(resolved_destination, output_root):
            raise ValueError(
                "予定出力が出力root外へ解決されます: "
                f"{destination} -> {resolved_destination}"
            )
        if _is_within(resolved_destination, input_root):
            raise ValueError(
                "予定出力が入力側へ解決されます: "
                f"{destination} -> {resolved_destination}"
            )
        destination_lexical = Path(os.path.abspath(destination))
        output_lexical = Path(os.path.abspath(output_dir))
        if _has_link_component(output_lexical, destination_lexical):
            raise ValueError(f"予定出力にlink/junction componentがあります: {destination}")
        if destination.exists():
            destination_stat = destination.stat()
            if destination_stat.st_nlink > 1:
                raise ValueError(f"予定出力がhardlinkです: {destination}")
            for protected_source in protected_sources:
                if os.path.samefile(destination, protected_source):
                    raise ValueError(
                        f"予定出力が入力sourceと同一fileです: "
                        f"{destination} == {protected_source}"
                    )

    relative_plans = [
        (
            processor,
            destination.relative_to(output_dir),
            tuple(part.casefold() for part in destination.relative_to(output_dir).parts),
        )
        for processor, _source, destination in planned
    ]
    resolved_plans = [
        (
            destination,
            tuple(
                part.casefold()
                for part in destination.resolve(strict=False).relative_to(output_root).parts
            ),
        )
        for _processor, _source, destination in planned
    ]
    for index, (destination, parts) in enumerate(resolved_plans):
        for other_destination, other_parts in resolved_plans[index + 1:]:
            common = min(len(parts), len(other_parts))
            if parts[:common] == other_parts[:common]:
                raise ValueError(
                    "予定出力の実体に同名・file/directory衝突があります: "
                    f"{destination} / {other_destination}"
                )
    for index, (processor, relative, parts) in enumerate(relative_plans):
        for other_processor, other_relative, other_parts in relative_plans[index + 1:]:
            common = min(len(parts), len(other_parts))
            has_prefix_conflict = parts[:common] == other_parts[:common] and (
                len(parts) != len(other_parts)
                or processor != other_processor
            )
            if has_prefix_conflict:
                raise ValueError(
                    "予定出力にfile/directory衝突があります: "
                    f"{relative} / {other_relative}"
                )


def validate_derived_write_paths(
    input_dir: Path,
    output_dir: Path,
    pdf_files: list[Path],
    image_files: list[Path],
) -> None:
    """processorが出力mirror外へ書く状態・reportパスの衝突を拒否する。"""

    input_root = input_dir.resolve(strict=True)
    output_root = output_dir.resolve(strict=False)
    work_root = Path(os.path.abspath(output_dir.parent))
    work_root_resolved = work_root.resolve(strict=False)
    derived: list[tuple[str, Path]] = [
        ("image error report", Path(f"{output_dir}.image-errors.csv")),
    ]
    if pdf_files:
        state_dir = work_root / ".pdf-shrink"
        temp_root = state_dir / "temp"
        derived.extend(
            [
                ("PDF state directory", state_dir),
                ("PDF temporary directory", temp_root),
                ("PDF state database", state_dir / "state.sqlite3"),
                ("PDF state journal", state_dir / "state.sqlite3-journal"),
                ("PDF state WAL", state_dir / "state.sqlite3-wal"),
                ("PDF state shared memory", state_dir / "state.sqlite3-shm"),
                ("PDF report", work_root / "report.csv"),
                ("PDF dry-run report", work_root / "report.dry-run.csv"),
            ]
        )
        derived.extend(
            (
                "PDF per-source temporary directory",
                temp_root / source.resolve(strict=True).relative_to(input_root).parent,
            )
            for source in pdf_files
        )

    protected_sources = tuple([*pdf_files, *image_files])

    for label, candidate in derived:
        candidate_lexical = Path(os.path.abspath(candidate))
        if not _is_within(candidate_lexical, work_root):
            raise ValueError(f"{label}がwork root外です: {candidate}")
        if _has_link_component(work_root, candidate_lexical):
            raise ValueError(f"{label}にlink/junctionが含まれます: {candidate}")
        resolved = candidate.resolve(strict=False)
        if not _is_within(resolved, work_root_resolved):
            raise ValueError(
                f"{label}がwork root外へ解決されます: {candidate} -> {resolved}"
            )
        if _is_within(resolved, input_root) or _is_within(input_root, resolved):
            raise ValueError(
                f"{label}が入力と衝突します: {candidate} -> {resolved}"
            )
        if _is_within(resolved, output_root) or _is_within(output_root, resolved):
            raise ValueError(
                f"{label}が出力mirrorと衝突します: {candidate} -> {resolved}"
            )
        if candidate.exists():
            candidate_stat = candidate.stat()
            if not candidate.is_dir() and candidate_stat.st_nlink > 1:
                raise ValueError(f"{label}がhardlinkです: {candidate}")
            for protected_source in protected_sources:
                if os.path.samefile(candidate, protected_source):
                    raise ValueError(
                        f"{label}が入力sourceと同一fileです: "
                        f"{candidate} == {protected_source}"
                    )


def _empty_result() -> dict[str, Any]:
    return {
        "count": 0,
        "errors": 0,
        "orig_size": 0,
        "new_size": 0,
        "saved": 0,
    }


def _unavailable_result() -> dict[str, Any]:
    return {
        "count": None,
        "errors": None,
        "orig_size": None,
        "new_size": None,
        "saved": None,
    }


def _file_signature(path: Path) -> tuple[int, int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size


def _was_updated(path: Path, previous: tuple[int, int, int] | None) -> bool:
    current = _file_signature(path)
    return current is not None and current != previous


def parse_pdf_report(report_path: Path) -> dict[str, Any]:
    total_in = 0
    total_out = 0
    saved = 0
    count = 0
    errors = 0
    input_sizes_complete = True
    output_sizes_complete = True
    status_counts: dict[str, int] = {}
    source_paths: list[str] = []

    if not report_path.exists():
        return {}

    try:
        with open(report_path, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or not PDF_REPORT_REQUIRED_COLUMNS.issubset(
                reader.fieldnames
            ):
                raise ValueError("required PDF report columns are missing")
            for row in reader:
                if None in row:
                    raise ValueError("PDF report row has unexpected extra columns")
                source_path = row.get("source_path")
                if not source_path:
                    raise ValueError("PDF report row has no source_path")
                source_paths.append(source_path)
                count += 1
                raw_input = row.get("source_size")
                raw_output = row.get("output_size")
                if raw_input in (None, ""):
                    raise ValueError("PDF report row has no source_size")
                else:
                    input_size = int(raw_input)
                    if input_size < 0:
                        raise ValueError("PDF report source_size must not be negative")
                    total_in += input_size
                if raw_output in (None, ""):
                    output_sizes_complete = False
                else:
                    output_size = int(raw_output)
                    if output_size < 0:
                        raise ValueError("PDF report output_size must not be negative")
                    total_out += output_size
                saved_bytes = int(row.get("saved_bytes") or 0)
                saved += saved_bytes
                status = row.get("status") or ""
                if status not in PDF_REPORT_STATUSES:
                    raise ValueError(f"unknown PDF report status: {status!r}")
                status_counts[status] = status_counts.get(status, 0) + 1
                if status == "ERROR":
                    errors += 1
    except Exception as exc:
        logging.warning("Failed to parse PDF report %s: %s", report_path, exc)
        return {}

    return {
        "count": count,
        "orig_size": total_in if input_sizes_complete else None,
        "new_size": total_out if output_sizes_complete else None,
        "saved": saved if input_sizes_complete and output_sizes_complete else None,
        "errors": errors,
        "status_counts": status_counts,
        "source_paths": source_paths,
    }


def pdf_report_matches_inputs(report_result: dict[str, Any], pdf_files: list[Path]) -> bool:
    """現在実行の全PDFが重複なくreportへ記録されたことを確認する。"""

    if report_result.get("count") != len(pdf_files):
        return False
    raw_paths = report_result.get("source_paths")
    if not isinstance(raw_paths, list) or len(raw_paths) != len(pdf_files):
        return False
    try:
        reported = [str(Path(path).resolve(strict=False)).casefold() for path in raw_paths]
        expected = [str(path.resolve(strict=True)).casefold() for path in pdf_files]
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    return len(set(reported)) == len(reported) and set(reported) == set(expected)


def parse_image_summary(lines: list[str]) -> dict[str, Any] | None:
    count: int | None = None
    errors = 0
    orig_size: int | None = None
    new_size: int | None = None

    for line in lines:
        m = IMAGE_SUMMARY_RE.search(line)
        if m:
            count = int(m.group(1))
            errors = int(m.group(2))
            continue
        m = IMAGE_SIZE_RE.search(line)
        if m:
            orig_size = _to_bytes(float(m.group(1)), m.group(2))
            new_size = _to_bytes(float(m.group(3)), m.group(4))

    if count is None:
        return None

    return {
        "count": count,
        "errors": errors,
        "orig_size": orig_size,
        "new_size": new_size,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="karufile",
        description="PDF と画像を、原本を変更せず別フォルダーへ軽量化する",
    )
    parser.add_argument("-i", "--input", required=True, help="入力ディレクトリ")
    parser.add_argument(
        "-o", "--output",
        help="出力ディレクトリ（未指定時は <input>_軽量化）",
    )
    parser.add_argument(
        "--pdf-workers", type=_positive_int, default=2,
        help="pdf-shrink の並列数（デフォルト 2）",
    )
    parser.add_argument(
        "--image-workers", type=_positive_int, default=4,
        help="media-shrink-tool の並列数（デフォルト 4）",
    )
    parser.add_argument(
        "-n", "--dry-run", action="store_true",
        help="完成PDF・画像を作らず判定を確認（状態・レポートは更新される場合あり）",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="詳細ログ")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    setup_logging(args.verbose)

    try:
        input_dir = Path(args.input).resolve()
        if args.output:
            output_dir = Path(args.output).resolve()
        else:
            output_dir = (input_dir.parent / f"{input_dir.name}_軽量化").resolve()
        validate_directories(input_dir, output_dir)
        pdf_files = collect_files(input_dir, PDF_EXTENSIONS)
        image_files = collect_files(input_dir, IMAGE_EXTENSIONS)
        validate_planned_destinations(input_dir, output_dir, pdf_files, image_files)
        validate_derived_write_paths(input_dir, output_dir, pdf_files, image_files)
    except (OSError, RuntimeError, ValueError) as exc:
        logging.error("%s", exc)
        return 1

    if not args.dry_run:
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            validate_planned_destinations(input_dir, output_dir, pdf_files, image_files)
            validate_derived_write_paths(input_dir, output_dir, pdf_files, image_files)
        except OSError as exc:
            logging.error("出力ディレクトリを作成できません: %s", exc)
            return 1
        except (RuntimeError, ValueError) as exc:
            logging.error("出力作成後の安全性検証に失敗しました: %s", exc)
            return 1

    print("KaruFile")
    print()
    print(f"Input  : {input_dir}")
    print(f"Output : {output_dir}")
    print()
    print(f"PDF    : {len(pdf_files)}")
    print(f"Images : {len(image_files)}")
    print()
    print("Source files : keep")
    print("Files deleted: 0")
    print()
    print("Starting...")
    sys.stdout.flush()

    start = time.perf_counter()
    report_name = "report.dry-run.csv" if args.dry_run else "report.csv"
    pdf_report_path = output_dir.parent / report_name
    pdf_report_before = _file_signature(pdf_report_path)
    image_error_report = Path(f"{output_dir}.image-errors.csv")
    image_report_before = _file_signature(image_error_report)

    # 1. PDF 軽量化
    pdf_exit = 0
    pdf_result = _empty_result()
    if pdf_files:
        pdf_args = [
            "python", "-m", "pdf_shrink", "run",
            "--input", str(input_dir),
            "--output", str(output_dir),
            "--workers", str(args.pdf_workers),
        ]
        if args.dry_run:
            pdf_args.append("--dry-run")
        if args.verbose:
            pdf_args.append("-v")

        pdf_exit, _pdf_lines, _pdf_elapsed = run_command("pdf-shrink", PDF_SHRINK_DIR, pdf_args)

        if _was_updated(pdf_report_path, pdf_report_before):
            parsed_pdf = parse_pdf_report(pdf_report_path)
            if parsed_pdf and pdf_report_matches_inputs(parsed_pdf, pdf_files):
                pdf_result = parsed_pdf
                if parsed_pdf.get("errors", 0) > 0:
                    pdf_exit = pdf_exit or 1
            else:
                logging.error(
                    "PDF report does not match the current input set: %s",
                    pdf_report_path,
                )
                pdf_result = _unavailable_result()
                pdf_exit = pdf_exit or 1
        else:
            logging.error("PDF report was not updated by this run: %s", pdf_report_path)
            pdf_result = _unavailable_result()
            pdf_exit = pdf_exit or 1

    # 2. 画像リサイズ
    image_args = [
        "python", "-m", "media_shrink", "resize",
        "-i", str(input_dir),
        "-o", str(output_dir),
        "-j", str(args.image_workers),
    ]
    if args.dry_run:
        image_args.append("-n")
    if args.verbose:
        image_args.append("-v")

    image_exit, image_lines, _image_elapsed = run_command("media-shrink", MEDIA_SHRINK_DIR, image_args)
    image_report_updated = _was_updated(image_error_report, image_report_before)
    if not image_report_updated:
        logging.error("Image error report was not updated by this run: %s", image_error_report)
        image_exit = image_exit or 1

    # 3. 結果集計
    image_result = parse_image_summary(image_lines)
    image_summary_valid = (
        image_result is not None
        and isinstance(image_result.get("count"), int)
        and isinstance(image_result.get("errors"), int)
        and isinstance(image_result.get("orig_size"), int)
        and isinstance(image_result.get("new_size"), int)
        and image_result["count"] >= 0
        and image_result["errors"] >= 0
        and image_result["count"] + image_result["errors"] == len(image_files)
    )
    if not image_summary_valid:
        logging.error(
            "Image summary does not match the current input set: expected %d images",
            len(image_files),
        )
        image_result = _unavailable_result()
        image_exit = image_exit or 1
    elif image_result["errors"] > 0:
        image_exit = image_exit or 1

    elapsed = time.perf_counter() - start

    # 4. 統合サマリー
    pdf_orig = pdf_result.get("orig_size", 0)
    pdf_new = pdf_result.get("new_size", 0)
    pdf_errors = pdf_result.get("errors", 0)

    img_orig = image_result.get("orig_size", 0)
    img_new = image_result.get("new_size", 0)
    img_errors = image_result.get("errors", 0)

    original_known = isinstance(pdf_orig, int) and isinstance(img_orig, int)
    output_known = isinstance(pdf_new, int) and isinstance(img_new, int)
    total_orig = pdf_orig + img_orig if original_known else None
    total_new = pdf_new + img_new if output_known else None
    totals_known = total_orig is not None and total_new is not None
    total_saved = total_orig - total_new if totals_known else None
    reduction = (
        total_saved / total_orig * 100
        if totals_known and total_orig
        else 0.0 if totals_known else None
    )

    print()
    print("KaruFile completed")
    print()
    print(f"PDF errors   : {pdf_errors if pdf_errors is not None else 'unknown'}")
    print(f"Image errors : {img_errors if img_errors is not None else 'unknown'}")
    print()
    if args.dry_run:
        print(f"Original size : {human_size(total_orig) if total_orig is not None else 'unknown'}")
        print("Output size   : not written (dry-run)")
        print("Saved         : not calculated (dry-run)")
        print("Reduction     : not calculated (dry-run)")
    else:
        print(f"Original size : {human_size(total_orig) if total_orig is not None else 'unknown'}")
        print(f"Output size   : {human_size(total_new) if total_new is not None else 'unknown'}")
        print(f"Saved         : {human_size(total_saved) if total_saved is not None else 'unknown'}")
        print(f"Reduction     : {f'{reduction:.2f}%' if reduction is not None else 'unknown'}")
    print()
    print("Source files changed: NO")
    print("Files deleted       : 0")
    print()
    print("Image error report:")
    if image_report_updated:
        print(image_error_report)
    else:
        print(f"{image_error_report} (not updated this run)")
    print(f"Elapsed: {elapsed:.2f}s")

    if args.dry_run:
        print("\n[DRY-RUN] PDF・画像出力は作成しません。状態とレポートは更新される場合があります。")

    return 0 if (pdf_exit == 0 and image_exit == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
