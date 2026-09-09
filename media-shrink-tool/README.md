# media-shrink-tool

KaruFileの画像専用処理コンポーネントです。入力画像を変更・削除せず、別の出力フォルダーへ
JPEGを保存します。通常の利用手順は [KaruFile 利用者マニュアル](../MANUAL.md)を参照し、
リポジトリ直下の `karufile.py` を使ってください。

この文書は、画像処理コンポーネントを個別に使う場合と実装を保守する場合の参照です。

## セットアップと個別CLI

リポジトリ直下で実行します。

```powershell
uv sync --project media-shrink-tool
uv run --project media-shrink-tool python -m media_shrink resize `
  -i "D:\作業\資料" `
  -o "D:\作業\資料_resized" `
  --preset standard `
  -j 4
```

公開サブコマンドは `resize` だけです。

| オプション | 意味 |
|---|---|
| `-i`, `--input` | 入力フォルダー。必須 |
| `-o`, `--output` | 別の出力フォルダー。省略時は `<input>_resized` |
| `-n`, `--dry-run` | 画像をデコードして予定を確認 |
| `-j`, `--workers` | 並列処理数。既定値は4、最小値は1 |
| `--preset` | `standard`または`compact`。既定値は`standard` |
| `-v`, `--verbose` | 詳細ログ |

統合CLIとPDF個別CLIの既定出力は `<input>_軽量化` ですが、この個別CLIは
`<input>_resized` です。入力と出力が同一、または互いに親子となる指定は処理前に拒否します。

`--dry-run` は画像出力を書きませんが、現在の検査結果を残すためエラーCSVとdry-run
manifestの更新を試みます。
通常実行では確認入力を求めません。

## 変換プリセット

より詳細な内部動作（寸法計算、marker、再利用、安全性検査、レポート形式など）は
[docs/image-processing.html](../docs/image-processing.html) を参照してください。

| 項目 | `standard` | `compact` |
|---|---:|---:|
| 最大寸法 | 長辺1280px・短辺960px | 長辺1024px・短辺768px |
| JPEG quality | 72 | 60 |

どちらもJPEG 4:2:0、optimize、progressiveを使います。縦横比を維持し、
拡大や切り抜きは行いません。EXIF Orientationは画素へ適用し、透過部分は
白背景へ合成します。animation・複数ページは先頭フレームだけを使用し、
ターミナルへ警告を表示します。

入力候補はJPEG、PNG、TIFF、BMP、GIF、WebP、HEIC、HEIF、出力はJPEGです。

## 出力名と衝突

JPEG入力は `.jpg` または `.jpeg` を維持します。非JPEG入力は元のファイル名全体へ
`.jpg` を追加します。

```text
photo.jpg  -> photo.jpg
photo.jpeg -> photo.jpeg
photo.png  -> photo.png.jpg
```

Windowsで大文字小文字を無視すると出力名が衝突する場合、処理開始前に相対入力パスの
SHA-256先頭8文字を付けます。ファイルとディレクトリのprefixが衝突する場合も、
ファイル側の出力名へハッシュを付けて解消します。

## JPEG候補と再利用

上限内のJPEGは、候補が32 KiB以上かつ10%以上小さくなる場合だけ再エンコード結果を
採用します。それ以外は入力JPEGを出力へコピーします。

KaruFileが生成したJPEGには、小文字の識別情報 `karufile:image-v2` と入力スナップショットを
保存します。

- 同じプリセットの生成物は再エンコードしません。
- `compact`生成物を`standard`で処理しても、拡大・再エンコードしません。
- `standard`生成物を`compact`で処理する場合だけ再処理し、寸法上限または品質を下げます。
  同寸法の候補は実ファイルが小さくなる場合だけ採用します。
- 生成済み短絡は、SHA-256を含む完全な現行markerかつ既知recipeで、Orientation適用が不要、
  現在presetの寸法上限内の場合だけ許可します。未知・破損・旧v1 markerは通常のJPEG候補
  判定へ戻し、markerだけを理由に圧縮を省略しません。
- 同じ入力SHA-256・ファイルサイズ・更新時刻と現在の変換条件に一致し、寸法が現在の上限内に
  ある完成済み出力は再利用します。旧v1 markerはSHA-256を持たないため一度再生成します。
- `standard`でコピー済みJPEGを再利用する場合は、ファイルサイズ・更新時刻に
  加えてbyte列の一致も確認します。`compact`では既存コピーを再評価します。

## メタデータと警告

EXIF、GPS、DateTimeOriginal、カメラ・レンズ情報、ICC、XMP、JPEG comment、DPIは、
PillowでJPEGへ保存できる範囲で可能な限り保持します。完全保持は保証しません。
Orientation適用後は古いOrientation値を残しません。CMYKなどからRGBへ単純変換した場合は、
意味の異なるICCを付けず、ターミナルへ警告を表示します。警告は画像エラーCSVへ
保存しません。

代表的な警告:

- `ANIMATION_DROPPED`
- `MULTIPAGE_DROPPED`
- `ALPHA_FLATTENED`
- `ICC_DROPPED`
- `OUTPUT_LARGER_THAN_SOURCE`
- `ENCODE_FAILED_ORIGINAL_COPIED`

警告だけなら終了コードは `0` です。

## エラー、レポート、終了コード

1件の変換失敗で残りの画像を停止しません。エラーは次へ記録します。

```text
<output>.image-errors.csv
```

列は `source,planned_output,error` です。入力・出力の検査を通過してレポート公開に成功した
場合は、現在実行の結果で置き換え、エラー0件でもヘッダーだけへ更新します。検査または公開に
失敗した場合は終了コード `1` となり、以前のCSVが残ることがあります。

全画像の現在実行結果は、通常実行とdry-runを分けた次の原子的manifestへ記録します。

```text
<output>.image-manifest.csv
<output>.image-manifest.dry-run.csv
```

列は `source_path,source_size,source_sha256,output_path,output_size,output_sha256,action,error,`
`preset,recipe_hash,orig_width,orig_height,new_width,new_height` です。公開直前に全入力と、通常実行で
生成・再利用した出力のpath、size、SHA-256、寸法を再検証します。manifestを更新できない場合も
終了コードは `1` です。既存の正式出力またはレポートがread-onlyの場合、入力側のmodeを変えない
ため自動でchmodせず、以前の内容を残してfail-closedにします。

| コード | 意味 |
|---:|---|
| `0` | 画像エラーなし |
| `1` | 画像エラーあり、レポート更新失敗、または入出力検査失敗 |
| `2` | 引数不正 |

候補JPEGと原本コピーは、出力先と同じディレクトリの一時ファイルへ書き、JPEGとして
再オープンしてから `os.replace()` で公開します。入力または出力に含まれるシンボリックリンク、
ジャンクション、危険なハードリンクは処理前または公開境界で拒否します。

## 対象外

動画、PDF、重複削除、知覚ハッシュ、元ファイル削除は対象外です。PDF処理は
`pdf-shrink` だけが担当します。

## 開発検証

リポジトリ直下で実行します。

```powershell
uv run --project media-shrink-tool --extra dev python -m pytest -q media-shrink-tool/tests
uv run --project media-shrink-tool python -m compileall -q media-shrink-tool/src media-shrink-tool/tests
uv run --project media-shrink-tool python -m media_shrink --help
```

テストは小さな合成画像を使用します。実データPilotは今回の実装では実施していません。
