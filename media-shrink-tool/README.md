# media-shrink-tool

KaruFileの画像専用処理コンポーネントです。入力画像を変更・削除せず、別の出力フォルダーへ
JPEG・PNG・WebPを保存します。通常の利用手順は [KaruFile 利用者マニュアル](../MANUAL.md)を参照し、
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

サブコマンドは通常処理`resize`、掲載用マスター`web-public`、ローカル画面`gui`です。
以下のオプション表・プリセット・CSVは`resize`の契約です。

### Web掲載用マスター

```powershell
uv run --project media-shrink-tool python -m media_shrink web-public -i "D:\写真" --kind photo
uv run --project media-shrink-tool python -m media_shrink web-public -i "D:\図版" --kind graphic --file "表紙.png"
uv run --project media-shrink-tool python -m media_shrink web-public -i "D:\写真" --dry-run
uv sync --project media-shrink-tool --extra gui --extra dev
uv run --project media-shrink-tool --extra gui python -m media_shrink gui
```

担当者は準備済み環境で`run-web-public.cmd`をダブルクリックできます。日本語画面は127.0.0.1:8080のみ。
GUI依存はoptionalで、通常CLIはNiceGUIをimportしません。cmdは`.venv`を使い、依存を取得・更新しません。

`--kind photo|graphic`（既定photo）、`-o/--output`（既定`<入力名>_HP掲載用`）、
繰り返し`--file`（globではない相対ファイル名）、`-j/--workers`（既定2、1〜4）、`--dry-run`を受け付けます。
写真はJPEG q90/4:4:4、図版は透過PNG。向き補正後の横幅1400pxまでで、長辺制限ではありません。
妥当なICCはsRGBへ変換し、入力metadataと内部markerを持ち出しません。公開用の原本コピーは行いません。
透明画素を含むphoto、壊れたICC、未対応色/HDR/高bit depth、複数フレーム、64MiB/80MP超過は画像別エラー。
完成画像を新しい`runs/<run-id>/files`へ中立名で保存し、社内用`manifest.web-public.json`に対応関係を記録します。
再利用は原本と完成画像のSHA・recipe・engine・出力検証に基づき、新runへのバイトコピーで行います。
公開用recipe v2はBMP/Exifの色情報検査を含み、v1の記録からは原本を再変換します。
プレビューは全タブで同時1件、変換との重複を防止します。エラー時のstage/例外種別は起動端末の診断へ出力します。
dry-runは出力もmanifestも書きません。終了0=全画像成功、1=画像/保存/manifest失敗、2=引数/選択不正・0枚。
詳しい操作・注意は[マニュアル](../MANUAL.md#web掲載用マスターを作る)、
固定値・manifestは[技術リファレンス](../docs/REFERENCE.md#web-public掲載用マスター)を参照してください。
通常resizeとの使い分け、処理の流れと責務は[Web掲載用マスターの解説](../docs/WEB_PUBLIC.md)にまとめています。

### resizeオプション

| オプション | 意味 |
|---|---|
| `-i`, `--input` | 入力フォルダー。必須 |
| `-o`, `--output` | 別の出力フォルダー。省略時は `<input>_resized` |
| `-n`, `--dry-run` | 画像をデコードして予定を確認 |
| `-j`, `--workers` | 並列処理数。既定値は4、最小値は1 |
| `--format` | 出力形式jpeg/png/webp。既定jpeg |
| `--strip-exif` | Orientation適用後にEXIFを除去。既定OFF |
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
JPEGでは白背景へ合成、PNG・WebPでは保持します。animation・複数ページは先頭フレームだけを使用し、
ターミナルへ警告を表示します。

入力候補はJPEG、PNG、TIFF、BMP、GIF、WebP、HEIC、HEIF、出力は既定JPEGで、PNG・WebPも選択できます。


### 出力形式とEXIF除去の設定

ルートは `--image-format jpeg|png|webp` / `--image-strip-exif`、画像CLIのresizeは
`--format jpeg|png|webp` / `--strip-exif`。既定jpeg、除去OFF。単独画像にのみ適用する。
`ImageConfig(output_format="webp", strip_exif=True)` でも指定できる。
PNGはリサイズ後のRGB/RGBAを可逆圧縮する。WebPはquality72/60、method6の非可逆圧縮。
PNG/WebPは透過を保持し、JPEGのみ白背景合成。寸法上限・先頭フレーム規則は全形式共通。

EXIFはOrientationを画素へ適用後に除去し、保存前の暗黙のmetadata継承を切る。
完成候補を再オープンして実形式・寸法・marker・EXIF除去を検査し、検証後に原子的に公開する。
除去指定時、またはPNG/WebP出力時は原本コピー・生成済み入力コピーを使わず、削減率によらず
候補を採用する。エンコード・検証失敗はERRORとなり、既存出力を置き換えず他画像を続行する。
EXIF以外の個人情報・metadata除去は保証しない。PNG/WebPのICC・EXIFは保存可能な範囲で渡す。
PNGのXMPはiTXtへ、WebPのXMPはXMP chunkへ渡す。WebPにはDPI・元コメントを引き継がない。

入力拡張子が選択形式と一致する場合は名前を維持し、異なる場合は元名全体へ出力拡張子を追加する。
JPEGの一致対象は.jpg/.jpeg、追加拡張子は.jpg。PNGは.png、WebPは.webp。
衝突時の8桁hash規則は全形式共通。形式変更後も過去形式の出力は自動削除しない。

完成出力の再利用は3形式ともsource SHA・stat・寸法・recipe markerを照合する。
JPEGはCOM、PNGはcomment text、WebPはXMP末尾のXML commentへ内部markerを保存する。
形式と除去設定をrecipe hashへ含める。旧jpeg/除去OFFのhashは維持し、その他は旧hashに
`\nformat=<format>\nstrip_exif=<true|false>\nversion=1`を付けたASCIIのSHA-256。
manifestに `output_format` と `strip_exif`（true/false）を追加し、rootで要求と照合する。
旧列構成はjpeg/除去OFFとしてのみ解釈する。dry-runは完成画像を作成・再利用せず要求を記録する。

## 出力名と衝突

JPEG出力では、JPEG入力の `.jpg` または `.jpeg` を維持します。非JPEG入力は元のファイル名全体へ
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

以下の原本コピー・生成済み入力の短絡はJPEG出力かつEXIF保持の場合に限ります。

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

EXIF除去を指定しない場合、EXIF、GPS、DateTimeOriginal、カメラ・レンズ情報、ICC、XMP、JPEG comment、DPIは、
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
`preset,recipe_hash,output_format,strip_exif,orig_width,orig_height,new_width,new_height` です。公開直前に全入力と、通常実行で
生成・再利用した出力のpath、size、SHA-256、寸法を再検証します。全行の検証後、公開直前に
全入力・完成出力のファイル同一性、size、mtime、ctimeを一括再照合し、後続行の検証中に先行
ファイルが差し替わった場合も公開を拒否します。以前のmanifestと正常な出力は保持します。
dry-runは完成済み出力があっても通常の再利用結果を記録せず、完成出力と通常manifestを変更しません。
共有の画像エラーCSVはdry-runでも更新します。manifestを更新できない場合も
終了コードは `1` です。既存の正式出力またはレポートがread-onlyの場合、入力側のmodeを変えない
ため自動でchmodせず、以前の内容を残してfail-closedにします。

| コード | 意味 |
|---:|---|
| `0` | 画像エラーなし |
| `1` | 画像エラーあり、レポート更新失敗、または入出力検査失敗 |
| `2` | 引数不正 |

候補画像と原本コピーは、出力先と同じディレクトリの一時ファイルへ書き、要求形式として
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
