# pdf-shrink

KaruFileのPDF専用処理コンポーネントです。入力フォルダーを再帰的に調べ、PyMuPDFまたはqpdfで
圧縮候補を作ります。候補を検証し、既定の削減条件を満たす場合だけ採用します。
採用しない場合や安全上圧縮しない場合は、原本を出力へコピーします。

通常の利用手順は [KaruFile 利用者マニュアル](../MANUAL.md)を参照し、リポジトリ直下の
`karufile.py` を使ってください。この文書はPDF処理コンポーネントの個別CLIと内部契約を扱います。

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
| `--photo-pattern PATTERN` | 一致するPDFだけphoto profileにする入力相対パターン。反復可 |
| `--photo-dpi DPI` | photoの目標DPI。150〜300の整数、既定200。photo-pattern必須 |
| `--preview` | 原本と実際の完成出力を比べるローカルHTMLを作成。既定OFF、photo-pattern必須 |
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
`--safe`は`--preset compact`および`--photo-pattern`と同時指定できず、
終了コード `2` になります。

写真PDFの閲覧用候補を明示的に選ぶ場合:

```powershell
uv run --project pdf-shrink pdf-shrink run --input "C:\作業\PDF" --output "C:\作業\閲覧用\PDF_軽量化" --photo-pattern "写真/*.pdf" --dry-run
```

