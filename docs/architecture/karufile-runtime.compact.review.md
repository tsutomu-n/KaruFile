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
