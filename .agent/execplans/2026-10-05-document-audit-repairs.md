# 情報資産監査で確定した5群の不整合修正

## Goal / Acceptance Criteria
入門ガイドの再生成で最新説明を失わず、現行の図・生成証拠・状態索引・検証説明が一致する。
runtime、依存関係、秘密情報の除外方針は変更しない。履歴資料の削除・移動は行わない。
当初はcommit/pushを含めなかったが、利用者の追加指示「終了したら、コミット、プッシュ」で
検証完了後のcommit/pushも承認された。

## Current State / Facts
基準は main / f71cf514dd9716eeafdbebc13a762c82d56ebedd。開始時の作業ツリーはclean。
読み取り専用監査後、利用者が「実装」と指示した。対象は監査のUPDATE 5群。
templateとガイドHTMLが1段落で不一致。構成図のdelivery/worktreeは旧版。
画像作業の索引は未コミット表記、PDFの検証説明と画像hash/CLI表に更新漏れがある。

## Decision / Scope
説明は実装・REFERENCEと照合して局所修正。ガイドと構成図は正本から再生成する。
図のソースリンクは基準commitに固定し、現在のローカルSHAをsnapshotに記録する。
以前の数値・判断は日付付き履歴を保持し、過去の検証結果を現在の証拠へ転用しない。
文書だけの変更なのでruntime pytest/compileallは不要。生成・表示・参照・hashを検証する。

## Checkpoints

### CP-001: 正本と状態の修正
- Status: Complete
- Objective: ガイドtemplate、PDF/画像説明、索引を現行状態へ更新。
- Dependencies: なし。
- Files: docs/guide/guide.template.html, MANUAL.md, docs/PDF_PROCESSING.md, docs/image-processing.html, .agent/execplans/README.md。
- Actions: 5群の局所修正。実装・Gitを根拠とする。
- Completion criteria: 生成元に最新画像機能があり、検証方式とhash式が実装と一致する。
- Validation: ソース照合、参照確認、git diff --check。
- Failure conditions: 履歴を現状へ書き換える、未確認の保証を追加する。
- Recovery: 今回の差分だけ局所修正。

### CP-002: 構成図と証拠の整合
- Status: Complete
- Objective: JSON、HTML、delivery、snapshot、reviewの版を一致させる。
- Dependencies: CP-001。
- Files: docs/architecture/karufile-runtime.architecture.json と compact成果物、docs/README.md。
- Actions: Archify validate/deliver/visual-check、ローカルSHA取得、明暗4画像の確認。
- Completion criteria: showcase9/9、errors/warnings0、containment成功、receiptと現物SHA一致。
- Validation: Archifyコマンド、SHA照合、view_image。
- Failure conditions: 検証失敗、改善しない2回の修正、画像目視不可。
- Recovery: 診断対象だけ修正し、未確認は明示する。

### CP-003: ガイド再生成と最終検証
- Status: Complete
- Objective: templateとHTML、build/verify/print証拠を一致させる。
- Dependencies: CP-001/002。
- Files: docs/guide と docs/KARUFILE_GUIDE.html、計画/確認記録。
- Actions: build-guide/check-guide/render-print、PC/狭幅とA4全ページ目視、リンク/JSON/hash検証。
- Completion criteria: オフライン・横overflow・目次/参照・本文境界・SHA確認が成功。
- Validation: 既存のガイド検証コマンド、view_image、git diff --check。
- Failure conditions: 古い説明への逆戻り、表示/印刷欠け、hash不一致。
- Recovery: 正本だけ修正して再生成・再検証。

## Progress / Validation Evidence
2026-10-05 JST: baseline確認、対象正本・生成手順・実装を読取確認。
正本を局所修正。構成図validate/deliver9/9・errors/warnings0、4viewport containment成功。
明暗4画像を目視し、図・ラベル・カードの欠けなし。snapshotは74ファイルの現在SHAを記録。
ガイドbuild/check/render-print成功。5画面幅、目次・リンク・オフライン確認、A4全7ページ境界検査成功。
ガイド変更段落のPC/390px画像4枚とA4全7ページを目視した。
注意事項にも写真PDF・EXIF範囲の旧説明が見つかり、同じtemplateで修正。
初回は段落が次ページへ孤立して8ページになったため、第1節の表の説明を短くして7ページへ戻した。
最終静的検査: Markdown49ファイルのローカル参照233件・アンカー27件に欠落なし。
JSON53件解析成功。template/HTML、build/verify、印刷PDF/pages JSON、図receipt/snapshotのSHAが一致。
runtime/依存/ignore差分なし、git diff --check終了コード0。
詳細は[検証記録](../../docs/validation/2026-10-05-document-audit/README.md)とstatic-checks.json。

## Outcomes
CP-001〜003の修正・検証完了。利用者の追加指示に従い、この差分のcommit/pushへ進む。
Git操作の成否・コミットIDは最終報告で示す。

## Remaining Issues
秘密情報の除外方針は監査の判断保留を維持する。実利用者データPilotはこの文書修正の範囲外。
