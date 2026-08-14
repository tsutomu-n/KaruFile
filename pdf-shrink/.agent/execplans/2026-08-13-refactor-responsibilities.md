# pdf-shrink 責務分離リファクタリング

この文書は living document である。実装中は Progress、Discoveries、
Decision Log、Validation、Outcomes を継続的に更新する。

## Goal

保守担当者が、CLI、バッチ実行、PDF単体処理、ファイル公開、状態永続化を
独立して変更・検証でき、利用者が従来の `pdf-shrink run` で入力PDFの
ミラー出力、再開、CSVレポートを利用できる状態にする。

## Acceptance Criteria

- CLIは引数解析と終了コードへの変換のみを担当する。
- 入力探索、処理対象選択、並列実行、状態保存、レポート対象選択の境界が
  名前付きの型とモジュールで表現される。
- workerと状態DBの境界で `dict[str, Any]` を使用しない。
- dry-runを実際の採用結果として記録しない。
- 現在の入力集合以外のDBレコードをCSVとサマリーへ混入させない。
- 大文字・小文字を問わず `.pdf` を探索する。
- 入力の処理前スナップショットを保存し、処理後の別内容を処理済みとして
  記録しない。
- 出力更新は同一ディレクトリの一時ファイルから `os.replace` で公開する。
- 白色テキストを不可視として扱うスキャン判定が、PyMuPDF 1.28.2 の
  整数sRGB表現で動作する。
- 全テスト、構文検査、CLIヘルプ、代表的な実行が成功する。

## Scope

### In Scope

- `src/pdf_shrink` の責務分離と型付きデータ境界
- 状態・レポート・dry-run・探索・出力公開の確認済み不具合
- 対応するテストとREADME

### Out of Scope

- 圧縮アルゴリズムと既定の画質・削減率の変更
- SQLiteスキーマの破壊的変更
- qpdf配布物のバージョン更新
- GUI、設定ファイル形式、クラウド連携

## Current State

`cli.py` が入力検証、探索、qpdf準備、再開判定、プロセスプール、障害復旧、
DB保存、レポートまで担当する。`worker.py` は `dict[str, Any]` を返し、
CLIは `worker.transform.copy_original` へ到達している。READMEは空である。

## Facts

- Gitは初期化済みだがコミットがなく、全ファイルが未追跡である。
- 変更前テストは `uv run pytest -q` で8件成功した。
- `report.write_csv` には `state.list_records` の全行が渡される。
- `config_hash` は `dry_run`、PyMuPDFバージョン、qpdfバージョンを含まない。
- CLIはworker完了後に入力SHA-256を再計算してDBへ保存する。
- dry-runのworker結果は `ADOPTED_LOSSLESS` または `ADOPTED_LOSSY` である。
- `_collect_pdfs` は `rglob("*.pdf")` のため `.PDF` を対象にしない。
- PyMuPDF 1.28.2のspan色は黒が `0`、白が `16777215` の整数だが、
  `_is_visible_color` は整数を常に可視と判定する。
- `transform.copy_original` と `adopt_candidate` は出力先へ直接コピーする。
- `state.set_pending`、`state.set_processing`、`state.record_exists`、
  `worker._temp_path_for`、`utils.atomic_replace`、`utils.copy_preserve` は未使用である。
- リポジトリ内に `[アドバイス]` に該当する文書はない。

## Inferences

- 現在の8テストはスモークテスト中心で、再開・レポート分離・dry-runの意味を
  保証していない。
- クラス階層や依存性注入フレームワークを追加するより、型付き値と純粋関数、
  小さなアプリケーションサービスへ分ける方が現規模に適する。
- 状態DBのスキーマを変えずに、照会対象を現在の入力パスへ限定すれば、
  既存DBとの互換性を保ってレポート混在を修正できる。

## Assumptions

- dry-runは出力PDFを生成しないが、状態DBと `report.dry-run.csv` は記録する。
- 圧縮中に入力が変更された場合、処理前SHA-256を記録すれば次回実行で再処理される。
- Python要件 `>=3.13` は維持し、標準ライブラリの `StrEnum` を使用できる。

## Unknowns

- `[アドバイス]` の原文は提示されておらず、案との逐語比較はできない。
- 実データにおけるスキャン判定閾値と72 DPI表示差分閾値の妥当性は、
  このリポジトリの合成PDFだけでは評価できない。
