# media-shrink

画像・動画・PDF の一括圧縮と重複ファイル削除を、**一発のコマンド**で行う Python ツールです。

## 対応処理

- **画像**: 横幅 1200px 以下にリサイズ、EXIF/ICC 保持、JPG 変換、HEIC/HEIF 対応
- **動画**: ffmpeg 経由で H.264/HEVC へのトランスコード、CRF ベース圧縮
- **PDF**: `pikepdf` で可逆圧縮、`PyMuPDF` で非可逆画像縮小
- **重複削除**: ファイルサイズ＋ハッシュで完全一致を検出、画像は知覚ハッシュでも検出可能

## インストール

```powershell
# uv が必要です
uv sync
```

または、依存を自動で解決しつつ直接実行：

```powershell
uv run shrink --help
```

## 使い方

### 一括実行（おすすめ）

```powershell
uv run shrink shrink -i "C:\Users\tn\Downloads\高倉地区復旧治山工事(R6補正)"
```

元画像は別フォルダ `..._resized` に保存され、元フォルダ内の動画・PDF が圧縮されます。重複ファイルも削除されます。

### 元画像も削除して最大限ディスクを空けたい

```powershell
uv run shrink shrink -i "C:\Users\tn\Downloads\高倉地区復旧治山工事(R6補正)" --remove-source-images
```

### ドライラン（何が起きるか先に確認）

```powershell
uv run shrink shrink -i "C:\Users\tn\Downloads\高倉地区復旧治山工事(R6補正)" -n
```

### 個別コマンド

```powershell
# 画像のみ
uv run shrink resize -i "C:\Users\tn\Downloads\高倉地区復旧治山工事(R6補正)" -o "C:\Users\tn\Downloads\縮小写真"

# 動画のみ
uv run shrink video -i "C:\Users\tn\Downloads\高倉地区復旧治山工事(R6補正)"

# PDF のみ（可逆）
uv run shrink pdf -i "C:\Users\tn\Downloads\高倉地区復旧治山工事(R6補正)"

# PDF 非可逆（スキャンPDF用）
uv run shrink pdf -i "C:\Users\tn\Downloads\高倉地区復旧治山工事(R6補正)" --lossy

# 重複削除のみ
uv run shrink dedup -i "C:\Users\tn\Downloads\高倉地区復旧治山工事(R6補正)"
```

## 設定ファイル

`shrink.toml` を作るとデフォルト値を上書きできます。

```toml
[image]
max_width = 1200
quality = 85
format = "jpg"

[video]
codec = "libx264"
crf = 23
preset = "medium"
max_height = 1080

[pdf]
mode = "lossless"  # "lossy" にすると画像縮小も行う

[dedup]
min_size = 1024
perceptual = false
```

指定：

```powershell
uv run shrink shrink -i "..." -c "C:\Users\tn\Downloads\shrink.toml"
```

## 安全設計

- **DRY-RUN**: `-n` で実際の書き込み・削除を行わずプレビュー
- **出力検証**: 変換後ファイルが存在しサイズが 0 でないことを確認してから元を削除
- **ゴミ箱**: 削除は `send2trash` で行い、即削除を避ける（`--no-trash` で変更可能）
- **ログ**: 処理内容をコンソールに表示

## プロジェクト構成

```text
media-shrink-tool/
├── pyproject.toml
├── README.md
└── src/
    └── media_shrink/
        ├── cli.py
        ├── config.py
        ├── image.py
        ├── video.py
        ├── pdf.py
        ├── dedup.py
        └── utils.py
```

## 依存

- Pillow
- pillow-heif
- imageio-ffmpeg
- pikepdf
- PyMuPDF
- xxhash
- send2trash
- imagehash
