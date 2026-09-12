# KaruFile 利用者マニュアル

この文書は、KaruFileを初めて使う人のための正本です。上から順に進めると、準備、
dry-run、本実行、結果確認まで完了できます。

用途や原本の扱いを先に知りたい方は、[KaruFileで何ができるの？（図入りガイド）](docs/KARUFILE_GUIDE.html)を
ご覧ください。仕事の例から説明する入門用HTMLで、本文と図は単独ファイルでもオフラインで読めます。

KaruFileは、フォルダー内のPDFと対応形式の画像、明示選択したExcel、compact presetでは対応動画も再帰的に探し、
別のフォルダーへ軽量化するWindows向けCLIです。CLIは、PowerShellへコマンドを入力して使う
形式です。入力原本は変更・削除しません。

基本操作は「実行前に確認すること」から「終了コードとエラー確認」までを順に読んでください。
数値、status、再利用条件、個別CLIは [技術リファレンス](docs/REFERENCE.md)、処理全体の関係は
[実行時アーキテクチャ](docs/architecture/karufile-runtime.compact.html)から確認できます。

## 実行前に確認すること

次の4点を確認してから実行してください。

1. 入力とは別の出力フォルダーを使います。入力と出力に、同じフォルダーや互いに
   親子となるフォルダーは指定できません。
2. `--dry-run`でも、PDF状態DB、判定レポート、画像エラーCSV、画像dry-run manifestは
   更新される場合があります。
   compact動画はdry-runレポートを更新し、空の状態領域を初期作成する場合がありますが、
   通常実行の成功記録は読み書きしません。
   明示選択したExcelもdry-runレポートを更新します。
   完成したPDF・画像・Excel・動画は作りません。
3. 画像のメタデータを削除する機能ではありません。GPSを含む情報が出力に残る場合があります。
4. 処理中の入力ファイルはロックしません。別の処理から同時に入力を更新しないでください。

PDF、対応形式の画像、明示選択した`.xlsx`、compactで探索する対応動画以外のファイルは、出力フォルダーへ
コピーしません。standardでは動画を探索・コピーせず、従来のPDF・画像動作を維持します。

### プリセットを選ぶ

| 項目 | `standard`（既定値） | `compact` |
|---|---|---|
| 画像 | 長辺1280px・短辺960px以内、quality 72 | 長辺1024px・短辺768px以内、quality 60 |
| PDF | 文字だけを自動処理。図・画像は原本保護、明示許可した対象だけ加工 | 同じ保護方針・文章レシピ |
| Excel | 明示選択したxlsxの画像を長辺800px・JPEG品質72で圧縮。無指定では探索・コピーしない | 同じ処理 |
| 動画 | 探索・コピーしない | 対応する構成だけAV1へ変換。未対応は原本コピー、音声除去指定時はエラー |

まず使うプリセットを選び、同じプリセットでdry-runと本実行を行ってください。
compactの方が必ず小さくなるとは限りません。PDFと動画は候補の検証・削減条件により
原本を採用することがあります。ただし動画の音声除去指定時は、条件を満たせなければエラーにします。
両プリセットの結果を比較するときは別の出力先を使います。

### PDFの保護と文章向けの指定

判定・候補生成・検証・採用のつながりは[PDF処理の流れと判断基準](docs/PDF_PROCESSING.md)を参照してください。

無指定では文字だけのPDFを処理し、図・写真・スキャンを含むPDFは一冊まるごと原本コピーします。
`--pdf-text-pattern`は文章と単純な水平・垂直罫線表、`--pdf-text-scan-pattern`は文章だけのスキャンを
明示的に許可します。`--pdf-preserve-pattern`はすべての許可に優先して保護します。
保護されていないPDFが複数の許可に一致すると処理前にエラーになります。
パターンの書式は次の写真指定と共通です。

```powershell
uv run --script karufile.py -i "D:\作業\資料" -o "D:\作業\文章比較\files" --pdf-text-pattern "文章と表/*.pdf" --pdf-text-scan-pattern "文章スキャン/*.pdf" --pdf-preserve-pattern "*保存用*" --pdf-preview --dry-run
```

内容を確認した資料だけを指定し、dry-run後に`--dry-run`を外して処理します。文章・表では文字を
保持した整理圧縮とグレー候補、文章スキャンでは300 DPI・グレーJPEG品質92/85/80を比較します。
小容量でも検証済み候補が原本より小さければ最小を採用し、増大するグレー化・縮小を強制しません。
グレー化は非可逆です。図や特殊な画像が混ざっている場合は明示指定しても文書全体を保護します。
`PRESERVED_ORIGINAL`は原本と出力のSHA-256一致、`DRY_RUN_PRESERVED`は保護予定を表します。

<a id="日本語英語のpdfを游ゴシックへ統一する"></a>

### 日本語・英語のPDFをメイリオへ統一する

**フォント置換の実行には対象の明示指定が必要です。置換先の字体はメイリオが既定なので、字体名の指定は不要です。通常のPDF圧縮ではフォントを変更しません。**

