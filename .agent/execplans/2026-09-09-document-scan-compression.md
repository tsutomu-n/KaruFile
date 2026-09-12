# スキャン書類の軽量化

この文書はliving documentであり、実行結果に合わせて更新する。2026-09-09: 今回の実装・検証は完了。

## Goal / Acceptance Criteria

利用者が指定したスキャンPDFを、原本を変更せず読みやすさを確認できる別出力へ軽量化する。まず既存text_scan処理を実資料で評価し、大幅削減に必要な追加処理だけを判断する。出力サイズ・採否・原本SHA一致・描画比較で結果を示す。個人資料の内容や原本をリポジトリへ追加しない。

## Scope / Current State

- 対象: PDFコンポーネントの文章スキャン処理と今回のローカル実資料。
- 対象外: 動画、OCR追加、原本削除、公開、commit、既存compact作業の再開。
- Gitは着手時clean。前のstandard実行はunpermitted_imageでPRESERVED_ORIGINAL。
- 実資料は1ページ、1646x2331の8-bit DeviceGray JPEGが1個。文字層・描画パスなし。原本425789 bytes、画像stream424722 bytes。約200 DPIで既にグレー化済み。
- 既存text_scanは明示指定、300 DPI上限、gray JPEG quality92/85/80およびqpdfの独立候補。既存の300 DPI検証を維持する。

## Facts / Inferences / Assumptions / Unknowns

- Facts: 上記構造はPyMuPDFで実物から確認。policy.pyとtext_optimize.pyを確認した。
- Inferences: このPDFでは300 DPI縮小は発生せず、JPEG再圧縮による利益をまず確認できる。
- Assumptions: 任意の画質質問への回答はなく、小さい文字の可読性を優先した。実資料は既にグレーで、目視で文字・罫線中心を確認できたため、原本と通常スキャン出力を保持したうえで二値化を別出力で比較した。
- Unknowns: 別の実資料に対する削減率と薄い筆画への影響は未評価。今回の実資料結果は以下に記録する。

## Options / Decision / Risks

1. 既存text_scanを利用: 新規依存・契約変更なし。最初に評価する。
2. 明示的な書類向け強圧縮を追加: 既存処理が不十分な場合に検討。二値化は薄い文字や印影の欠落リスクがあり、無指定へ適用しない。
3. 全面置換・OCR追加: 今回は不要。

検証を緩めて採用しない。外部送信、原本変更、大きな依存追加が必要なら先に再評価する。

## Checkpoints

### CP-001: 既存レシピの実資料評価

- Status: Complete
- Objective: 現行処理の削減率と見た目を確かめる。
- Dependencies: 現行MANUAL、policy/text_optimize、対象PDF。
- Files or components: PDF processor、ローカルDocumentsの別出力、今回の計画。
- Actions: 指定資料のみtext_scanでdry-run、本実行、候補履歴と描画比較、原本SHAを確認。
- Completion criteria: 終了コード、採否、サイズ、原本一致、見た目を記録する。
- Validation: 実CLI、report.csv、SHA-256、全ページおよび文字部分の描画確認。
- Failure conditions: エラー、保護、品質棄却、削減不足を明確に区別する。
- Recovery: 原本と既存standard出力を保持し、新規出力だけで評価する。

### CP-002: 結果に応じた必要最小限の対応

- Status: Complete
- Objective: 書類スキャンを小さくする要求への実用的な対応を確定する。
- Dependencies: CP-001、利用者の画質方針。
- Files or components: 必要ならPDF実装・テスト・関係文書。
- Actions: 既存機能で十分なら操作方法と実出力を提示。不十分なら明示的処理の設計・実装・検証チェックポイントを追加する。
- Completion criteria: 要求への実結果と残る制約が具体的に説明できる。
- Validation: コード変更時は影響スイートとcompileall、関係文書とdiff-check。実装しない場合は実資料検証を根拠にする。
- Failure conditions: 小型化のための文字欠落、既存保護回避、検査の無効化。
- Recovery: 未検証候補は完成物として採用しない。

### CP-003: 明示的二値化の実装と回帰・実資料検証

- Status: Complete
- Objective: 利用者が白黒書類だけを指定でき、安全な候補選択・結果照合・再実行を維持する。
- Dependencies: CP-001/002の10%削減結果と画像streamの二値化試算。
- Files or components: PDF config/cli/policy/text_optimize/worker/preview、統合CLI、関連テスト、MANUAL/REFERENCE/処理説明/各README/AGENTS。
- Actions: text_scan_bilevel profileとパターン、既存scanと同じ保護・DPI・検証・予算の独立候補を追加。schema5の既存profile/candidate_detailsへ記録し、パターンとレシピをhash化。状態・出力境界の変更や新規依存追加なし。
- Completion criteria: 新規指定だけで二値化候補を作り、未指定・保護・safe・競合・棄却を既存契約通り扱い、実資料を小型化して比較できる。
- Validation: 4コンポーネントの全pytest、compileall、両help、diff-check、実資料dry-run/通常/再開、SHAと画像比較。
- Failure conditions: 許可回避、文字/OCR/リンク/配置喪失、品質閾値変更、原本変更、レポート誤照合。
- Recovery: 個別候補棄却時は既存候補群、ツール/構造/I/O失敗はERRORと原本復旧。出力は別tree。

