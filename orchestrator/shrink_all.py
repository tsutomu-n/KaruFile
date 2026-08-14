# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""pdf-shrink と media-shrink-tool を 1 回のコマンドで実行するオーケストレータ。

サードパーティ依存を持たない単一ファイルスクリプト（PEP 723）。`pdf-shrink` と
`media-shrink-tool` を `uv run --project` 経由でサブプロセス実行し、混在する
PDF + 画像フォルダーをまとめて軽量化する。実行環境には uv と各プロジェクトの
`.venv` が必要。

使用例:
    uv run --script orchestrator/shrink_all.py -i "C:\\...\\input" [-o "C:\\...\\output"] -n
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# shrinker/orchestrator/shrink_all.py から見て parent.parent が shrinker リポジトリのルート。
REPO_ROOT = Path(__file__).resolve().parent.parent

# 呼び出し対象プロジェクト。環境変数で上書き可能。
PDF_SHRINK_DIR = Path(os.environ.get("PDF_SHRINK_ROOT", REPO_ROOT / "pdf-shrink"))
MEDIA_SHRINK_DIR = Path(os.environ.get("MEDIA_SHRINK_ROOT", REPO_ROOT / "media-shrink-tool"))

PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".gif", ".webp", ".heic", ".heif"
}

IMAGE_SUMMARY_RE = re.compile(r"Resized\s+(\d+)\s+images\s+\((\d+)\s+errors\)")
IMAGE_SIZE_RE = re.compile(
    r"([\d.]+)\s*(B|KB|MB|GB|TB)\s*->\s+([\d.]+)\s*(B|KB|MB|GB|TB)",
    re.IGNORECASE,
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


def collect_files(input_dir: Path, extensions: set[str]) -> list[Path]:
    return [
        p for p in input_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in extensions
    ]


def sum_size(files: list[Path]) -> int:
    return sum(p.stat().st_size for p in files if p.exists())


def parse_pdf_report(report_path: Path) -> dict[str, Any]:
    total_in = 0
    total_out = 0
    saved = 0
    count = 0
    errors = 0
    status_counts: dict[str, int] = {}

    if not report_path.exists():
        return {}

    try:
        with open(report_path, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                count += 1
                in_size = int(row.get("source_size") or 0)
                out_size = int(row.get("output_size") or in_size)
                total_in += in_size
                total_out += out_size
                saved += int(row.get("saved_bytes") or 0)
                status = row.get("status") or "UNKNOWN"
                status_counts[status] = status_counts.get(status, 0) + 1
                if status == "ERROR":
                    errors += 1
    except Exception as exc:
        logging.warning("Failed to parse PDF report %s: %s", report_path, exc)

    return {
        "count": count,
        "orig_size": total_in,
        "new_size": total_out,
        "saved": saved,
        "errors": errors,
        "status_counts": status_counts,
    }


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
        "orig_size": orig_size or 0,
        "new_size": new_size or 0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shrink_all.py",
        description="pdf-shrink と media-shrink-tool を 1 回のコマンドで実行する",
    )
    parser.add_argument("-i", "--input", required=True, help="入力ディレクトリ")
    parser.add_argument(
        "-o", "--output",
        help="出力ディレクトリ（未指定時は <input>_軽量化）",
    )
    parser.add_argument(
        "--pdf-workers", type=int, default=2,
        help="pdf-shrink の並列数（デフォルト 2）",
    )
    parser.add_argument(
        "--image-workers", type=int, default=4,
        help="media-shrink-tool の並列数（デフォルト 4）",
    )
    parser.add_argument(
        "-n", "--dry-run", action="store_true",
        help="書き込みせず計画のみ確認",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="詳細ログ")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    setup_logging(args.verbose)

    input_dir = Path(args.input).resolve()
    if not input_dir.exists():
        logging.error("入力ディレクトリが存在しません: %s", input_dir)
        return 1

    if args.output:
        output_dir = Path(args.output).resolve()
    else:
        output_dir = input_dir.parent / f"{input_dir.name}_軽量化"

    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    pdf_files = collect_files(input_dir, PDF_EXTENSIONS)
    image_files = collect_files(input_dir, IMAGE_EXTENSIONS)

    logging.info("入力: %s", input_dir)
    logging.info("出力: %s", output_dir)
    logging.info("対象ファイル数: PDF=%d, 画像=%d", len(pdf_files), len(image_files))

    start = time.perf_counter()

    # 1. PDF 軽量化
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

    # 3. 結果集計
    report_name = "report.dry-run.csv" if args.dry_run else "report.csv"
    pdf_report_path = output_dir.parent / report_name
    pdf_result = parse_pdf_report(pdf_report_path)

    image_result = parse_image_summary(image_lines)
    if image_result is None:
        # サマリー行が取得できなかった場合は出力ディレクトリ内の .jpg サイズで近似
        output_images = list(output_dir.rglob("*.jpg"))
        image_result = {
            "count": len(output_images),
            "errors": max(0, len(image_files) - len(output_images)),
            "orig_size": sum_size(image_files),
            "new_size": sum_size(output_images),
        }

    elapsed = time.perf_counter() - start

    # 4. 統合サマリー
    pdf_count = pdf_result.get("count", 0)
    pdf_orig = pdf_result.get("orig_size", 0)
    pdf_new = pdf_result.get("new_size", 0)
    pdf_saved = pdf_result.get("saved", 0)
    pdf_errors = pdf_result.get("errors", 0)

    img_count = image_result.get("count", 0)
    img_orig = image_result.get("orig_size", 0)
    img_new = image_result.get("new_size", 0)
    img_saved = img_orig - img_new
    img_errors = image_result.get("errors", 0)

    total_orig = pdf_orig + img_orig
    total_new = pdf_new + img_new
    total_saved = total_orig - total_new

    print("\n" + "=" * 55)
    print("Shrink All Summary")
    print("=" * 55)
    print(f"入力ディレクトリ : {input_dir}")
    print(f"出力ディレクトリ : {output_dir}")
    print(f"処理時間         : {elapsed:.2f}s")
    print("-" * 55)
    print(f"PDF")
    print(f"  ファイル数      : {pdf_count}")
    print(f"  サイズ          : {human_size(pdf_orig)} -> {human_size(pdf_new)}")
    print(f"  削減量          : {human_size(pdf_saved)}")
    print(f"  エラー数        : {pdf_errors}")
    print(f"画像")
    print(f"  ファイル数      : {img_count}")
    print(f"  サイズ          : {human_size(img_orig)} -> {human_size(img_new)}")
    print(f"  削減量          : {human_size(img_saved)}")
    print(f"  エラー数        : {img_errors}")
    print("-" * 55)
    print(f"合計")
    print(f"  ファイル数      : {pdf_count + img_count}")
    print(f"  サイズ          : {human_size(total_orig)} -> {human_size(total_new)}")
    print(f"  削減量          : {human_size(total_saved)}")
    if total_orig > 0:
        print(f"  削減率          : {total_saved / total_orig * 100:.2f}%")
    print("=" * 55)

    if args.dry_run:
        print("\n[DRY-RUN] 実際の書き込みは行っていません。")

    return 0 if (pdf_exit == 0 and image_exit == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
