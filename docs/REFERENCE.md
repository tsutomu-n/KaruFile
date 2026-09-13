# KaruFile 技術リファレンス

この文書は、KaruFileの数値、status、保存先、再利用条件、個別CLIを検索するための
技術リファレンスです。基本操作は [KaruFile利用者マニュアル](../MANUAL.md)を参照してください。

製品動作とこの文書が矛盾する場合は、コードとテストを正とします。

## 自動スキャン画像化と単一PDF入力

root/PDF個別CLIの`--input`はPDF1ファイルも受け付ける。周辺探索・入力コピーを行わず、入力相対名は元ファイル名。
出力省略時は`<source-parent>/<source-stem>_軽量化/files/<source-name>`、report/state/previewは`files`の親に置く。
明示`--output`は従来どおり完成ファイルのディレクトリを指定する。フォルダー入力の配置は変更しない。
単一PDFでは画像・Excel・動画子CLIを起動せず、それらの空レポートも生成しない。
同一・親子出力、symlink/junction/hardlink宛先、原本変更検出、検証後の原子的公開を維持する。

standard/compactの未選択PDFについて、文書に画像があり、全ページが画像とclipのみ（空白混在可）で、
文字描画・不可視OCR・vector paintを含まない場合に`classification=raster_scan`、
`permission_basis=automatic_scan_raster`とする。写真だけのPDFも含む構造判定であり、意味分類ではない。
`profile`/`requested_policy`はstandard/compactのまま。preserveおよび明示した他のPDF処理が優先し、
個別CLIのsafeでは無効。暗号化、修復、署名、フォーム/添付、レイヤー、注釈等の既存保護は維持する。

`raster_scan`候補は各ページを300 DPI・DeviceGray・JPEG品質92にし、画素格子を一致させて配置する。
元のページbox/rotation/表示寸法、リンク、詳細しおり、名前解決、metadata/XMPを検証する。
元の文字を画像化しない。低解像度の元画像もページ描画時に300 DPIへ再標本化される。
原本由来qpdf候補と独立に生成し、厳密に小さい検証済み候補の最小を採用、同サイズならqpdf優先。
採用はADOPTED_LOSSY、kind=raster_scan、reason=adopted_raster_scan。images_changedは採用した画像化ページ数。
可逆候補はADOPTED_LOSSLESS、dry-runはDRY_RUN_LOSSY・候補/完成PDFなし。tool/I/O/構造失敗はERROR。

上限は100ページ、入力128 MiB、元画像80 MP/枚、ページ描画32 MP/枚。
画像化候補の生成＋原本/候補検証の累積600 MP、独立qpdf候補検証も別枠600 MP。
事前超過は保護、実行中超過は候補棄却。判定と全候補で300秒の協調的期限を共有する。
検証はqpdf --checkと300 DPI全ページ比較。qpdf候補はRGB完全一致、画像化候補はグレーの
平均絶対差が各ページ5/255以下、32×32画素ごと10/255以下。任意倍率や文字単位の同一性保証ではない。
画像化を拒否しても適格なqpdf候補は採用し、両候補不採用なら原本コピーでUNCHANGED。
任意lossless-jpegの要求は記録するが、この分類にはjpegtran候補を追加しない。
CSV/DB schema6の既存欄を使用し、新分類・permission basisをrootが検証する。
protection_policyと画像化recipe（v3、数値上限含む）をconfig hashに追加し、旧成功記録は再処理する。

## 統合CLI