| やりたいこと | 通常の圧縮コマンドに追加する指定 |
|---|---|
| フォントを変えずに圧縮する | 追加なし |
| 報告書1冊をメイリオへ置換する | `--pdf-font-replace-pattern "報告書.pdf"` |
| 入力フォルダー内の全PDFをメイリオへ置換する | `--pdf-font-replace-pattern "*.pdf"`（サブフォルダーも対象） |
| 報告書1冊を游ゴシックへ置換する | `--pdf-font-replace-pattern "報告書.pdf" --pdf-font-family yu-gothic` |

`--pdf-font-family`だけでは対象を選べないため、引数エラーになります。
対象指定は置換の許可であり、採用の保証ではありません。処理後は下記レポートの採用状態を確認します。


フォント置換は通常CLIに実装済みで、既定はOFFです。埋め込みフォントが容量を占めるPDFに、
`--pdf-font-replace-pattern`で字体統一を指定します。
置換先の既定はWindowsのメイリオRegular（`Meiryo Regular`）で、必要な文字を
PDFへ埋め込みます。フォントの同梱・ダウンロードや字体選択は行いません。
無指定では字体を変えません。画像になっている文字やスキャン画像には、この置換は効きません。

```powershell
uv run --script karufile.py -i "D:\作業\資料" -o "D:\作業\字体統一\files" --pdf-font-replace-pattern "報告書.pdf" --dry-run
uv run --script karufile.py -i "D:\作業\資料" -o "D:\作業\字体統一\files" --pdf-font-replace-pattern "報告書.pdf"
```

パターンは入力フォルダーからの相対パスです。複数指定でき、`*.pdf`は配下の全PDFに一致します。
この指定で選ぶのは字体置換の対象です。一致しないPDFや画像も通常のルールで処理します。
1冊だけ試す場合は、そのPDFのコピーだけを入れた専用フォルダーを`-i`に指定してください。

日本語・英語の横書きが対象で、対応できない文字・符号化・PDF構造は一冊まるごと原本保護します。
選択したWindowsフォントを確認できない場合はPDF処理の開始前エラーです。保護指定が優先し、別の許可との
重複は拒否します。PDF個別CLIでは`--font-replace-pattern`で、`--safe`と併用できません。

文字の表示順序や位置、図表・画像の保持を検証し、字体統一候補とqpdfだけの可逆候補を比較します。
検証に合格して原本より小さい候補だけを採用するため、指定しても字体が変わらない場合があります。
字体統一の採用は`ADOPTED_LOSSY`です。明朝体からゴシック体になるなど、字形は変わります。
Regularへ統一するため、元の太字も細くなり、見出しなどの強調が弱まる場合があります。
タグ付きPDFと入力欄のない空のフォーム情報は、構造を保持して字体変更を試せます。
対応する透過ロゴも保持します。選択した字体にない文字や注釈内の文字がある場合は、
引き続き文書全体の字体を保持します。文字検索できない画像・図形の文字は置換できません。

コピー・検索時に推定される空白や改行も変わる場合があります。例えば`30fps`が`30f ps`と抽出される
可能性があるため、完成後はPDFの表示に加えて、必要な語句の検索やコピーも確認してください。

メイリオが既定なので、字体名の指定は不要です。明示する場合は `--pdf-font-family meiryo`、
游ゴシックを使う場合は `--pdf-font-family yu-gothic` を追加します。例えば：

```powershell
uv run --script karufile.py -i "D:\作業\PDF" -o "D:\作業\メイリオ\files" --pdf-font-replace-pattern "報告書.pdf" --pdf-font-family meiryo
```

「☑」など、游ゴシックにはない文字を扱える場合があります。選択した字体に必要な文字がなければ
文書全体を保持します。メイリオでも注釈内の文字は置換しません。字体によって容量・字形・字間は異なります。

上の例では完成PDFは`D:\作業\字体統一\files\報告書.pdf`、通常レポートは
`D:\作業\字体統一\report.csv`です。入力内のサブフォルダー構造も保ちます。

```powershell
Import-Csv "D:\作業\字体統一\report.csv" | Select-Object source_path,status,decision_reason,replacement_font,text_extraction_changed
```

字体置換を指定した行は、次のように読みます。

| レポート | 実際の出力 |
|---|---|
| `status=ADOPTED_LOSSY`かつ`decision_reason=adopted_font_replace` | 選択した字体へ置換した候補を採用 |
| `status=ADOPTED_LOSSLESS` | 元の字体を保つqpdfの可逆候補を採用 |
| `status=PRESERVED_ORIGINAL` | 未対応構造や保護指定などにより原本をコピー。`preservation_reason`に理由を記録 |
| `status=UNCHANGED` | 採用条件を満たす候補がなく原本をコピー。`candidate_details`に各候補の結果を記録 |
| `status=ERROR` | 処理失敗。復旧コピーがあっても成功ではなく、`error_message`を確認 |

`font_replacement_requested=true`は要求の記録であり、実際の置換採用とは区別します。
`text_extraction_changed`は採用した字体統一候補についてMuPDFの抽出差を検出した結果で、
`false`でもすべてのPDF閲覧ソフトで同じ検索・コピー結果を保証するものではありません。
dry-runではフォントと構造を読み取るだけで、削減量や完成後の表示は確認できません。

比較HTMLを追加する場合、通常圧縮とは別の100ページ上限があります。上限を超える文書へ
`--pdf-preview`を付けると、PDF圧縮が成功しても比較側はエラーになります。

