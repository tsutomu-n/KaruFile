# WindowsフォントによるPDF置換機能

この文書はliving document。9月9〜10日の1冊試験とは別に、利用者の「実装して」に基づき通常CLIへ組込み、実装・検証を完了した。

## Goal / Acceptance criteria

利用者がroot `--pdf-font-replace-pattern`（PDF単独 `--font-replace-pattern`）で対象を明示すると、Windows搭載の游ゴシックRegularへ統一し、原本を保った別出力と正確な採用/保護/エラー理由を得られる。実ファイル101ページを通常CLIで処理し、dry-run・再開・原本保護・失敗経路・既存全suiteを検証する。

## Current reality / Scope

- Facts: 既存試験は7,436,386→4,270,674 bytes（42.57%減）。元glyphの輪郭/hmtxを加工せず、font subsetと整数PDF W/TJ補正を使った。コピー・検索時の推定空白差（例30fps→30f ps）は既知。実装依頼はこの機能に対する指示で、空白差の完全解消という新しい保証は置かない。
- 開始時のFacts: 通常runtimeは代替フォントを使わなかった。既存未コミット変更はbilevel等なので保存する。typed RunConfig/ProcessResult、atomic出力、SQLite/CSV、root report照合を維持する。
- Assumptions: 字体変更のある処理なので明示patternでのみ許可、preserve優先、他許可の重複はpreflightエラー。safeとは併用不可。既定フォントは游ゴシックRegular、日本語・英語に限定するが全文字/全PDF構造の対応とはしない。
- In Scope: 変換/独立検証/CLI/config hash/state/report/preview表示/文書/自動テスト/1冊実データPilot。
- Out of Scope: GUI、字体選択UI、Windowsfontの同梱/改変/ダウンロード、縦書き/複雑構造/OCR/画像文字の置換、全18冊の追加処理、commit/push。
- 残る限界: 対応構造を限定した。全PDF/全字体には対応せず、字体・太さ・抽出空白の同一性を保証しない。300秒はcooperativeで単一library呼出しにOS強制メモリ/時間上限を設定したものではない。

## Decisions / contracts

明示profile=`font_replace`、classification=`font_replace`、permission=`explicit_font_replace`。preserve/unsupportedは原本コピーでSHA一致。壊れた構造/I/O/tool失敗は復旧コピーに成功してもERROR。欠字や未対応符号化は文書全体保護。正常な小型PDFも候補を試し、検証済みでstrictly smallerだけ採用する。

Windowsfontはインストール済みYuGothR.ttc face0、family/style・fsTypeとSHAを確認。fontToolsとpikepdfを通常依存に加え、インストール済みfontのSHAとrecipeをconfig hashへ含める。字体輪郭・hmtx・権限を維持し、PDF側のWを最寄り整数へ換算、そのWからTJ補正を計算。原1回のTj/TJは1回のTJへ変換してfill/stroke順序を保つ。ActualTextによる本文上書きはしない。

原本由来のqpdf-onlyとfont置換+qpdfの2候補を独立検証し、小さい候補を採用、同サイズなら可逆qpdf優先。置換採用はADOPTED_LOSSY。任意JPEG追加flagは既存textprofile同様、このprofileでは候補を増やさない。dry-runはフォント/構造の読取りだけで、subset/候補/追加外部tool実行をしない。

processing_schema=6。全CSV/DB行にfont_replacement_requested、replacement_font、replacement_font_sha256、text_extraction_changedを加算移行。対象profileだけ要求true/字体名/hash、他はfalse/空。空白差flagは実際のfont候補採用時だけ。rootは値/対象/形式/行間SHAと現在の入力・出力を照合し、古いschemaを受理しない。

Limits確定（RECIPE5）: 200ページ、原本128MiB、256字体、表示文字/全字体mapping各100万、font圧縮32MiB/展開64MiB、本文stream圧縮・展開32MiB/展開本文累積32MiB、画像圧縮32MiB/展開64MiBかつ32MP/個、事前展開累積256MiB。検証はstream圧縮32MiB/展開64MiB、元と候補展開累積256MiB、144DPI/32MPページ/600MP各候補（最大2候補計1.2GMP）。文書共有300秒cooperative。preflight超過は保護、runtime超過は候補棄却。REFERENCEと実codeに同期。

## Checkpoints

### CP-001: 変換と独立検証
- Status: Complete
- Objective: 試験をファイル名固定でない有界な処理へ移す。
- Dependencies: 試験script/Windowsfont/既存型境界。
- Files: font_replace関連module、font_validate.py、単体テスト。
- Actions: 厳密な対応範囲とbounded解凍、glyph/文字/描画順/画像/構造の独立検証。
- Completion: 支持構造を処理でき、欠字/未対応/巨大/改変を正しく拒否するtestが通る。
- Validation: 合成fixtureの成功と失敗ケース、実試験PDF。
- Failure: 不明構造を推測処理、無制限解凍、無検証採用。
- Recovery: 原本保護、候補非公開。