## Decision Log

- 2026-09-09: 現行text_scanは間接Length（例: `8 0 R`）をint変換してERRORになる実不具合を確認。画像streamを読み込まず参照先整数を読む修正と、独立に構成したscanner型PDFでの再現テストを追加。
- 2026-09-09: 通常スキャンJPEGの最小合格候補は383174 bytes（約10.01%削減）。大幅削減には不十分なため、明示パターン`--pdf-text-scan-bilevel-pattern` / `--text-scan-bilevel-pattern`を追加。別profileにより既存CSV/DB欄で要求を厳密照合でき、重複するbool列やDB migrationを不要にした。
- 2026-09-09: 二値化は閾値220、1-bit DeviceGray/Flate、dither/字形置換なし。既存gray JPEG 92/85/80とqpdfを残し、二値化は同サイズ時の最下位とした。閾値220は薄い画線の保持を優先する一方、輪郭が太くなることを比較で確認。新規依存なし。
- 2026-09-09: 既存scanの全体5%/局所20%、300 DPI検証を緩めずに実資料が合格。灰色面が大きく変わるsynthetic fixtureは二値化候補を棄却することを確認。
- 2026-09-09: テストfixtureの`update_object(..., "4 0 R")`はPyMuPDFに整数4として解釈され、意図した不正参照fixtureにならなかった。非整数辞書へ修正。統合CLIは大小文字を保存して照合時casefoldする既存契約のため、parser段階の小文字化を期待した新規テストを修正した。

## Progress / Discoveries / Validation Evidence

- 2026-09-09: 前回の「画像を含む」という説明はスキャン文書としての利用意図を十分に反映していなかった。明示text_scanを最初に実行する方針。
- 実資料: 原本425789 → 通常scan383174 → 二値化39777 bytes、90.65804894%。元画像1646x2331を維持。二値化採用はADOPTED_LOSSY / adopted_text_scan_bilevel。
- 初回PDF suite: 339 passed, 4 skipped（jpegtran実物テスト4件、KARUFILE_TEST_JPEGTRAN未指定）。追加のOCR/配置テスト後、対象test_protection_text.pyは46 passed。
- 画像64 passed、動画104 passed、統合CLI250 passed。指定4つのcompileall、root help、PDF run help、git diff --checkが成功。
- 実資料の二値化CLI/preview生成、dry-run、dry-run後通常再処理がexit0。通常→通常+previewの再開はFiles to process 0 / skipped 1で出力を再利用。
- 目視: 原本と二値化の全1ページ144 DPI、ヘッダー・印影・金額と下部細字300 DPIをPyMuPDFで描画して確認。輪郭の太さと階調の差はあるが、確認部分に文字/数字/罫線の欠落を認めなかった。Popplerは環境で未検出。HTML生成/manifest照合は実CLIで確認し、ブラウザー操作検証は今回実施していない。
- 実資料や描画はDocuments内の別出力に保存し、リポジトリへ追加しない。原本・比較用コピー・通常スキャン出力を削除しない。
- 最終PDF suiteは343 passed, 4 skipped、29.08秒。4件は手動jpegtran指定なしによる既存実物テストのskip。4スイート合計761 passed, 4 skipped。
- 原本の処理前後SHA一致、完成出力・report・最新previewコピーのSHA一致、最新完成出力の144 DPI描画と目視済みPNGの完全一致を確認。通常scanの全1ページ描画も確認した。
- 最終実資料記録は出力parentのverification.json。最新比較はpdf-preview/20260909T061813Z-60b7c1ab5882/index.html。元の個人資料や描画はGit対象外。

### 実行した最終検証コマンド

リポジトリrootから実行。統合CLIテストだけorchestratorをworking directoryに指定した。

```powershell
uv run --project pdf-shrink python -m pytest -q -rs pdf-shrink/tests
uv run --project media-shrink-tool --extra dev python -m pytest -q media-shrink-tool/tests
uv run --project video-shrink python -m pytest -q video-shrink/tests
# working directory: orchestrator
uv run --with pytest python -m pytest -q
# working directory: repository root
uv run --project pdf-shrink python -m compileall -q pdf-shrink/src pdf-shrink/tests
uv run --project media-shrink-tool python -m compileall -q media-shrink-tool/src media-shrink-tool/tests
uv run --project video-shrink python -m compileall -q video-shrink/src video-shrink/tests
uv run --project pdf-shrink python -m compileall -q karufile.py orchestrator
uv run --script karufile.py --help
uv run --project pdf-shrink pdf-shrink run --help
git diff --check
```

## Outcomes / Remaining Issues

CP-001/002/003完了。既存スキャン停止の修正と明示二値化を実装し、実資料の約91%削減、原本保持、内容・描画検証、回帰検証を完了。commit/pushは行っていない。
残る制約: 他資料の薄い文字・色印影・網掛けの再現性、可読性/OCR精度は保証しない。既に1-bitまたは特殊画像のPDFは既存scan保護に従う。任意jpegtran経路の直接Length前提は今回のscan経路ではなく未変更。アーキテクチャ境界・パスは変更していない。
