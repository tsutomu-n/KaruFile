# Web掲載用マスター Pilot・source identity最小共通化

この文書はliving document。実装、検証、利用できない実環境を区別して更新する。

## Goal / Acceptance Criteria

既存web-publicの変換・CLI/GUI・保存契約を維持し、通常resizeとweb-publicが
画像処理に依存しないsource fingerprintを共有する。旧import名・例外型・monkeypatchの
呼出しを保ち、共通化前後の合成画像比較と全componentのfresh検証を記録する。
許可済み実写真・NAS・下流サイトが未提供の領域は、実行済みと扱わない。

## Scope / Current State

- In scope: baseline、許可されたPilot、再現した局所問題、file_identity.pyへの移設、
  非回帰比較、全suite/compile/help/lock、正本文書・構成図・下流引継ぎ・指定テンプレート報告。
- Out of scope: プラグイン基盤、新用途/recipe、resizeやPDF/Excel/動画の契約変更、
  本番NAS障害注入、実写真の外部送信、別repo編集、commit/push/PR/公開。
- 開始branch: main。HEAD: 79df924a924808b4aa7601d7aa797d15ecfd4dcc。
- 開始worktree: 追跡変更なし、未追跡KaruFile_Codex_Pilot_20261008.zipのみ。
- ZIP SHA256: 008d8d9f2dd3229a3bff1b755dd0585e04c7070a2becf7eeb9d6271fe1bcc341。
- ZIPを既存ファイルを上書きせずrootの同名フォルダーへ展開し、指定順に全手順とテンプレートを読んだ。

## Facts / Inferences / Assumptions / Unknowns

- Facts (開始時): image.pyがSourceChangedError/SourceFingerprintとSHA/stat/change checksを所有し、
  web_public.py/web_public_batch.pyがprivate importしていた。
- Facts (現在): file_identity.pyへ移設し、旧名とhash/capture/change-checkのmonkeypatch経路を維持した。
  独立import・互換・原本検証と全回帰が成功した。
- Inferences: 同じファイル検証が必要になった別用途は、この小さなmoduleを直接使える。新用途自体は未実装。
- Assumptions: 提供された指示の公開APIと最小移設は承認済み。既存checkoutで作業する。
- Unknowns: 許可済み実写真、専用NAS共有/障害試験権限、下流サイトの作業環境は未提供。
  BLOCKED_REAL_PHOTOS / BLOCKED_REAL_NAS / PENDING_DOWNSTREAMとして残し、独立した作業を完了する。

## Options / Decision

1. 現状維持: 画像moduleへのprivate依存が残りG3を満たさない。
2. source SHA/stat/change checksのみ移設: 推奨。utilsのpath guard、既存公開/画像処理を維持。
3. generic recipe/plugin/publish層: 実用途がなく差分と失敗経路を増やすため不採用。

## Risks / Stop Conditions

例外identity、monkeypatch、同size/復元mtime変更、hash中の変更、link/junction、再利用/manifestを重点検証。
原本・既存runを破壊する操作、外部書込み、未提供の実環境試験は行わない。
広い再設計が必要なら共通化だけ保留し、証拠と理由を残す。

## Checkpoints

### CP-001: baseline（パックCP0）
- Status: Complete
- Objective: 変更前のGit/環境/全suite/画像契約を凍結する。
- Dependencies: ZIP/AGENTS/既存計画と正本の確認。
- Files: validation/2026-10-08-web-public-pilot、現行code/tests/lock。
- Actions: 追跡source SHA、環境、全suite、help/lock、合成比較snapshotを取得。
- Completion criteria: fresh commands/exit/countsと比較用snapshotが保存される。
- Validation: ログ、環境JSON、原本/旧run保全チェック。
- Failure conditions: baseline suite失敗、比較入力の不整合。
- Recovery: 原因を調べ、変更前の失敗と今回の変更を分離して記録する。

### CP-002: 実写真/NAS（パックCP1/2）
- Status: Blocked (未提供)
- Objective: 許可済み実写真10〜15枚と安全な専用NASで実証する。
- Dependencies: 素材の使用許可、専用共有、必要な障害試験承認。
- Files: 匿名化PILOT_CASES.csv、指定テンプレート報告。
- Actions: 提供時のみ実行。現在は未実施の理由と引継ぎ項目を記録する。
- Completion criteria: 実環境のPASS、または未提供領域を明示して実行可能作業と分離。
- Validation: 原本SHA、目視、UNC/drive/reuse/recoveryの実機証拠。
- Failure conditions: 素材/共有/承認なし、業務影響の可能性。
- Recovery: 合成fixtureで代替済みと扱わず、提供後の手順を残す。

