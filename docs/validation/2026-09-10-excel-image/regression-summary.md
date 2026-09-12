# Excel画像対応: 既存コンポーネント回帰検証

2026-09-10、作業ツリーに対して実行。PDF・画像・動画のpytestは独立プロセスで並列実行した。
時間はpytest自身の表示と、PowerShell Stopwatchで測ったuvプロセス全体を区別する。

| 対象 | 結果 | pytest表示時間 | uvコマンド全体 | exit |
|---|---|---|---|---|
| PDF | 433 passed, 4 skipped | 42.09秒 | 42.6776612秒 | 0 |
| 単独画像 | 64 passed | 2.24秒 | 2.6202831秒 | 0 |
| 動画 | 113 passed | 2.65秒 | 3.0973484秒 | 0 |

実行コマンド（リポジトリrootから）:

```powershell
uv run --project pdf-shrink python -m pytest -q pdf-shrink/tests
uv run --project media-shrink-tool --extra dev python -m pytest -q media-shrink-tool/tests
uv run --project video-shrink python -m pytest -q video-shrink/tests
```

完全な標準出力は `pdf-pytest.log`、`image-pytest.log`、`video-pytest.log` に保存した。
各 `*-pytest-result.json` は開始UTC、実コマンド、計測時間、exitを記録する。
PDFの4 skipは、`pdf-shrink/tests/test_lossless_jpeg.py` の実jpegtranテスト4組合せ。
fixtureが要求する `KARUFILE_TEST_JPEGTRAN` が未設定だったため、手動準備jpegtran 3.2.0を使う実テストは実行していない。

各compileallも成功:

| コマンド | uvコマンド全体 | exit |
|---|---|---|
| `uv run --project pdf-shrink python -m compileall -q pdf-shrink/src pdf-shrink/tests` | 0.1185677秒 | 0 |
| `uv run --project media-shrink-tool python -m compileall -q media-shrink-tool/src media-shrink-tool/tests` | 0.1068163秒 | 0 |
| `uv run --project video-shrink python -m compileall -q video-shrink/src video-shrink/tests` | 0.1206726秒 | 0 |

標準出力は各 `*-compile.log`（成功時は空）、開始UTC・時間・exitは各 `*-compile-result.json` に保存した。

orchestratorは本実行の前に、`orchestrator`を作業ディレクトリとして
`uv run --with pytest python -m pytest -q` を実行し、**420 passed in 11.66s、exit 0**。
この結果は同セッションのtool出力で確認した記録であり、後から完全ログを再構成したものではない。
その420件には、新規Excelテスト99件を含む。
`uv run --project pdf-shrink python -m compileall -q karufile.py orchestrator` と
`uv run --project excel-shrink python -m compileall -q excel-shrink/src excel-shrink/tests` も別途exit 0で確認済み。

## 実root CLIの合成スモーク

`root-smoke.py` はリポジトリrootから次で再実行できる。
入力ブックと出力は毎回OSの一時ディレクトリに作成する。

```powershell
uv run --project excel-shrink python docs/validation/2026-09-10-excel-image/root-smoke.py
```

保存した証拠は `root-smoke-summary.json` と次の4ログ。

- `root-normal.log`: 通常CLI。JPEG/PNG 1200×900を220×165へ縮小、小画像は原本コピー。exit 0。
- `root-dry-run.log`: 150 DPIのdry-run。通常レポートと完成ブックを変更せず、候補生成なし。exit 0。
- `root-compact-rerun.log`: compactで再処理。画像レシピは通常と共通、原本SHA一致。exit 0。
- `root-errors-and-preservation.log`: 壊れたZIPはERRORで既存出力を維持し、独立したOLE形式入力は原本コピー。想定通りexit 1。

同じスクリプト内で、原本SHA、すべての非変更ZIP partの展開後bytes一致、変更part集合、
画像寸法、dry-run前後の完成出力と通常レポートのSHA一致をassertした。

| 合成ブック | 元サイズ | 通常出力 | status |
|---|---|---|---|
| `good/jpeg.xlsx` | 282,496 B | 11,030 B | ADOPTED_LOSSY |
| `good/png.xlsx` | 537,353 B | 36,228 B | ADOPTED_LOSSY |
| `good/small.xlsx` | 3,564 B | 3,564 B | PRESERVED_ORIGINAL |

ノイズ画像のファイルサイズの固定値は、再実行の合格条件に含めていない。
ログ・JSON内の絶対パスは、この検証で生成した一時入力と出力を指す。
入力画像やxlsxのバイナリは保存対象に含めていない。
これは合成fixtureによる実CLI検証であり、実業務資料のPilotやExcelでの表示・印刷確認ではない。

## 中央ディレクトリ事前検証の追加後

Rootの独立ZIP検証とExcel processorの両方に、`ZipFile`生成前の中央ディレクトリ検証を追加した。
EOCDの申告値だけでなく、最大4 MiBを読み取って中央レコードの実entry数を数え、4096件上限と
申告値との一致を確認する。ZIP64 locatorも明示的に拒否する。
正当なZIPコメントにEOCD署名が含まれ、PythonのZIP readerが別の終端レコードを選ぶ場合は、
processorはブック全体を原本保護する。壊れた中央レコードや偽の件数はERRORとする。

追加後の全suite:

- orchestrator: **431 passed in 11.48s、exit 0**（新規Excelテスト110件を含む）。
- excel-shrink: **138 passed in 8.30s、exit 0**。
- Excel/root/orchestratorのcompileall、対象差分の`git diff --check`: exit 0。

完全ログと計測JSONは `orchestrator-directory-guard.log` / `orchestrator-directory-guard-result.json` と
`excel-directory-guard.log` / `excel-directory-guard-result.json` に保存した。
実rootスモークも再実行し、通常・dry-run・compactがexit 0、エラー混在が想定通りexit 1。
前述の寸法・サイズ・原本SHA保護・非変更part一致のassertはすべて成功した。
この再実行のsummaryと4ログは `final-root-*` に保存した。
最終suiteの終了は06:50:31 UTCより前で、スモークの通常処理開始は06:50:49 UTC。
以前の `root-smoke-summary.json` と4ログは、native Excel検証からの参照を保つため変更していない。
