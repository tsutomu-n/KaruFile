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
-n, --dry-run            完成出力を作らず判定を確認
-v, --verbose            詳細ログを表示
```

並列処理数には1以上の整数を指定します。入力と出力が同一、または互いに親子となる指定は
処理前に拒否します。

処理順序:

1. 入出力、予定出力、状態DB、レポートの保存先を検査
2. PDFを処理
3. 画像を処理
4. 現在実行のレポートと画像サマリーを入力集合へ照合
5. 統合サマリーと終了コードを出力

PDFと画像の片方が失敗しても、可能な範囲でもう片方を実行します。正確な集計値を取得できない
場合は、過去の出力から推測せず `unknown` と表示します。

## 統合CLIの保存先

入力が `D:\作業\資料`、出力が `D:\作業\資料_軽量化` の場合:

| 内容 | 保存先 |
|---|---|
| PDFと画像 | `D:\作業\資料_軽量化\` |
| 通常実行のPDFレポート | `D:\作業\report.csv` |
| dry-runのPDFレポート | `D:\作業\report.dry-run.csv` |
| PDF状態DB | `D:\作業\.pdf-shrink\state.sqlite3` |
| PDF一時ファイル | `D:\作業\.pdf-shrink\temp\` |
| 画像エラーCSV | `D:\作業\資料_軽量化.image-errors.csv` |

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

## 終了コード

| コード | 意味 |
|---:|---|
| `0` | PDFと画像のエラーが0件 |
| `1` | 処理失敗、レポート更新失敗、結果不整合、または安全性検査失敗 |
| `2` | 引数不正 |

子処理の終了コードが `0` でも、現在入力とレポート・サマリーが一致しない場合や、報告された
エラーが1件以上ある場合は、統合CLIも `1` を返します。

## dry-run

- 完成したPDFと画像を作りません。
- PDF処理用の一時PDFを作りません。
- qpdfを探索、実行、自動取得しません。
- PDF状態DBと `report.dry-run.csv`、画像エラーCSVは更新される場合があります。
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

### 固定変換条件

| 項目 | 値 |
|---|---|
| 最大寸法 | 長辺1280px、短辺960px |
| リサイズ | 縦横比維持、拡大・切り抜きなし |
| JPEG | quality 72、4:2:0、optimize、progressive |
| Orientation | EXIF Orientationを画素へ適用 |
| 透過 | 白背景へ合成 |
| animation・複数ページ | 先頭フレームだけを使用し、ターミナルへ警告を表示 |

### JPEG候補の採用と再利用

上限内で、Orientationの画素適用が不要なJPEGは、再エンコード候補が32 KiB以上かつ
10%以上小さくなる場合だけ候補を採用します。それ以外は入力JPEGを出力へコピーします。

非JPEG、上限を超えるJPEG、Orientationの画素適用が必要なJPEGは変換対象です。非JPEGでは
出力が入力より大きい場合があり、`OUTPUT_LARGER_THAN_SOURCE` を表示します。

KaruFileが生成したJPEGには、小文字の識別情報 `karufile:image-v1` と入力スナップショットを
保存します。

- この識別情報を持つ入力は、旧変換条件で生成された場合も再エンコードしません。
- 同じ入力ファイルサイズ・更新時刻と現在の変換条件に一致し、寸法が現在の上限内にある
  完成済み出力は再利用します。
- コピー済みJPEGを再利用する場合は、ファイルサイズ・更新時刻に加えてbyte列の一致も確認します。

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

- 256 KiB未満のPDFは圧縮せず、通常実行では原本をコピーします。
- 暗号化、電子署名、フォーム、添付ファイル、修復済みPDFなどは圧縮しません。
- ページ内で最大の画像配置がページ面積の80%以上、実効解像度が450 DPI超、
  可視テキストが20文字以下のページをスキャンページと判定します。
- 実効解像度は、画像のpixel寸法と表示bboxから90度回転も考慮して求めます。
- 可視文字数はtexttraceを優先し、非表示または透明なspanだけを除外します。
  白色だけでは不可視扱いしません。
- 全ページの80%以上がスキャンページの場合、300 DPI、quality 92の非可逆候補を作ります。
- それ以外はqpdfの可逆候補を作ります。

### 候補の検証

- qpdfの構造検査
- ページ数の一致
- NFC正規化後の抽出テキストの一致
- 72 DPIグレースケール表示の平均絶対差が5%以下

### 採用条件

| 候補 | 最小削減量 | 最小削減率 |
|---|---:|---:|
| 可逆 | 64 KiB | 2% |
| 非可逆 | 256 KiB | 5% |

候補を採用しない場合は原本を出力へコピーします。出力は同じディレクトリの一時ファイルへ
書いて検証してから `os.replace()` で公開します。

### 状態DBと再処理

状態DBには、対象を決めた時点の入力SHA-256を保存します。処理中に入力が変わった場合は、
新しい内容を誤って処理済みと記録せず、次回に再処理します。ただし、処理中の入力自体は
ロックしません。

### PDFレポートのstatus

| status | 意味 |
|---|---|
| `ADOPTED_LOSSLESS` | 可逆圧縮候補を採用 |
| `ADOPTED_LOSSY` | 非可逆圧縮候補を採用 |
| `UNCHANGED` | 候補の削減量が不足したため原本を採用 |
| `SKIPPED_SMALL` | 256 KiB未満のため原本を採用 |
| `SKIPPED_ENCRYPTED` | 暗号化PDFのため原本を採用 |
| `SKIPPED_SIGNED` | 電子署名を含むため原本を採用 |
| `SKIPPED_COMPLEX` | フォーム、添付ファイル、修復済みなどのため原本を採用 |
| `DRY_RUN_LOSSLESS` | dry-runで可逆処理を選択予定 |
| `DRY_RUN_LOSSY` | dry-runで非可逆処理を選択予定 |
| `ERROR` | 処理に失敗。可能な場合は原本を復旧コピー |

PDFレポートの列:

```text
source_path,source_size,output_size,saved_bytes,saved_percent,mode,status,page_count,scan_page_ratio,error_message
```

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
-v, --verbose         詳細ログ
```

Nが奇数の場合、`--limit` は固定seedのランダム側を1件多く選びます。

## 画像個別CLI

個別画像CLIの出力省略時の既定値は `<input>_resized` です。統合CLIとPDF個別CLIの
`<input>_軽量化` とは異なります。

```text
-i, --input PATH      入力フォルダー。必須
-o, --output PATH     省略時は <input>_resized
-n, --dry-run         画像出力を作らず、画像エラーCSVを更新
-j, --workers N       既定値4、最小値1
-v, --verbose         詳細ログ
```

個別CLIの実行例と開発者向け情報:

- [pdf-shrink](../pdf-shrink/README.md)
- [media-shrink-tool](../media-shrink-tool/README.md)
- [orchestrator](../orchestrator/README.md)

## 対象外と確認済みの制約

KaruFile v1の対象外:

- 動画圧縮
- 重複削除
- 知覚ハッシュ
- 元ファイル削除
- GUI

確認済みの未解決事項:

1. qpdf配布ZIPの真正性
   - バージョンと展開先は固定・検査しますが、SHA-256または署名は検証しません。
2. PDF表示検証の局所差分
   - 72 DPIのページ全体平均差を使うため、小さな領域だけの欠落を見逃す可能性があります。
3. 入力ファイルの同時更新
   - 処理前スナップショットにより次回実行で変更を検出できますが、処理中の入力をロックしません。
4. 実データでの判定閾値
   - テストは合成データが中心です。今回の実装では実データPilotを実施していません。
