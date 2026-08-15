# KaruFile

KaruFile は、指定フォルダー内の PDF と画像を、原本を変更・削除せず別フォルダーへ一括で軽量化する Windows 向け CLI です。

```text
KaruFile/
├── karufile.py         通常使う入口
├── pdf-shrink/         PDF 処理の正本（PyMuPDF + qpdf + SQLite）
├── media-shrink-tool/  画像を JPEG へ変換する processor
└── orchestrator/       2つの processor を順番に呼ぶ薄い統合 CLI
```

## 必要環境

- Windows
- Python 3.13 以上
- [uv](https://docs.astral.sh/uv/)
- `pdf-shrink` が利用する qpdf（初回実行時に既存実装が取得する場合があります）

各 project の依存は lockfile に従って準備します。

```powershell
uv sync --project pdf-shrink --dev
uv sync --project media-shrink-tool
```

## 実行

Repo ルートから次を実行します。

```powershell
uv run --script karufile.py `
  -i "D:\資料" `
  -o "D:\資料_軽量化"
```

`-o` を省略すると `<入力フォルダー名>_軽量化` を使います。入力と出力が同一、または互いに親子関係になる指定は、processor を起動する前に拒否します。

`--dry-run`（`-n`）は任意です。通常実行で確認入力は求めません。

```powershell
uv run --script karufile.py -i "D:\資料" --dry-run
```

dry-run は PDF・画像の完成出力を作りませんが、判定用の状態やレポートを更新する場合があります。

## 出力契約

- PDF と画像の相対フォルダー構造を維持します。
- 入力 PDF・画像の byte 列を変更せず、入力ファイルを削除しません。
- 一部のファイルが失敗しても残りを処理します。
- PDF または画像で1件以上失敗すると終了コード `1` を返します。
- 画像エラーは `<出力フォルダー>.image-errors.csv` に記録します。エラー0件でも header のみへ更新します。
- PDF の詳細レポートと再開状態は `pdf-shrink` の既存契約に従い、出力フォルダーの親に保存します。

## 画像仕様

JPEG、PNG、TIFF、BMP、GIF、WebP、HEIC/HEIF を読み込み、JPEG として出力します。

- 長辺 1280px、短辺 960px 以内（拡大・切り抜きなし）
- JPEG quality 72、4:2:0、optimize、progressive
- EXIF Orientation を画素へ適用
- 透過は白背景へ合成
- animation と複数ページは先頭フレームだけを変換し warning を記録
- 生成 marker と入力 snapshot により、完成済み JPEG の不要な再圧縮を回避
- 一時ファイルを検証してから原子的に正式出力へ公開

EXIF、GPS、ICC、XMP、comment、DPI は Pillow で扱える範囲の best-effort 保持です。全 metadata、MakerNotes、入力形式固有情報の完全保持は保証しません。共有前に位置情報を含む metadata の扱いを確認してください。

## 対象外

動画圧縮、重複削除、知覚ハッシュ、元ファイル削除、GUI は KaruFile v1 の対象外です。PDF 処理は `pdf-shrink` だけが担当します。

各 component の詳細:

- [pdf-shrink/README.md](pdf-shrink/README.md)
- [media-shrink-tool/README.md](media-shrink-tool/README.md)
- [orchestrator/README.md](orchestrator/README.md)

## 開発検証

```powershell
uv run --project pdf-shrink python -m pytest -q pdf-shrink/tests
uv run --project media-shrink-tool --with pytest python -m pytest -q media-shrink-tool/tests
Push-Location orchestrator
uv run --with pytest python -m pytest -q
Pop-Location
uv run --script karufile.py --help
```

自動テストは小さな合成 fixture を使います。今回の実装では実データ Pilot は未実施です。代表的な実データでの Pilot は別途実施してください。