過去の游ゴシックによる通常CLI検証では、101ページの1冊が7,436,386 → 4,265,318 bytes（42.64%減）になりました。
この1冊の結果と既知の表示・抽出差は[検証記録](docs/validation/2026-09-10-windows-font-replacement.md)に記載しています。
別のPDFで同じ削減率になるとは限りません。

メイリオの既定化検証では、別の11ページの報告書が、圧縮済み273,959 → 204,602 bytes
（追加25.32%減、元原本340,536 bytesから39.92%減）になりました。「☑」4個を保持しましたが、
コピー・検索時の推定空白差があります。[この検証の記録](.agent/execplans/2026-09-10-nishimaki-pdf-compression.md)を参照してください。
この2件は異なる資料なので、数値だけで字体の優劣を比較できません。

### 白黒のスキャン書類を大幅に小さくする

スキャナーで取り込んだ書類は、ページ全体が画像のPDFになります。見積書・請求書などの
白黒文字と罫線が中心の資料には、`--pdf-text-scan-bilevel-pattern`を使えます。
通常の文章スキャン候補に、白黒2色に整理して圧縮する候補を追加します。
元が300 DPI以下なら解像度を維持し、300 DPIを超える軸だけ縮小します。

```powershell
uv run --script karufile.py -i "D:\作業\スキャン書類" -o "D:\作業\白黒圧縮\files" --pdf-text-scan-bilevel-pattern "*.pdf" --pdf-preview --dry-run
uv run --script karufile.py -i "D:\作業\スキャン書類" -o "D:\作業\白黒圧縮\files" --pdf-text-scan-bilevel-pattern "*.pdf" --pdf-preview
```

色と灰色の階調は失われます。写真・網掛け・薄い鉛筆書き・色付き印影を残したいPDFには
この指定を使わず、通常の文章スキャン候補や原本保護を選んでください。完成後は比較HTMLで
細字、金額、罫線、印影を確認します。機械検証は文字の意味や可読性を保証しません。
二値化候補が検証に通らない場合も、他の検証済み候補と原本が選択肢に残ります。
既に1-bitで圧縮されたPDFや特殊な画像構造は原本保護になります。
同じPDFへ`--pdf-text-scan-pattern`など別の許可を重ねず、どちらか一方を選びます。
無指定で自動的に白黒化することはありません。

### 写真PDFの閲覧用コピーを作る

写真の細部の劣化を許容できるPDFだけ、`--pdf-photo-pattern`で明示的に選べます。
一致するPDFには`photo` profileを適用し、対象JPEGの既定200 DPI・quality 80の縮小候補を作ります。
`--pdf-photo-dpi`で目標を150〜300の整数へ変更できます。この指定には写真パターンが必要です。
指定しないPDFは共通の保護方針に従います。単独画像・動画の設定は変わりません。

```powershell
uv run --script karufile.py -i "D:\作業\資料" -o "D:\作業\閲覧用\資料_軽量化" --pdf-photo-pattern "2.現地写真*.pdf" --pdf-photo-pattern "5.採取写真*.pdf" --dry-run
uv run --script karufile.py -i "D:\作業\資料" -o "D:\作業\閲覧用\資料_軽量化" --pdf-photo-pattern "2.現地写真*.pdf" --pdf-photo-pattern "5.採取写真*.pdf"
```