- qpdf自動ダウンロードには配布物ハッシュの固定がなく、供給網の完全性は
  この変更範囲では解消しない。

## Options Considered

1. 現状維持: 変更量はゼロだが、責務集中と確認済みの誤報告を残すため不採用。
2. CLIから関数を数個移動するだけ: 差分は小さいが、`dict[str, Any]` と状態境界の
   不整合が残り、変更理由を型で表現できないため不採用。
3. 型付きモデルと機能別モジュールへ部分置換: 既存CLIとSQLiteを維持しながら、
   誤動作と責務境界を同時に直せるため採用。
4. 全面的なクリーンアーキテクチャ化: 現規模では抽象層とテスト用モックが増え、
   追加費用に対する効果が小さいため不採用。

## Recommended Decision

既存のPyMuPDF、qpdf、SQLite、CLI表面は維持する。`models.py` に処理結果、
`discovery.py` に入力探索、`output.py` に原子的な出力公開、`runner.py` に
ユースケースを配置する。設定をfrozen dataclassへ変更し、PDF検査、変換、
状態保存には必要な設定だけを渡す。

## Risks

- ProcessPoolへ渡す型を変更するため、Windowsのspawnでpickle可能か実行確認が必要。
- 既存DB内の文字列statusをEnumへ変換する際、未知値への互換性を失わない設計が必要。
- 原子的公開の一時ファイルが例外時に残らないことをテストする必要がある。

## Stop Conditions

- 既存CLIを維持するためにSQLiteスキーマの破壊的移行が必要になる。
- 実PDFでのみ判断できる閾値変更が受入条件に不可欠になる。
- qpdfやPyMuPDFの外部障害で、ローカルの代表実行を検証できない。

## Checkpoints

### CP-001: 現状と回帰条件の固定

- Status: Completed
- Objective: 確認済みの責務集中と誤動作をテスト可能な受入条件にする。
- Dependencies: なし
- Files or components: tests、ExecPlan
- Actions: 現状テスト、探索、状態、dry-run、色判定、出力公開のテストを追加する。
- Completion criteria: 追加テストが変更前の問題を特定し、変更後の契約を表す。
- Validation: `uv run pytest -q`
- Failure conditions: 合成PDFで対象経路を再現できない。
- Recovery: テストをより小さい純粋関数の境界へ移す。

### CP-002: 型付き境界と責務分離

- Status: Completed
- Objective: CLIとworkerの過剰な責務・内部依存を除去する。
- Dependencies: CP-001
- Files or components: config、models、discovery、output、runner、cli、worker
- Actions: 型付き設定・結果、探索、出力公開、バッチ実行を分割する。
- Completion criteria: CLIが引数解析とrunner呼出しだけを行い、workerが型付き結果を返す。
- Validation: 単体テスト、Windows ProcessPoolを通るCLIスモークテスト。
- Failure conditions: pickle不能、循環import、CLI互換性喪失。
- Recovery: データ型をトップレベルdataclassへ限定し、依存方向を戻す。

### CP-003: 状態と報告の整合性

- Status: Completed
- Objective: 再開判定とレポートが現在の入力・実行内容を正しく表す。
- Dependencies: CP-002
- Files or components: state、report、runner
- Actions: 現在パス限定照会、処理前snapshot保存、dry-run status、ERROR復旧判定を実装する。
- Completion criteria: 別入力の記録が混在せず、dry-runと実処理を区別できる。
- Validation: 状態・CLIテスト。
- Failure conditions: 既存スキーマで区別不能。
- Recovery: 互換的な列追加を検討するが、破壊的変更は停止条件とする。

### CP-004: 文書化と全体検証

- Status: Completed
- Objective: 開発者が設計境界、実行方法、残るリスクを確認できる。
- Dependencies: CP-001、CP-002、CP-003
- Files or components: README、ExecPlan、全ソース、全テスト
- Actions: README更新、不要コード除去、全テスト、compileall、CLI実行、再評価を行う。
- Completion criteria: 検証が成功し、未解決事項が文書化される。
- Validation: `uv run pytest -q`、`uv run python -m compileall -q src tests`、CLI代表実行。
- Failure conditions: 必須検証が失敗する。
- Recovery: 原因単位で修正し、閾値や検査を緩和しない。

## Progress

- [x] CP-001
- [x] CP-002
- [x] CP-003
- [x] CP-004

## Discoveries