### CP-002: 実行・記録・root統合
- Status: Complete
- Objective: 一般利用者のCLIから実行・再開・監査できる。
- Dependencies: CP-001 API。
- Files: config/cli/worker/runner/models/state/report、orchestrator。
- Actions: pattern境界、候補選択、schema6加算移行、root整合検証、preview説明。
- Completion: dry-run/normal/resume/error/preserve/overlapをsuiteで確認。
- Validation: PDF/orchestrator suite、compile、help。
- Failure: 意図しない字体変更、input上書き、古い結果再利用、成功誤記。
- Recovery: 既定経路保護、ERRORと復旧コピー。

### CP-003: 実データと文書・最終検証
- Status: Complete
- Objective: 通常CLIの実結果と使用方法を納品する。
- Dependencies: CP-001/002。
- Files: MANUAL/REFERENCE/関連README/AGENTS/引継ぎ、検証記録。
- Actions: 同じ101pだけの別入力workspaceでnormal/dry-run/resume、画像確認、全suite、compile、diff-check。
- Completion: 実結果と限界が文書に一致し、必要検証が合格。
- Validation: 元23件/旧出力/旧試験のSHA保持、全processor+orchestrator tests。
- Failure: 既存回帰・Pilot未達・文書矛盾。
- Recovery: 原因修正、未確認を完了扱いしない。

## Progress / Evidence / Outcomes

- 読み取り確認: AGENTS、作業tree、既存pilot/手引き、config/worker/policy/state/report/runner。関連memoryは型境界と再開契約の履歴として参照し、現物を優先した。
- 分担: 変換エンジン、独立validation、orchestrator境界を各担当、rootはPDF側統合と最終確認。
- 依存候補確認: github-stars-oss doctor smoke PASS。catalogでfontTools/pikepdf該当なし、enrichも未登録で不可。既存trialで成功した最小の追加候補として公式README/LICENSEへ切替確認し、fonttools 4.64.0（MIT）、pikepdf 10.13.0.post1（MPL 2.0）を通常依存へ固定。uv lock/sync成功。新しい代替libraryの探索は終了。
- PDF側の候補選択・原本復旧・dry-run・字体未使用時探索省略・schema加算移行を統合テスト15件で確認。既存PDF＋独立validatorの先行検証364 passed/4 skipped、画像64、動画104、orchestrator310 passed。これは途中結果で、最終全suiteを別途残す。
- 通常CLIの初回101p実行は `PRESERVED_ORIGINAL/font_replace_complex_content`。描画/本文を変更しないmarked contentまで事前拒否していた。具体的なArtifact/Span/Pと受動的propertyだけを型・nesting検査して保持するよう修正した。初回を圧縮成功と扱わない。
- font_pipelineの候補開始前・qpdf開始前・check開始前にも共有deadlineを確認し、期限切れで新しい外部toolを開始しない。

- 統合Pilotで追加検出: 原本の非UTF8 PDF NameをUTF-8化していた検証不具合をbyte-exact比較へ修正。さらに1byte ASCII CMapのhex文字case差を誤拒否し、qpdf-onlyへfallbackした。拒否記録を保持し、意味を変えないhex case対応とengine→validatorのWinAnsi統合回帰を追加した。qpdf-only採用を字体置換成功とは記録しない。


## Final outcome (2026-09-10)

- CP-001: 実engine→独立validatorのType0/ASCII統合を含む専用76件を確認。原点0.02pt、glyph/hmtx/fsType、image/描画順、bounded解凍/mapping、保護/ERRORを維持。
- CP-002: root/PDF引数、schema6加算移行、SHA/recipe/library版による再開、preview record照合、typed manifestを実装。PDF/画像/動画の責任境界・出力ツリーは変えていない。
- CP-003: 通常CLIで101p原本7,436,386→4,265,318 bytes、42.642595%減、ADOPTED_LOSSY/adopted_font_replace、79.70秒。qpdf-only7,156,384 bytesも独立検証に合格。再実行は状態/出力不変、dry-runは候補なし/通常出力とreport不変。原本等44件サイズ/SHA不変。
- 最終suite: PDF433 passed/4 skipped、画像64 passed、動画113 passed、orchestrator321 passed。compileall/root・PDF help/diff-check正常。4skipは任意jpegtran実物の環境条件。途中で現れた動画の並行変更を維持し、字体機能の変更とは区別した。
- PDFium追加検証: 全101p144DPI描画成功、非空白41,835文字順序一致、原点最大差0.000030517578125pt。推定空白差11ページを保持。MuPDFでは以前の游ゴシック試験と全101p144DPI画素一致。
- 今回出力の4/12/27/48/49/91/92p代表部分を300DPIで目視。明白な欠字・表枠越え等なし。91/92pは太字が細くなり強調が弱まるためMANUAL/REFERENCEに明記した。全字校正・印刷・全ビューアーの保証ではない。
- 記録: docs/validation/2026-09-10-windows-font-replacement.mdと同名証拠フォルダー、docs/handoffs/2026-09-09-pdf-font-compression.mdへ現在地を反映。既存試験・原本・他18冊出力を維持、commit/push/追加一括処理なし。
