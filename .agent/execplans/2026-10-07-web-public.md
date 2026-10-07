# Web掲載用マスター CLI・ローカルGUI

この文書は living document。仕様は `KARUFILE_WEB_PUBLIC_CODEX.md`（2026-10-07）。

## Goal / Acceptance Criteria
担当者が画像専用CLIまたは日本語GUIから選択画像を処理し、原本を保全して、幅1400以内の
sRGB JPEG q90/444 または透過PNGを今回専用のフォルダーから取り出せる。
入力metadataを継承せず、実行結果・警告・失敗を区別する。既存resize/rootの契約を維持する。

## Scope / Current State
- In scope: 専用変換、選択・manifest再利用、CLI、NiceGUI optional extra、Windows起動、テスト、文書・構成図。
- Out of scope: commit/push/PR/公開、クラウド連携、実素材の外部送信、PDF/Excel/動画のGUI。
- Facts: 開始HEAD bc88f56a6aadeaa11b0cd6687c45e113ce539547。未追跡の指示書のみ、追跡変更なし。
  既存 image.py に fingerprint / staged replace、utils.py にpath guardあり。
- Inferences: 通常画像のmetadata/marker契約は公開用と異なるため、変換・検証を専用化する。
- Assumptions: 指示書の用途・設定・実装順は承認済み。再質問せず既存作業ツリーで実装する。
- Unknowns: 実写真の利用許可、実NAS接続、後段サイト環境。未提供なら未検証と記録する。

## Options / Decision
既存preset拡張は長辺/短辺、marker、metadata、再利用契約を壊すため不採用。
専用の不変設定と変換コア、独立JSON manifestを採用。共通path/fingerprint/replaceは既存から再利用。
長くなる場合のみコアとバッチを分割。GUIは構造化結果を使用し処理をスレッドへ分離する。

## Risks / Stop Conditions
誤った色変換、metadata漏出、リンク・途中変更・manifest障害、UI二重実行を重点検証する。
原本/既存成果物を変更する回避策は取らない。外部権限が必要な実環境検証は未実行として残す。

## Checkpoints
### CP-001 変換コア
- Status: Complete
- Objective: 向き、横幅、色、alpha、metadata、入力限度の契約を実画像で検査する。
- Dependencies: 既存の安全helper、lock済みPillow/pillow-heif。
- Files: web_public.py、test_web_public.py。
- Actions: 失敗テスト→専用変換/候補検証→回帰。
- Completion criteria: 指定寸法、ICC対照、metadata、保全、形式/限度テスト成功。
- Validation: 画像pytest、候補再オープン、SHA照合。
- Failure conditions: 禁止metadata、原本変更、誤色/透過採用。
- Recovery: 一時候補のみ破棄、既存成果物保持。

### CP-002 バッチ・CLI
- Status: Complete
- Objective: 選択画像だけを中立名の新runへ出し、再利用とエラーを報告する。
- Dependencies: CP-001。
- Files: web_public batch、cli.py、test_web_public_cli.py。
- Actions: dry-run、選択、安全なmanifest読書き、SHA再利用、実subprocessテスト。
- Completion criteria: 0/1/2、無書込みdry-run、混合失敗、再利用/改変検知が成功。
- Validation: pytest、実CLI。
- Failure conditions: 不正path参照、古い出力混入、manifest障害を成功扱い。
- Recovery: 前manifestと旧run保全。

### CP-003 GUI・Windows起動
- Status: Complete
- Objective: 日本語画面で選択→変換→今回出力を開く。
- Dependencies: CP-002。
- Files: gui.py、extra/lock、cmd、GUI tests。
- Actions: ローカルbind、二重実行防止、スレッド分離、表示/操作検証。
- Completion criteria: 用途/選択一致、進捗/部分失敗表示、起動とCLI依存分離を検証。
- Validation: 自動GUIテスト、ローカルブラウザー確認、Windows日本語/空白path。
- Failure conditions: UI停止、二重実行、外部origin操作、manifest失敗の通常完了。
- Recovery: 原本保全、再実行可能、起動エラーを日本語表示。

### CP-004 回帰・文書・最終確認
- Status: Complete (実環境Pilotは下記の未検証範囲)
- Objective: 操作手順と正確な検証証拠を残す。
- Dependencies: CP-001..003。
- Files: MANUAL、REFERENCE、README、AGENTS、architecture、validation。
- Actions: 必要な全suite/compile/help、構成図生成/visual-check、最終差分確認。
- Completion criteria: 自動検証成功、実環境未検証範囲明記、文書の矛盾解消。
- Validation: 実行コマンドと結果を以下に追記。
- Failure conditions: 回帰、文書と挙動の相違。
- Recovery: 今回の変更を局所修正。無関係な問題は区別する。

