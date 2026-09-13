# KaruFile orchestrator

**フォント置換の実行には対象の明示指定が必要です。置換先の字体はメイリオが既定なので、字体名の指定は不要です。通常のPDF圧縮ではフォントを変更しません。**

`pdf-shrink`、`media-shrink-tool`、明示選択時の `excel-shrink`、compact時の `video-shrink` を順に呼び、開始・終了表示と
終了コードをまとめる薄い統合CLIです。変換処理や共通DBは持ちません。

通常の利用手順は [KaruFile 利用者マニュアル](../MANUAL.md)を参照し、リポジトリ直下の
`karufile.py` を使ってください。この文書は統合処理の契約と開発用情報を扱います。

## 単一PDFと既定のスキャン圧縮

PDFファイルを`--input`へ直接指定できます。ファイル入力ではその1冊だけを読み、相対パターンはファイル名に照合します。
出力省略時は元と同じ階層の`<拡張子なし名>_軽量化/files/<元ファイル名>`へ保存します。
`--output`は従来どおり完成ファイルを置くフォルダーで、report/stateはその親に置きます。
単一PDFでは画像・Excel・動画子処理を起動しません。周囲のファイルを探索せず、入力のコピーも作りません。
既定では文字なし・画像とclipだけのPDFをページ画像化し、色を失う300 DPI・グレー・JPEG品質92で圧縮します。
写真だけのPDFも含み、不可視OCRや文字・画像混在は自動画像化しません。
明示したpreserve/text/text-scan/bilevel/photo/font-replaceは既定処理より優先します。
PDF個別CLIの`--safe`は自動画像化を無効にします。詳細な条件と上限は技術リファレンスを参照してください。

## CLI

リポジトリ直下で実行します。

```powershell
uv run --script karufile.py `
  -i "D:\作業\資料" `
  -o "D:\作業\資料_軽量化"
```

| オプション | 意味 |
|---|---|
| `-i`, `--input` | 入力フォルダーまたはPDFファイル。必須 |
| `-o`, `--output` | 出力フォルダー。フォルダー入力の省略時は `<input>_軽量化`。単一PDFは `<stem>_軽量化/files` |
| `--pdf-workers` | PDFの並列数。既定値は2、最小値は1 |
| `--image-workers` | 画像の並列数。既定値は4、最小値は1 |
| `--excel-pattern PATTERN` | 入力相対globでxlsxを明示選択。反復可、無指定では探索しない |
| `--excel-max-side PX` | Excel画像の長辺上限。100〜10000、既定800 |
| `--excel-jpeg-quality N` | JPEG品質。40〜95、既定72（DPI時85）。上限以下のJPEGも再圧縮 |
| `--excel-dpi DPI` | 配置寸法方式を選択。150〜300、長辺指定と排他。Excel設定の明示時はexcel-pattern必須 |
| `--video-workers` | 動画の並列数。既定値は1、最小値は1 |
| `--video-safe` | 動画のprogressive/SAR/CFR明示を要求。既定OFF、compact専用 |
| `--video-remove-audio` | 動画を全音声除去して圧縮。既定OFF、compact専用 |
| `--preset` | `standard` または `compact`。既定値は `standard` |
| `--pdf-preserve-pattern PATTERN` | 最優先の原本保護。反復可 |
| `--pdf-text-pattern PATTERN` | 文章と単純罫線表の処理許可。反復可 |
| `--pdf-text-scan-pattern PATTERN` | 文章スキャンの300 DPIグレーJPEG候補を許可。反復可 |
| `--pdf-text-scan-bilevel-pattern PATTERN` | 白黒書類スキャンに二値化候補を追加。反復可、色・階調を失う |
| `--pdf-font-replace-pattern PATTERN` | 日本語・英語をWindowsのメイリオRegularへ統一する候補を許可。反復可、字形・検索/コピーの推定空白が変わる場合あり |
| `--pdf-font-family {yu-gothic,meiryo}` | 置換字体を選択。既定meiryo、明示指定にはfont-replace-patternが必須 |
| `--pdf-preview` | 全PDFの原本と実際出力・保護理由の比較HTML。既定OFF |
| `--pdf-photo-pattern PATTERN` | 一致するPDFだけphoto profileにする入力相対パターン。反復可 |
| `--pdf-lossless-jpeg` | JPEG可逆候補を追加。既定OFF |
| `--pdf-jpegtran-path PATH` | 手動準備したjpegtran 3.2.0を明示。パスだけでは有効化しない |
| `--ffmpeg-path` | compact動画用ffmpeg。省略時はPATH |
| `--ffprobe-path` | compact動画用ffprobe。省略時はPATH |
| `-n`, `--dry-run` | 完成出力を作らず判定を確認 |
| `-v`, `--verbose` | 詳細ログ |

