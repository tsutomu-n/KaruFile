# KaruFile 技術リファレンス

この文書は、KaruFileの数値、status、保存先、再利用条件、個別CLIを検索するための
技術リファレンスです。基本操作は [KaruFile利用者マニュアル](../MANUAL.md)を参照してください。

製品動作とこの文書が矛盾する場合は、コードとテストを正とします。

## 統合CLI

```text
-i, --input PATH         入力フォルダー。必須
-o, --output PATH        出力フォルダー。省略時は <input>_軽量化
--pdf-workers N          PDFの並列処理数。既定値は2
--image-workers N        画像の並列処理数。既定値は4
--video-workers N        動画の並列処理数。既定値は1
--preset NAME            standardまたはcompact。既定値はstandard
--pdf-photo-pattern PATTERN  一致するPDFだけphoto profileを適用。反復可
--ffmpeg-path PATH       compact動画用ffmpeg。省略時はPATH
--ffprobe-path PATH      compact動画用ffprobe。省略時はPATH
-n, --dry-run            完成出力を作らず判定を確認
-v, --verbose            詳細ログを表示
```

並列処理数には1以上の整数を指定します。入力と出力が同一、または互いに親子となる指定は
処理前に拒否します。

処理順序:

1. 入出力、予定出力、状態DB、レポートの保存先を検査
2. PDFを処理
3. 画像を処理
4. compactの場合、対応動画を処理
5. 現在実行のPDF・画像・動画レポートを入力集合と実ファイルへ照合
6. 統合サマリーと終了コードを出力

1つのprocessorが失敗しても、可能な範囲で他を実行します。正確な集計値を取得できない
場合は、過去の出力から推測せず `unknown` と表示します。

## 統合CLIの保存先

入力が `D:\作業\資料`、出力が `D:\作業\資料_軽量化` の場合:

| 内容 | 保存先 |
|---|---|
| PDF、画像、compact動画 | `D:\作業\資料_軽量化\` |
| 通常実行のPDFレポート | `D:\作業\report.csv` |
| dry-runのPDFレポート | `D:\作業\report.dry-run.csv` |
| PDF状態DB | `D:\作業\.pdf-shrink\state.sqlite3` |
| PDF一時ファイル | `D:\作業\.pdf-shrink\temp\` |
| 画像エラーCSV | `D:\作業\資料_軽量化.image-errors.csv` |
| 通常実行の画像manifest | `D:\作業\資料_軽量化.image-manifest.csv` |
| dry-runの画像manifest | `D:\作業\資料_軽量化.image-manifest.dry-run.csv` |
| 通常実行の動画レポート | `D:\作業\資料_軽量化.video-report.csv` |
| dry-runの動画レポート | `D:\作業\資料_軽量化.video-report.dry-run.csv` |
| 動画状態DB | `D:\作業\資料_軽量化.video-state\state.sqlite3` |
| 動画一時ファイル | `D:\作業\資料_軽量化.video-state\temp\` |

PDFレポート、状態DB、一時ファイルはPDFがある場合だけ使用します。PDFがない実行では
作成・更新せず、以前の実行で同じ場所にあるファイルも削除しません。PDFレポートと状態DBは、
複数の出力フォルダーが同じ親フォルダーにある場合、同じ保存先を使います。レポートは状態DB
全体ではなく、現在選択した入力だけを対象に更新します。

画像エラーCSVの一般形は `<output>.image-errors.csv` です。列:

```text
source,planned_output,error
```

画像処理が起動し、レポート公開に成功した場合は、現在実行の結果で置き換え、エラー0件でも
ヘッダーだけへ更新します。安全性検査、画像処理の起動、またはレポート公開に失敗した場合は
終了コード `1` となり、以前のCSVが残ることがあります。画像warningはターミナルへ表示し、
画像エラーCSVには保存しません。

画像manifestは現在入力を重複なく1行ずつ記録します。列:

```text
source_path,source_size,source_sha256,output_path,output_size,output_sha256,
action,error,preset,recipe_hash,orig_width,orig_height,new_width,new_height
```

通常実行とdry-runは別ファイルです。統合CLIは更新の有無、入力との1:1対応、予定出力、presetと
recipe hash、source/outputの安定したsize・SHA-256、action別の空欄、処理後寸法上限、エラーCSV
との対応を検査し、manifestの整数値から集計します。子CLIの丸め済みstdoutサマリーは集計に
使用しません。既存の正式出力または画像レポートがread-onlyならchmodせず終了コード `1` で
fail-closedにします。

動画レポートとstateはcompactで動画がある場合だけ使います。reportは現在入力を重複なく1行ずつ
記録し、orchestratorは更新、入力・予定出力path、preset、実ファイルのsize/SHA-256、削減値の
整合を照合します。

## 終了コード

| コード | 意味 |
|---:|---|
| `0` | 対象となったPDF・画像・動画のエラーが0件 |
| `1` | 処理失敗、レポート更新失敗、結果不整合、または安全性検査失敗 |
| `2` | 引数不正 |

子処理の終了コードが `0` でも、現在入力とレポートが一致しない場合や、報告された
エラーが1件以上ある場合は、統合CLIも `1` を返します。
統合CLIはprocessor起動前に全対象のidentityとSHA-256を記録し、全processor終了後に再照合します。
入力変更または検証不能を検出した場合は集計値を `unknown` とし、終了コード `1` を返します。
各processorには24時間の固定実行期限があり、超過時は子process treeを停止して失敗とします。

## dry-run

- 完成したPDF・画像・動画を作りません。
- PDF処理用の一時PDFを作りません。
- qpdfを探索、実行、自動取得しません。
- PDF状態DBと `report.dry-run.csv`、画像エラーCSV、画像dry-run manifestは更新される場合があります。
- compact動画ではffprobeで構成を確認し、dry-run reportを更新します。空の動画state領域を
  初期作成する場合がありますが、通常実行の成功recordは読み書きしません。
- 統合サマリーの出力サイズ、削減量、削減率は計算しません。
- 圧縮対象PDFの処理方法は `DRY_RUN_LOSSLESS` または `DRY_RUN_LOSSY` として記録します。

## 画像処理

### 対応形式と出力名

入力候補はJPEG、PNG、TIFF、BMP、GIF、WebP、HEIC、HEIFです。出力はJPEGです。

- JPEG入力は `.jpg` または `.jpeg` を維持します。
- 非JPEG入力は元のファイル名全体へ `.jpg` を追加します。

```text
photo.jpg  -> photo.jpg
photo.jpeg -> photo.jpeg
photo.png  -> photo.png.jpg
```

Windowsで大文字小文字を無視すると出力名が衝突する場合、処理開始前に相対入力パスの
SHA-256先頭8文字を付けます。ファイルとディレクトリのprefixが衝突する場合も、ファイル側の
出力名へハッシュを付けて解消します。

### 変換プリセット

| 項目 | `standard` | `compact` |
|---|---:|---:|
| 最大寸法 | 長辺1280px・短辺960px | 長辺1024px・短辺768px |
| JPEG quality | 72 | 60 |

両presetで共通:

| 項目 | 値 |
|---|---|
| リサイズ | 縦横比維持、拡大・切り抜きなし |
| JPEG | 4:2:0、optimize、progressive |
| Orientation | EXIF Orientationを画素へ適用 |
| 透過 | 白背景へ合成 |
| animation・複数ページ | 先頭フレームだけを使用し、ターミナルへ警告を表示 |

### JPEG候補の採用と再利用

上限内で、Orientationの画素適用が不要なJPEGは、再エンコード候補が32 KiB以上かつ
10%以上小さくなる場合だけ候補を採用します。それ以外は入力JPEGを出力へコピーします。

非JPEG、上限を超えるJPEG、Orientationの画素適用が必要なJPEGは変換対象です。非JPEGでは
出力が入力より大きい場合があり、`OUTPUT_LARGER_THAN_SOURCE` を表示します。

KaruFileが生成したJPEGには、小文字の識別情報 `karufile:image-v2` と入力スナップショットを
保存します。

- SHA-256を含む完全な現行markerかつ既知recipeで、Orientation適用が不要、現在presetの
  寸法上限内にある生成物だけを短絡できます。同じpresetの生成物と、compact生成物を
  standardで処理する場合が該当します。
- standard生成物をcompactで処理する場合と、未知・破損・旧v1 markerは通常のJPEG候補
  判定へ戻し、markerだけを理由に圧縮を省略しません。
- 同じ入力SHA-256・ファイルサイズ・更新時刻と現在の変換条件に一致し、寸法が現在の上限内に
  ある完成済み出力は再利用します。SHA-256を持たない旧v1 markerは一度再生成します。
- standardでコピー済みJPEGを再利用する場合は、ファイルサイズ・更新時刻に加えてbyte列の
  一致も確認します。compactではpreset不明のコピーを再評価します。

### メタデータ

EXIF、GPS、DateTimeOriginal、カメラ・レンズ情報、ICC、XMP、JPEG comment、DPIは、
PillowでJPEGへ保存できる範囲で可能な限り保持します。完全保持は保証しません。

Orientation適用後は古いOrientation値を残しません。CMYKなどからRGBへ単純変換した場合は、
意味の異なるICCを付けず警告を表示します。

代表的なwarning:

- `ANIMATION_DROPPED`
- `MULTIPAGE_DROPPED`
- `ALPHA_FLATTENED`
- `ICC_DROPPED`
- `OUTPUT_LARGER_THAN_SOURCE`
- `ENCODE_FAILED_ORIGINAL_COPIED`

warningだけなら終了コードは `0` です。

### 画像出力の公開と失敗

候補JPEGと原本コピーは、出力先と同じディレクトリの一時ファイルへ書き、JPEGとして
再オープンしてから `os.replace()` で公開します。

JPEG候補生成に失敗した場合は、可能なら入力JPEGを出力へコピーします。必須のリサイズまたは
Orientation適用を完了できなかった場合は、原本をコピーしてもエラーとして記録します。

1件の失敗で残りの画像を停止しません。シンボリックリンク、junction、危険なhardlinkは、
処理前または公開境界で拒否します。

## PDF処理

### 必要なツール

PyMuPDF 1.28.2を使用します。PDFを含む通常実行ではqpdfも使用し、次の順で探索します。
PDF dry-runではqpdfを使用しません。

1. PDF個別CLIの `--qpdf-path` で明示したファイル
2. `PATH`
3. ローカルキャッシュ

見つからない場合は、qpdf 12.3.2のWindows向け配布ZIPをGitHub Releasesから取得します。

### 圧縮対象の判定

次の300 DPIの処理値は、写真用パターンで選択していないstandard/compactの契約です。
256 KiB未満と安全性による除外はphotoを含む全profileで共通です。

- 256 KiB未満のPDFは圧縮せず、通常実行では原本をコピーします。
- 暗号化、電子署名、フォーム、添付ファイル、修復済みPDFなどは圧縮しません。
  添付ファイルまたは電子署名の有無を検査できない場合も、安全側で
  `SKIPPED_COMPLEX` として原本を採用します。
- ページ内で最大の画像配置がページ面積の80%以上、実効解像度が450 DPI超、
  可視テキストが20文字以下のページをスキャンページと判定し、`scan_page_ratio` に記録します。
  非可逆候補にするかの判定には使いません。
- 実効解像度は、画像のpixel寸法と配置transformのX/Y基底長から軸別に求めます。
  回転・skew・非等方配置と、同じ画像の複数配置を考慮します。
- 可視文字数はtexttraceを優先し、非表示または透明なspanだけを除外します。
  白色だけでは不可視扱いしません。
- 配置サイズから見た画像実効DPIが300を超える画像がある場合、standardではその画像を
  300 DPI・JPEG quality 92、compactでは300 DPI・quality 80へ縮小した候補を作ります。
- compactは300DPI以下の既存JPEGも、pixel寸法を変えずquality 80で再圧縮候補にします。
- compactの個別JPEG streamは、再圧縮後に5%以上小さくならなければ書き換えません。
- 実効DPIはpixel寸法と配置transformから軸別に求めます。JPEGのxres/yresメタデータは
  使いません。300 DPI未満の軸は拡大しません。
- 拡大しません。1bit画像とsoft mask付き画像は縮小しません。ベクター文字は残します。
- xrefを持たないinline画像がいずれかの軸で300 DPIを超える場合、非safe実行では
  `SKIPPED_COMPLEX` として原本を採用します。safe実行のqpdf可逆候補は阻害しません。
- 可視テキストが多くても、standardでは300DPI超、compactでは再圧縮可能な既存JPEGが
  あれば非可逆候補を作ります。
- standardで超過画像が無い場合はqpdfの可逆候補を作ります。

各軸300 DPIはstandard/compactで非可逆候補を作るときの固定目標です。非可逆候補を作る場合は、
元PDFからqpdf可逆候補も作って比較します。最終的に可逆候補または原本を採用すると、
入力由来の300 DPI超画像が残ることがあります。

### 写真用profileの明示選択

統合CLIの`--pdf-photo-pattern PATTERN`、PDF個別CLIの`--photo-pattern PATTERN`は反復指定でき、
1つ以上のパターンに一致するPDFにだけ`photo`を適用します。`preset`は`standard`または`compact`
のままです。一致しないPDF、単独画像・動画のpresetは変わりません。

- 入力フォルダーからの相対パスを対象とし、大文字小文字を区別しません。
- `\`は`/`へ正規化し、重複する区切りと`.`を除きます。`*`は区切り`/`にも一致します。
  例: `*.pdf`はサブフォルダーを含む全PDF、`写真/*.pdf`は写真フォルダー以下に一致します。
- 空、絶対パス、drive付きパス、`..`要素を含むパターンは拒否します。
- PDF個別CLIの`--safe`とは併用できません。
- 画像内容の自動分類、OCR実行、DPIからのOCR要否判定は行いません。

photoの画像候補条件:

- 8bit、`/Filter /DCTDecode`、`/ColorSpace /DeviceRGB`または`/DeviceGray`のJPEGのみです。
- 非JPEG、1bit、`Mask`・`SMask`・`Decode`・`DecodeParms`を持つ画像、`ImageMask true`、
  複雑な色空間、xrefのないinline画像は書き換えません。
- 同じ画素内容が複数xrefに対応し、画像参照の同定が曖昧な群も保持します。
- 同じxrefの全配置で、画像のX/Y軸ごとに最小の実効DPIを使います。JPEGのxres/yresは使いません。
- 200 DPIを超える軸の寸法は`ceil(元pixel寸法 × 200 / 最小実効DPI)`へ縮小します。
  丸めで200 DPI未満にしないため、目標は約200 DPIです。元から200 DPI以下の軸は寸法を維持し、
  拡大しません。どちらの寸法も縮まないJPEGは同寸法再圧縮をしません。
- 候補JPEG qualityは80です。片軸だけを縮小する場合もJPEG全体を再エンコードします。
- 元PDF内の対象画像を置換し、ベクター文字・線を維持します。PDF→HTML→PDFは使いません。

明示選択したPDFでも、その中のJPEGが写真であるとは判定しません。図面や黒板文字などの細部を
含む場合は、利用者が出力を原本と比較する必要があります。
photoで配置の検査処理に失敗した場合は`ERROR`にします。通常presetの既存の保守的な
`SKIPPED_COMPLEX`判定とは区別します。

### 候補の検証

- qpdfの構造検査
- ページ数の一致
- NFC正規化後の抽出テキストの一致
- standardは72 DPIグレースケール表示の平均絶対差が5%以下
- compactは72 DPI RGB表示のチャンネル平均絶対差が5%以下、かつ最大32×32 pixelの
  局所タイルごとのチャンネル平均絶対差が20%以下
- photoはページgeometryも照合し、compactと同じ72 DPI RGB比較に加え、変更画像の各配置領域を
  300 DPI RGBで比較します。256×256 pixel単位で描画し、その中の最大32×32 pixelの局所平均差は
  20%以下、変更領域全体の平均差は5%以下です。
- photoの細部検査は変更配置10,000箇所、累計80,000,000 pixel、120秒を上限とします。
  上限超過の候補は採用しません。OCR精度や人間の可読性を保証する検査ではありません。

### 採用条件

| 候補 | 最小削減量 | 最小削減率 |
|---|---:|---:|
| 可逆 | 64 KiB | 2% |
| 非可逆（standard/compact） | 256 KiB | 5% |
| 非可逆（photo） | 64 KiB | 5% |

最小削減量と最小削減率の両方を満たす必要があります。非可逆候補を作る場合は、元PDFから
可逆候補も作ります。各候補を独立に検証し、採用条件を満たす最小サイズを選び、同サイズなら
可逆候補を優先します。条件を満たす候補がなければ原本を出力へコピーします。
ツール実行、構造検査、I/Oの失敗は`ERROR`であり、回復コピー成功でも成功へ変えません。
出力は同じディレクトリの一時ファイルへ
書いて検証してから `os.replace()` で公開します。

### 状態DBと再処理

状態DBには入力と完成出力のSHA-256を保存します。処理中に入力または出力が変わった場合は、
新しい内容を誤って処理済みと記録せず、次回に再処理します。ただし、処理中の入力自体は
ロックしません。出力SHA-256を持たない旧recordは一度再処理します。

出力先、presetで選ばれた画像処理値、写真選択パターンとphoto recipe、tool versionは設定hashに
含みます。standard/compactまたは写真選択を切り替えると再処理します。候補診断と可逆候補への
切り替えを導入した版は`processing_schema=2`をhashに含むため、以前のstateも一度再処理します。
SQLiteは診断列を追加して移行し、既存行は削除しません。旧行の未記録候補サイズは`NULL`、
profileと理由は空文字、候補履歴は空配列として扱います。

### PDFレポートのstatus

| status | 意味 |
|---|---|
| `ADOPTED_LOSSLESS` | 可逆圧縮候補を採用 |
| `ADOPTED_LOSSY` | 非可逆圧縮候補を採用 |
| `UNCHANGED` | 候補の画質・削減条件により原本を採用。理由は`decision_reason` |
| `SKIPPED_SMALL` | 256 KiB未満のため原本を採用 |
| `SKIPPED_ENCRYPTED` | 暗号化PDFのため原本を採用 |
| `SKIPPED_SIGNED` | 電子署名を含むため原本を採用 |
| `SKIPPED_COMPLEX` | フォーム、添付ファイル、修復済みなどのため原本を採用 |
| `DRY_RUN_LOSSLESS` | dry-runで可逆処理を選択予定 |
| `DRY_RUN_LOSSY` | dry-runで非可逆処理を選択予定 |
| `ERROR` | 処理に失敗。可能な場合は原本を復旧コピー |

PDFレポートの列:

```text
source_path,source_size,source_sha256,output_path,output_size,output_sha256,saved_bytes,saved_percent,preset,mode,status,page_count,scan_page_ratio,error_message,profile,decision_reason,candidate_size,candidate_saved_bytes,candidate_saved_percent,images_changed,candidate_details
```

### PDFレポートの診断列

| 列 | 意味 |
|---|---|
| `preset` | 起動時に指定した`standard`または`compact` |
| `profile` | ファイルに適用した`standard`・`compact`・`photo`。統合CLIは相対パスと指定パターンから検証 |
| `decision_reason` | 最終的な採否理由 |
| `candidate_size` | 一次候補のbyte数。生成していない場合は空欄 |
| `candidate_saved_bytes` | 入力byte数−一次候補byte数。増大した候補では負数 |
| `candidate_saved_percent` | 一次候補の削減割合。0.05が5%。未生成の場合は空欄 |
| `images_changed` | 一次候補で書き換えた画像xref数。配置箇所数ではない |
| `candidate_details` | 試した候補の順序付きJSON配列。一次候補が先頭 |

非可逆候補を試した場合はそれが一次候補です。後から可逆候補を採用しても、`candidate_*`は
非可逆候補の記録のままです。完成出力の`output_size`・`saved_bytes`・`saved_percent`と混同しないで
ください。`saved_percent`も0.05が5%です。dry-runでは候補サイズを計算しません。

`candidate_details`の各要素は`kind`（非可逆は`standard`・`compact`・`photo`、可逆は`lossless`）、
`size`（byte数または`null`）、
`images_changed`、`reason`、`validation_reason`、`selected`を持ちます。採用した候補だけ
`selected=true`で、原本採用時は全て`false`です。検証の具体的な棄却理由は`validation_reason`へ
保存します。未試行の場合は`[]`です。

主な`decision_reason`:

| 値 | 意味 |
|---|---|
| `adopted_lossless` / `adopted_lossy` | 一次候補を採用 |
| `fallback_lossless` | 非可逆候補を採用せず、後続の可逆候補を採用 |
| `no_image_savings` | 生成した画像候補が採用されず、画像の書き換えなし |
| `candidate_not_smaller` | 候補が原本より小さくならなかった |
| `reduction_below_threshold` | 候補の削減量が採用基準未満 |
| `quality_rejected` | 候補を画質検証等で棄却 |
| `source_too_small` | 入力が256 KiB未満 |
| `dry_run_lossless` / `dry_run_lossy` | dry-runの処理予定 |
| `processing_error` | ツール・検証処理・I/O等の失敗 |

各候補の`reason=eligible`は検証と削減条件を満たしたことを表し、実際に選ばれたかは
`selected`で判別します。`fallback_lossless`は非可逆候補が不合格のときだけでなく、
両方が合格して可逆候補がサイズ比較で選ばれた場合も使います。

安全上の除外では`encrypted`、`signed`などの検査理由を記録します。最終理由だけで複数候補の
棄却経緯を説明しきれない場合は`candidate_details`を確認してください。

### PDF個別CLI

```text
--input PATH          入力フォルダー。必須
--output PATH         省略時は <input>_軽量化
--workers N           既定値2、最小値1
--dry-run             出力PDFを作らず判定結果を記録
--safe                非可逆画像縮小を無効化し、qpdfの可逆処理だけを選択
--limit N             サイズ上位floor(N/2)件と、残りから固定seedでN-floor(N/2)件を選択
--retry-errors        前回ERRORを再処理
--qpdf-path PATH      qpdf.exeを明示
--preset NAME         standardまたはcompact。既定値standard
--photo-pattern PATTERN  一致するPDFをphoto profileにする入力相対パターン。反復可
-v, --verbose         詳細ログ
```

Nが奇数の場合、`--limit` は固定seedのランダム側を1件多く選びます。
`--safe`は`--preset compact`および`--photo-pattern`と併用できません。

## 画像個別CLI

個別画像CLIの出力省略時の既定値は `<input>_resized` です。統合CLIとPDF個別CLIの
`<input>_軽量化` とは異なります。

```text
-i, --input PATH      入力フォルダー。必須
-o, --output PATH     省略時は <input>_resized
-n, --dry-run         画像出力を作らず、画像エラーCSVとdry-run manifestを更新
-j, --workers N       既定値4、最小値1
--preset NAME         standardまたはcompact。既定値standard
-v, --verbose         詳細ログ
```

## 動画処理

統合CLIではcompactのときだけ `.mp4`、`.m4v`、`.mkv`、`.webm` を探索します。
入力拡張子とcontainer familyを維持し、対応可能な構成だけを変換します。

### 対応する変換条件

- attached pictureではない映像1本
- 8-bit SDR、progressive、固定frame rate、sample aspect ratio 1:1
- 音声なし、またはmono/stereo 1本
- 字幕、data、attachment、chapterなし
- 1280×720以内、30fps以内、拡大なし
- 映像は `libsvtav1`
- MP4/M4VはAAC、MKV/WebMはOpus

初期recipeの固定値:

- CRFは38、35、32の順で候補化し、SVT-AV1 `preset=8`、`tune=0`
- 音声bitrateはmono 64 kbps、stereo 96 kbps。AACは入力以下かつ最大48 kHz、
  Opusは48 kHzへする
- VMAF `vmaf_v0.6.1`を5 frameごとに評価し、mean 85以上かつ5 percentile 70以上
- 入力より1 MiB以上かつ10%以上小さい候補だけを採用
- container durationと、両方で取得できた映像・音声stream durationの許容差は0.25秒

HDR、VFR、interlace、複数stream等は `SKIPPED_COMPLEX` または
`SKIPPED_UNSUPPORTED` として原本を同じ相対pathへコピーします。

### 動画候補の検証と採用

候補はffprobe構造検査、全stream decode、duration・stream・寸法・fps、rotation 0、
明示progressive/SAR 1:1、予定した音声sample rate、VMAF mean/p5、削減量をすべて満たした
場合だけ `os.replace()` で公開します。品質不合格または削減不足は `UNCHANGED` として原本を
コピーします。処理中に入力snapshotが変わった候補は公開しません。

動画reportの主なstatus:

| status | 意味 |
|---|---|
| `ADOPTED` | 検証済みAV1候補を採用 |
| `UNCHANGED` | 品質または削減条件により原本を採用 |
| `SKIPPED_STANDARD` | 動画個別CLIのstandardで原本を採用 |
| `SKIPPED_COMPLEX` | 複雑なstream構成のため原本を採用 |
| `SKIPPED_UNSUPPORTED` | 未対応container/codec条件のため原本を採用 |
| `SKIPPED_COMPLETE` | source/config/output検証済みの既存結果を再利用 |
| `DRY_RUN` | dry-runで予定だけを記録 |
| `ERROR` | tool、probe、encode、validation、公開に失敗 |

保存先は `<output>.video-state/` と `<output>.video-report.csv`、dry-runは
`<output>.video-report.dry-run.csv` です。FFmpeg/ffprobeは自動取得せず、PATHまたはCLIで
指定します。
`SKIPPED_COMPLETE` の再利用時はstateに保存したsource/config/tool versionと出力hashを照合し、
full decodeとVMAFは再実行しません。state/reportは利用者のローカル管理下にある信頼済みcacheと
みなします。手動編集が疑われる場合は `<output>.video-state` を別名へ退避して再実行してください。

動画個別CLI:

```text
--input PATH          入力フォルダー。必須
--output PATH         出力フォルダー。必須
--workers N           既定値1、最小値1
--preset NAME         standardまたはcompact。既定値standard
--dry-run             動画出力を作らず予定を記録
--ffmpeg-path PATH    ffmpegを明示
--ffprobe-path PATH   ffprobeを明示
-v, --verbose         詳細ログ
```

個別CLIの実行例と開発者向け情報:

- [pdf-shrink](../pdf-shrink/README.md)
- [media-shrink-tool](../media-shrink-tool/README.md)
- [video-shrink](../video-shrink/README.md)
- [orchestrator](../orchestrator/README.md)

## 対象外と確認済みの制約

KaruFileの対象外:

- HDR、VFR、interlace、字幕、複数映像・音声等を保持した動画変換
- 重複削除
- 知覚ハッシュ
- 元ファイル削除
- GUI

確認済みの未解決事項:

1. qpdf配布ZIPの真正性
   - バージョンと展開先は固定・検査しますが、SHA-256または署名は検証しません。
2. PDF表示検証の局所差分
   - standardは72 DPIグレースケールのページ全体平均差を使います。compactは72 DPI RGBの
     全体差と最大32×32 pixelの局所差を検査します。photoでは変更配置を300 DPIでも比較しますが、
     細部の可読性やOCR精度を保証しません。検査量上限を超えた非可逆候補は採用しません。
3. 入力ファイルの同時更新
   - 起動前と終了時に全対象のidentity・SHA-256を照合して変更を失敗として検出しますが、
     処理中の入力をロックせず、別プロセスによる変更そのものは防止しません。
4. 実データでの判定閾値
   - テストは合成データが中心です。今回の実装では実データPilotを実施していません。
5. 動画の自動判定と知覚品質
   - CFRはffprobeの `r_frame_rate == avg_frame_rate` を使う入口判定で、全timestampの均一性を
     証明しません。既知のHDR/Dolby Vision metadataは拒否しますが、metadata欠落時のSDR性までは
     証明しません。VMAFは映像だけを評価し、30fps化の滑らかさと音声品質は測定しません。
6. 動画VMAFの一時ファイル上限
   - VMAF JSONは生成完了後に64 MiB上限を検査するため、異常なlibvmaf実行中はvalidation timeoutまで
     一時領域を消費する余地があります。
7. 完了済み動画の再検証
   - state再利用時は出力hashを照合しますが、full decodeとVMAFを再実行しません。ローカルstateを
     信頼境界に含めることで、再実行を高速化しています。
