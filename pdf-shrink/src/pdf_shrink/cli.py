"""pdf-shrinkのコマンドライン境界。"""
from __future__ import annotations

import argparse
import logging
import sys

from . import runner
from .config import CompressionPreset, build_config
from .utils import logger, setup_logging


def cmd_run(args: argparse.Namespace) -> int:
    try:
        cfg = build_config(args)
    except ValueError as exc:
        logger.error("%s", exc)
        return 2
    return runner.run(cfg)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf-shrink",
        description="Windows向けPDF一括軽量化ツール",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="PDFフォルダーを軽量化する")
    run_parser.add_argument("--input", required=True, help="入力PDFフォルダー")
    run_parser.add_argument("--output", help="出力フォルダー（未指定時は <input>_軽量化）")
    run_parser.add_argument("--workers", type=int, default=2, help="並列プロセス数（デフォルト2）")
    run_parser.add_argument(
        "--preset",
        choices=tuple(preset.value for preset in CompressionPreset),
        default=CompressionPreset.STANDARD.value,
        help="圧縮プリセット（デフォルトstandard）",
    )
    run_parser.add_argument(
        "--photo-pattern", action="append", default=[], metavar="PATTERN",
        help="写真中心PDFを相対globで明示選択し約200 DPI・JPEG品質80の閲覧用候補を作る（反復可）",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="出力PDFを作らず、判定結果だけを記録する",
    )
    run_parser.add_argument("--safe", action="store_true", help="非可逆画像縮小を無効化しqpdf可逆のみ")
    run_parser.add_argument(
        "--limit",
        type=int,
        help="パイロット実行：サイズ上位floor(N/2)件 + 残りから固定seedでN-floor(N/2)件",
    )
    run_parser.add_argument("--retry-errors", action="store_true", help="前回ERRORを再処理")
    run_parser.add_argument("--qpdf-path", help="qpdf.exe のパス")
    run_parser.add_argument("-v", "--verbose", action="store_true", help="詳細ログ")
    run_parser.set_defaults(func=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
