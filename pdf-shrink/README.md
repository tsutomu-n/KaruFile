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
| `--dry-run` | 出力PDFを作らず、判定結果を記録 |
| `--safe` | 非可逆画像縮小を無効化し、qpdfの可逆候補だけを作成 |
| `--limit N` | サイズ上位 `floor(N/2)` 件と、残りから固定seedで選ぶ `N-floor(N/2)` 件のPilot実行。Nが奇数ならランダム側が1件多い |
| `--retry-errors` | 前回 `ERROR` の入力を再処理 |
| `--qpdf-path PATH` | `qpdf.exe` を明示 |
| `-v`, `--verbose` | 詳細ログ |

入力と出力に、同じフォルダーや互いに親子となるフォルダーは指定できません。

## 出力、状態、レポート

入力内の相対フォルダー構造を出力内でも維持します。出力が
`C:\作業\PDF_軽量化` の場合、PDF以外の補助ファイルは次へ保存します。

| 内容 | 保存先 |
|---|---|
| 通常実行のレポート | `C:\作業\report.csv` |
| dry-runのレポート | `C:\作業\report.dry-run.csv` |
| 状態DB | `C:\作業\.pdf-shrink\state.sqlite3` |
| 一時ファイル | `C:\作業\.pdf-shrink\temp\` |

dry-runでも状態DBと `report.dry-run.csv` を更新する場合があります。完成PDFと処理用の
一時PDFは作りません。レポートは状態DB全体ではなく、現在選択した入力だけを対象にします。

状態DBには、対象を決めた時点の入力SHA-256を保存します。処理中に入力が変わった場合は、
新しい内容を誤って処理済みと記録せず、次回に再処理します。ただし、処理中の入力自体は
ロックしません。

## 圧縮対象の判定

- 256 KiB未満のPDFは圧縮せず、通常実行では原本をコピーします。
- 暗号化、電子署名、フォーム、添付ファイル、修復済みPDFなどは圧縮しません。
- ページ内で最大の画像配置がページ面積の80%以上、実効解像度が450 DPI超、
  可視テキストが20文字以下のページをスキャンページと判定します。
- 実効解像度は、画像のpixel寸法と表示bboxから90度回転も考慮して求めます。
- 可視文字数はtexttraceを優先し、非表示または透明なspanだけを除外します。
  白色だけでは不可視扱いしません。
- 全ページの80%以上がスキャンページの場合、300 DPI、quality 92の非可逆候補を作ります。
- `--safe` では常にqpdfの可逆候補だけを作ります。

## 候補の検証と採用

候補は次の方法で検証します。

- qpdfの構造検査
- ページ数の一致
- NFC正規化後の抽出テキストの一致
- 72 DPIグレースケール表示の平均絶対差が5%以下

採用条件:

| 候補 | 最小削減量 | 最小削減率 |
|---|---:|---:|
| 可逆 | 64 KiB | 2% |
| 非可逆 | 256 KiB | 5% |

候補を採用しない場合は原本を出力へコピーします。出力は同じディレクトリの一時ファイルへ
書いて検証してから `os.replace()` で公開します。シンボリックリンク、ジャンクション、ハードリンクによって
入力または別の保存先へ書く可能性がある場合は拒否します。

## レポートのstatus

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

現在選択した入力に `ERROR` が1件以上あれば終了コードは `1`、それ以外は `0` です。
入力・出力検査、qpdf準備、レポート更新の失敗も `1`、不正な数値オプションは `2` です。

レポート列:

```text
source_path,source_size,output_size,saved_bytes,saved_percent,mode,status,page_count,scan_page_ratio,error_message
```

## モジュール境界

| モジュール | 責務 |
|---|---|
| `cli.py` | 引数解析、ログ設定、終了コードへの受け渡し |
| `runner.py` | 一括処理、ProcessPool、状態保存、レポート対象の決定 |
| `models.py` | 入力スナップショット、検査結果、処理結果、status |
| `config.py` | 型付き設定と再開条件ハッシュ |
| `discovery.py` | 入力検証、PDF探索、Pilot選択、SHA-256取得 |
| `worker.py` | 1ファイルの検査、候補生成、検証、採否判断 |
| `inspect_pdf.py` | 安全性検査とスキャン主体判定 |
| `transform.py` | 可逆・非可逆候補の生成 |
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

2. 表示検証の局所差分

   現在の表示検証は全ページの72 DPIグレースケール画素の平均絶対差を使います。
   小さな領域だけの欠落はページ全体の平均で薄まる可能性があります。

3. 入力ファイルの同時更新

   処理前スナップショットにより次回実行で変更を検出できますが、処理中の入力をロックしません。

4. 実データでの判定閾値

   テストは合成PDFが中心です。スキャン判定、削減率、表示差分の既定値を変更する前に、
   代表的な実PDFと失敗例を匿名化した回帰コーパスが必要です。今回の実装では
   実データPilotを実施していません。