パターンは入力フォルダーからの相対パスです。大文字小文字を区別せず、`/`と`\`を同じ区切りと
みなします。`*`はサブフォルダーの区切りにも一致するため、`*.pdf`は全PDFを選びます。
絶対パス、空のパターン、`..`を含むパスは使えません。複数選ぶときはオプションを繰り返します。

写真かどうかは自動分類しません。図面、黒板の小さい文字、顕微鏡写真などの細部を保護する必要が
あるPDFを一括指定しないでください。300 DPI以下を「OCR不要」と判断する機能でもありません。
dry-runのPDFレポートで`profile`が`photo`になった対象を確認し、本実行後は文字や細部を原本と
見比べてください。画質検証はありますが、可読性やOCR精度を保証しません。

### PDFの原本と完成出力を見比べる

`--pdf-preview`を付けると、文章・罫線表・文章スキャン・写真・字体統一のPDFの原本と実際の完成出力を、ローカルHTMLで
同じ倍率・スクロール位置に揃えて比較できます。既定では作成しません。ブラウザーで開くだけで使え、
サーバーの起動や外部CDNへの接続は必要ありません。

次は完成出力を200 DPI目標のまま処理し、180 DPI・150 DPIも比較する例です。

```powershell
uv run --script karufile.py -i "D:\作業\資料" -o "D:\作業\比較\資料_軽量化" --pdf-photo-pattern "*写真*.pdf" --pdf-preview --pdf-preview-dpi 180 --pdf-preview-dpi 150
```

保護対象も理由と原本・実際出力を表示し、追加候補は生成しません。
`--pdf-preview-dpi`は保護されていないphoto用に150〜300の整数を最大5種類まで指定できます。各比較候補は原本から独立に
作り、通常処理の採用結果を変えません。比較後に150 DPIを完成出力の候補として使う場合は、
別の出力先へ`--pdf-photo-dpi 150`を指定して実行します。写真の表示サイズは維持し、
元から指定DPI以下の画像は拡大しません。

終了時に表示される`PDF preview`の`index.html`を開いてください。全ページと写真領域を切り替え、
写真内の黒板文字や細い線を拡大して確認できます。「完成出力」は実際の採用結果なので、
検証や削減条件により原本・可逆候補を採用した場合は、指定DPIに縮小されていないことがあります。
追加DPIは比較専用と表示し、完成出力と区別します。

比較資料は出力の親の`pdf-preview/<runid>/`へ保存します。原本・完成出力・比較候補のPDFと
表示画像を含むため、保存・共有するときは`index.html`だけでなく、この実行フォルダー全体を
まとめてください。比較資料にも原本の内容が含まれます。

`--dry-run --pdf-preview`では要求設定のJSONだけを記録し、HTML・描画画像・比較PDFは作りません。
比較資料の生成が失敗したり上限を超えたりすると終了コードは1になりますが、通常処理で完成した
PDFとその結果は保持し、他のファイルは続行します。詳細は`pdf-preview.json`のエラーを確認します。

### Excel内の大きな画像を縮小する

写真を貼り付けた報告書や台帳では、シート上の表示サイズに対して画像が大きすぎる場合があります。
`--excel-pattern`で明示選択した`.xlsx`だけ、その余分な画素数を減らします。無指定ではExcelを探索・コピーしません。
`standard`と`compact`でExcelの処理は同じです。

初回はExcel用の依存関係を準備し、コピーした1冊から試します。

```powershell
uv sync --project excel-shrink
uv run --script karufile.py -i "D:\作業\資料" -o "D:\作業\資料_軽量化" --excel-pattern "写真台帳/*.xlsx" --dry-run
uv run --script karufile.py -i "D:\作業\資料" -o "D:\作業\資料_軽量化" --excel-pattern "写真台帳/*.xlsx"
```

パターンは入力からの相対パスで、大文字小文字を区別せず、`*`はサブフォルダーにも一致します。
複数回指定できます。空のパターン、絶対パス、`..`を含む指定は拒否します。Excelの一時ロックファイル
（名前が`~$`で始まるもの）は対象にしません。選ばなかったPDFや単独画像は通常のルールで処理します。

既定は**長辺800px・JPEG品質72**です。`--excel-max-side 800`で長辺上限（100〜10000）、
`--excel-jpeg-quality 72`でJPEG品質（40〜95）を指定できます。上限以下のJPEGも再圧縮し、
画像ごと・ブック全体で元より小さくなった候補だけを採用します。不可逆の画質劣化があります。
色差は間引かず4:4:4を維持します。表示サイズは変えず、拡大やトリミング領域の削除もしません。
保護画像や検証で棄却した画像は、上限を超えていても変更しません。
従来の配置寸法方式は`--excel-dpi 220`（150〜300）で選べます。長辺上限と同時には使えず、
この方式のJPEG品質既定は85です。全配置と内側cropから必要画素数の最大値を確保し、
縮小不要のJPEGは再圧縮しません。各オプションの明示指定には`--excel-pattern`が必要です。
JPEGはJPEG、PNGは透過を維持したPNGとして処理し、画像以外の内部ファイルは展開後のバイト一致を検証します。

初版は表示寸法を確定できる貼り付け画像に限定します。1セル基準・絶対位置の画像と、
開始点と終了点が同じセルにある2セル基準の画像を扱います。複数セルにまたがる画像も、
**標準字体がCalibri 11またはWindowsで確認できる游ゴシック11の標準書体で、
列幅と行高を確定できる場合に処理します。** 空行の既定行高・確認済みの既定列幅も扱います。
Excel本体のインストールは処理の必須条件ではありません。内容による自動高さ、非表示の行列、未対応の標準字体、
数式表示などは対応しません。通常保存した写真入りブックでも、縮小できない場合があります。
同じ画像が未対応の場所でも使われていれば、その画像全体を変更しません。他の独立した対応画像は処理できます。
セル内画像、マクロ付き、暗号化・署名付き、埋め込みオブジェクト等を含むブックは加工せず、
そのブック全体を原本のまま別出力へコピーします。
`.xls`・`.xlsb`・`.xlsm`は対象外です。安全に解析できない破損やI/O失敗はエラーで、回復コピーを作りません。
以前の出力が残ることがあるため、ファイルの存在だけで成功と判断しないでください。

dry-runは構造と処理予定を調べ、Excelレポートだけを更新します。完成xlsxや縮小候補は作りません。
通常実行では画像を変更したうえでブック全体が原本より小さくなり、検証を通った場合だけ採用します。
変更可能な画像がない場合や小さくならない場合は原本コピーです。
画像パートは最大1000個まで検査しますが、総画素数などの上限もあるため全画像の処理を保証しません。
CSVには実画像数、画像ごとの寸法と保護理由を記録します。画像数を取得できなかった場合は空欄で、0個と区別します。

実行後はExcelで開き、修復警告がないか、写真・小さい文字・トリミング・数式・印刷結果を原本と見比べてください。
内部ファイルの一致検証は、Excelでの表示・印刷・再保存後の同一性を保証するものではありません。
利用する実資料での表示・印刷と削減効果は、別途確認が必要です。

## 必要なもの

- Windows
- Python 3.13以上
- [uv](https://docs.astral.sh/uv/)

PDFを含む通常実行ではqpdfを使用します。KaruFileは `PATH` とローカルキャッシュから
qpdfを探し、見つからない場合はqpdf 12.3.2のWindows向け配布ZIPをGitHub Releasesから
取得します。初回実行時に取得が必要になる場合があります。PDFを含まない実行と
`--dry-run` ではqpdfを使用しません。

JPEG画像の解像度を変えない追加最適化は、`--pdf-lossless-jpeg`で有効にできます（既定OFF）。
[公式libjpeg-turbo 3.2.0 Windows x64配布物](https://github.com/libjpeg-turbo/libjpeg-turbo/releases/tag/3.2.0)を
手動で準備し、公式配布物のSHA-256とWindows署名を確認してください。自動取得・インストールはしません。
`jpegtran.exe`と同梱DLLの配置を維持し、明示パスまたはPATHを使います。

```powershell
uv run --script karufile.py -i "D:\作業\資料" -o "D:\作業\JPEG検証\資料_軽量化" --pdf-photo-pattern "*写真*.pdf" --pdf-lossless-jpeg --pdf-jpegtran-path "C:\Tools\libjpeg-turbo\bin\jpegtran.exe"
```

パス指定だけでは有効になりません。有効時にツールが見つからない、または3.2.0でない場合はPDF処理開始前に
エラーとなります。dry-runではツールを探索・実行せず、要求設定だけをCSVへ記録します。
この指定は保護されていないphoto PDFへ可逆候補を追加します。保護指定を迂回しません。presetや写真指定による既存の非可逆候補も比較対象に残るため、
「完成出力は必ず可逆」を意味しません。文章を可逆処理だけに限定する場合はPDF個別CLIの`--safe`を使います。
`--safe`は写真指定と併用できないため、`--safe --lossless-jpeg`としても写真PDFのJPEG可逆候補は作りません。

compactで動画を処理する場合は、`ffmpeg` と `ffprobe` が `PATH` に必要です。KaruFileは
これらを自動取得・同梱しません。別の実行ファイルを使う場合は `--ffmpeg-path` と
`--ffprobe-path` で指定できます。利用するFFmpeg buildにはSVT-AV1、AAC、Opus、libvmaf、
scale/fps filter、MP4/Matroska/WebM muxerが必要です。不足は処理開始時にエラーとして検出します。

動画の`--dry-run`ではffprobeだけを使い、FFmpegのencoder/filterや実際の圧縮品質は検証しません。
compactでも対象動画がなければFFmpeg/ffprobeは使いません。

## 基本手順

### 1. PowerShellでリポジトリを開く

以降のコマンドは、`karufile.py` があるKaruFileリポジトリの直下で実行します。

### 2. 初回だけ依存関係を準備する

```powershell
uv sync --project pdf-shrink --dev
uv sync --project media-shrink-tool
```

compactで動画も処理する場合は、追加で動画コンポーネントを準備します。

```powershell
uv sync --project video-shrink
```

これらは各コンポーネントのPython環境を準備するコマンドです。FFmpeg/ffprobeは含まれません。

### 3. 入力と出力を決める

このマニュアルでは、次のフォルダーを例にします。

| 用途 | フォルダー |
|---|---|
| 入力 | `D:\作業\資料` |
| 出力 | `D:\作業\資料_軽量化` |

`-o`を省略すると、入力と同じ階層の `<入力フォルダー名>_軽量化` を使います。

### 4. dry-runで対象を確認する

```powershell
uv run --script karufile.py -i "D:\作業\資料" -o "D:\作業\資料_軽量化" --dry-run
```

`--dry-run`の短縮形は `-n` です。dry-runでは、対象の検査と処理方法の判定を行います。
完成したPDF・画像・Excel・動画は作りませんが、状態DBとレポートは更新される場合があります。
圧縮後のサイズや品質、通常実行の成功を保証する検査ではありません。

compactのPDF・画像・動画候補を確認する場合:

```powershell
uv run --script karufile.py --preset compact -i "D:\作業\資料" -o "D:\作業\資料_軽量化" --dry-run
```

### 5. 本実行する

```powershell
uv run --script karufile.py -i "D:\作業\資料" -o "D:\作業\資料_軽量化"
```

出力を既定値にする場合:

```powershell
uv run --script karufile.py -i "D:\作業\資料"
```

compactを選んだ場合は、上のstandard実行に代えて次を実行します:

```powershell
uv run --script karufile.py --preset compact -i "D:\作業\資料" -o "D:\作業\資料_軽量化"
```

通常実行では確認入力を求めません。PDF、画像、明示選択したExcel、compactの場合は動画の順に処理します。
1つが失敗しても、可能な範囲で他のprocessorを処理します。

### 6. 結果を確認する

終了時の統合サマリーを確認します。

PowerShellでは、実行コマンドの直後に`$LASTEXITCODE`を入力すると終了コードを確認できます。

| 表示 | 意味 |
|---|---|
| `PDF errors` | PDFの失敗件数 |
| `Image errors` | 画像の失敗件数 |
| `Excel errors` | 明示選択したExcelの失敗件数 |
| `Video errors` | compact動画の失敗件数 |
| `Original size` | 処理結果から集計した入力サイズ |
| `Output size` | 処理結果から集計した出力サイズ |
| `Saved` | 削減できたサイズ |
| `Reduction` | 削減率 |
| `Source files changed: NO` | 起動前と終了時のidentity・SHA-256検査で入力変更を検出しなかったこと |
| `Files deleted: 0` | 入力を削除していないこと |

正確な値を取得できなかった項目は `unknown` と表示します。dry-runでは完成出力を
作らないため、出力サイズ、削減量、削減率を計算しません。
`Source files changed: YES OR COULD NOT VERIFY` の場合は入力の変更または検証不能を表し、
他の集計値も `unknown`、終了コードは `1` になります。

PDFが`UNCHANGED`になった場合はPDFサマリーの理由別件数と、`report.csv`の`decision_reason`を
確認します。`candidate_not_smaller`は候補が小さくならなかった、`reduction_below_threshold`は
削減基準未達、`quality_rejected`は画質検証による棄却、`no_image_savings`は画像候補が採用されず
画像の書き換えがなかったことを表します。`candidate_size`は最初に試した
候補のサイズで、完成出力の`output_size`とは異なります。可逆候補への切り替えも含む全履歴は
`candidate_details`に残ります。詳細は[PDFレポートの診断列](docs/REFERENCE.md#pdfレポートの診断列)を参照してください。

## 出力とレポートの場所

入力内の相対フォルダー構造は、出力内でも維持します。前の例では、保存先は次のとおりです。

| 内容 | 保存先 |
|---|---|
| 軽量化したPDF・画像・Excel・動画 | `D:\作業\資料_軽量化\` |
| 通常実行のPDFレポート | `D:\作業\report.csv` |
| dry-runのPDFレポート | `D:\作業\report.dry-run.csv` |
| PDFの再開状態 | `D:\作業\.pdf-shrink\state.sqlite3` |
| 指定時のPDF比較資料 | `D:\作業\pdf-preview\<runid>\index.html`と同じ実行フォルダー内のPDF・画像 |
| PDF比較の結果JSON | `D:\作業\pdf-preview.json` |
| PDF比較のdry-run JSON | `D:\作業\pdf-preview.dry-run.json` |
| 画像エラーCSV | `D:\作業\資料_軽量化.image-errors.csv` |
| 通常実行の画像manifest | `D:\作業\資料_軽量化.image-manifest.csv` |
| dry-runの画像manifest | `D:\作業\資料_軽量化.image-manifest.dry-run.csv` |
| 通常実行の動画レポート | `D:\作業\資料_軽量化.video-report.csv` |
| 通常実行のExcelレポート | `D:\作業\資料_軽量化.excel-report.csv` |
| dry-runのExcelレポート | `D:\作業\資料_軽量化.excel-report.dry-run.csv` |
| Excelの一時領域 | `D:\作業\資料_軽量化.excel-work\` |
| dry-runの動画レポート | `D:\作業\資料_軽量化.video-report.dry-run.csv` |
| 動画の再開状態・一時領域 | `D:\作業\資料_軽量化.video-state\` |

PDFレポートと状態DBは、入力ではなく出力フォルダーの親へ保存します。PDFがなく、比較指定もない
実行では作成・更新しません。`--pdf-preview`を指定した場合は、対象0件でも空のPDFレポート・状態領域と
比較JSONを用意し、通常実行では対象なしの比較HTMLも作ります。以前のファイルは削除しません。

複数の出力フォルダーが同じ親フォルダーにある場合、PDFレポートと状態DBは同じ保存先を
使います。PDFレポートは、現在の実行で選ばれた入力を対象に更新します。
実行を並行させる場合は、出力先だけでなくPDFの状態・レポートを置く親フォルダーも分けてください。

画像処理が起動し、CSVの更新に成功した場合、画像エラーが0件でもエラーCSVをヘッダーだけへ
更新します。全画像のpath、size、SHA-256、action、preset、recipe、処理前後の寸法は、通常実行と
dry-runを分けた画像manifestへ記録します。統合CLIはこのmanifestを現在の入力・出力と照合して
集計します。安全性検査、画像処理の起動、またはレポート更新に失敗した場合は終了コード `1` と
なり、以前のレポートが残ることがあります。

動画レポートと状態領域は、統合CLIでcompactを選び、対象動画がある場合だけ使用します。
standardの実行で過去の動画出力やレポートを削除することはありません。

### 再実行と結果の比較

Excelには成功結果のキャッシュや状態DBがなく、再実行時も原本を調べ直します。
Excelレポートは今回の選択対象を記録し、`ADOPTED_LOSSY`は縮小採用、`PRESERVED_ORIGINAL`は
原本コピー、`ERROR`は失敗です。dry-runでは`DRY_RUN`または`DRY_RUN_PRESERVED`を使います。

再実行では、各処理の再利用条件を満たす完成済み出力を再利用し、それ以外は再評価します。
同じ出力先でプリセットを変えると、既存出力が新しい結果へ置き換わる場合があります。
以前の結果を残す場合は別の出力先を指定してください。PDFレポートも別々に残す場合は、
出力先の親フォルダーも分けます。

PDFの保護・文章・文章スキャン・写真・字体統一の選択パターンや`--pdf-photo-dpi`を変えた場合も再評価します。
字体統一では使用するWindowsフォントの内容・処理レシピ・関連ライブラリの版が変わった場合も再評価します。この版では処理schemaが
変わるため、以前のPDF状態がある場合も一度再処理します。比較資料の有無や追加比較DPIだけを
変えても通常PDFの再利用条件は変わりません。比較資料は実行ごとに新しいフォルダーへ作成します。

画像の非JPEG入力は、元のファイル名全体へ`.jpg`を追加します（例: `photo.png` → `photo.png.jpg`）。
JPEG入力は`.jpg`または`.jpeg`を維持します。出力名が衝突する場合は名前を調整するため、
最終的な出力先は画像manifestの`output_path`で確認してください。

## 終了コードとエラー確認

| コード | 意味 |
|---:|---|
| `0` | 対象となったPDF・画像・Excel・動画と、指定したPDF比較のエラーが0件 |
| `1` | 1件以上の処理・PDF比較失敗、レポート更新失敗、結果不整合、または入出力の安全性検査失敗 |
| `2` | コマンド引数が不正 |

終了コードが `1` の場合は、次を確認します。

1. ターミナルのエラー表示
2. PDFレポートの `status` と `error_message`
3. 画像エラーCSVの `error`
4. 画像manifestの `action` と `error`
5. 動画レポートの `status`、`reason`、`error_message`
6. Excelレポートの `status`、`reason`、`images_changed`
6. PDF比較を指定した場合は`pdf-preview.json`（dry-runは`pdf-preview.dry-run.json`）の`status`と`errors`

集計に必要なレポートが現在の入力と一致しない場合、KaruFileは過去の出力から
推測せず、該当値を `unknown` として終了コード `1` を返します。

## 処理される内容

### 画像

JPEG、PNG、TIFF、BMP、GIF、WebP、HEIC、HEIFをJPEGとして出力します。

- standardは長辺1280px・短辺960px以内、quality 72
- compactは長辺1024px・短辺768px以内、quality 60
- 縦横比を維持し、拡大・切り抜きなし
- EXIF Orientationを画素へ適用
- 透過部分を白背景へ合成
- animationと複数ページは先頭フレームだけを使用
- 印刷DPIへ合わせる変換ではない

情報が変わった場合はターミナルへ警告を表示します。警告だけなら終了コードは `0` です。
警告は画像エラーCSVへ保存しません。

### PDF

PDFの特性に応じてPyMuPDFまたはqpdfで候補を作り、検証と削減条件を満たした候補だけを
採用します。候補を採用しない場合や、安全上圧縮しない場合は原本を出力へコピーします。

未許可の図・画像PDFは可逆圧縮もせず原本保護します。文章向けの詳しい分類・検証は
[技術リファレンス](docs/REFERENCE.md#圧縮対象の判定)を参照してください。
PDF個別CLIの`--safe`では文字候補のグレー化を無効にします。写真・文章スキャン・字体統一指定とは併用できません。

明示選択した`photo`では、単純なRGB・グレースケールの8bit JPEGだけを対象にします。
非JPEG、1bit、mask付き、複雑な色空間・色変換を使う画像や、画像参照の同定が曖昧な群は維持します。同じ画像が複数箇所で
使われる場合は最も低い実効DPIを軸ごとに基準とし、指定目標（既定200 DPI）を超える軸だけを
その目標へ縮小します。目標以下の軸は寸法を維持し、両軸に縮小余地のない画像は再圧縮しません。
拡大もしません。写真用DPIの指定は、文章スキャンの300 DPI目標を変更しません。
候補は元PDFの画像を書き換えて作り、ベクター文字や線を維持します。HTMLへの往復変換は行いません。

暗号化、電子署名、フォーム、添付ファイル、修復済みPDFなどは圧縮しません。通常実行では
原本を出力へコピーします。
添付ファイルまたは電子署名の有無を検査できないPDFも、安全側で
`ERROR`として原本復旧を試みます。

非可逆候補を作る場合は元PDFから可逆候補も作り、検証と採用条件を満たす最小の候補を選びます。
同サイズなら可逆候補を優先します。採用条件を満たす候補がなければ原本を採用します。
photoの可逆候補は16 KiB以上かつ2%以上の削減が必要です。文章向けは原本より小さければ採用します。JPEG可逆を指定した場合の同サイズ優先順は
qpdf単独、JPEG baseline、JPEG progressive、非可逆です。JPEG候補は原寸画素と完成PDFの
描画一致を検査しますが、全ビューアーでの互換性やOCR精度を保証するものではありません。
ツール、構造検査、I/Oの失敗は`ERROR`であり、
回復コピーが成功しても成功扱いにしません。300 DPIや写真用DPIは候補作成の目標であり、最終出力の
強制上限ではありません。

変換条件、採用基準、再利用条件、PDF status、全オプションは
[KaruFile技術リファレンス](docs/REFERENCE.md)を参照してください。

### 動画

目的に応じて、次のオプションを選びます。

| やりたいこと | 指定するオプション |
|---|---|
| 動画を圧縮する（音声を残す） | `--preset compact` |
| 音声を消して動画を圧縮する | `--preset compact --video-remove-audio` |
| 従来の厳しい形式判定で圧縮する | `--preset compact --video-safe` |

`--video-safe` を付けない場合、プログレッシブ方式・画素比の情報不足だけでは除外しません。
ただし、すべての動画を変換できるわけではありません。対応条件は以下のとおりです。
元ファイルの保護・危険な保存先の拒否・変換後の検証は、指定にかかわらず有効です。

動画は `--preset compact` のときだけ処理します。MP4、M4V、MKV、WebMのうち、単一映像、
8-bit SDR、音声なしまたはmono/stereo 1本など、対応する構成を変換します。
音声除去指定時は入力音声の本数・channel数を制限しません。

- 1280×720以内、30fps以内。小さい動画は拡大しません
- 寸法上限は表示方向の幅1280px・高さ720pxです。縦1080×1920の動画は404×720になります
- 映像はSVT-AV1
- MP4/M4Vの音声はAAC、MKV/WebMの音声はOpus
- 全decode、duration・stream構成、VMAF、削減量を検証した候補だけ採用
- 通常はprogressive/SAR情報の欠落とVFRを許容し、最大30fpsのCFRへ変換
- HDR、interlace、非正方SAR、字幕、複数映像・音声、chapter等は変換せず原本を出力へコピー（音声除去指定時は下記）

従来の厳格な入力判定を使う場合は `--video-safe` を付けます。progressive、SAR 1:1、
公称fpsと平均fpsの一致が明示された動画だけが対象になります。
通常モードでも、原本保護・危険な保存先の拒否・変換後の検証は常に有効です。

音声を除去して圧縮する場合:

```powershell
uv run --script karufile.py --preset compact --video-remove-audio -i "D:\動画" -o "D:\動画_無音軽量化"
```

`--video-safe` と `--video-remove-audio` は併用でき、どちらもcompact専用です。
音声除去指定時は全音声を除去するため、複数音声・多channel音声も除去対象になります。
圧縮候補が未対応・品質不合格・削減不足なら `ERROR`（終了コード1）とし、音声付き原本の
代替コピーは作りません。既存出力は維持するため、過去の有音ファイルが残る場合があります。
成功はレポートの `ADOPTED` または検証済み無音結果の `SKIPPED_COMPLETE` で確認してください。

FFmpegまたは候補検証が失敗した場合は他ファイルを継続しますが、該当行を `ERROR` として
終了コード `1` を返します。
音声除去を指定していない場合、出力が未作成なら原本の回復コピーを試みる場合がありますが、コピーが成功しても`ERROR`のままです。
ファイルが出力先にあることだけで成功と判断せず、終了コードと動画レポートを確認してください。

## 図で全体を確認する

[KaruFile実行時アーキテクチャ](docs/architecture/karufile-runtime.compact.html)は、利用者から
`karufile.py`、PDF・画像・Excel・動画処理、出力、状態・レポートまでの関係を示す対話型HTMLです。

PowerShellからローカルのブラウザで開く場合:

```powershell
Start-Process .\docs\architecture\karufile-runtime.compact.html
```

静止画は [light](docs/architecture/karufile-runtime.compact.visual-check.1440x900.light.png) と
[dark](docs/architecture/karufile-runtime.compact.visual-check.1440x900.dark.png) を用意しています。

## 対象外と確認済みの制約

KaruFileは、HDR/VFR/interlace/字幕/複数stream等を保持した動画変換、重複削除、
知覚ハッシュ、元ファイル削除、GUIを提供しません。
PDF処理は `pdf-shrink` だけが担当します。

現在確認できている未解決事項:

- 自動取得するqpdf配布ZIPのSHA-256または署名は検証していません。
- PDF表示検証はstandardで72 DPIグレースケール、compactで72 DPI RGBと局所差を使います。
  photoではこれに変更画像の配置領域を300 DPIでタイル比較する検査を追加しますが、細かい文字の
  可読性やOCR精度を保証しません。検査量の上限を超えた非可逆候補も採用しません。
- 処理中の入力はロックしません。KaruFileは起動前と全processor終了後に全対象のidentityと
  SHA-256を照合して変更を失敗として検出しますが、別プロセスによる変更そのものは防止しません。
- 自動テストは小さな合成データが中心です。写真DPIと比較HTMLは実資料5冊で限定検証しました。
  [検証範囲と結果](docs/validation/2026-09-09-photo-preview.md)は、別資料の削減率や細字の可読性を保証しません。
- 動画のsafe時のCFR判定はffprobeのrate比較による入口判定です。通常はVFRをCFRへ変換するためフレームの複製・間引きがあります。既知のHDR metadataは拒否しますが、
  metadataが欠けた動画のSDR性までは証明しません。VMAFは映像だけを評価し、30fps化の
  滑らかさと音声品質は測定しません。
- 動画のVMAF JSONは生成後に64 MiB上限を検査するため、異常なlibvmaf実行中の一時領域消費を
  事前停止できません。
- 完了済み動画の再利用時は、保存したsource/config/tool versionと出力hashを照合しますが、
  full decodeとVMAFを再実行しません。動画stateを手動編集した疑いがある場合は
  `<output>.video-state` を別名へ退避してから再実行してください。

代表的な実データでのPilotを行わずに、スキャン判定、削減率、表示差分の既定値が実際の
文書群に適するとは確認できません。