`--pdf-photo-pattern`は大文字小文字を区別せず、`/`と`\`を正規化します。`*`は区切りにも
一致します。空、絶対パス、`..`を含むパターンは拒否します。一致するPDFだけに約200 DPIの
写真用候補を許可します。無指定では文字PDFと画像だけのスキャンを自動圧縮します。
スキャンは300 DPI・グレー・JPEG品質92です。文字・画像混在や描画線入りは既存の保護を維持します。
保護指定を最優先し、残る複数許可の一致は処理前エラーです。単独画像・動画の設定は変えません。
`--pdf-font-replace-pattern`も同じglob規則でPDFだけを選び、子CLIへ`--font-replace-pattern`として
渡します。フォント探索・置換・検証はPDFコンポーネントが担当し、統合CLIでは行いません。
Windowsにある`Meiryo Regular`（既定）または`Yu Gothic Regular`を使用し、無指定のPDFの字体は変えません。

## 実行契約

1. 入出力と、予定されるPDF・画像・Excel・動画・レポート・状態DBの保存先を検査します。
2. PDFを処理します。
3. 画像を処理します。
4. 明示選択したExcelがある場合はExcelを処理します。
5. compactの場合は動画を処理します。
6. 現在実行で更新されたPDF・画像・Excel・動画レポートを入力と実ファイルへ照合します。
7. 全processorの結果を統合して表示します。

ExcelのglobはPDF photoと同じ規則です。`~$`で始まるxlsxは除外し、選択0件では子CLIを起動しません。
両presetで同じExcel設定を使い、1冊ずつ処理します。画像の表示寸法解析・候補生成・検証・
レポート公開はExcel側が所有します。統合側は現在入力との1:1対応、要求DPI/長辺上限/JPEG品質、
予定出力、実ファイルのsize/SHA-256とstatusを照合し、不整合は失敗にします。

通常の動画判定はfield_order/SAR欠落とVFRを許容し、最大30fpsのCFRへ変換します。
`--video-safe` は従来の厳格判定です。両オプションは動画コンポーネントへ渡し、
CSVの`safe`/`remove_audio`が指定と一致することを確認します。音声除去指定時の成功は
無音の`ADOPTED`またはその再利用だけです。未対応・不採用時はERRORとし有音コピーを作りません。

入力と出力が同一または親子関係の場合、処理コンポーネント起動前に終了コード `1` で拒否します。
シンボリックリンク、ジャンクション、ハードリンク、出力名の衝突によって入力や別の出力へ書き込む可能性がある
場合も拒否します。
全対象のidentityとSHA-256をprocessor起動前と終了後に照合し、入力変更または検証不能は
集計を `unknown` として終了コード `1` にします。入力自体はロックしません。

1つのprocessorが失敗しても、可能な範囲で他を実行します。子処理コンポーネントの終了コード、
エラー件数、入力件数、更新されたレポートが一致しない場合は成功として扱いません。
いずれかが失敗した場合、統合CLIは `1` を返します。引数不正は `2` です。
各processorの実行期限は24時間で、超過時は子process treeを停止して失敗とします。

## 保存先

出力が `D:\作業\資料_軽量化` の場合:

| 内容 | 保存先 |
|---|---|
| PDF、画像、指定Excel、compact動画 | `D:\作業\資料_軽量化\` |
| PDFレポート（PDFがある場合） | `D:\作業\report.csv` |
| dry-run PDFレポート（PDFがある場合） | `D:\作業\report.dry-run.csv` |
| PDF状態DB（PDFがある場合） | `D:\作業\.pdf-shrink\state.sqlite3` |
| 画像エラーCSV | `D:\作業\資料_軽量化.image-errors.csv` |
| 画像manifest | `D:\作業\資料_軽量化.image-manifest.csv` |
| Excelレポート | `D:\作業\資料_軽量化.excel-report.csv` |
| dry-run Excelレポート | `D:\作業\資料_軽量化.excel-report.dry-run.csv` |
| Excel一時領域 | `D:\作業\資料_軽量化.excel-work\` |
| dry-run画像manifest | `D:\作業\資料_軽量化.image-manifest.dry-run.csv` |
| 動画レポート | `D:\作業\資料_軽量化.video-report.csv` |
| dry-run動画レポート | `D:\作業\資料_軽量化.video-report.dry-run.csv` |
| 動画状態・一時領域 | `D:\作業\資料_軽量化.video-state\` |

統合サマリーで正確な値を取得できない場合、その項目は `unknown` と表示します。
dry-runは完成したPDF・画像・Excel・動画を作りません。PDF状態と各report等は更新される場合があります。
video dry-runはstate workspace・空DBを初期化する場合がありますが、通常実行の成功recordを
読み書きしません。

PDFレポートはschema 6と要求policy・分類・許可根拠・保護理由を必須とし、各入力相対パスへの
指定内容を照合します。profileはstandard/compact/photo/text/text_scan/text_scan_bilevel/font_replace/preserveです。
保護statusは`PRESERVED_ORIGINAL`（dry-runは`DRY_RUN_PRESERVED`）で、通常出力のSHA一致を必須にします。
文章・表・文章スキャン・字体統一の採用は原本より小さい場合だけです。photoは可逆16 KiBかつ2%以上、
非可逆64 KiBかつ5%以上を照合します。一次候補の診断sizeを完成出力の集計には使用しません。
全行の`lossless_jpeg_requested`とphoto行の`photo_dpi`も要求と照合し、欠落・不一致を拒否します。
全行で`font_replacement_requested`、`replacement_font`、`replacement_font_sha256`、
`text_extraction_changed`を必須とします。font_replace行だけ要求`true`・選択した`Yu Gothic Regular`/`Meiryo Regular`・
64桁小文字SHA-256を認め、フォントSHAは同じ実行の行間でも一致を要求します。他profileは要求`false`・
字体名とSHAは空欄です。抽出差`true`はfont_replaceの`ADOPTED_LOSSY`だけに許可します。
qpdf候補採用・保護・dry-runでも要求とフォント名・SHAは記録しますが、抽出差は`false`です。
抽出差はMuPDFでの検出結果で、すべての閲覧ソフトの検索・コピー動作を保証しません。
JPEG可逆は保護を迂回しません。比較manifestは全PDFの集合と原本・実出力のSHA、statusを照合します。
比較itemにも字体統一の要求・字体名・抽出差を必須とし、PDFレポートとの一致を確認します。

画像の統合集計は子プロセスのstdoutではなく、現在実行で原子的に更新された画像manifestを
使います。入力・予定出力path、preset/recipe、size/SHA-256、action、寸法上限、画像エラーCSV
との対応が1件でも一致しなければ、画像集計を `unknown` として終了コード `1` を返します。

## 処理コンポーネントの場所

既定では、リポジトリ直下の `pdf-shrink/`、`media-shrink-tool/`、`excel-shrink/`、`video-shrink/` を使います。
開発・テスト時だけ、次の環境変数で差し替えられます。

- `PDF_SHRINK_ROOT`
- `MEDIA_SHRINK_ROOT`
- `EXCEL_SHRINK_ROOT`
- `VIDEO_SHRINK_ROOT`

## 開発検証

```powershell
Push-Location orchestrator
uv run --with pytest python -m pytest -q
Pop-Location
uv run --script karufile.py --help
```

内部構造と責務境界は [設計文書](docs/shrink_orchestrator_design.md)を参照してください。
