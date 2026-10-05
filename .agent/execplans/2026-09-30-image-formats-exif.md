# EXIF除去とPNG・JPEG・WebP出力

> 2026-10-05追補: この計画の実装・文書・検証資料は`f71cf51`に収録し、origin/mainへpush済み。
> 本文の未コミット・公開なしの記載は2026-09-30時点の履歴を保持する。

## Goal / Acceptance Criteria
ルートCLIと画像CLIで出力形式を選択でき、EXIF除去を指定できる。原本は変更しない。
Orientationを画素に適用後、除去指定時は完成画像にEXIFを残さない。PNG/WebPの透過を保持する。
通常・再実行・dry-run、衝突回避、失敗時の既存出力保持、manifest検証を全形式で成立させる。

## Current State / Facts
開始時点はJPEG固定、EXIF best-effort保持。画像処理とrootに独立した出力計画がある。
画像処理と文書にはcompact最終検証の未コミット変更があるため維持する。

## Assumptions / Scope
単独画像を対象とし、1回の実行でjpeg/png/webpから1形式を選択する。既定jpeg、EXIF保持。
PDF/Excel内部の画像には適用しない。EXIF以外の個人情報除去は保証しない。

## Options / Decision
既存Pillowと安全な公開処理を拡張する。新規依存や別processorは不要。
PNGは可逆圧縮、WebPはpreset品質72/60の非可逆圧縮。両者は透過を保持。
形式変更・EXIF除去指定時は原本コピーの短絡とfallbackを禁止する。
設定をrecipe hashへ結びつけ、旧既定hashは維持する。

## Checkpoints

### CP-001: 画像processor
- Status: Complete
- Objective: 設定・出力計画・encoder・除去・再利用を実装
- Dependencies: なし
- Files: media-shrink-tool/src, tests
- Actions: format/strip-exif設定、安全な候補検証と失敗処理
- Completion criteria: 3形式と除去、透過、Orientation、再利用、失敗テスト成功
- Validation: image pytest
- Failure conditions: 原本漏出、異形式出力、安全契約の後退
- Recovery: 本作業の変更のみ局所修正

### CP-002: root統合
- Status: Complete
- Objective: CLI転送、形式別衝突検査とmanifest recipe照合
- Dependencies: CP-001
- Files: orchestrator/shrink_all.py, tests
- Actions: rootオプションと出力計画更新
- Completion criteria: root実行・dry-run・設定不一致拒否を確認
- Validation: orchestrator pytest、合成画像CLI
- Failure conditions: rootとchildの出力/設定の不一致
- Recovery: 局所修正、既存出力維持

### CP-003: 文書と最終検証
- Status: Complete
- Objective: 利用手順と正確な制約を更新
- Dependencies: CP-001/002
- Files: MANUAL.md, docs/REFERENCE.md, component README, AGENTS.md, 関連図
- Actions: 影響文書更新、全suite・compile・help・diff検査
- Completion criteria: 全必須検証成功、要件ごとの証拠記録
- Validation: AGENTS.mdの検証コマンド
- Failure conditions: 回帰または未検証の要件
- Recovery: 修正後に対象検証を再実行

### CP-004: 依頼されたPNGの2パターンを実フォルダーCLIで確認
- Status: Complete
- Objective: EXIF全除去と従来の保持処理を、既存リサイズのまま利用できることを確認
- Dependencies: CP-001/002/003
- Files: MANUAL.md, docs/validation/2026-09-30-image-formats
- Actions: 既存の未コミット実装を確認して維持し、利用手順を2パターンに明示。再現可能な合成フォルダー検証を追加
- Completion criteria: サブフォルダーの全4画像がPNGとなり、保持・除去・原本不変・再実行・dry-runを検証
- Validation: png-exif-smoke.py、全suite、指定compileall、両CLI help、git diff --check
- Failure conditions: EXIF残存、保持指定の情報喪失、原本変更、dry-runによる完成出力変更
- Recovery: 検証用fixtureまたは対象の局所差分だけを修正し再確認

## Progress / Validation Evidence
全CP完了。画像108、統合468、PDF471、Excel187、動画113 passed（合計1347 passed、PDF4 skipped）。
最終の既定JPEG透過判定の互換性調整後、新機能44 testsを再実行し成功。
全指定compileall、root/画像CLI help、git diff --check成功。
詳細は[検証記録](../../docs/validation/2026-09-30-image-formats/README.md)を参照。

2026-09-30 14:12 JST再検証: 本依頼の開始時点で3形式とEXIF除去の実装は作業ツリーに存在した。
コードと既定互換性・失敗経路を確認し、既存差分を維持した。全suiteを再実行して1347 passed/4 skipped。
PNGのEXIF保持・除去で各4画像を通常・再実行・dry-runの計6回実CLI処理し、原本SHA/mtime、
再実行とdry-runでの出力SHA/mtime、dry-runでの通常manifest不変を確認した。
ユーザー指定の実データは提供されていないため、合成画像のみを使用した。

## Risks / Stop Conditions
EXIF除去はXMP等の全metadata除去ではない。WebP codec非対応環境ではERRORとして扱う。
破壊操作・外部書込みは不要。

## Outcomes / Remaining Issues
両CLIから形式選択とEXIF除去を利用できる。原本変更なし、透過・向き・再利用・失敗経路の検証完了。
合成画像で検証し、実利用者データのPilotは実施していない。EXIF以外の個人情報除去は範囲外。
外部書込み・コミット・公開なし。2026-09-30 12:01 JST。
