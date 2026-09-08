# KaruFile

KaruFileは、フォルダー内のPDFと画像、およびcompact presetで対応する動画を、
入力原本を変更・削除せず別フォルダーへ一括で軽量化するWindows向けCLIです。

## 利用者向け正本

初回準備、安全上の注意、実行手順、出力場所、変換条件、終了コードは
[KaruFile 利用者マニュアル](MANUAL.md)を参照してください。このREADMEは入口です。

数値、status、再利用条件、個別CLIは [KaruFile技術リファレンス](docs/REFERENCE.md)で
検索できます。

処理全体は、Archifyで生成・検証した図から先に確認できます。

[![KaruFile実行時アーキテクチャ](docs/architecture/karufile-runtime.compact.visual-check.1440x900.light.png)](docs/architecture/karufile-runtime.compact.html)

- [対話型HTMLを開く](docs/architecture/karufile-runtime.compact.html)
- [図の検証済みJSONを確認する](docs/architecture/karufile-runtime.architecture.json)

## 最短の実行手順

必要環境はWindows、Python 3.13以上、[uv](https://docs.astral.sh/uv/)です。
`karufile.py`があるリポジトリ直下のPowerShellで実行します。
PDFの通常実行ではqpdfを使い、未検出時は自動取得します。

```powershell
uv sync --project pdf-shrink --dev
uv sync --project media-shrink-tool
```

準備後、PDF・画像を既定の`standard`で処理する場合:

```powershell
uv run --script karufile.py --dry-run -i "D:\作業\資料" -o "D:\作業\資料_軽量化"
uv run --script karufile.py -i "D:\作業\資料" -o "D:\作業\資料_軽量化"
```

既定の`standard`はPDF・画像を処理し、動画は探索・コピーしません。
PDF・画像をより強く圧縮し、対応動画も処理する場合は、上の実行手順に代えて
次の`compact`手順を使います。動画の通常実行には対応機能を備えた外部FFmpeg/ffprobeが必要です。
自動取得はしないため、[マニュアルの必要環境](MANUAL.md#必要なもの)を先に確認してください。

```powershell
uv sync --project video-shrink
uv run --script karufile.py --preset compact --dry-run -i "D:\作業\資料" -o "D:\作業\資料_軽量化"
uv run --script karufile.py --preset compact -i "D:\作業\資料" -o "D:\作業\資料_軽量化"
```

`-o` を省略すると、入力と同じ階層の `<入力フォルダー名>_軽量化` を使います。
入力と出力が同一、または互いに親子となる指定は処理前に拒否します。

写真PDFを選んで閲覧用候補を作る場合は、
[マニュアルの写真PDF手順](MANUAL.md#写真pdfの閲覧用コピーを作る)を参照してください。
`--pdf-photo-pattern`で明示選択し、`--pdf-photo-dpi`で150〜300 DPI（既定200）を選べます。
`--pdf-preview`では原本・完成出力と、任意の追加DPI候補をローカルHTMLで比較できます。

> `--dry-run` でも状態DBとレポートは更新される場合があります。画像のメタデータは
> 削除を保証せず、GPS情報が残る場合があります。実行前に正本マニュアルを確認してください。

## 構成

| パス | 役割 |
|---|---|
| `karufile.py` | 通常使うCLI入口 |
| `orchestrator/` | PDF・画像・compact動画の処理コンポーネントを順に呼び、結果を集計 |
| `pdf-shrink/` | PDF処理の正本。PyMuPDF、qpdf、SQLiteを使用 |
| `media-shrink-tool/` | 画像をJPEGへ変換する処理コンポーネント |
| `video-shrink/` | compact動画を外部FFmpegで変換・検証する処理コンポーネント |

コンポーネント固有のCLIと内部契約:

- [pdf-shrink](pdf-shrink/README.md)
- [media-shrink-tool](media-shrink-tool/README.md)
- [video-shrink](video-shrink/README.md)
- [orchestrator](orchestrator/README.md)

文書の正本・補足・履歴の区別は [文書ガイド](docs/README.md)、AI向けのリポジトリ指示は
[AGENTS.md](AGENTS.md)、実装計画と検証記録は [ExecPlan索引](.agent/execplans/README.md) にあります。

## 開発検証

検証コマンドと変更範囲ごとの実行方針は [AGENTS.md](AGENTS.md#validation)を参照してください。
自動テストは小さな合成データが中心です。写真DPI・比較HTMLの実資料5冊による限定検証は
[検証記録](docs/validation/2026-09-09-photo-preview.md)を参照してください。
compactの最終検証は [ExecPlan索引](.agent/execplans/README.md)上で中断・再開待ちです。
