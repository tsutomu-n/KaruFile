# 2026-10-08 Git統合・Windows運用反映時の構成図確認

実装の根拠commitは`61871c6c45edc22e280b57dc2c45ed76af3abdcc`。
未commitという表示を収録済みcommitへ更新し、JSONからArchifyで再生成した。
runtime経路・用途・保存契約は変更していない。HTML手編集なし。

- validate/deliver: exit0、showcase9/9、errors/warnings0。
- visual-check: exit0、4viewport overflowなし。最小/最大light/dark4画像を開き、欠け・重なりなし。
- correction_rounds: 0、visual_review: passed。自動receiptのpendingとは区別する。
- JSON SHA-256: `248c91e653d17945bd48b0ab4dacc2c0efd3cd48474cfd0fd442389a11409a74`。
- HTML SHA-256: `7df545de324a9dbd86a151e6aebf2506329424b1c758899c1c30ea1f322bf3ac`、649617 bytes。
- [統合記録](../validation/2026-10-08-web-public-integration/README.md)にGitとprepared runtimeの結果を分けて記録。
- [delivery](karufile-runtime.compact.delivery.json) / [visual-check](karufile-runtime.compact.visual-check.json) /
  [source snapshot](karufile-runtime.compact.worktree.json)を同じ実ファイルへ照合する。

以下は統合前の履歴であり、各SHAと基準HEADは当時の値。

# 2026-10-08 source identity共通化の構成図確認

基準HEADは`79df924a924808b4aa7601d7aa797d15ecfd4dcc`。未コミットの共通化・局所修正を含む。
既存の安全カードへ「画像のSHA/stat共有：file_identity.py」を追記し、現在の根拠日付を更新した。
root→orchestrator→各processor、画像専用CLI/GUI→batch→web-publicの2行と保存契約は維持した。
JSONを正本にArchifyで再生成し、HTMLは手編集していない。旧karufile-runtime.htmlは保全した。

- validate/deliver: `--repo-root . --quality showcase`、exit0、9/9、errors/warnings 0。
- visual-check: exit0。1440×900、1600×1000、1920×1080、2048×1320でoverflowなし。
- 最小/最大のlight/dark計4画像を開き、文字・カード・矢印の欠けや重なりなしを確認した。
- 今回のcorrection_rounds: 0、visual_review: passed。自動receiptのvisualReview: pendingは維持。
- JSON SHA-256: `479acc53faea7a2ddbef71a0d5833c813b21009e71d7ab9ac5d02164092b4654`。
- HTML SHA-256: `ecb0dcd0aca7f19bd9ba3c89d2300f838913fdf3754b0d8fa87b4816aa762ba5`、649623 bytes。
- [delivery](karufile-runtime.compact.delivery.json)、[visual-check](karufile-runtime.compact.visual-check.json)、
  [worktree snapshot](karufile-runtime.compact.worktree.json)を実ファイルのSHAと照合した。
- 今回の画像215件を含むfresh全回帰1454/4と、実写真・NAS未提供の境界は
  [検証記録](../validation/2026-10-08-web-public-pilot/README.md)に記載する。

以下は過去の確認履歴。SHA・基準commit・ファイル数・sidecarへの言及は当時の値。

# 2026-10-07 Web掲載用マスターの構成図確認

基準HEADは`bc88f56a6aadeaa11b0cd6687c45e113ce539547`。未コミットのweb-public実装を含む。
同日再レビュー後のBMP/Exif検査・GUI排他修正でソースSHA snapshotを再取得した。
runtime境界と図のJSON/HTMLは変わらず、図の生成・目視証拠は下記を維持する。
通常のroot CLI→orchestrator→各processorと、画像専用CLI/GUI→batch→公開用変換を別行に配置。
出力先・独立manifest・任意GUI依存の境界をJSONへ反映し、Archifyで生成した。
未コミットファイルへの架空のGitHubリンクは作らず、ローカルSHA snapshotを根拠にした。

- validate/deliver: `--repo-root . --quality showcase`、9/9、errors/warnings 0。
- visual-check: 1440×900、1600×1000、1920×1080、2048×1320でoverflowなし。
- 1440×900と2048×1320のlight/dark計4枚を開き、文字・経路・カードの欠けや重なりなし。
- 修正2回: 最初のnode追加時のはみ出し解消、2行の間隔調整。HTML手編集なし。
- visual_review: passed。自動receiptの`visualReview: pending`は自動判定の境界として維持。
- [delivery](karufile-runtime.compact.delivery.json)、[visual-check](karufile-runtime.compact.visual-check.json)、
  [worktree snapshot](karufile-runtime.compact.worktree.json)に現時点のJSON/HTML SHAを記録。
- [実装の検証記録](../validation/2026-10-07-web-public/README.md)。実写真・NAS・後段サイトは未検証。

以下は過去の確認履歴。SHA・基準commit・ファイル数は当時の値。

# 2026-10-05 監査修正後の構成図確認

基準commitは`f71cf514dd9716eeafdbebc13a762c82d56ebedd`。runtimeは変更せず、
ソースリンクを収録済み実装へ固定し、未commit runtimeを含むという旧説明を修正した。
JSONからArchifyで再生成し、HTMLを直接編集していない。