```text
-i, --input PATH         入力フォルダーまたはPDFファイル。必須
-o, --output PATH        出力フォルダー。省略時は <input>_軽量化
--pdf-workers N          PDFの並列処理数。既定値は2
--image-workers N        画像の並列処理数。既定値は4
--excel-pattern PATTERN  対象xlsxを入力相対globで明示選択。反復可、既定は探索しない
--excel-max-side PX      Excel画像の長辺上限。100〜10000、既定800。excel-dpiと排他
--excel-jpeg-quality N   Excel JPEG品質。40〜95、既定72（DPI指定時85）
--excel-dpi DPI          配置寸法方式を選択。150〜300。Excel各設定の明示時はexcel-pattern必須
--video-workers N        動画の並列処理数。既定値は1
--video-safe             動画の厳格な入力形式判定。既定OFF、compact専用
--video-remove-audio     音声を除去して動画圧縮。既定OFF、compact専用
--preset NAME            standardまたはcompact。既定値はstandard
--pdf-preserve-pattern PATTERN 原本保護（反復可、最優先）
--pdf-text-pattern PATTERN 文章・単純罫線表を許可（反復可）
--pdf-text-scan-pattern PATTERN 文章スキャンを許可（反復可）
--pdf-text-scan-bilevel-pattern PATTERN 白黒書類スキャンに二値化候補を追加（反復可）
--pdf-font-family {yu-gothic,meiryo} 置換字体（既定meiryo、font-replace-pattern必須）
--pdf-font-replace-pattern PATTERN 日本語・英語をWindowsメイリオRegularへ統一（反復可）
--pdf-photo-pattern PATTERN  一致するPDFだけphoto profileを適用。反復可
--pdf-photo-dpi DPI       photoの目標DPI。150〜300の整数、既定200。photo-pattern必須
--pdf-preview             PDFのローカル比較HTMLを作成。既定OFF
--pdf-preview-dpi DPI     比較専用DPI候補。150〜300、反復可、最大5種類。preview必須
--pdf-lossless-jpeg       JPEG可逆候補を追加。既定OFF
--pdf-jpegtran-path PATH  jpegtran 3.2.0を明示。パスだけでは有効化しない
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
4. 明示選択したExcelがある場合、Excelを処理
5. compactの場合、対応動画を処理
6. 現在実行のPDF・画像・Excel・動画レポートを入力集合と実ファイルへ照合
7. 統合サマリーと終了コードを出力

1つのprocessorが失敗しても、可能な範囲で他を実行します。正確な集計値を取得できない
場合は、過去の出力から推測せず `unknown` と表示します。

## 統合CLIの保存先

入力が `D:\作業\資料`、出力が `D:\作業\資料_軽量化` の場合:

| 内容 | 保存先 |
|---|---|
| PDF、画像、指定Excel、compact動画 | `D:\作業\資料_軽量化\` |
| 通常実行のPDFレポート | `D:\作業\report.csv` |
| dry-runのPDFレポート | `D:\作業\report.dry-run.csv` |
| PDF状態DB | `D:\作業\.pdf-shrink\state.sqlite3` |
| PDF一時ファイル | `D:\作業\.pdf-shrink\temp\` |
| PDF比較資料（指定時のみ） | `D:\作業\pdf-preview\<runid>\index.html`および同じ実行フォルダー内のPDF・PNG |
| PDF比較manifest | `D:\作業\pdf-preview.json` |
| PDF比較dry-run manifest | `D:\作業\pdf-preview.dry-run.json` |
| 画像エラーCSV | `D:\作業\資料_軽量化.image-errors.csv` |
| 通常実行の画像manifest | `D:\作業\資料_軽量化.image-manifest.csv` |
| dry-runの画像manifest | `D:\作業\資料_軽量化.image-manifest.dry-run.csv` |
| 通常実行の動画レポート | `D:\作業\資料_軽量化.video-report.csv` |
| 通常実行のExcelレポート | `D:\作業\資料_軽量化.excel-report.csv` |
| dry-runのExcelレポート | `D:\作業\資料_軽量化.excel-report.dry-run.csv` |
| Excel一時領域 | `D:\作業\資料_軽量化.excel-work\` |
| dry-runの動画レポート | `D:\作業\資料_軽量化.video-report.dry-run.csv` |
| 動画状態DB | `D:\作業\資料_軽量化.video-state\state.sqlite3` |
| 動画一時ファイル | `D:\作業\資料_軽量化.video-state\temp\` |

PDFレポート、状態DB、一時領域はPDFがある場合、または`--pdf-preview`を指定した場合に使用します。
PDFがなく比較指定もない実行では作成・更新せず、以前のファイルも削除しません。
比較指定があれば対象0件でも空のPDFレポート・状態領域と比較manifestを用意し、通常実行では
対象なしの比較HTMLも作成します。対象0件のためだけにqpdf・jpegtranを準備することはありません。
PDFレポートと状態DBは、
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
| `0` | 対象となったPDF・画像・Excel・動画のエラーが0件 |
| `1` | 処理失敗、レポート更新失敗、結果不整合、または安全性検査失敗 |
| `2` | 引数不正 |

子処理の終了コードが `0` でも、現在入力とレポートが一致しない場合や、報告された
エラーが1件以上ある場合は、統合CLIも `1` を返します。
統合CLIはprocessor起動前に全対象のidentityとSHA-256を記録し、全processor終了後に再照合します。
入力変更または検証不能を検出した場合は集計値を `unknown` とし、終了コード `1` を返します。
各processorには24時間の固定実行期限があり、超過時は子process treeを停止して失敗とします。

## dry-run

- 完成したPDF・画像・Excel・動画を作りません。
- PDF処理用の一時PDFを作りません。
- qpdfを探索、実行、自動取得しません。
- jpegtranも探索・実行せず、要求設定を`lossless_jpeg_requested`へ記録します。
- PDF状態DBと `report.dry-run.csv`、画像エラーCSV、画像dry-run manifestは更新される場合があります。
- 明示選択したExcelは構造と処理予定を調べ、Excel dry-runレポートを更新します。縮小候補は作りません。
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

処理を順に読む場合は[PDF処理の流れと判断基準](PDF_PROCESSING.md)を参照してください。

### 必要なツール

PyMuPDF 1.28.2を使用します。PDFを含む通常実行ではqpdfも使用し、次の順で探索します。
PDF dry-runではqpdfを使用しません。

1. PDF個別CLIの `--qpdf-path` で明示したファイル
2. `PATH`
3. ローカルキャッシュ

見つからない場合は、qpdf 12.3.2のWindows向け配布ZIPをGitHub Releasesから取得します。

### 圧縮対象の判定

standard/compactとも、文字だけのPDFに加え、文字データがなく画像と切り抜き指定だけのPDFを自動対象にします。
画像だけのPDFは300 DPI・グレー・JPEG品質92のページ画像へ変換します。写真だけのPDFも含まれます。
文字（不可視OCRを含む）と画像が混在するPDFや描画線入りPDFは、従来どおり明示指定なしでは保護します。
空白ページの混在は許可します。保護時は候補を生成せず原本をコピーします。

| 指定 | 処理 |
|---|---|
| 無指定 | 文字PDFと画像だけのスキャンPDFを自動対象にし、その他は保護 |
| `--pdf-preserve-pattern` | 必ず原本保護。すべての許可に優先 |
| `--pdf-text-pattern` | 文章と水平・垂直の直線・枠線だけの罫線表を許可 |
| `--pdf-text-scan-pattern` | 明示した文章だけのスキャンを許可 |
| `--pdf-text-scan-bilevel-pattern` | 明示した白黒書類スキャンに二値化候補を追加 |
| `--pdf-font-replace-pattern` | 明示したPDFの字体をWindowsメイリオRegularへ統一する候補を許可 |
| `--pdf-photo-pattern` | 既存の写真用150〜300 DPI候補を許可 |

PDF個別CLIでは`--pdf-text-pattern`を`--text-pattern`とするように名前の`pdf-`を外します。すべて反復可能な入力相対globで、
大小文字を無視し、区切りを正規化、`*`はディレクトリ区切りにも一致します。空・絶対path・
`..`は禁止です。保護されていないPDFが複数の処理許可に一致すると処理開始前にエラーになります。
罫線表の意味や画像の内容を自動推測しません。文章・罫線表の許可では曲線、塗り、斜線、特殊な描画は保護します。
暗号化、署名、フォーム、添付、修復済みPDFなどの除外を維持し、検査失敗は`ERROR`として原本復旧します。

文章・罫線表は原本から独立に、qpdf単独、フォントサブセット化・整理圧縮＋qpdf、
グレー化＋同じ整理圧縮＋qpdfを作ります。PyMuPDF `recolor(components=1)`と
`subset_fonts(fallback=False)`を使用し、文字の画像化・再配置・代替フォント・OCR・scrubは行いません。
字体置換は後述の`font_replace`を明示したPDFだけの別処理です。
`--safe`はグレー化を無効にし、文章スキャン指定・写真指定・字体統一指定・compactとの併用は引数エラーです。

文章スキャンは単純な8-bit DeviceRGB/DeviceGray画像だけを対象に、300 DPI・グレーJPEG品質92/85/80を
独立比較し、qpdf単独候補も残します。既存OCR文字層は保持し、新しいOCRはしません。
`--pdf-text-scan-bilevel-pattern`（PDF個別CLIは`--text-scan-bilevel-pattern`）では、
同じ候補に1-bit DeviceGray・Flate候補を原本から独立に追加します。グレー画素値220未満を黒、
220以上を白にし、dither・文字認識・字形の置換は行いません。色・階調は失われ、薄い筆画の保持を
保証しません。寸法計算・構造保護・検証閾値・処理予算は通常の文章スキャンと同じです。
同サイズではqpdf、JPEG 92/85/80、二値化の順に優先します。二値化の採用は`ADOPTED_LOSSY`、
kindは`text_scan_bilevel`、理由は`adopted_text_scan_bilevel`。棄却時も他の候補を選べます。
requested_policy/profileは`text_scan_bilevel`、classificationは`text_scan`、
permission_basisは`explicit_text_scan_bilevel`。保護時のclassificationは`protected`です。
新規パターンと二値化レシピを処理hashへ含めます。現行の処理schemaは6で、DB行は削除しません。
スキャン画像の`Length`は直接整数と間接参照整数に対応し、復号前に圧縮stream上限を確認します。
配置transformから共有xrefの各軸の最小DPIを求め、300 DPI超の軸だけをceilで縮小します。
低DPI軸は拡大せず、低DPI画像もグレーJPEG候補にはできます。マスク、特殊Decode/DecodeParms、
複雑な色空間、inline画像、曖昧な画像参照・配置は文書全体を保護します。
上限は100ページ、1画像80 MP、圧縮stream64 MiB、候補検証累積600 MP（比較双方を計上）、
文書候補工程300秒の協調的予算です。事前超過は保護、実行中超過は候補棄却です。

文章向けでは256 KiB未満の除外と最小削減量・率を外し、検証済みで原本より小さい最小候補だけを
採用します。同サイズならqpdf、色を維持したsubset、グレーの順。scan JPEG同士は92、85、80の順です。
グレー候補は`ADOPTED_LOSSY`であり可逆とは表示しません。増大・不合格の場合は原本を残します。
qpdf検査、ページ形状・抽出文字・文字位置・罫線と画像の配置・リンク・しおり・metadataを照合します。
文字候補は全ページ72/300 DPIでRGB完全一致、グレー文字候補は原本のグレー描画と完全一致が必要です。
スキャンは原本のグレー描画に対し72 DPI全ページと300 DPI画像配置を比較し、全体差5%・
最大32×32 pixel局所差20%を超える候補を棄却します。可読性やOCR精度の保証ではありません。

### Windowsフォントへの明示置換

**フォント置換の実行には対象の明示指定が必要です。置換先の字体はメイリオが既定なので、字体名の指定は不要です。通常のPDF圧縮ではフォントを変更しません。**


統合CLIの`--pdf-font-replace-pattern PATTERN`、PDF個別CLIの`--font-replace-pattern PATTERN`は、
日本語・英語の横書きPDFに`font_replace` profileを適用します。入力相対glob、反復指定、保護優先、
他許可との重複拒否は他のPDFパターンと共通です。`--safe`とは併用できません。
`requested_policy`は`font_replace`、処理可能時の`classification`は`font_replace`、
`permission_basis`は`explicit_font_replace`です。保護時は`classification=protected`です。

Windowsにインストールされた`meiryo.ttc`のface 0（`Meiryo Regular`）を既定とし、
root `--pdf-font-family yu-gothic` / PDF `--font-family yu-gothic`で`YuGothR.ttc` face 0（`Yu Gothic Regular`）を選べます。
選択肢は`yu-gothic`/`meiryo`。明示したfamilyにはfont-replace-patternが必須です。
実ファイルのfamily/Regular/face0/埋め込み権限を確認し、選択を処理hash・状態・CSV・preview・root照合へ伝えます。
同じPDFでも字体を切り替えると再処理します。字体の自動fallbackやダウンロードはしません。
元の字体の太さを選び分けないため、元の太字による強調は弱まる場合があります。
字体名・style・埋め込み権限・SHA-256を確認し、対応する文字だけをサブセット埋め込みします。
Windowsフォントの同梱・取得・字形や文字幅の改変は行いません。字体ファイルの準備に失敗すると
PDF処理の開始前エラーです。保護指定を適用した後にfont_replace対象が0件なら、このフォントを要求しません。

元の文字表示命令をPDF側の幅と字間調整へ変換して位置を保ち、文字を画像化したり、`ActualText`で
本文を書き直したりしません。画像として焼き込まれた文字は置換しません。
画像・描画パスを含むPDFも、このprofileで検証できる構造に限って保持したまま字体を置換します。
通常の文章・罫線表profileでは代替フォントを使わず、自動スキャン条件に該当しない未指定の図・画像PDFは原本保護します。

原本からqpdf単独と字体置換＋qpdfの2候補を独立に作り、検証済みで原本より厳密に小さい候補を採用します。
同サイズならqpdf単独を優先します。字体置換候補の採用は`ADOPTED_LOSSY`、qpdf単独は`ADOPTED_LOSSLESS`です。
`--lossless-jpeg`を併用してもこのprofileにJPEG可逆候補は追加しませんが、要求フラグは記録します。
欠字・未対応の字体符号化やPDF構造は一冊まるごと保護し、構造検査・ツール・I/Oの失敗は復旧コピーに
成功しても`ERROR`です。dry-runはフォントと構造の読取りだけで、subsetや候補・完成PDFを作らず、
外部ツールも実行しません。

字形・字幅の見え方は変わるため、字体置換は表示画素の完全一致を要求する可逆処理ではありません。
コピー・検索で推定される空白や改行にも差が生じ得ます。`text_extraction_changed`は、実際に採用した
字体置換候補のMuPDF抽出差を示し、全閲覧ソフトでの抽出一致や検索成功を保証しません。
空白以外の文字変更、表示順序や配置の不整合は許可しません。

変換対象の字体は、埋め込みTrueTypeのType0／Identity-H／CIDFontType2（IdentityのCIDToGIDMapと
1文字ずつのBMP ToUnicode）またはASCII範囲の単純TrueType／WinAnsiです。
空白だけに使う非埋め込みの単純フォントは保持します。横書きを直交する軸のまま回転した文字行列は
許可し、非直交・反転・退化した行列は保護します。Identity-V等の縦書き、文字クリッピング、
Form XObject、inline画像、注釈、フォーム、レイヤー、添付などは対応外です。
例外として空のAcroForm辞書（Fieldsなし/空配列、キーはFields/DR/DA/NeedAppearancesのみ）は
保持して処理します。Widget・XFA・SigFlags・Permsや実フィールドはこの例外に含めません。
StructTreeRoot・ParentTree・ページ参照・MarkInfo等のタグ構造は削除せず、有界なグラフ比較
（深さ64、間接オブジェクト100000）で保持を検証します。構造要素や親子対応の変更は候補不採用です。
画像と同寸法の8bit DeviceGray単層SMaskも保持します。ネストしたSMask・Mask・Decodeは対象外。
画像/マスク辞書とストリームを独立比較し、既存の画像・復号量制限をマスクにも適用します。
字体レシピversionは6。生成時にXMPのPDFVersionを自動修正せず、元のmetadataを保持します。
意味を変更しないBMC／BDC／EMCは深さ64まで保持し、inline辞書のMCID・Lang・Type・Subtype・
Attached・BBoxを型検査します。ActualText・OC・resource property参照は許可しません。
埋め込む文字は元のToUnicode対応表と正の幅を持つASCII対応表を基準とし、表示命令で未使用の対応文字も含みます。
文字対応表の項目数は全字体の累計でも制限し、ExtGStateは未使用の定義も事前検査します。
対応可能な画像は保持し、復号画素・画像辞書・配置を検証します。

独立検証では、文字コードと表示命令の順序・文字送り、Unicodeと実際のglyph、文字の方向・大きさ・
描画モード・色・不透明度・線幅・描画順を照合します。表示原点の許容差は各座標0.02 ptです。
埋め込んだ字体の輪郭・hmtx・埋め込み権限等をWindowsフォントと照合し、ページ形状・非文字の
演算子／resource・図形・画像・しおり・メタデータ等も検証します。両PDFを全ページ144 DPI RGBで描画し、
qpdf単独候補では画素の完全一致も要求します。字体置換候補では画素一致を要求しません。

字体統一profileの上限（MiBは1,048,576 byte、MPは1,000,000 pixel）:

| 対象 | 上限 |
|---|---:|
| 文書 | 200ページ、原本・候補は各128 MiB |
| 字体resource・表示文字・文字対応表 | 256字体、表示1,000,000文字、全字体の文字対応表は累計1,000,000項目 |
| 元の字体stream | 圧縮32 MiB／展開64 MiB、各stream |
| 元の本文stream | 圧縮32 MiB／展開32 MiB、展開本文は文書合計32 MiB |
| 元の画像stream | 圧縮32 MiB／展開64 MiB、1画像32 MP |
| 事前検査の展開stream累積 | 文書256 MiB |
| 候補検証のstream | 圧縮32 MiB／展開64 MiB、原本と候補の展開累積256 MiB。展開本文は各文書合計32 MiB |
| 描画 | 144 DPI、1ページ32 MP、原本と候補の合計600 MP／候補 |
| 検証する候補 | 最大2候補。描画の最大合計1,200 MP |
| 時間 | 事前検査・生成・両候補の検証で文書300秒を共有 |

時間は呼出し間で確認する協調的な予算で、個々の外部ツール・ライブラリ呼出しを正確に300秒で
強制停止するものではありません。事前の上限超過は原本保護、実行中の上限超過は候補棄却です。

通常の比較HTMLは別の100ページ上限を維持します。字体統一が完了しても、`--pdf-preview`の上限超過は
比較側`ERROR`となり、完成PDFを維持したまま終了コード1へ反映されます。

### 写真用profileの明示選択

統合CLIの`--pdf-photo-pattern PATTERN`、PDF個別CLIの`--photo-pattern PATTERN`は反復指定でき、
1つ以上のパターンに一致するPDFにだけ`photo`を適用します。`preset`は`standard`または`compact`
のままです。一致しないPDF、単独画像・動画のpresetは変わりません。

統合CLIの`--pdf-photo-dpi DPI`、PDF個別CLIの`--photo-dpi DPI`は150〜300の整数で、既定200です。
明示指定には写真パターンが必要です。写真用DPIを変えても文章スキャンの300 DPI目標は変わりません。

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
- 目標DPIを超える軸の寸法は`ceil(元pixel寸法 × 目標DPI / 最小実効DPI)`へ縮小します。
  ceilで丸めるため、実効DPIは目標を少し上回る場合があります。元から目標DPI以下の軸は寸法を維持し、
  拡大しません。どちらの寸法も縮まないJPEGは同寸法再圧縮をしません。
- 候補JPEG qualityは80です。片軸だけを縮小する場合もJPEG全体を再エンコードします。
- 元PDF内の対象画像を置換し、ベクター文字・線を維持します。PDF→HTML→PDFは使いません。

明示選択したPDFでも、その中のJPEGが写真であるとは判定しません。図面や黒板文字などの細部を
含む場合は、利用者が出力を原本と比較する必要があります。
photoで配置の検査処理に失敗した場合は`ERROR`にします。共通保護判定の
`PRESERVED_ORIGINAL`とは区別し、原本復旧できても成功扱いにはしません。

### 候補の検証

文章・罫線表・文章スキャンには、前述の文章向け検証を使います。qpdf単独を含む色を維持する候補は
全ページ72／300 DPI RGB完全一致、グレー文字候補は同DPIの原本グレー描画との完全一致が必要です。
スキャンJPEGは72 DPI全ページ・300 DPI画像配置領域のグレー差分を検査します。
standard/compactの選択によって文章向けの検査を緩めることはありません。

写真向けの通常候補では次を検査します。任意のJPEG可逆候補は次節の完全一致検査を使います。

- qpdfの構造検査、ページ数、NFC正規化後の抽出テキスト、ページgeometryの一致
- 72 DPI RGB表示のチャンネル平均絶対差が5%以下、かつ最大32×32 pixelの局所平均差が20%以下
- 非可逆候補では72 DPI RGB比較に加え、変更画像の各配置領域を
  300 DPI RGBで比較します。256×256 pixel単位で描画し、その中の最大32×32 pixelの局所平均差は
  20%以下、変更領域全体の平均差は5%以下です。
- photoの細部検査は変更配置10,000箇所、累計80,000,000 pixel、120秒を上限とします。
  上限超過の候補は採用しません。OCR精度や人間の可読性を保証する検査ではありません。

### 任意のJPEG可逆候補

統合CLIの`--pdf-lossless-jpeg`、PDF個別CLIの`--lossless-jpeg`は既定OFFです。
有効時は明示`--pdf-jpegtran-path` / `--jpegtran-path`、次にPATHでjpegtranを解決し、
libjpeg-turbo 3.2.0以外・未検出はPDF処理開始前にエラーにします。自動取得・インストールはしません。
パス指定だけでは有効化せず、dry-runでは探索・実行せず要求設定だけを記録します。
PDF個別CLIの`--safe`と引数上は併用できます。既存の非可逆候補は無効化しません。
ただし`--safe`は写真指定と併用できず、現行の保護方針ではsafe時にJPEG可逆候補を生成する対象はありません。

保護判定を通ったphoto PDFへ追加します。保護対象や文章向け候補を迂回しません。
初版の対象は単一DCTDecode・8-bit・直接指定のDeviceRGB/DeviceGray画像です。
Mask/SMask、Decode/DecodeParms、ImageMask、複雑/間接ColorSpace、inline画像は変更しません。
xrefごとに一度だけ処理し、画像辞書・配置を保持して圧縮streamだけを更新します。

- 原本からbaseline/progressiveを独立生成。`-copy all -optimize -maxmemory 128M -maxscans 100 -strict`を使い、progressiveだけ`-progressive`を追加。
- 画像20,000,000 pixels、圧縮stream32 MiBが事前上限。超過画像は対象外。
- 呼出し30秒、追加JPEG工程全体に文書単位300秒の協調的予算。baseline/progressiveで共用し、候補保存・qpdf・検証も含む。
- 個々のMuPDF/qpdf呼出しを文書予算で強制停止するものではありません。qpdf自体の既存timeoutは300秒です。
- 寸法・成分・量子化表・同一MuPDF decoderによる原寸画素が一致し、JPEG streamが縮小した場合だけ置換。
- 完成PDFはqpdf検査、ページ数・形状、抽出文字、描画パスが一致し、全ページを72/300 DPI RGBで完全比較（512 pixel単位のタイル描画）。
- JPEG画素/描画差、候補stream上限超過、文書予算超過は当該候補を棄却。ツール失敗・警告・timeout、破損、構造/I/OエラーはPDFを`ERROR`として原本復旧を試み、他PDFは続行。
- 同一decoderの一致は、全ビューアーの互換性・文字可読性・OCR精度の保証ではありません。

### 採用条件

| 候補 | 最小削減量 | 最小削減率 |
|---|---:|---:|
| 文章・罫線表・文章スキャン・字体統一 | 原本より小さい | 下限なし |
| 可逆（photo） | 16 KiB | 2% |
| 非可逆（photo） | 64 KiB | 5% |

最小削減量と最小削減率の両方を満たす必要があります。非可逆候補を作る場合は、元PDFから
可逆候補も作ります。各候補を独立に検証し、採用条件を満たす最小サイズを選び、同サイズなら
可逆候補を優先します。条件を満たす候補がなければ原本を出力へコピーします。
ツール実行、構造検査、I/Oの失敗は`ERROR`であり、回復コピー成功でも成功へ変えません。
出力は同じディレクトリの一時ファイルへ
書いて検証してから `os.replace()` で公開します。

JPEG可逆指定時も最小の合格候補を採用します。同サイズならqpdf単独、JPEG baseline、
JPEG progressive、非可逆の順です。候補の画質検査や非可逆の採用閾値は緩めません。

### 状態DBと再処理

状態DBには入力と完成出力のSHA-256を保存します。処理中に入力または出力が変わった場合は、
新しい内容を誤って処理済みと記録せず、次回に再処理します。ただし、処理中の入力自体は
ロックしません。出力SHA-256を持たない旧recordは一度再処理します。

出力先、presetで選ばれた画像処理値、保護・文章・文章スキャン・写真・字体統一の指定パターン、保護規則、
文章recipe、`photo_dpi`とphoto recipe、tool versionは設定hashに含みます。
standard/compact、各指定パターン、写真用DPIを切り替えると再評価します。
現行版は`processing_schema=6`をhashに含み、以前のstateを一度再処理します。
字体統一ではWindowsフォントファイル全体のSHA-256、固定レシピ、fontTools・pikepdfの版もhashに含みます。
採用下限、JPEG有効状態、固定レシピ・検証規則、jpegtranのversion・SHA-256もhashへ含めます。
SQLiteは列の追加移行で旧行を保持します。無効時のjpegtranパスは処理結果へ影響しません。
SQLiteは診断列を追加して移行し、既存行は削除しません。旧行の未記録候補サイズは`NULL`、
profileと理由は空文字、候補履歴は空配列として扱います。追加列`photo_dpi`は旧行で`NULL`です。
追加列`font_replacement_requested`と`text_extraction_changed`は旧行で0、`replacement_font`と
`replacement_font_sha256`は空文字です。古い成功行はschemaとhashの不一致により再利用しません。
`preview`と`preview_dpis`は通常処理のhashに含めません。比較資料だけの設定変更は正常PDFの
再処理を要求せず、現在の原本と実際の完成出力から比較資料を改めて作ります。

### PDFレポートのstatus

| status | 意味 |
|---|---|
| `PRESERVED_ORIGINAL` | 保護方針により候補を生成せず原本コピー、SHA-256一致必須 |
| `DRY_RUN_PRESERVED` | dry-runの保護判定、完成出力なし |
| `ADOPTED_LOSSLESS` | 可逆圧縮候補を採用 |
| `ADOPTED_LOSSY` | 非可逆圧縮候補を採用 |
| `UNCHANGED` | 候補の画質・削減条件により原本を採用。理由は`decision_reason` |
| `SKIPPED_SMALL` | photoが256 KiB未満のため原本を採用 |
| `SKIPPED_ENCRYPTED` | 暗号化PDFのため原本を採用 |
| `SKIPPED_SIGNED` | 電子署名を含むため原本を採用 |
| `SKIPPED_COMPLEX` | フォーム、添付ファイル、修復済みなどのため原本を採用 |
| `DRY_RUN_LOSSLESS` | dry-runで可逆処理を選択予定 |
| `DRY_RUN_LOSSY` | dry-runで非可逆処理を選択予定 |
| `ERROR` | 処理に失敗。可能な場合は原本を復旧コピー |

PDFレポートの列:

```text
source_path,source_size,source_sha256,output_path,output_size,output_sha256,saved_bytes,saved_percent,preset,mode,status,page_count,scan_page_ratio,error_message,profile,decision_reason,candidate_size,candidate_saved_bytes,candidate_saved_percent,images_changed,candidate_details,lossless_jpeg_requested,photo_dpi,requested_policy,classification,permission_basis,preservation_reason,processing_schema,font_replacement_requested,replacement_font,replacement_font_sha256,text_extraction_changed
```

`SKIPPED_ENCRYPTED`・`SKIPPED_SIGNED`・`SKIPPED_COMPLEX`は旧記録との互換値です。共通保護判定は`PRESERVED_ORIGINAL`と理由を記録します。

### PDFレポートの診断列

JPEG可逆の採用statusは`ADOPTED_LOSSLESS`、採用理由は`adopted_jpeg_lossless_baseline`または
`adopted_jpeg_lossless_progressive`です。一次候補の`candidate_*`は採用候補で上書きしません。
完成出力は`output_*`、採用候補は履歴の`selected`で確認します。

| 列 | 意味 |
|---|---|
| `preset` | 起動時に指定した`standard`または`compact` |
| `profile` | ファイルに適用した`standard`・`compact`・`photo`・`text`・`text_scan`・`text_scan_bilevel`・`font_replace`・`preserve`。統合CLIは相対パスと指定パターンから検証 |
| `photo_dpi` | photo行の要求目標DPI（150〜300の整数）。原本・可逆採用でも要求値を記録。他profileは空欄。統合CLIは列の欠落・指定不一致を拒否 |
| `decision_reason` | 最終的な採否理由 |
| `candidate_size` | 一次候補のbyte数。生成していない場合は空欄 |
| `candidate_saved_bytes` | 入力byte数−一次候補byte数。増大した候補では負数 |
| `candidate_saved_percent` | 一次候補の削減割合。0.05が5%。未生成の場合は空欄 |
| `images_changed` | 一次候補で書き換えた画像xref数。配置箇所数ではない |
| `candidate_details` | 試した候補の順序付きJSON配列。一次候補が先頭 |
| `lossless_jpeg_requested` | 全行で`true`または`false`。統合CLIが実行指定と照合し、旧CSVの欠落・不一致を拒否 |
| `font_replacement_requested` | font_replace行だけ`true`、他は`false`。要求の記録であり、置換候補の採用を意味しない |
| `replacement_font` | font_replace行は選択した`Yu Gothic Regular`または`Meiryo Regular`、他は空欄。可逆候補採用・保護・dry-runでも要求字体を記録 |
| `replacement_font_sha256` | font_replace行はWindowsのフォントファイル全体の64桁小文字SHA-256、他は空欄。同じ実行のfont_replace行間で一致が必要 |
| `text_extraction_changed` | 採用したfont_replaceの非可逆候補についてMuPDFの抽出に空白・改行差があれば`true`。それ以外は`false`。全閲覧ソフトの検索・コピー動作の保証ではない |

photoでは非可逆候補を試した場合はそれが一次候補です。後から可逆候補を採用しても、`candidate_*`は
非可逆候補の記録のままです。完成出力の`output_size`・`saved_bytes`・`saved_percent`と混同しないで
ください。`saved_percent`も0.05が5%です。dry-runでは候補サイズを計算しません。

文章向けの一次候補はqpdf（`lossless`）です。追加kindは`text_subset`、`text_gray`、`text_scan_jpeg_92/85/80`、`text_scan_bilevel`。
字体統一の一次候補もqpdf（`lossless`）で、追加kindは`font_replace`です。
`requested_policy`は要求profile、`classification`はtext/text_table/text_scan/photo/font_replace/protected/unclassified、
`permission_basis`は自動文字判定または明示指定、`preservation_reason`は保護理由、`processing_schema`は6です。
これらの列をDBへ追加移行し、保護規則・全指定パターン・文章レシピ・採用条件をhashへ含めます。
統合CLIは列欠落・schema不一致・要求不一致・分類不整合を拒否し、保護出力SHA一致を必須にします。

`candidate_details`の各要素は`kind`（非可逆は`standard`・`compact`・`photo`、可逆は`lossless`・`jpeg_lossless_baseline`・`jpeg_lossless_progressive`）、
`size`（byte数または`null`）、
`images_changed`、`reason`、`validation_reason`、`selected`、`text_extraction_changed`を持ちます。
候補内の抽出差はその候補の診断で、CSV行の抽出差は実際に採用した字体置換候補についてだけ記録します。採用した候補だけ
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

### 任意のPDF比較HTML

統合CLIの`--pdf-preview`、PDF個別CLIの`--preview`は既定OFFです。
全PDFの原本・実際出力を比較し、保護理由も表示します。追加DPI候補は保護されていないphotoだけに生成します。
PDF処理と状態・CSV保存の後に、今回処理対象として選択した全PDF行について独立に比較資料を生成します。
PDFの`ERROR`・`SKIPPED_*`は描画せず、比較側の`SKIPPED`と理由を記録します。
対象なしも有効な結果です。

- 比較の基準は原本と**実際の完成出力**です。指定DPIの一次候補が採用されたとは仮定しません。
- `--pdf-preview-dpi DPI` / `--preview-dpi DPI`は150〜300の整数を反復指定でき、重複を除いて
  降順へ正規化します。上限は5種類で、preview指定が必要です。追加候補の既定は空です。
- 各追加DPI候補を原本から独立に生成し、photoの画像条件と既存の構造・画質検証を使います。
  通常の採用結果・DB・CSVの`candidate_details`へは追加しません。
- 画質検証を通った比較候補は、容量が増大した場合や削減量が採用条件未満の場合も表示できます。
  画質棄却は比較候補の`REJECTED`で、比較PDF・描画は公開しません。
  縮小対象がない候補は`no_image_savings`として原本を表示します。
  ツール・構造・I/O等の実処理失敗は比較側`ERROR`です。
- PyMuPDFで全ページを144 DPI RGB、画像の配置領域を300 DPI RGBでPNGへ描画します。
  各版の同じ領域を同じ寸法で表示し、倍率・スクロール位置を同期します。OCRは行いません。
- 1冊の上限は100ページ、画像配置領域500件、1描画32,000,000 pixel、全版の累積600,000,000 pixel、
  300秒です。ページ・領域数を先に確認します。時間上限は呼出し間で確認する協調的な予算であり、
  実行中の個々の変換・検証・描画を即時停止する保証はありません。上限超過は比較側`ERROR`です。
- 原本と完成出力のsize・SHA-256・安全な保存先を検査し、比較処理後にも変化がないことを確認します。
  比較資料は入力・完成出力ツリーと分け、link・junction・hardlinkによる危険な保存先を拒否します。
- 新しい`<output-parent>/pdf-preview/<runid>/`へJavaScriptを内包する`index.html`、PNGと比較用PDFを格納します。
  原本・実際の完成出力もこの実行フォルダーへコピーし、外部サーバー・CDNは使用しません。
  持ち運びには実行フォルダー全体が必要です。HTML・manifestは検査した一時ファイルから原子的に公開します。
- 比較資料の失敗は完成PDFのstatusや成功stateを変更せず、終了コード1へ反映します。他PDFは続行します。
  再実行では前の比較フォルダーを上書きせず、最新manifestだけを更新します。
- dry-runは要求設定を`pdf-preview.dry-run.json`へ記録し、HTML・PNG・比較PDFを作りません。
  比較用の外部ツールは実行しません。通常実行の`pdf-preview.json`とは別です。

比較manifestの`schema`は1です。主要フィールド:

| フィールド | 契約 |
|---|---|
| `requested` / `dry_run` | `true` / 現在実行のdry-run指定 |
| `photo_dpi` / `preview_dpis` | 通常写真処理の要求DPI / 降順・重複なしの追加比較DPI配列 |
| `input_root` / `output_root` | 現在実行の絶対パス |
| `status` / `errors` | 通常`COMPLETE`、dry-run`DRY_RUN`、失敗`ERROR` / エラー文字列配列 |
| `run_dir` / `index_path` / `index_sha256` | 比較実行ディレクトリ、HTML、SHA-256。dry-runは全て`null` |
| `items` | 今回処理対象として選択した全PDF行と1対1に対応する配列。保護・失敗・skip行も含み、対象なしは空 |

各itemは入力相対パス、source/outputのパスとSHA-256、`pdf_status`、比較側`status`、`reason`を持ちます。
`classification`、`permission_basis`、`preservation_reason`で判定・許可根拠・保護理由も記録します。
比較側のstatusは`READY`・`SKIPPED`・`ERROR`です。`variants`は原本・完成出力・追加DPIごとの
サイズ、リンク、`READY`・`REJECTED`・`ERROR`と理由、`views`はページ・領域と各PNGへの相対参照を持ちます。
統合CLIはmanifestが現在実行で更新されたこと、要求設定・PDF入力集合・検証済みPDFレポートとの
整合、HTMLの保存先とSHA-256を照合します。欠落・古いmanifest・不一致・危険なパスは終了コード1です。
各itemの`font_replacement_requested`、`replacement_font`、`text_extraction_changed`もPDFレポートと
照合し、列欠落・型不正・値の不一致を拒否します。HTMLには字体統一の要求と、採用出力で検出した抽出差を表示します。
字体統一の比較は処理記録と現在の原本・完成出力のSHAを再確認して描画し、通常文章の分類をかけ直しません。

### PDF個別CLI

```text
--input PATH          入力フォルダーまたはPDFファイル。必須
--output PATH         フォルダー入力の省略時は <input>_軽量化。PDF1冊は <stem>_軽量化/files
--workers N           既定値2、最小値1
--dry-run             出力PDFを作らず判定結果を記録
--safe                非可逆処理を無効化し、可逆候補だけを選択
--lossless-jpeg       JPEG可逆候補を追加。既定OFF、safeと併用可能
--jpegtran-path PATH  jpegtran 3.2.0を明示。パスだけでは有効化しない
--limit N             サイズ上位floor(N/2)件と、残りから固定seedでN-floor(N/2)件を選択
--retry-errors        前回ERRORを再処理
--qpdf-path PATH      qpdf.exeを明示
--preset NAME         standardまたはcompact。既定値standard
--preserve-pattern PATTERN  一致するPDFを必ず原本保護。反復可
--text-pattern PATTERN      文章と単純な罫線表を許可。反復可
--text-scan-pattern PATTERN  文章だけのスキャンを許可。反復可
--text-scan-bilevel-pattern PATTERN 白黒書類スキャンに二値化候補を追加。反復可
--font-family {yu-gothic,meiryo} 置換字体（既定meiryo、font-replace-pattern必須）
--font-replace-pattern PATTERN 日本語・英語をWindowsメイリオRegularへ統一。反復可
--photo-pattern PATTERN  一致するPDFをphoto profileにする入力相対パターン。反復可
--photo-dpi DPI        photoの目標DPI。150〜300の整数、既定200。photo-pattern必須
--preview              PDFのローカル比較HTMLを作成。既定OFF
--preview-dpi DPI      比較専用DPI候補。150〜300、反復可、最大5種類。preview必須
-v, --verbose         詳細ログ
```

Nが奇数の場合、`--limit` は固定seedのランダム側を1件多く選びます。
`--safe`は`--preset compact`、`--photo-pattern`、`--text-scan-pattern`、`--text-scan-bilevel-pattern`、`--font-replace-pattern`と併用できません。

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

## Excel処理

### 選択・処理範囲

統合CLIでは`--excel-pattern`を指定した`.xlsx`だけを探索します。無指定では探索・コピーしません。
`~$`で始まるExcel一時ファイルは除外します。パターンはPDF photoと同じ入力相対globで、
大文字小文字を区別せず、区切りを`/`へ正規化し、`*`はディレクトリー区切りにも一致します。
空、絶対パス、`..`は拒否します。既定は長辺800px、JPEG品質72です。
`--excel-max-side`は100〜10000、`--excel-jpeg-quality`は40〜95の整数です。
`--excel-dpi`（150〜300）を明示すると従来の配置寸法方式になり、品質未指定時は85です。
DPIと長辺上限は排他です。Excel設定の明示時にはパターンが必要です。
両presetで同じ処理を行い、Excel用の並列数指定はなく、1冊ずつ処理します。

Excelをブック編集ライブラリで読み書きし直さず、OOXMLの参照と表示寸法を解析し、JPEG/PNGの
画像パートだけを置き換えます。PNGは透過を維持し、JPEGは指定品質、subsampling 0（4:4:4）です。
固定上限方式は長辺が上限を超えた画像を縦横比維持で縮小し、短辺は最も近い整数（半端は上）に丸め、最小1pxです。
上限以下のJPEGも再圧縮しますが、PNGは縮小不要なら変更しません。拡大せず表示寸法も変更しません。
DPI方式では単純な内側cropを考慮し、共有画像の全参照で必要な画素数の最大値を確保します。
DPI方式は縮小不要なら再圧縮しません。どちらもcrop外の画像領域は削除しません。
固定上限でも下記の配置・形式保護を維持し、保護/棄却画像は上限を超えて残る場合があります。
XML、数式、書式、関係ファイルなど、対象画像以外は展開後のバイト一致を検証します。
`autoCompressPictures`などExcelの再保存時設定も書き換えません。

初版の対象は`oneCellAnchor`、`absoluteAnchor`、および表示寸法を確定できる`twoCellAnchor`の
浮動JPEG/PNGです。同一セル内の`twoCellAnchor`はoffset差で計算します。複数セルにまたがる場合は、
次の条件を満たすものだけを`grid.py`で解決します。

- 描画の所有worksheetは1つ。標準スタイル（builtinId 0）から参照する字体はCalibri/游ゴシック/Yu Gothicの
  標準11pt。Windows GDIの96DPI相当DCで実字体・標準書体・15pxの字体高・charset・数字0〜9の最大幅を確認。
  MDWはCalibri 7、游ゴシック8。代替字体や未確認metricsは保護。字体データSHA-256を診断へ記録し、字体は同梱しない。
  font scheme使用時はCalibriのLatin、游ゴシックのEAまたはJpanを照合。非Windowsでは従来のCalibri計算だけを使用する。
- 列幅は0より大きく255以下。明示width、明示defaultColWidth、baseColWidth=8（省略時も8）の既定幅に対応。
  範囲定義の重複、hidden・collapsedは不可。bestFitは保存widthとcustomWidth=trueがある場合だけ使い、内容から再計算しない。
- 両端セルを含む全行のhtが明示され、0より大きく409pt以下、96 DPIで整数pixelになること。
  customHeight=true、またはセル・個別ht・非標準行/列スタイルのない空行でdefaultRowHeightが確定していること。
  hidden・collapsed・thickTop・thickBotは不可。内容依存の自動高さは保護する。
  x14ac:dyDescentは0以上かつ行のpixel高さ以下なら許可する。
- 通過する列・行はそれぞれ両端込み最大1,024個。数式表示、右から左のシート、customSheetViews、
  未対応拡張などは不可。両端offsetはそれぞれのセル寸法以内であること。

明示列幅は`floor(((256 × width + floor(128 / MDW)) × MDW) / 256)`でpixelへ変換します。
baseColWidth=8の既定列幅は`ceil((8 × MDW + 5) / 8) × 8`pxで、Calibri 64px、游ゴシック72px。
このExcelの既定幅丸めは独立したExcel16実測で確認した限定recipeで、任意字体・base値への一般化はしません。
1pxは9,525 EMU、1ptは12,700 EMUとして列・行とoffsetから寸法を計算します。
保存された`xfrm/ext`があれば、求めた寸法との完全一致が必要です。`xfrm/ext`だけを現在の表示寸法と
推定しません。自動行高さや未対応の標準字体など、条件を満たさない画像パートは保護します。
通常のExcel保存でもこの制限に当たる場合があります。
同じパートを未対応の描画・変換・未知の参照でも使っていれば、そのパート全体を保護し、
他の独立した対応画像は処理します。回転、外向きcrop、複雑な効果、未使用の画像参照も保護対象です。
`cNvPr/extLst/ext/a16:creationId`は既知URI・namespace・位置・GUID（id省略可）を限定検査して保持します。
`useLocalDpi`はBoolean（省略時true）を検査して保持し、配置DPIには使いません。
未知属性/子/text・重複拡張・未知拡張との混在は保護。省略されたfillRectも未対応として画像単位で保護します。
JPEGは8bitのL/RGB、PNGは8bitのL/LA/RGB/RGBAに限定し、パレット・16bit・アニメーション、
EXIF Orientationが1以外の画像、未対応の追加メタデータはその画像を変更しません。
JPEGは走査データの後もmarkerを調べ、未知APP、重複メタデータ（分割ICCを除く）、
走査後のAPP/COM、末尾の追加データを持つ画像を保護します。対応するICC・EXIF・コメントは
保持を検証します。PNGは対応するmetadata chunkのpayloadを元のバイトで保持し、
色キー透過は縮小前にalphaへ展開します。位置情報やコメントを消す機能ではありません。
セル内画像（IMAGE/DISPIMGを含む）、richdata、埋め込みオブジェクト、署名・暗号化・マクロ等がある
ブックは全体を保護します。`.xls/.xlsb/.xlsm`は探索対象外です。
破損構造、I/O、候補処理失敗は`ERROR`とし、回復コピーを作らず既存出力を維持します。

### 採用と上限

候補を再開封し、画像の形式・寸法・ICCとパッケージ内容を検証します。PNGは縮小後画素とalphaが一致すること、
JPEGは縮小後RGBとのchannel別平均絶対差が全体8以下、128×128pxの各領域16以下であることを要求します。
これらはExcelでの表示や、画像内の文字の可読性を保証しません。画像を変更し、ブック全体が
原本より厳密に小さくなった場合だけ`ADOPTED_LOSSY`を採用します。それ以外は
`PRESERVED_ORIGINAL`として原本とSHA-256が一致するコピーを公開します。
一時出力とレポートは保存先の安全性を検証して`os.replace()`で公開します。

| 対象 | 上限 |
|---|---:|
| 元ZIP | 128 MiB |
| ZIP entry数 | 4,096 |
| ZIP中央directory | 4 MiB（ZipFileがentry情報を展開する前に検査） |
| 1パートの展開サイズ | 64 MiB |
| 全パートの展開サイズ | 256 MiB |
| XML 1パート | 8 MiB |
| XML累計 | 32 MiB、1,000,000ノード（構築中に検査） |
| XML構造 | 1パート250,000ノード、深さ64 |
| 画像パート数 | 1000（Content Typesのimage/*で分類、一般shapeや参照回数は含めない） |
| 画像1枚 | 32 MP |
| 原本・候補の画像デコード合計 | 200 MP |
| ブック処理時間 | 300秒の協調的期限 |

ZIP/XML・総数・累積予算の事前上限超過はブック保護です。画像1枚の32 MP上限はその画像を保護します。
ZIP64・複数disk・非標準の中央directory配置もブックを保護します。
実行中の予算・期限超過は`ERROR`です。
協調的期限は各検査地点で確認し、1回の外部ライブラリ呼出しを途中で強制停止する保証ではありません。
通常の処理パイプラインはExcelを起動せず、開封・表示・印刷・再保存を自動検証しません。

### レポート・dry-run・個別CLI

レポートは`<output>.excel-report.csv`または`<output>.excel-report.dry-run.csv`、一時領域は
`<output>.excel-work/`です。状態DB・成功キャッシュは持たず、再実行でも原本から判定します。
通常statusは`ADOPTED_LOSSY`、`PRESERVED_ORIGINAL`、`ERROR`、dry-runは`DRY_RUN`、
`DRY_RUN_PRESERVED`、`ERROR`です。dry-runは構造と処理予定を調べてレポートを更新するだけで、
完成xlsx・縮小候補は作らず、変更画像数は0です。

```powershell
uv run --project excel-shrink excel-shrink run --input "D:\資料" --output "D:\資料_軽量化" --pattern "写真台帳/*.xlsx" --dpi 220 --dry-run
```

個別CLIの`--input`、`--output`、1個以上の`--pattern`は必須です。
詳しい構成とreport列は[ExcelコンポーネントREADME](../excel-shrink/README.md)を参照してください。

CSV schema 3の必須列:

```text
schema_version,source_path,relative_path,output_path,source_size,output_size,
source_sha256,output_sha256,status,dpi,images_total,images_changed,changed_parts,reason,max_side,jpeg_quality,
recipe_version,analysis_complete,diagnostics_complete,image_diagnostics
```

`changed_parts`は変更した画像パート名のJSON配列です。保護・ERROR・dry-runは`[]`で、
`images_changed`は0です。ERROR・dry-runの`output_size`と`output_sha256`は空欄です。
`reason`は全体の結果に加え、保護や候補棄却の画像別理由を件数で併記します。
`images_total`は確定画像数で未取得は空欄、0は画像なしです。上限保護でも既知の画像数を保持します。
処理版は`grid2-pixel-jpeg-v2`。固定上限時はmax_sideに指定値、dpiは空欄。DPI時はその逆です。
jpeg_qualityは両方式とも実指定値を記録します。Booleanは小文字true/false。
`analysis_complete`は全画像の判定完了、`diagnostics_complete`は全件の詳細収録完了で、許可の意味ではありません。
`image_diagnostics`はpart/format/size/placements/required_pixels/geometry_basis/reasons/outcomeの配列。
size/required_pixelsの未取得はnull。geometry_basisはvalidated_anchor、grid_iso_calibri11、
grid_gdi96_regular11:字体データSHA（共有配置は重複なしのカンマ結合）、pixel_cap、またはunresolvedです。
pixel_cap時のrequired_pixelsは長辺上限による目標寸法であり、配置DPI由来ではありません。
outcomeはplanned/preserved/adopted/rejected。dry-runのplannedは変換予定で、完成出力ではありません。
最大1000件、JSON深さ8、UTF-8で2MiB/field、CSV全体32MiB。詳細省略時はdiagnostics_complete=false。
セルや画像内容は診断へ複製しません。ERRORにも取得済みの診断を残します。
統合側は現在選択との1:1対応、要求DPI/長辺上限/JPEG品質、status、変更数、予定出力、実ファイルのsize/SHA-256を
照合し、既知の画像数と診断partを元ZIPのContent Typesで独立確認します。schema1/2・未知recipe・不正型・重複JSONキーを拒否します。
固定上限時は変更画像の寸法が原寸から計算した目標と一致することを要求し、同寸法の変更はJPEG再圧縮だけに限定します。
CSV欠落、古いreport、矛盾は集計`unknown`・終了1にします。

## 動画処理

統合CLIではcompactのときだけ `.mp4`、`.m4v`、`.mkv`、`.webm` を探索します。
入力拡張子とcontainer familyを維持し、対応可能な構成だけを変換します。

### 対応する変換条件

- attached pictureではない映像1本
- 8-bit SDR。通常はfield_order/SAR情報の欠落とVFRを許容（欠落SARは1:1扱い）
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

音声除去なしの場合、HDR、既知interlace、非正方SAR、複数stream等は `SKIPPED_COMPLEX` または
`SKIPPED_UNSUPPORTED` として原本を同じ相対pathへコピーします。音声除去指定時の扱いは下記のとおりです。
寸法上限は表示方向の幅1280px・高さ720pxであり、長辺1280pxではありません。
縦1080×1920の入力は、縦横比を保って偶数へ切り下げた404×720になります。

root `--video-safe` / 単体 `--safe` はprogressiveとSAR 1:1の明示、および
`r_frame_rate == avg_frame_rate` を要求する従来の入力判定です。既定OFF。
通常は公称fpsと平均fpsの大きい方を上限30fpsでCFR化します。フレーム複製・間引きがあります。
root `--video-remove-audio` / 単体 `--remove-audio` は全音声を除去して圧縮します。
音声除去時は複数音声・多channel音声も受け付けます。両オプションは併用でき、compact専用で
standardでは処理開始前に引数エラーです。原本・パス保護と候補検証は両モードで共通です。

### 動画候補の検証と採用

候補はffprobe構造検査、全stream decode、duration・stream・寸法・fps、rotation 0、
AV1（field_order欠落/unknownは許容、既知interlaceは拒否）/SAR 1:1、予定した音声sample rate、VMAF mean/p5、削減量をすべて満たした
場合だけ `os.replace()` で公開します。品質不合格または削減不足は `UNCHANGED` として原本を
コピーします。処理中に入力snapshotが変わった候補は公開しません。

音声除去時は候補の音声stream数0を必須とし、未対応・品質不合格・削減不足を含め
無音圧縮が成立しなければ`ERROR`（終了1）です。有音原本のfallback/回復コピーを作らず、
既存出力は維持します。container durationは取得できる元映像stream durationを基準とし、
取得できない場合は元container durationを使います。音声付き既存出力が残っていても成功ではありません。
CSV全行に`safe`、`remove_audio`をtrue/falseで記録し、統合CLIは指定値との一致を要求します。
両設定は`video-shrink-v2`のprocessing hashに含め、旧DB行を削除せず旧設定の再利用を防ぎます。

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
--safe                厳格な入力形式判定。既定OFF、compact専用
--remove-audio        全音声を除去して圧縮。既定OFF、compact専用
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
   - 文章向けは72／300 DPIの完全一致、スキャンJPEGはグレーの全体・局所差を検査します。
     photoは72 DPI RGBと変更配置の300 DPI RGBを比較します。いずれも細部の可読性やOCR精度は
     保証しません。検査量上限を超えた候補は採用しません。
3. 入力ファイルの同時更新
   - 起動前と終了時に全対象のidentity・SHA-256を照合して変更を失敗として検出しますが、
     処理中の入力をロックせず、別プロセスによる変更そのものは防止しません。
4. 実データでの判定閾値
   - テストは合成データが中心です。写真DPI・比較HTMLは実資料5冊で限定検証しています。
     [検証記録](validation/2026-09-09-photo-preview.md)の結果を別資料の画質・削減率保証へ拡張しません。
5. 動画の自動判定と知覚品質
   - safe時のCFRはffprobeの `r_frame_rate == avg_frame_rate` を使う入口判定で、全timestampの均一性を
     証明しません。既知のHDR/Dolby Vision metadataは拒否しますが、metadata欠落時のSDR性までは
     証明しません。VMAFは映像だけを評価し、30fps化の滑らかさと音声品質は測定しません。
6. 動画VMAFの一時ファイル上限
   - VMAF JSONは生成完了後に64 MiB上限を検査するため、異常なlibvmaf実行中はvalidation timeoutまで
     一時領域を消費する余地があります。
7. 完了済み動画の再検証
   - state再利用時は出力hashを照合しますが、full decodeとVMAFを再実行しません。ローカルstateを
     信頼境界に含めることで、再実行を高速化しています。
