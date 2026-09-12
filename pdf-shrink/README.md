# pdf-shrink

**フォント置換の実行には対象の明示指定が必要です。置換先の字体はメイリオが既定なので、字体名の指定は不要です。通常のPDF圧縮ではフォントを変更しません。**

KaruFileのPDF専用処理コンポーネントです。入力フォルダーを再帰的に調べ、PyMuPDF・qpdf等で
圧縮候補を作ります。候補を検証し、既定の削減条件を満たす場合だけ採用します。
採用しない場合や安全上圧縮しない場合は、原本を出力へコピーします。

通常の利用手順は [KaruFile 利用者マニュアル](../MANUAL.md)を参照し、リポジトリ直下の
`karufile.py` を使ってください。この文書はPDF処理コンポーネントの個別CLIと内部契約を扱います。
判断の順序は[PDF処理の流れと判断基準](../docs/PDF_PROCESSING.md)にまとめています。

## 必要環境とセットアップ

- Windows
- Python 3.13以上
- [uv](https://docs.astral.sh/uv/)

リポジトリ直下で依存関係を準備します。

```powershell
uv sync --project pdf-shrink --dev
```

通常実行ではqpdfを、明示したパス、`PATH`、ローカルキャッシュの順で探索します。
見つからない場合は、qpdf 12.3.2のWindows向け配布ZIPをGitHub Releasesから取得します。
dry-runではqpdfを探索、実行、自動取得しません。
字体統一を明示する場合はWindowsにインストール済みの選択字体（既定はメイリオRegular）も必要です。
フォントを同梱・取得する機能はありません。fontTools・pikepdfはこのコンポーネントのPython依存です。

## 個別CLI

```powershell
uv run --project pdf-shrink pdf-shrink run `
  --input "C:\作業\PDF" `
  --output "C:\作業\PDF_軽量化"
```

| オプション | 意味 |
|---|---|
| `--input PATH` | 入力フォルダー。必須 |
| `--output PATH` | 出力フォルダー。省略時は `<input>_軽量化` |
| `--workers N` | 並列プロセス数。既定値は2、最小値は1 |
| `--preset standard|compact` | 圧縮プリセット。既定値は `standard` |
| `--preserve-pattern PATTERN` | 最優先の原本保護。反復可 |
| `--text-pattern PATTERN` | 文章と単純罫線表を許可。反復可 |
| `--text-scan-pattern PATTERN` | 文章スキャンを許可。反復可 |
| `--text-scan-bilevel-pattern PATTERN` | 白黒書類スキャンに二値化候補を追加。反復可、色・階調を失う |
| `--font-replace-pattern PATTERN` | 日本語・英語をWindowsメイリオRegularへ統一。反復可、字形・検索/コピーの推定空白が変わる場合あり |
| `--font-family {yu-gothic,meiryo}` | 置換字体を選択。既定meiryo、明示指定にはfont-replace-patternが必須 |
| `--photo-pattern PATTERN` | 一致するPDFだけphoto profileにする入力相対パターン。反復可 |
| `--photo-dpi DPI` | photoの目標DPI。150〜300の整数、既定200。photo-pattern必須 |
| `--preview` | 原本と実際の完成出力を比べるローカルHTMLを作成。既定OFF |
| `--preview-dpi DPI` | 比較専用DPI候補。150〜300、反復可、最大5種類。preview必須 |
| `--dry-run` | 出力PDFを作らず、判定結果を記録 |
| `--safe` | 非可逆処理を無効化し、可逆候補だけを作成 |
| `--lossless-jpeg` | JPEG可逆候補を追加。既定OFF、safeと併用可能 |
| `--jpegtran-path PATH` | 手動準備したjpegtran 3.2.0を明示。パスだけでは有効化しない |
| `--limit N` | サイズ上位 `floor(N/2)` 件と、残りから固定seedで選ぶ `N-floor(N/2)` 件のPilot実行。Nが奇数ならランダム側が1件多い |
| `--retry-errors` | 前回 `ERROR` の入力を再処理 |
| `--qpdf-path PATH` | `qpdf.exe` を明示 |
| `-v`, `--verbose` | 詳細ログ |

入力と出力に、同じフォルダーや互いに親子となるフォルダーは指定できません。
`--safe`は`--preset compact`、`--text-scan-pattern`、`--text-scan-bilevel-pattern`、`--photo-pattern`、`--font-replace-pattern`と同時指定できず、
終了コード `2` になります。

写真PDFの閲覧用候補を明示的に選ぶ場合:

```powershell
uv run --project pdf-shrink pdf-shrink run --input "C:\作業\PDF" --output "C:\作業\閲覧用\PDF_軽量化" --photo-pattern "写真/*.pdf" --dry-run
```

パターンは入力相対パスに大文字小文字を無視して照合します。`\`は`/`へ正規化し、`*`は
ディレクトリ区切りにも一致します。空、絶対パス、drive付き、`..`要素を含む指定は拒否します。
一致しないPDFは元のpresetに従います。写真やスキャンの意味を自動分類せず、DPIによるOCR要否判定は行いません。

## 出力、状態、レポート

入力内の相対フォルダー構造を出力内でも維持します。出力が
`C:\作業\PDF_軽量化` の場合、PDF以外の補助ファイルは次へ保存します。

| 内容 | 保存先 |
|---|---|
| 通常実行のレポート | `C:\作業\report.csv` |
| dry-runのレポート | `C:\作業\report.dry-run.csv` |
| 状態DB | `C:\作業\.pdf-shrink\state.sqlite3` |
| 一時ファイル | `C:\作業\.pdf-shrink\temp\` |
| 比較資料（指定時のみ） | `C:\作業\pdf-preview\<runid>\index.html`と同じ実行フォルダー内のPDF・PNG |
| 比較manifest | `C:\作業\pdf-preview.json` |
| 比較dry-run manifest | `C:\作業\pdf-preview.dry-run.json` |

dry-runでも状態DBと `report.dry-run.csv` を更新する場合があります。完成PDFと処理用の
一時PDFは作りません。レポートは状態DB全体ではなく、現在選択した入力だけを対象にします。

状態DBには入力と完成出力のSHA-256を保存します。処理中に入力または出力が変わった場合は、
新しい内容を誤って処理済みと記録せず、次回に再処理します。ただし、処理中の入力自体は
ロックしません。
プリセットの画像処理値、写真選択パターン、`photo_dpi`とphoto recipeは再開判定用の設定ハッシュに
含みます。字体統一パターン、WindowsフォントファイルのSHA-256、固定レシピ、fontTools・pikepdfの版も含みます。
現行版は`processing_schema=6`を含むため、以前のstateも一度再処理します。
状態DBは`photo_dpi`や字体統一の要求・字体名・SHA・抽出差などの列追加で移行し、既存行は削除しません。
`preview`・`preview_dpis`は通常処理のhashから除外し、比較資料だけの変更では正常PDFを再処理しません。

## 任意のPDF比較

```powershell
uv run --project pdf-shrink pdf-shrink run --input "C:\作業\PDF" --output "C:\作業\比較\PDF_軽量化" --photo-pattern "*写真*.pdf" --photo-dpi 200 --preview --preview-dpi 180 --preview-dpi 150
```

`--preview`は通常PDF処理後に、原本と実際の完成出力をローカルHTMLで比較できる資料を作ります。
`--preview-dpi`は重複を除いて降順に揃えた最大5種類です。保護されていないphotoだけに原本から独立に比較候補を作り、
通常の採用結果・成功state・CSV候補履歴へ影響させません。画質検証に合格した候補は容量が増大しても
表示でき、画質棄却は`REJECTED`と理由だけを残します。通常PDFの`ERROR`・`SKIPPED_*`は描画しません。

全ページ144 DPI・画像領域300 DPIのRGB PNGを、倍率とスクロール位置を同期して表示します。
上限は1冊100ページ、500画像配置、1描画32 MP、全版累積600 MP、300秒の協調的予算です。
超過・処理失敗は比較側`ERROR`として終了コード1へ反映し、完成PDFの結果を保持して他PDFを続行します。

新しい`pdf-preview/<runid>/`に原本・完成出力・候補PDFもコピーします。サーバー・CDNは不要です。
保存・共有には`index.html`だけでなく実行フォルダー全体を使います。結果は出力の親の
`pdf-preview.json`へ記録します。dry-runは`pdf-preview.dry-run.json`だけで、HTML・PNG・比較PDFは作りません。
PDFが0件でも比較指定時は空report・状態領域・manifestを用意し、通常実行では対象なしHTMLを作ります。
仕様の詳細は[PDF比較HTML](../docs/REFERENCE.md#任意のpdf比較html)を参照してください。

## 保護と文章向け候補

standard/compactとも、図・写真・その他の画像を含む未許可PDFは一冊まるごと原本コピーします。
可逆候補、JPEG可逆候補、比較用追加候補も生成しません。自動対象は、文字を確認でき、画像・
描画パス・その他の非文字描画がないPDFだけです。空白ページの混在は許可します。

| 指定 | 処理 |
|---|---|
| 無指定 | 文字だけを自動対象にし、その他は保護 |
| `--preserve-pattern` | 必ず原本保護。すべての許可に優先 |
| `--text-pattern` | 文章と水平・垂直の直線・枠線だけの罫線表を許可 |
| `--text-scan-pattern` | 明示した文章だけのスキャンを許可 |
| `--text-scan-bilevel-pattern` | 明示した白黒書類スキャンに二値化候補を追加 |
| `--font-replace-pattern` | 明示したPDFの字体をWindowsメイリオRegularへ統一する候補を許可 |
| `--photo-pattern` | 既存の写真用150〜300 DPI候補を許可 |

上表はPDF個別CLIの名前です。統合CLIでは`--text-pattern`を`--pdf-text-pattern`とするように`pdf-`を付けます。すべて反復可能な入力相対globで、
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
`--text-scan-bilevel-pattern`では同じ候補に1-bit DeviceGray・Flate候補を追加します。
グレー画素値220未満を黒、220以上を白にし、dither・文字認識・字形の置換は行いません。
同サイズではJPEG候補を二値化より優先します。採用時は`ADOPTED_LOSSY`、候補kindと理由は
`text_scan_bilevel`と`adopted_text_scan_bilevel`です。色・階調・薄い筆画の保持は保証しません。
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

写真レシピ・候補検証・採用条件の正確な値は[技術リファレンス](../docs/REFERENCE.md#写真用profileの明示選択)を参照してください。

## Windowsフォントへの明示置換

通常CLIに実装済みです。既定はOFFで、PDF個別CLIでは次のように指定します。
統合CLIからの操作は[利用者マニュアル](../MANUAL.md#日本語英語のpdfをメイリオへ統一する)を参照してください。

```powershell
uv run --project pdf-shrink pdf-shrink run --input "C:\作業\PDF" --output "C:\作業\字体統一\files" --font-replace-pattern "報告書.pdf" --dry-run
uv run --project pdf-shrink pdf-shrink run --input "C:\作業\PDF" --output "C:\作業\字体統一\files" --font-replace-pattern "報告書.pdf"
```

`--font-replace-pattern`は字体置換の対象選択であり、一致しないPDFも既存ルールで処理します。
1冊だけ試す場合はそのコピーだけを置いた入力フォルダーを使います。上の例の通常レポートは
`C:\作業\字体統一\report.csv`です。`ADOPTED_LOSSY`かつ`adopted_font_replace`で置換採用を確認できます。

`font_replace` profileはWindowsの`meiryo.ttc` face 0（`Meiryo Regular`、既定）または
`--font-family yu-gothic`で`YuGothR.ttc` face 0（`Yu Gothic Regular`）を使い、日本語・英語の
横書きで対応可能な文字だけをサブセット埋め込みします。フォント名・埋め込み権限・SHAを確認し、
字体の輪郭や文字幅自体は改変せず、PDF側の字間を調整します。画像として焼き込まれた文字は対象外です。
無指定のPDFでは字体を変えません。必要なWindowsフォントの準備失敗は開始前エラーですが、
preserve優先の適用後にfont_replace対象が0件ならフォントを要求しません。

qpdf単独と字体置換＋qpdfを原本から独立に比較し、検証済みで原本より小さい候補だけを採用します。
タグ構造と空のAcroFormは保持して独立検証します。空AcroFormはFieldsなし/空配列で、
キーをFields/DR/DA/NeedAppearancesに限定します。注釈・入力欄・XFA・署名は対応外です。
同寸法8bit DeviceGrayの単層SMask付き画像を保持でき、XMPのPDFVersionも自動書換えしません。
同サイズならqpdfを優先し、字体置換の採用は`ADOPTED_LOSSY`です。`--lossless-jpeg`を併用しても
このprofileの候補は増やさず、要求フラグは記録します。欠字・未対応構造は文書全体を保護し、
構造検査・ツール・I/O失敗は復旧コピー後も`ERROR`です。dry-runはフォント・構造の読取りだけです。

表示文字・順序・位置、図表・画像等の保持を独立検証しますが、字形と検索・コピー時の推定空白は
変わり得ます。Regular化で元の太字の強調が弱まる場合もあります。
MuPDFでの抽出差は採用時に`text_extraction_changed`へ記録し、全閲覧ソフトの一致は
保証しません。対応構造、検証方法、上限の正確な契約は
[Windowsフォントへの明示置換](../docs/REFERENCE.md#windowsフォントへの明示置換)を参照してください。
比較HTMLの100ページ上限は通常PDF処理と別であり、font_replaceにも適用されます。

## レポートのstatus

`SKIPPED_ENCRYPTED`・`SKIPPED_SIGNED`・`SKIPPED_COMPLEX`は旧記録との互換値です。共通保護判定は`PRESERVED_ORIGINAL`と理由を記録します。

`--lossless-jpeg`は保護されていないphoto PDFの原本からbaseline/progressiveの可逆候補を追加し、既存の非可逆候補を無効化しません。
手動準備したlibjpeg-turbo 3.2.0のjpegtranだけを使用し、明示パス→PATHで解決します。
未検出/版不一致は処理開始前エラー。dry-runでは外部toolを実行しません。
単純な8-bit DeviceRGB/DeviceGray DCT画像のstreamだけを変更し、辞書・原寸画素・DQTと
全ページの形状・文字・パス・72/300 DPI RGBの一致を確認します。Mask、Decode、複雑な色空間、inlineは対象外です。
20 MP/32 MiB、128M/100 scans/30秒、文書300秒協調予算を使用します。
同サイズ優先順はqpdf、JPEG baseline、JPEG progressive、非可逆です。
詳細は[任意JPEG可逆の契約](../docs/REFERENCE.md#任意のjpeg可逆候補)を参照してください。

| status | 意味 |
|---|---|
| `PRESERVED_ORIGINAL` | 候補を生成せず原本保護、出力SHA一致 |
| `DRY_RUN_PRESERVED` | 保護予定、完成出力なし |
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

現在選択した入力に `ERROR` が1件以上あれば終了コードは `1`、それ以外は `0` です。
入力・出力検査、qpdf準備、レポート更新、比較資料生成の失敗も `1`、不正な数値オプションは `2` です。

レポート列:

```text
source_path,source_size,source_sha256,output_path,output_size,output_sha256,saved_bytes,saved_percent,preset,mode,status,page_count,scan_page_ratio,error_message,profile,decision_reason,candidate_size,candidate_saved_bytes,candidate_saved_percent,images_changed,candidate_details,lossless_jpeg_requested,photo_dpi,requested_policy,classification,permission_basis,preservation_reason,processing_schema,font_replacement_requested,replacement_font,replacement_font_sha256,text_extraction_changed
```

`profile`はファイルに適用した`standard`・`compact`・`photo`・`text`・`text_scan`・`text_scan_bilevel`・`font_replace`・`preserve`です。`preset`は起動時の値を維持します。
`photo_dpi`はphoto行の要求目標DPIで、それ以外はCSVで空欄、DBで`NULL`です。原本・可逆候補を
採用しても要求値を維持します。統合CLIは旧CSVでの列欠落、不正値、指定不一致を拒否します。
`candidate_*`と`images_changed`は一次候補の診断値です。photoでは非可逆候補を試した場合はそれを一次とし、文章向けはqpdfを一次とします。
可逆候補を後から採用しても記録を置き換えません。`candidate_saved_percent`と`saved_percent`は
0.05が5%の割合です。候補未生成のサイズは空欄であり、0 byteとは異なります。

`candidate_details`は`kind`、`size`、`images_changed`、`reason`、`validation_reason`、`selected`、`text_extraction_changed`を
持つJSON配列です。`kind`は非可逆候補でprofile名、可逆候補で`lossless`、
`jpeg_lossless_baseline`、`jpeg_lossless_progressive`を記録します。
`lossless_jpeg_requested`は全行`true`/`false`で保存し、統合CLIが指定と照合します。
`font_replacement_requested`はfont_replace行だけ`true`で、`replacement_font`は選択した`Yu Gothic Regular`または`Meiryo Regular`、
`replacement_font_sha256`はWindowsフォントファイル全体の64桁小文字SHA-256です。他profileは要求`false`・
字体名/SHAは空欄です。保護・dry-run・qpdf候補採用でも要求を記録します。`text_extraction_changed`は
採用した字体置換候補にMuPDF抽出の空白・改行差がある場合だけ`true`、他は`false`です。
DBは旧行を保持した列追加移行。hashには採用下限、JPEG有効状態、固定recipe/検証、tool version/SHA-256を含めます。
採用候補だけ`selected=true`で、原本採用時は全て`false`です。最終理由と
一次候補だけで判断せず、後続候補の経緯も確認できます。各理由の意味は
[PDFレポートの診断列](../docs/REFERENCE.md#pdfレポートの診断列)を参照してください。

## モジュール境界

| モジュール | 責務 |
|---|---|
| `cli.py` | 引数解析、ログ設定、終了コードへの受け渡し |
| `runner.py` | 一括処理、ProcessPool、状態保存、レポート対象の決定 |
| `models.py` | 入力スナップショット、検査結果、候補履歴、処理結果、status |
| `config.py` | 型付き設定、ファイル別profile選択、再開条件ハッシュ |
| `discovery.py` | 入力検証、PDF探索、Pilot選択、SHA-256取得 |
| `worker.py` | 1ファイルの検査、候補生成、検証、採否判断 |
| `policy.py` | 候補生成前の文書全体の保護・許可判定、文章スキャン画像の事前検査 |
| `text_optimize.py` | 文章・罫線表・文章スキャン候補、内容・配置・描画検証、文書予算 |
| `font_replace.py` / `font_replace_parse.py` | Windows字体の準備、字体置換の有界な事前検査・サブセット・PDF文字送り変換 |
| `font_validate.py` / `font_pipeline.py` | 字体・文字・非文字構造の独立検証／qpdf単独と字体置換候補の評価 |
| `inspect_pdf.py` | 写真処理等の安全性検査と画像配置の実効DPI判定 |
| `transform.py` | 写真向け等の可逆・非可逆候補の生成 |
| `lossless_jpeg.py` | 任意jpegtran検出、JPEG可逆stream生成、原寸画素・完全描画検査 |
| `preview.py` / `preview.html` | 任意のローカル比較資料生成・比較専用候補・独立manifest / 静的viewer |
| `validate.py` | 元PDFと候補の構造・内容比較 |
| `output.py` | 原本または検証済み候補の原子的な公開 |
| `state.py` | SQLite永続化と再開判定 |
| `report.py` | CSVとコンソールサマリー |
| `qpdf.py` | qpdfの探索、取得、実行 |

`worker.py` は `ProcessResult` を返します。CLIやrunnerからworker内部の変換実装へはアクセスしません。

## 開発検証

リポジトリ直下で実行します。

```powershell
uv run --project pdf-shrink python -m pytest -q pdf-shrink/tests
uv run --project pdf-shrink python -m compileall -q pdf-shrink/src pdf-shrink/tests
uv run --project pdf-shrink python -m pdf_shrink --help
```

qpdfを実行する統合テストがあり、初回はqpdfを取得する場合があります。

## 確認済みの未解決事項

1. qpdf配布ZIPの真正性

   バージョンと展開先は固定・検査しますが、配布ZIPのSHA-256または署名は検証しません。

2. 表示検証の解像度

   文章向けは72／300 DPIの完全一致またはグレースキャンの差分を検査し、`photo`は72 DPI RGBと変更配置の300 DPI RGBを比較します。
   写真中の小さい文字の可読性やOCR精度を保証しません。photoで選んだPDF内のJPEGが
   写真かどうかも自動分類しないため、利用者による原本との比較が必要です。

3. 入力ファイルの同時更新

   処理前スナップショットにより次回実行で変更を検出できますが、処理中の入力をロックしません。

4. 実データでの判定閾値

   テストは合成PDFが中心です。スキャン判定、削減率、表示差分の既定値を変更する前に、
   代表的な実PDFと失敗例を匿名化した回帰コーパスが必要です。写真DPI・比較HTMLの
   [実資料5冊による限定検証](../docs/validation/2026-09-09-photo-preview.md)は、別資料の画質保証ではありません。