## Progress / Discoveries / Decision Log
- 2026-10-07 再レビュー後の修正: BMP V4/V5の色情報見落とし、Exif Interop矛盾、再実行失敗時の件数残存、無制限のプレビューを再現。既存66テストは成功しており対象漏れだった。
- 方針: BMPのbounded ICC読取り/外部参照拒否、Exif照合、共有controllerでプレビュー排他、結果表示初期化、ローカルloggerの段階/例外種別を追加。既存の原本保全・保存構造・依存を維持。
- 2026-10-07: 実装開始。通常resizeの共通helperを変更せず利用する方針。
- 2026-10-07: コア・バッチ・CLI・NiceGUIを分離して実装。既存の画像/PDF等の処理条件は維持。
- 独立レビューでPNGのHDR/破損ICC、manifest最終変更検知、GUI同一エラー再表示を修正し回帰検証。
- 実画面でNiceGUI TableのAPI差、実cmdでLF改行問題を検出・修正。CRLFを属性で固定。
- GUIは大画像6枚の変換中にも再読込みが応答し、同じrunが6件成功で完了することを確認。
- 構成図を通常経路/専用経路の2行へ再構成。JSONから生成し、4枚を目視確認。

## Validation Evidence
- Baseline image suite: 108 passed。
- 最終: image 174 passed、PDF 471 passed/4 skipped、Excel 187 passed、video 113 passed、orchestrator 468 passed。
- 合計1413 passed/4 skipped。compileall全対象、既存/新CLI help、uv lock整合、git diff --check成功。
- Windows日本語/空白path、実ブラウザーの写真/図版/部分失敗/プレビュー/処理中再読込み、HTTP/Socket.IO Origin制限を確認。
- 詳しいコマンド、件数、画面証拠、未検証範囲は[検証記録](../../docs/validation/2026-10-07-web-public/README.md)を参照。

## Outcomes / Remaining Issues
承認済みのCLI/GUI・安全性契約・文書の実装と、利用可能なローカル自動/画面検証を完了。
実写真の画質、実NASのUNC/割当ドライブ/切断、後段AVIF/WebP表示は未実行。
OSフォルダー選択とExplorer起動の手動確認、プロセス強制終了の実機試験も未実行。
これらを合成fixtureやローカルテストで代替済みとは扱わない。commit/push/公開は未実施。
2026-10-07（東京、日本）。

## CP-005 再レビューで判明した色・診断の修正
- Status: Complete
- Objective: BMP/Exifの明示色情報を見落とさず、障害の段階と例外種別を内部診断に残す。
- Dependencies: CP-001/002、再現した2種類の画像。
- Files: web_public.py、web_public_batch.py、test_web_public.py、関連文書。
- Actions: 失敗テスト、bounded BMP header/ICC検査、Exif Interop照合、logger、回帰。
- Completion criteria: 壊れた/未知のBMP色情報とExif矛盾はERROR、妥当なICCは変換、原本・旧出力保持、診断テスト成功。
- Validation: 画像suite、compileall、文書/証拠照合。
- Failure conditions: 誤ったsRGB仮定、外部ICCファイル読取り、既存成果物の破壊。
- Recovery: 今回の局所変更を修正し、既存入力/outputを保持。

## CP-006 GUI再実行・プレビュー制御
- Status: Complete
- Objective: 前回件数を今回の結果と混同せず、大画像プレビューを重複実行しない。
- Dependencies: CP-003。
- Files: gui.py、test_web_public_gui.py、関連文書/検証記録。
- Actions: 成功→失敗表示テスト、共有排他、ボタン状態、閉じたdialogの破棄、GUI検証。
- Completion criteria: 前回件数/容量/出力案内を消去、連打/複数タブでも同時プレビュー1件、例外後に再実行可。
- Validation: 実NiceGUI要素を使うテスト、controller並行試験、画像suite。
- Failure conditions: 状態混在、二重処理、例外後のbusy残存。
- Recovery: controller状態をfinallyで解放、原本は変更しない。

### 修正後の証拠・結果
- 新規14ケースの失敗→成功、追加のキャンセルケースも失敗→成功を確認。
- BMPのvalid ICC実変換、sRGB宣言許可、ICC範囲拒否、v1再利用拒否を対照検査。
- 最終画像196 passed、PDF471 passed/4 skipped、Excel187 passed、動画113 passed、orchestrator468 passed。
  合計1435 passed/4 skipped。全compileall、公開用help、lock、差分検査成功。
- 最終GUIでプレビュー開閉3回、成功→再実行失敗時の古い件数消去、出力ボタン無効、console errors/warnings 0を確認。
- recipe v2へ更新。診断はローカルloggerにstage/typeを記録し、例外本文は含めない。
- 実写真/NAS/後段サイトは引き続き未検証。commit/push/公開は未実施。詳細は検証記録の最新追補を参照。
