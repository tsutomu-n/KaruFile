# KaruFile orchestrator

`pdf-shrink`、`media-shrink-tool`、compact時の `video-shrink` を順に呼び、開始・終了表示と
終了コードをまとめる薄い統合CLIです。変換処理や共通DBは持ちません。

通常の利用手順は [KaruFile 利用者マニュアル](../MANUAL.md)を参照し、リポジトリ直下の
`karufile.py` を使ってください。この文書は統合処理の契約と開発用情報を扱います。

## CLI

リポジトリ直下で実行します。

```powershell
uv run --script karufile.py `
  -i "D:\作業\資料" `
  -o "D:\作業\資料_軽量化"
```

| オプション | 意味 |
|---|---|
| `-i`, `--input` | 入力フォルダー。必須 |
| `-o`, `--output` | 出力フォルダー。省略時は `<input>_軽量化` |
| `--pdf-workers` | PDFの並列数。既定値は2、最小値は1 |
| `--image-workers` | 画像の並列数。既定値は4、最小値は1 |
| `--video-workers` | 動画の並列数。既定値は1、最小値は1 |
| `--preset` | `standard` または `compact`。既定値は `standard` |
| `--ffmpeg-path` | compact動画用ffmpeg。省略時はPATH |
| `--ffprobe-path` | compact動画用ffprobe。省略時はPATH |
| `-n`, `--dry-run` | 完成出力を作らず判定を確認 |
| `-v`, `--verbose` | 詳細ログ |

## 実行契約

1. 入出力と、予定されるPDF・画像・動画・レポート・状態DBの保存先を検査します。
2. PDFを処理します。
3. 画像を処理します。
4. compactの場合は動画を処理します。
5. 現在実行で更新されたPDF・画像・動画レポートを入力と実ファイルへ照合します。
6. 全processorの結果を統合して表示します。

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
| PDF、画像、compact動画 | `D:\作業\資料_軽量化\` |
| PDFレポート（PDFがある場合） | `D:\作業\report.csv` |
| dry-run PDFレポート（PDFがある場合） | `D:\作業\report.dry-run.csv` |
| PDF状態DB（PDFがある場合） | `D:\作業\.pdf-shrink\state.sqlite3` |
| 画像エラーCSV | `D:\作業\資料_軽量化.image-errors.csv` |
| 画像manifest | `D:\作業\資料_軽量化.image-manifest.csv` |
| dry-run画像manifest | `D:\作業\資料_軽量化.image-manifest.dry-run.csv` |
| 動画レポート | `D:\作業\資料_軽量化.video-report.csv` |
| dry-run動画レポート | `D:\作業\資料_軽量化.video-report.dry-run.csv` |
| 動画状態・一時領域 | `D:\作業\資料_軽量化.video-state\` |

統合サマリーで正確な値を取得できない場合、その項目は `unknown` と表示します。
dry-runは完成したPDF・画像・動画を作りません。PDF状態と各report等は更新される場合があります。
video dry-runはstate workspace・空DBを初期化する場合がありますが、通常実行の成功recordを
読み書きしません。

画像の統合集計は子プロセスのstdoutではなく、現在実行で原子的に更新された画像manifestを
使います。入力・予定出力path、preset/recipe、size/SHA-256、action、寸法上限、画像エラーCSV
との対応が1件でも一致しなければ、画像集計を `unknown` として終了コード `1` を返します。

## 処理コンポーネントの場所

既定では、リポジトリ直下の `pdf-shrink/`、`media-shrink-tool/`、`video-shrink/` を使います。
開発・テスト時だけ、次の環境変数で差し替えられます。

- `PDF_SHRINK_ROOT`
- `MEDIA_SHRINK_ROOT`
- `VIDEO_SHRINK_ROOT`

## 開発検証

```powershell
Push-Location orchestrator
uv run --with pytest python -m pytest -q
Pop-Location
uv run --script karufile.py --help
```

内部構造と責務境界は [設計文書](docs/shrink_orchestrator_design.md)を参照してください。