- 2026-08-13: 変更前テスト8件は成功したが、状態と報告の意味を検証していない。
- 2026-08-13: PyMuPDF 1.28.2で白色spanが整数 `16777215` になることを
  ローカル生成PDFで確認した。
- 2026-08-13: 状態DBは出力フォルダーの親で共有されるため、全件照会では
  別入力のレコードがレポートへ混在した。現在の入力パス限定照会で修正した。
- 2026-08-13: workerへ渡すfrozen dataclassはWindowsのProcessPoolで動作し、
  CLIスモークテストを含む全20テストが成功した。

## Decision Log

### Decision-001

- Date: 2026-08-13
- Decision: 全面再設計ではなく、型付きモデルと4つの責務モジュールを追加する。
- Rationale: 現行のCLI表面とSQLiteを維持し、確認済みの不具合を最小の依存追加で直せる。
- Alternatives: 現状維持、関数移動だけ、全面再設計。
- Consequences: 複数ファイルの変更になるが、依存方向とテスト境界が明示される。

### Decision-002

- Date: 2026-08-13
- Decision: dry-run、ツールバージョン、出力先を再開条件ハッシュへ含める。
- Rationale: dry-runを実処理として再利用せず、ツール更新後と出力先変更後に
  古いDBレコードを誤って再利用しないため。
- Alternatives: DB主キーとスキーマの変更、既存ハッシュの維持。
- Consequences: 条件変更後の初回は再処理するが、スキーマ移行は不要である。

### Decision-003

- Date: 2026-08-13
- Decision: 出力公開を候補生成から分離し、同一ディレクトリの一時ファイルから
  `os.replace` する。
- Rationale: コピーまたは採用の途中失敗で既存出力を破損させないため。
- Alternatives: 既存の直接 `copy2`、未使用だったunlink後のreplace。
- Consequences: 一時ファイル作成が1回増えるが、失敗時に既存出力を保持できる。

### Decision-004

- Date: 2026-08-13
- Decision: 現在の入力レコードに `ERROR` があればCLI終了コード1を返す。
- Rationale: CSVを手動確認しなくても自動実行側が失敗を検出できるようにするため。
- Alternatives: 従来どおり常に0、ERROR件数に応じた独自終了コード。
- Consequences: ERRORを含む既存運用では終了コードが0から1へ変わる。

## Validation Evidence

- 変更前: `uv run pytest -q` -> `8 passed in 2.23s`
- 変更前: `uv run python -m compileall -q src tests` -> 成功
- 変更前: `uv run python -m pdf_shrink --help` -> 終了コード0
- 変更後: `uv run pytest -q` -> `20 passed in 2.55s`
- 変更後: `uv run python -m compileall -q src tests` -> 成功
- 変更後: 全Pythonファイルの `ast.parse` -> 成功
- 変更後: `uv run python -m pdf_shrink --help` -> 終了コード0
- 変更後: `uv build` -> sdistとwheelの生成成功
- 変更後: `test_cli_smoke` -> Windows ProcessPool、qpdf圧縮、CSV生成に成功

## Outcomes

- CLIからバッチ処理を `runner.py` へ移し、入力探索、型付きデータ、出力公開を
  それぞれ `discovery.py`、`models.py`、`output.py` へ分離した。
- `RunConfig` と処理結果をdataclass化し、workerと状態DBの `dict[str, Any]` を除去した。
- dry-run status、現在入力だけのレポート、処理前SHA-256の保存、大文字 `.PDF`、
  白色整数sRGB、ERROR復旧判定、出力サイズ不一致の再処理を実装した。
- qpdf指定パスの実行確認とZIP展開時の親ディレクトリ逸脱防止を追加した。
- READMEへ利用方法、status、設計境界、検証方法、優先課題を記録した。

## Remaining Issues

- qpdf配布ZIPのバージョンは固定されているが、SHA-256または署名は検証していない。
- 72 DPIのページ全体平均差分は、局所的な欠落を見逃す可能性がある。
- 処理中の入力ファイルをロックしていない。処理前ハッシュにより次回は再処理するが、
  同時更新自体を防止しない。
- 閾値検証は合成PDF中心であり、代表的な実PDF回帰コーパスは存在しない。
- リポジトリにlint・型検査ツールの設定はなく、この実行環境にもruffとpyrightは
  インストールされていない。構文検査とテストは成功したが、静的型検査は未実施である。