### CP-003: 再現問題と最小共通化（パックCP3/4）
- Status: Complete
- Objective: 旧契約を保ちfile_identityを2つの既存用途で共有する。
- Dependencies: CP-001。CP-002未提供は独立作業を妨げない。
- Files: file_identity.py、image.py、web_public*.py、test_file_identity.py。
- Actions: 現行実装を移設、旧alias/薄い委譲、公開import、意味のある変更検知/互換試験。
- Completion criteria: Pillow/NiceGUI非依存、旧import/例外/monkeypatch維持、対象テスト成功。
- Validation: 新規テストの失敗→成功、通常resize/web-publicの既存suite。
- Failure conditions: 意味変更、広い改造、未使用抽象化。
- Recovery: 今回の局所差分を修正。無関係な既存処理は変更しない。

### CP-004: 比較・全回帰（パックCP5）
- Status: Complete
- Objective: 共通化前後の出力と全componentの非回帰を確認する。
- Dependencies: CP-003。
- Files: validation証拠、全tests。
- Actions: 同じ合成入力で寸法/画素/色/metadata/manifest/reuse/dry-run/exitを比較、全suiteと必要な検査。
- Completion criteria: 比較差異なし、全検査終了0、skip理由を説明できる。
- Validation: 比較JSON、pytest logs、compile/help/lock/diff。
- Failure conditions: 回帰または原因不明の差異。
- Recovery: 差異を再現して局所修正後、影響範囲を再検証する。

### CP-005: 文書・下流引継ぎ・報告（パックCP6）
- Status: Complete (実サイト受入はPENDING_DOWNSTREAM)
- Objective: 事実と未検証領域を指定形式で引き継ぐ。
- Dependencies: CP-004、正本とarchitectureの責務確認。
- Files: MANUAL、REFERENCE、WEB_PUBLIC、AGENTS、execplan index、architecture、validation。
- Actions: 影響箇所のみ更新、必要ならArchify再生成/visual-check、公式情報確認済み下流手順、報告テンプレート記入。
- Completion criteria: 参照/差分検査成功、原本/無関係変更保持、G1..G4の状態とTokyo時刻を報告。
- Validation: Markdown参照、source snapshot、構成図生成検査とlight/dark目視、最終Git状態。
- Failure conditions: 文書の過大なPASS主張、機密の混入、想定外の変更。
- Recovery: 正本文書と証拠を局所修正する。

## Progress
- [x] CP-001
- [x] CP-002 (未提供の記録を完了。実写真/NAS試験はBLOCKEDのまま)
- [x] CP-003
- [x] CP-004
- [x] CP-005

## Discoveries / Decision Log
- 2026-10-08: 旧private呼出しのmonkeypatch互換が必要。移設時に確認する。
- 2026-10-08: 以前の1435 passed / 4 skippedは履歴。fresh結果として流用しない。
- 2026-10-08: 最初の合成比較でatime-only更新によるreuse拒否を再現。全statの等値比較から
  既存stat署名とSHA比較へ局所修正し、失敗テスト→成功を確認。実NASで発見した問題とは扱わない。
- 2026-10-08: 共通化前後比較は局所atime修正後の同一入力を使用。元HEADのreuseバグを含めて同一という主張はしない。
- 2026-10-08: helperを2つのprivate入口で委譲し旧monkeypatchを保持。汎用plugin/recipe/publish層は不要。
- 2026-10-08: 検証中の長いparameter名によるWindows環境変数上限、親子encoding不一致は検証側を修正。
  helpは開始HEADのsourceを一時領域へ読み出し、同じUTF-8環境でreplayしてbyte照合した。

## Validation Evidence
証拠の保存先: [docs/validation/2026-10-08-web-public-pilot/README.md](../../docs/validation/2026-10-08-web-public-pilot/README.md)。

- fresh baseline: 1435 passed / 0 failed / 4 skipped、画像196件。
- 最終fresh: 1454 passed / 0 failed / 4 skipped、画像215件。PDFの既存合成widget warning1件。
- compileall全5組、CLI help3入口、画像lock check、git diff/参照/SHA検査成功。
- 合成10画像の共通化前後JSON一致、通常resizeの両preset・reuse・dry-run・exit0/1/2・原本/前run不変。
- 独立code review指摘0件。43件の対象試験、全suiteのfresh証拠とは範囲を分けて記録。
- Archify validate/deliver9/9、errors/warnings0、4viewport containment、最小/最大light/dark4枚目視成功。

## Outcomes / Remaining Issues
実行可能なローカル実装・検証・文書・指定報告・下流手順は完了。
実写真/NAS/下流表示/今回のOSフォルダー選択・Explorer・GUI実操作は未実施。
READY_KARUFILE=YES、READY_TO_INTEGRATE=NO、READY_WEBSITE=NO。
提供後は使用許可済み実写真10〜15枚、独立NAS試験領域、実サイトの作業branchで別受入を行う。
原本・既存run・無関係なsource/lockを保全。commit/push/PR/本番公開は未実施。
記録日：2026-10-08（東京）。最終時刻はvalidation/final-boundary.jsonのcaptured_jst。
