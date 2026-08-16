# KaruFile 文書ガイド

この文書は、KaruFileリポジトリ内の文書の役割と現行性を示します。

## 正本の順序

製品動作を判断するときは、次の順で確認します。

1. 実行コード、設定、テスト、lockfile
2. 利用者向け正本の [MANUAL.md](../MANUAL.md)
3. 数値・status・保存契約の [技術リファレンス](REFERENCE.md)
4. コンポーネント固有のREADMEと内部設計書
5. Archifyの構成図
6. 完了済みExecPlan

文書とコードが矛盾する場合はコードとテストを正とし、影響する文書を同じ変更で更新します。
ExecPlanは当時の判断と検証を残す履歴であり、現行仕様の正本ではありません。

## 現行文書

| 文書 | 用途 | 更新する契機 |
|---|---|---|
| [利用者マニュアル](../MANUAL.md) | 利用者向けの基本手順、安全条件、結果確認 | CLI、保存先、終了コード、対応形式の変更 |
| [ルートREADME](../README.md) | リポジトリの入口と最短手順 | 正本や主要入口の変更 |
| [技術リファレンス](REFERENCE.md) | 数値、status、保存先、再利用条件、個別CLI | 製品契約または固定値の変更 |
| [AGENTS.md](../AGENTS.md) | AI・保守者向けの短い作業契約 | 責務境界、正本、検証入口の変更 |
| [pdf-shrink README](../pdf-shrink/README.md) | PDF個別CLIと内部契約 | PDF処理、status、レポート、依存関係の変更 |
| [media-shrink-tool README](../media-shrink-tool/README.md) | 画像個別CLIと内部契約 | 画像recipe、再利用、警告、エラーCSVの変更 |
| [orchestrator README](../orchestrator/README.md) | 統合CLIと保存先 | 実行順序、集計、環境変数の変更 |
| [orchestrator設計](../orchestrator/docs/shrink_orchestrator_design.md) | 内部責務、安全性検査、結果照合 | `orchestrator/shrink_all.py` の境界変更 |
| [文書ガイド](README.md) | 文書の正本順序、現行性、監査結果 | 文書の追加、役割、保存方針の変更 |
| [ExecPlan索引](../.agent/execplans/README.md) | 完了済み計画の状態と導線 | ExecPlanの追加または状態変更 |
| [Architecture JSON](architecture/karufile-runtime.architecture.json) | Archify図の編集可能な正本 | 実行時コンポーネントやデータ経路の変更 |
| [Architecture HTML](architecture/karufile-runtime.html) | 対話型の閲覧用生成物 | Architecture JSONを変更して再生成したとき |

生成HTMLは直接編集しません。Architecture JSONを更新し、Archifyのvalidate、deliver、
visual-checkを実行してから、light/darkの画像を確認します。

## 2026-08-16 コード基準監査

| 分類 | 対象 | 判断と対応 |
|---|---|---|
| 作り直して維持 | 利用者向け正本 | README群に分散していた基本操作を `MANUAL.md` として新設・再構成し、詳細仕様を技術リファレンスへ分離 |
| 新規作成 | 技術リファレンス | 数値、status、再利用条件、個別CLIを検索できる形で集約 |
| 更新して維持 | 各README、AGENTS.md、構成図 | 役割が重ならないよう現行文書として維持 |
| 古い内容を修正 | orchestrator設計 | 廃止済みの出力JPEG概算を削除し、現在のレポート・件数照合へ更新 |
| 古い内容を修正 | `karufile --help` | dry-runを「書き込みなし」とする説明を、完成出力と状態・レポートを区別する説明へ更新 |
| 明確化 | 画像文書 | 警告はターミナル表示であり、画像エラーCSVには保存しないことを明記 |
| 古い内容を修正 | 正本・技術リファレンス・画像README | 画像エラーCSVを「毎回更新」とする断定を改め、検査・起動・公開失敗時は既存CSVが残り得ることを明記 |
| 明確化 | 正本・技術リファレンス・PDF README | qpdfを使用する範囲をPDFを含む通常実行に限定し、PDFなしとdry-runでは使用しないことを明記 |
| 明確化 | 技術リファレンス・画像README | 完成画像の再利用条件へ、現在の画像寸法上限を追加 |
| 用語統一 | Archify構成図 | 「対応画像」を正本と同じ「対応形式の画像」へ更新し、JSONからHTMLと検証画像を再生成 |
| 明確化 | PDF CLI・README | 奇数を含む `--limit N` の選択件数とdry-run statusを実装どおりに記載 |
| 作り直し不要 | コンポーネントREADME | 固有CLIと内部契約に限定されており、局所更新で整合可能 |
| 履歴として保持 | 完了済みExecPlan | 現行仕様として読ませず、判断・検証証拠として保持 |
| 再生成可能 | `*.visual-check.*` | Archify検証用。利用者向け正本ではなく、必要なら再生成できる |

現時点で、内容を失わずに削除すべき現行文書はありません。完了済みExecPlanはアーカイブ候補
ですが、再現済みの安全性判断と検証証拠を含むため保持します。Archifyのvisual-check生成物は
配布対象を絞る場合に削除できますが、READMEまたはマニュアルから参照するlight/dark画像は、
リンクを更新せずに削除できません。

## 履歴資料

完了済み計画の一覧と扱いは [ExecPlan索引](../.agent/execplans/README.md)を参照してください。
履歴本文の `Current State`、`Facts`、検証件数は、その計画を実施した時点の記録です。
