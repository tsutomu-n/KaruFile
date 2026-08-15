# KaruFile image processor

KaruFile の画像専用コンポーネントです。入力画像を変更・削除せず、別の出力フォルダーへ軽量版 JPEG を保存します。通常はリポジトリ直下の `karufile.py` から利用します。

## セットアップ

```powershell
uv sync --project media-shrink-tool
```

## 個別CLI

公開サブコマンドは `resize` だけです。

```powershell
uv run --project media-shrink-tool python -m media_shrink resize `
  -i "D:\資料" `
  -o "D:\資料_軽量化" `
  -j 4
```

`-o` を省略した場合は `<input>_resized` を使います。入力と出力が同一、または互いに親子となる指定は処理前に拒否します。

`--dry-run` は画像をデコードして予定を確認します。入力画像と画像出力は書き込みませんが、現在の検査結果を正しく残すため、後述の error CSV は更新します。通常実行で確認入力は求めません。

## 固定変換仕様

- 入力候補: JPEG、PNG、TIFF、BMP、GIF、WebP、HEIC、HEIF
- 出力: JPEG、quality 72、4:2:0、optimize、progressive
- 寸法: 長辺1280px・短辺960px以内、縦横比維持、拡大・切り抜きなし
- EXIF Orientation を画素へ適用してからリサイズ
- 透過は白背景へ合成
- animated GIF/WebP と multi-page TIFF は先頭フレームだけを使用し、warning を記録

JPEG入力は `.jpg` / `.jpeg` を維持します。非JPEG入力は元のファイル名全体へ `.jpg` を追加します。

```text
photo.jpg  -> photo.jpg
photo.jpeg -> photo.jpeg
photo.png  -> photo.png.jpg
```

Windowsで大文字小文字を無視すると出力名が衝突する場合は、処理開始前に相対入力パスの SHA-256 先頭8文字を付けます。

上限内のJPEGは、候補が32 KiB以上かつ10%以上小さくなる場合だけ再エンコードし、それ以外は原本を出力へコピーします。KaruFileが生成したJPEGには lowercase の `karufile:image-v1` markerを保存し、marker付き入力は旧recipeでも再エンコードしません。同じ入力size・mtimeと現recipeに一致する完成済み出力も再利用します。

## metadata と warning

EXIF、GPS、DateTimeOriginal、カメラ・レンズ情報、ICC、XMP、JPEG comment、DPIは、PillowでJPEGへ保存できる範囲でbest-effort保持します。完全保持は保証しません。Orientation適用後は古いOrientation値を残しません。CMYK等からRGBへ単純変換した場合は、意味の異なるICCを添付せずwarningを記録します。

代表的なwarning:

- `ANIMATION_DROPPED`
- `MULTIPAGE_DROPPED`
- `ALPHA_FLATTENED`
- `ICC_DROPPED`
- `OUTPUT_LARGER_THAN_SOURCE`

warningだけなら終了コードは0です。

## エラー

変換失敗は残りの画像を止めず、次のCSVへ記録します。

```text
<output_dir>.image-errors.csv
```

列は `source,planned_output,error` です。現在実行の結果で毎回置き換え、エラー0件でもheaderだけへ更新します。

終了コード:

- `0`: 画像エラーなし
- `1`: 画像エラーあり、レポート更新失敗、または入出力検査失敗
- `2`: 引数不正

候補JPEGと原本コピーは出力先と同じディレクトリの一時ファイルへ書き、JPEGとして再オープンしてから `os.replace()` で公開します。

## 対象外

動画、PDF、重複削除、知覚ハッシュ、元ファイル削除はこのコンポーネントの対象外です。PDF処理はリポジトリの `pdf-shrink` が唯一の正本です。

実データPilotは環境ごとに別途実施してください。この実装の自動テストは小さな合成画像を使用します。