パターンは入力相対パスに大文字小文字を無視して照合します。`\`は`/`へ正規化し、`*`は
ディレクトリ区切りにも一致します。空、絶対パス、drive付き、`..`要素を含む指定は拒否します。
一致しないPDFは元のpresetに従います。内容の自動分類や、DPIによるOCR要否判定は行いません。

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
含みます。現行版は`processing_schema=4`を含むため、以前のstateも一度再処理します。
状態DBは`photo_dpi`などの列追加で移行し、既存行は削除しません。
`preview`・`preview_dpis`は通常処理のhashから除外し、比較資料だけの変更では正常PDFを再処理しません。

## 任意の写真比較

```powershell
uv run --project pdf-shrink pdf-shrink run --input "C:\作業\PDF" --output "C:\作業\比較\PDF_軽量化" --photo-pattern "*写真*.pdf" --photo-dpi 200 --preview --preview-dpi 180 --preview-dpi 150
```

`--preview`は通常PDF処理後に、原本と実際の完成出力をローカルHTMLで比較できる資料を作ります。
`--preview-dpi`は重複を除いて降順に揃えた最大5種類です。原本から独立に比較候補を作り、
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

## 圧縮対象の判定

- 256 KiB未満のPDFは圧縮せず、通常実行では原本をコピーします。
- 暗号化、電子署名、フォーム、添付ファイル、修復済みPDFなどは圧縮しません。
  添付ファイルまたは電子署名の有無を検査できない場合も、安全側で `SKIPPED_COMPLEX`
  として原本を採用します。
- ページ内で最大の画像配置がページ面積の80%以上、実効解像度が450 DPI超、
  可視テキストが20文字以下のページをスキャンページと判定し、`scan_page_ratio` に記録します。
  非可逆候補にするかの判定には使いません。
- 実効解像度は、画像のpixel寸法と配置transformのX/Y基底長から軸別に求めます。
  回転・skew・非等方配置と、同じ画像の複数配置を考慮します。
- 可視文字数はtexttraceを優先し、非表示または透明なspanだけを除外します。
  白色だけでは不可視扱いしません。
- 写真用profileを適用しない場合、どちらのプリセットも縮小候補の固定目標は各軸300 DPIです。
- `standard` は、配置サイズから見た画像実効DPIが300を超える画像を300 DPI、
  JPEG quality 92へ縮小した非可逆候補を作ります。
- `compact` は、300 DPI超の画像を300 DPI、JPEG quality 80へ縮小します。
  300 DPI以下の既存DCTDecode JPEGも、pixel寸法を変えずquality 80の再圧縮候補にします。
  ただし、個別画像streamが5%以上小さくならない場合はその画像を書き換えません。
- 実効DPIはpixel寸法と配置transformから軸別に求めます。JPEGのxres/yresメタデータは
  使いません。300 DPI未満の軸は拡大しません。
- 拡大しません。1bit画像とsoft mask付き画像は縮小も再圧縮もしません。
  ベクター文字は残します。
- xrefを持たないinline画像はいずれかの軸が300 DPIを超える場合に安全に縮小できないため、
  standard/compactの非safe実行では `SKIPPED_COMPLEX` として原本を採用します。
  `--safe` の可逆処理は妨げません。photoではinline画像をそのまま残します。
- 可視テキストが多くても、300DPI超の画像があれば非可逆候補を作ります。
- `--safe` では可逆候補だけを作ります。qpdf単独に加え、明示時のみJPEG可逆候補も比較します。

photoでは単純な8bit DeviceRGB/DeviceGrayのDCT JPEGだけを指定DPI・quality 80へ縮小します。
`--photo-dpi`は150〜300の整数で既定200です。明示指定には`--photo-pattern`が必要です。
非JPEG、1bit、Mask/SMask、Decode/DecodeParms、複雑な色空間、画像参照の同定が曖昧な群は
書き換えません。photoで配置の検査処理が失敗した場合は`ERROR`にします。同じxrefの
全配置から軸ごとの最小DPIを求め、目標DPI超の軸を`ceil(元pixel寸法 × 目標DPI / 最小DPI)`へ縮小し、
目標DPI以下の軸は寸法を維持します。どちらも縮まなければ再圧縮せず、拡大もしません。
ベクター文字・線を維持し、PDF→HTML→PDFによる再構成は行いません。

非可逆候補を作る場合は、元PDFから可逆候補も作って比較します。
可逆候補または原本を採用した出力には、入力由来の高DPI画像が残ることがあります。
300 DPIや写真用DPIは検証前候補の目標であり、画質gateを無効化する強制上限ではありません。

## 候補の検証と採用

候補は次の方法で検証します。

- qpdfの構造検査
- ページ数の一致
- NFC正規化後の抽出テキストの一致
- `standard`: 72 DPIグレースケール表示の平均絶対差が5%以下
- `compact`: 72 DPI RGB表示のチャンネル平均絶対差が5%以下で、かつ最大32×32 pixelに
  分けた局所タイルごとのチャンネル平均絶対差が20%以下
- `photo`: compactと同じ72 DPI比較とページgeometry照合に加え、変更画像の各配置領域を
  300 DPI RGBで比較。256×256 pixel単位の描画、最大32×32 pixel局所差20%以下、全体差5%以下
- photoの細部検査は変更配置10,000箇所、累計80,000,000 pixel、120秒が上限。超過候補は不採用

採用条件:

| 候補 | 最小削減量 | 最小削減率 |
|---|---:|---:|
| 可逆 | 16 KiB | 2% |
| 非可逆（standard/compact） | 256 KiB | 5% |
| 非可逆（photo） | 64 KiB | 5% |

最小削減量と率の両方を満たす候補だけを採用します。非可逆候補を作る場合は元PDFから可逆候補も
作り、検証と採用条件を満たす最小サイズを選びます。同サイズなら可逆候補を優先し、採用候補が
なければ原本を出力へコピーします。ツール、構造検査、
I/Oの失敗は回復コピーが成功しても`ERROR`です。出力は同じディレクトリの一時ファイルへ
書いて検証してから `os.replace()` で公開します。シンボリックリンク、ジャンクション、ハードリンクによって
入力または別の保存先へ書く可能性がある場合は拒否します。

## レポートのstatus

`--lossless-jpeg`は原本からbaseline/progressiveの可逆候補を追加し、既存の非可逆候補を無効化しません。
手動準備したlibjpeg-turbo 3.2.0のjpegtranだけを使用し、明示パス→PATHで解決します。
未検出/版不一致は処理開始前エラー。dry-runでは外部toolを実行しません。
単純な8-bit DeviceRGB/DeviceGray DCT画像のstreamだけを変更し、辞書・原寸画素・DQTと
全ページの形状・文字・パス・72/300 DPI RGBの一致を確認します。Mask、Decode、複雑な色空間、inlineは対象外です。
20 MP/32 MiB、128M/100 scans/30秒、文書300秒協調予算を使用します。
同サイズ優先順はqpdf、JPEG baseline、JPEG progressive、非可逆です。
詳細は[任意JPEG可逆の契約](../docs/REFERENCE.md#任意のjpeg可逆候補)を参照してください。

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

現在選択した入力に `ERROR` が1件以上あれば終了コードは `1`、それ以外は `0` です。
入力・出力検査、qpdf準備、レポート更新、比較資料生成の失敗も `1`、不正な数値オプションは `2` です。

レポート列:

```text
source_path,source_size,source_sha256,output_path,output_size,output_sha256,saved_bytes,saved_percent,preset,mode,status,page_count,scan_page_ratio,error_message,profile,decision_reason,candidate_size,candidate_saved_bytes,candidate_saved_percent,images_changed,candidate_details,lossless_jpeg_requested,photo_dpi
```

`profile`はファイルに適用した`standard`・`compact`・`photo`です。`preset`は起動時の値を維持します。
`photo_dpi`はphoto行の要求目標DPIで、それ以外はCSVで空欄、DBで`NULL`です。原本・可逆候補を
採用しても要求値を維持します。統合CLIは旧CSVでの列欠落、不正値、指定不一致を拒否します。
`candidate_*`と`images_changed`は一次候補の診断値です。非可逆候補を試した場合はそれを一次とし、
可逆候補を後から採用しても記録を置き換えません。`candidate_saved_percent`と`saved_percent`は
0.05が5%の割合です。候補未生成のサイズは空欄であり、0 byteとは異なります。

`candidate_details`は`kind`、`size`、`images_changed`、`reason`、`validation_reason`、`selected`を
持つJSON配列です。`kind`は非可逆候補でprofile名、可逆候補で`lossless`、
`jpeg_lossless_baseline`、`jpeg_lossless_progressive`を記録します。
`lossless_jpeg_requested`は全行`true`/`false`で保存し、統合CLIが指定と照合します。
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
| `inspect_pdf.py` | 安全性検査とスキャン主体判定 |
| `transform.py` | 可逆・非可逆候補の生成 |
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

   `compact`は72 DPI RGBの全体・局所差、`photo`は変更配置を300 DPIでも比較します。
   写真中の小さい文字の可読性やOCR精度を保証しません。photoで選んだPDF内のJPEGが
   写真かどうかも自動分類しないため、利用者による原本との比較が必要です。

3. 入力ファイルの同時更新

   処理前スナップショットにより次回実行で変更を検出できますが、処理中の入力をロックしません。

4. 実データでの判定閾値

   テストは合成PDFが中心です。スキャン判定、削減率、表示差分の既定値を変更する前に、
   代表的な実PDFと失敗例を匿名化した回帰コーパスが必要です。写真DPI・比較HTMLの
   [実資料5冊による限定検証](../docs/validation/2026-09-09-photo-preview.md)は、別資料の画質保証ではありません。