- validate/deliver: `--repo-root . --quality showcase`、9/9、errors/warnings 0。
- visual-check: 1440×900、1600×1000、1920×1080、2048×1320すべて横・縦overflowなし。
- 1440×900と2048×1320のlight/dark計4枚を開いて確認。ラベル・矢印・下部カードの欠けや重なりなし。
- visual_review: passed。自動receiptの`visualReview: pending`は自動判定の境界として維持する。
- 現在のJSON/HTMLのSHA・基準commitは[delivery](karufile-runtime.compact.delivery.json)、
  74ファイルの取得時点のSHAは[worktree snapshot](karufile-runtime.compact.worktree.json)を参照する。
  [visual-check](karufile-runtime.compact.visual-check.json)も同じHTMLのSHAに一致する。
- 詳しい範囲・コマンド・最終照合は[監査修正の検証記録](../validation/2026-10-05-document-audit/README.md)。

以下は過去の確認履歴であり、記載したSHA・基準commit・ファイル数は当時の値。

# 2026-09-13 単一PDF入力・自動スキャンの確認

基準commitは`78c3e4e183ae26532a680cc2c6a06eab120d5881`、未コミットの実装を含む。
単一PDF入力、自動スキャン、専用出力の説明をJSONで更新し、Archifyで再生成した。
新規raster_scan.pyは基準commitに存在しないため架空のソースリンクを作らず、
[worktree snapshot](karufile-runtime.compact.worktree.json)へ実ファイルのSHAを記録した。

- validate/deliver: --repo-root . --quality showcase、9/9、errors/warnings 0。
- [validation](karufile-runtime.compact.validation.json) / [delivery](karufile-runtime.compact.delivery.json)。
- visual-check: 1440×900、1600×1000、1920×1080、2048×1320でoverflowなし。
- 1440×900と2048×1320のlight/dark計4枚を目視。本文・経路・カードに欠けや重なりなし。
- visual_review: passed。機械receiptのpendingは自動では目視を判定しないため維持。
- 生成前の診断はrepo-root未指定と基準commitにないソース参照。各原因を修正し通過した。

以下は9月10日の履歴であり、当時のSHA・ソース数を現在値として使わない。

# 実行時アーキテクチャの確認記録

2026-09-10、明示選択したExcel画像の処理経路を追加した。
JSONを正本としてArchifyで生成し、既存の`karufile-runtime.compact.html`を更新した。
古い`karufile-runtime.html`は変更していない。

## 根拠と成果物

- 基準commit: `ce7f4bdca6ec36f8ebc8df5c9eee97b5ba426e36`。
- 図は未コミットの実装を含む。図内の既存ソースリンクは基準commitを指し、
  Excelの未コミットファイルを架空のGitHubリンクにしていない。
- 最終のローカルソースと依存設定27ファイルは[worktree snapshot](karufile-runtime.compact.worktree.json)で
  SHA-256を記録した。`grid.py`、中央directoryの事前上限、最終の報告照合を含む実装を照合した。
- [JSON](karufile-runtime.architecture.json)のSHA-256:
  `e315bb8517b03038d7b0a576a0bf4bb83a125b8de084236df5ba88799ff067c6`。
- [HTML](karufile-runtime.compact.html)は663,913 bytes、SHA-256:
  `f44a99449d2e760e94c3d9a2e8e3886b60b51fd540a1ef3a02f13b2e893b7d5e`。

## 検証

使用したArchifyは`C:/Users/tn/.agents/skills/archify/bin/archify.mjs`。
リポジトリrootから以下を実行した。

```powershell
node C:/Users/tn/.agents/skills/archify/bin/archify.mjs validate architecture docs/architecture/karufile-runtime.architecture.json --repo-root . --quality showcase --json
node C:/Users/tn/.agents/skills/archify/bin/archify.mjs deliver architecture docs/architecture/karufile-runtime.architecture.json docs/architecture/karufile-runtime.compact.html --repo-root . --quality showcase --json
node C:/Users/tn/.agents/skills/archify/bin/archify.mjs visual-check docs/architecture/karufile-runtime.compact.html --json
```

validateとdeliverは9/9、errors/warningsは0。最終ソース確定後のvalidate再実行も同じ結果だった。
[visual-check記録](karufile-runtime.compact.visual-check.json)は成功し、
1440×900、1600×1000、1920×1080、2048×1320で横・縦のはみ出しがない。

最小・最大画面のlight/dark計4枚を目視確認した。入力から統合、各処理系、出力・レポートへの
流れを読め、文字・カード・矢印の欠けや重なりはない。Excel経路と順序が判別できる。
調整は2回で、`visual_review: passed`。機械receiptの`visualReview: pending`とは別の目視記録である。

この確認は図の表示と実装上の境界の照合を対象とし、Excelブックの画質や実資料Pilotの検証ではない。

2026-09-10対応拡大追補: Excel nodeの詳細tagへWindows GDIを追記。現行specをvalidate/deliver9/9、errors/warnings0。4画面のcontainmentと最小/最大light/dark4枚を再確認し、文字・経路・カードの欠けなし。既存guideもcheck-guide成功。

2026-09-10固定px追補: Excelカードを長辺800px/JPEG品質72へ更新。validate/deliver9/9、errors/warnings0。
4画面containment成功、最小/最大light/dark計4枚を目視して欠け・重なりなし。上記SHAはこの版。
