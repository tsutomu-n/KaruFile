# KaruFile 正本マニュアル整備

> **状態: 完了済みの履歴資料。** 現行の利用手順は [MANUAL.md](../../MANUAL.md)、文書の役割と
> 現行性は [文書ガイド](../../docs/README.md)を参照してください。

この文書はliving documentである。実装中はProgress、Discoveries、
Decision Log、Validation、Outcomesを継続的に更新する。

## Goal

初めてKaruFileを使う利用者が、原本と出力の扱い、必要環境、実行手順、
結果確認、制約を誤解せずに一つの正本から確認できるようにする。同時に、
AIがリポジトリの事実・文書の正本・検証手順を短い指示から特定できるようにする。

## Acceptance Criteria

- 人間向け正本がリポジトリ直下にあり、READMEの先頭から到達できる。
- 初回準備、dry-run、通常実行、出力場所、終了コード、対象形式、固定値、
  metadata、安全上の制約、対象外、未検証事項を実装どおりに確認できる。
- 数値、固有名詞、コマンド、因果関係、不確実性を実装またはテストで裏付ける。
- AI向け情報は `AGENTS.md` に必要最小限で分離する。
- Archifyで検証した実行時アーキテクチャ図へ、READMEと正本から到達できる。
- 全ドキュメントが用途と現行性で分類され、コードと矛盾する記述が残っていない。
- 完了済み計画と再生成可能な検証物が、現行仕様と混同されない。
- 高校生程度の論理的読解力があれば、専門仕様を先に読まず基本操作と結果確認を完了できる。
- 詳細な数値・status・保存契約は、短い検索用リファレンスから失わず確認できる。
- README群の重複と用語揺れを減らし、各文書の役割を明示する。
- Markdownリンク、記載コマンド、テスト、`git diff --check` が成功する。

## Scope

### In Scope

- 新規の利用者向け正本マニュアル
- リポジトリ直下のREADME
- `pdf-shrink`、`media-shrink-tool`、`orchestrator` のREADME
- AI向けのリポジトリ指示
- Archifyによる実行時アーキテクチャ図と検証証拠
- コードを正とした全ドキュメント監査、文書台帳、履歴資料の整理
- 文書変更を裏付ける検証

### Out of Scope

- CLI、変換条件、保存場所、終了コードなど製品動作の変更
- GUI、インストーラー、配布パッケージの追加
- 実データPilotの実施
- GitHubへのcommitまたはpush

## Current State

利用者向けの基本手順は `MANUAL.md`、数値と保存契約は `docs/REFERENCE.md`、
AI向けの最小指示は `AGENTS.md` へ分離されている。ルートREADMEと3コンポーネントの
READMEは、それぞれ入口と固有契約に限定している。全13 Markdownの役割と現行性は
`docs/README.md` とExecPlan索引から確認できる。

## Facts

- 通常入口はリポジトリ直下の `karufile.py` で、Python 3.13以上を要求する。
- 統合CLIはPDFを先、画像を後に処理し、片方が失敗しても可能な範囲で他方を実行する。
- 統合CLIの既定出力は `<input>_軽量化`、PDF workerは2、画像workerは4である。
- 入力と出力が同一または親子関係の場合は処理前に拒否する。
- PDFの状態DBとレポートは出力フォルダー内ではなく、その親へ書く。
- 画像error CSVは、入力・出力の検査とレポート公開に成功した場合、
  `<output>.image-errors.csv` を現在実行の結果で置き換える。
- dry-runは完成PDF・画像を作らないが、状態とレポートは更新し得る。
- 自動テストは合成fixture中心で、実データPilotは未実施である。

## Inferences

- 人間向け手順と内部コンポーネント仕様を一つのREADMEへ詰め込むより、
  正本マニュアルと短い入口READMEへ分ける方が検索しやすい。
- AI向けの短い作業指示は、Codexがプロジェクト指示として読む `AGENTS.md` が適する。

## Assumptions

- 正本マニュアルのファイル名は、リポジトリ直下で発見しやすい `MANUAL.md` とする。

## Unknowns

- 一般利用者向けの配布方法、インストーラー、リリース版の取得手順は定義されていない。
  この改稿では推測して追加しない。

## Options Considered

1. ルートREADMEだけを長文化する。
2. `MANUAL.md` を正本にし、READMEを短い入口にする。
3. Wikiや外部サイトへ正本を置く。

## Recommended Decision

案2を採用する。リポジトリ内で完結し、リンク切れや外部公開の追加運用を避けながら、
正本と入口の役割を分けられる。外部サイトは現状の範囲と根拠を超えるため採用しない。

## Risks

- 文書だけを更新して実装値と食い違う可能性がある。
- 同じ説明を複数READMEへ残すと、将来の変更で再び不整合になる。
- 出力フォルダーの親に置くPDF状態・レポートを曖昧に書くと、利用者が見失う。

## Stop Conditions

- 現行実装とテストから確定できない情報が手順の成立に不可欠である。
- 文書修正だけでは解消できない製品動作上の重大な矛盾が見つかる。
- 依頼範囲外の配布方式または製品仕様変更が必要になる。

## Checkpoints

### CP-001: 文書の事実を確定する

- Status: Complete
- Objective: 現行文書の各主張をCLI、実装、テストと照合する。
- Dependencies: なし。
- Files or components: 全README、CLI、設定、レポート、関連テスト。
- Actions: Git状態、文書、help、固定値、出力場所、終了コードを確認する。
- Completion criteria: 正本へ記載する事実と未確認事項が区別されている。
- Validation: 実ファイルの読取りとCLI help実行。
- Failure conditions: 必須操作がコードから確定できない。
- Recovery: 未確認事項として記録し、推測で補わない。

### CP-002: 正本と入口を作る

- Status: Complete
- Objective: 人間向け正本と短いREADMEを作る。
- Dependencies: CP-001。
- Files or components: `MANUAL.md`、`README.md`。
- Actions: 安全事項を先に置き、準備から結果確認までを一続きに再構成する。
- Completion criteria: 初めて使う人が正本だけで基本操作と結果確認を完了できる。
- Validation: 記載コマンドと実装値の照合、Markdownリンク検査。
- Failure conditions: 重要事項が別文書を読まないと分からない。
- Recovery: 正本へ必要情報を戻し、READMEは入口に限定する。

### CP-003: AI指示とコンポーネント文書を整理する

- Status: Complete
- Objective: AIと開発者が正本・責務・検証コマンドを短く特定できるようにする。
- Dependencies: CP-002。
- Files or components: `AGENTS.md`、3コンポーネントのREADME。
- Actions: 重複を正本へのリンクへ置換し、固有の契約だけを残す。
- Completion criteria: 各READMEの対象読者と責務が先頭で分かる。
- Validation: 重複、用語、リンクの目視・検索検査。
- Failure conditions: コンポーネント固有の事実が失われる。
- Recovery: 実装で裏付けられる固有情報を該当READMEへ戻す。

### CP-004: 文書と回帰を検証する

- Status: Complete
- Objective: 改稿が事実を変えず、既存動作を壊していないことを確認する。
- Dependencies: CP-002、CP-003。
- Files or components: 全変更ファイル、3テスト群、CLI help。
- Actions: リンク検査、表記検索、test、help、compileall、diff checkを実行する。
- Completion criteria: すべて成功し、差分が文書目的に限定される。
- Validation: コマンドの終了コードとGit差分。
- Failure conditions: リンク切れ、誤記、テスト失敗、意図しない差分。
- Recovery: 問題箇所を修正して該当検査だけでなく関連検査も再実行する。

### CP-005: Archifyで図解導線を作る

- Status: Complete
- Objective: 実装根拠に結び付いたruntime architectureを、正本の入口として提供する。
- Dependencies: CP-001、CP-002、CP-003。
- Files or components: `docs/architecture/`、`README.md`、`MANUAL.md`、`AGENTS.md`。
- Actions: Archifyを導入し、architecture JSONを作成、showcase検証、HTML delivery、
  4画面サイズのvisual-check、light/dark目視を行う。
- Completion criteria: 9/9 checks、エラー0、警告0、overflowなし、目視合格、正本から到達可能。
- Validation: Archifyのvalidate、deliver、visual-check receiptと4枚のcapture。
- Failure conditions: source evidence不一致、検証失敗、overflow、視覚上の重なり、リンク切れ。
- Recovery: 診断された対象だけを修正し、JSONから再生成する。生成HTMLは直接編集しない。

### CP-006: 全ドキュメントをコード基準で分類する

- Status: Complete
- Objective: 現行文書、古い記述、再作成候補、削除・アーカイブ候補を根拠付きで区別する。
- Dependencies: CP-001〜CP-005。
- Files or components: 全Markdown、Archify生成物、CLI、設定、処理実装、テスト。
- Actions: 文書ごとの役割と主張をコード・CLI・テストへ照合し、重複と履歴資料を分類する。
- Completion criteria: 全文書に維持・更新・再作成・履歴・再生成可能の判断が付く。
- Validation: 文書台帳とコード参照の突合。
- Failure conditions: コードから確定できない事項を現行仕様として断定する。
- Recovery: 未確認として台帳へ残し、推測による修正を戻す。

### CP-007: 古い記述と文書ライフサイクルを整える

- Status: Complete
- Objective: 現行利用者・保守者が古い資料を正本と誤認しない状態にする。
- Dependencies: CP-006。
- Files or components: 利用者文書、コンポーネント文書、設計書、ExecPlan、docs索引。
- Actions: 古い記述を修正し、文書台帳を追加し、完了済み計画へ履歴表示を付ける。
- Completion criteria: 既知の矛盾が解消し、正本・補足・履歴・生成物の関係が一義的である。
- Validation: 相対リンク検査、文言検索、差分レビュー。
- Failure conditions: 履歴の事実を現行仕様へ書き換える、または有用な設計根拠を失う。
- Recovery: 履歴資料を保持し、現行性の注記だけを戻す。

### CP-008: 文書体系を最終検証する

- Status: Complete
- Objective: 修正後の文書が実装・CLIと一致し、参照可能であることを確認する。
- Dependencies: CP-007。
- Files or components: 全文書、3 CLI、関連test suite。
- Actions: help、Markdownリンク、差分検査、変更影響に応じた回帰テストを実行する。
- Completion criteria: 必須検証が成功し、残存候補が明記される。
- Validation: コマンド終了コードと検査結果。
- Failure conditions: リンク切れ、コードとの矛盾、回帰失敗。
- Recovery: 失敗した文書変更を局所修正し、同じ検査を再実行する。

### CP-009: 人間向け手順と技術契約を分離する

- Status: Complete
- Objective: 正本を上から実行できる初心者向け手順にし、詳細仕様を検索用文書へ分ける。
- Dependencies: CP-006〜CP-008。
- Files or components: `MANUAL.md`、新規technical reference、`docs/README.md`、`AGENTS.md`。
- Actions: 現行MANUALの全情報を安全、手順、結果確認、技術契約、制約へ分類する。
- Completion criteria: 情報を落とさず、人間向け正本と詳細リファレンスの役割が一義的になる。
- Validation: 旧MANUALと新しい2文書の事実・数値・コマンド対照。
- Failure conditions: 詳細値、因果関係、不確実性が失われる、または重複して食い違う。
- Recovery: 欠落した情報をreferenceへ戻し、MANUALは操作に必要な情報へ限定する。

### CP-010: 正本とAI導線を改稿する

- Status: Complete
- Objective: 初回利用者とAIが、それぞれ必要な情報へ最短で到達できるようにする。
- Dependencies: CP-009。
- Files or components: `MANUAL.md`、`docs/REFERENCE.md`、`README.md`、`AGENTS.md`、文書台帳。
- Actions: MANUALを安全→準備→dry-run→本実行→結果確認の順へ改稿し、AIはreferenceを読むよう更新する。
- Completion criteria: MANUALだけで基本操作でき、referenceだけで固定契約を検索できる。
- Validation: 目視レビュー、見出し・用語・重複検査。
- Failure conditions: 初心者向け説明が技術仕様に埋もれる、またはAI向け情報が曖昧になる。
- Recovery: 人間向け手順をMANUALへ、数値表とstatusをreferenceへ再配置する。

### CP-011: 分割後の情報保持と回帰を検証する

- Status: Complete
- Objective: 文書分割で事実を失わず、コードとリンクが一致することを確認する。
- Dependencies: CP-010。
- Files or components: 全Markdown、3 CLI、関連test suite。
- Actions: 数値・固有名詞・status検索、相対リンク、help、test、compileall、diff checkを実行する。
- Completion criteria: 必須検査が成功し、未検証事項が同じ位置づけで残る。
- Validation: コマンド終了コードと差分レビュー。
- Failure conditions: 情報欠落、リンク切れ、コードとの矛盾、回帰失敗。
- Recovery: 欠落または矛盾箇所を局所修正して再検証する。

### CP-012: コードから製品契約を再抽出する

- Status: Complete
- Objective: 前回の監査結果を前提にせず、現コードの外部契約を再確定する。
- Dependencies: CP-009〜CP-011。
- Files or components: root、orchestrator、PDF、画像のCLI・設定・処理・テスト。
- Actions: 既定値、対象形式、保存先、status、warning、再利用、終了コードをコードから抽出する。
- Completion criteria: 文書照合に使う契約一覧がコードとテストで裏付けられる。
- Validation: ソース読取り、CLI help、テスト期待値。
- Failure conditions: 文書または前回結果を根拠にコード契約を推測する。
- Recovery: 未確定項目を除外し、該当コードとテストを追加確認する。

### CP-013: 全文書を再分類して調整する

- Status: Complete
- Objective: 全文書を維持、更新、再作成、削除・アーカイブ候補へ再分類し、必要な修正を行う。
- Dependencies: CP-012。
- Files or components: 全13 Markdown、Archify生成物、文書索引。
- Actions: コードにない主張、見つけにくい契約、現行仕様に見える履歴を照合して修正する。
- Completion criteria: 各文書の分類と処置が文書ガイドへ反映され、既知の矛盾が0件になる。
- Validation: 文書台帳、全文検索、差分レビュー。
- Failure conditions: 履歴を書き換える、現行文書を不要に複製する、根拠なく削除する。
- Recovery: 有用な履歴を保持し、正本への導線だけを修正する。

### CP-014: ダブルチェック後の回帰を検証する

- Status: Complete
- Objective: 調整後の文書体系とコードの一致を独立した検査で確認する。
- Dependencies: CP-013。
- Files or components: 全文書、3 CLI、3 test suite、compileall、Git差分。
- Actions: 契約照合、リンク、古い文言、help、test、compileall、diff checkを実行する。
- Completion criteria: 全検査が成功し、残す履歴と再生成可能物が明示される。
- Validation: コマンド終了コードと検査結果。
- Failure conditions: 事実欠落、リンク切れ、回帰、意図しないファイル変更。
- Recovery: 問題を局所修正し、関連する全検査を再実行する。

## Progress

- [x] CP-001
- [x] CP-002
- [x] CP-003
- [x] CP-004
- [x] CP-005
- [x] CP-006
- [x] CP-007
- [x] CP-008
- [x] CP-009
- [x] CP-010
- [x] CP-011
- [x] CP-012
- [x] CP-013
- [x] CP-014

## Discoveries

- 統合CLIと個別画像CLIでは、出力省略時の名前がそれぞれ
  `<input>_軽量化` と `<input>_resized` で異なる。
- 統合CLIの `--dry-run` は「書き込みなし」ではなく、完成出力を作らず
  状態・レポートは更新し得る動作である。
- qpdf 12.3.2の自動取得は実装されているが、配布ZIPのSHA-256または署名検証はない。
- 旧PDF READMEはqpdf探索順を `PATH`、明示パス、ローカルキャッシュとしていたが、
  実装は明示パス、`PATH`、ローカルキャッシュの順だった。改稿は実装に合わせた。
- ユーザーの追記により「tt」は不要文字ではなく `tt-a1i/archify` の指定だと確定した。
  先の仮定を撤回し、Archifyによる図解導線を追加した。
- orchestrator設計の「画像サマリー取得失敗時に出力JPEGから概算する」は現コードに存在せず、
  現コードは件数・エラー数・入力集合の不一致を失敗にする。
- root CLIのdry-run helpは「書き込みなし」と表示していたが、実装は完成出力だけを抑止し、
  状態DBとレポートを更新し得る。
- 画像warningはターミナルへ表示するが、`<output>.image-errors.csv` には保存しない。
- 完了済みExecPlanは現在の契約ではないが、再現済みの安全性判断と検証証拠を含む。
  削除せず履歴表示と索引を追加する方が、現行性と証拠保全を両立できる。
- 旧MANUALは基本手順の途中から、出力契約、固定recipe、status、個別CLI、未解決事項まで
  264行に同居し、初回利用者が実行完了までに読む範囲と検索用仕様を区別しにくかった。
- 内容を削らず、MANUALを安全→準備→dry-run→本実行→結果確認へ短縮し、数値・status・
  再利用条件・個別CLIを `docs/REFERENCE.md` へ移すことで、2種類の読者を分離できる。
- PDFを含まない通常実行とPDF dry-runでは、qpdfを探索・実行・自動取得しない。
- 画像error CSVは安全性検査、子プロセス起動、レポート公開の失敗時には更新されず、
  以前のCSVが残り得る。旧文書の「毎回置き換え」は条件不足だった。
- marker付きの完成画像を再利用する条件には、入力サイズ、入力更新時刻、現在recipeに加え、
  出力寸法が現在の上限内であることも含まれる。

## Decision Log

### Decision-001

- Date: 2026-08-16
- Decision: `MANUAL.md` を人間向け正本、`AGENTS.md` をAI向け最小指示にする。
- Rationale: 対象読者の目的が異なり、長文を共用すると重要情報の即時性が落ちる。
- Alternatives: README単独、外部Wiki。
- Consequences: README群は正本への導線と固有契約に絞る。

### Decision-002

- Date: 2026-08-16
- Decision: 操作例はドライブ直下ではなく `D:\作業\...` と `C:\作業\...` を使う。
- Rationale: PDFのレポートと状態DBは出力の親へ置かれるため、保存関係を例だけで確認できる。
- Alternatives: 旧READMEの `D:\資料`、`C:\PDF` を維持する。
- Consequences: 製品仕様を変えず、補助ファイルが作られる場所を明確に示せる。

### Decision-003

- Date: 2026-08-16
- Decision: Archifyの `architecture` 形式で静的な実行時構成図を作り、READMEに静止画、
  正本に対話型HTMLへの導線を置く。
- Rationale: 利用者が処理順と保存先を文章の前に把握でき、JSONとsource evidenceで
  図の事実を検証できる。
- Alternatives: 手書きMermaid、画像だけ、文章だけ。
- Consequences: 生成HTMLは直接編集せず、runtime境界変更時はJSONから再生成する。

### Decision-004

- Date: 2026-08-16
- Decision: `docs/README.md` を文書台帳にし、完了済みExecPlanは移動・削除せず
  履歴バナーと索引で現行文書から分離する。
- Rationale: 利用者の検索導線を短くしながら、実装時の判断と検証証拠を失わないため。
- Alternatives: 完了済み計画を削除する、archiveディレクトリへ一括移動する、区別せず残す。
- Consequences: 現行仕様はコード、テスト、MANUALへ集約し、履歴資料の古い記述は
  当時の記録として保持する。

### Decision-005

- Date: 2026-08-16
- Decision: `MANUAL.md` を人間向けの実行正本、`docs/REFERENCE.md` を検索用の技術契約、
  `AGENTS.md` をAI向け最小指示とする。
- Rationale: 1文書に初心者手順と全固定値を併記すると、重要な実行手順が埋もれるため。
- Alternatives: MANUALをさらに長文化する、技術値を削除する、読者別の導線を作らない。
- Consequences: 利用者はMANUALを上から実行でき、AIと保守者はREFERENCEで正確な値を検索する。

## Validation Evidence

- 変更前 `git status -sb`: `main...origin/main`、作業ツリーはクリーン。
- `karufile.py`、3つのCLI help、設定値、レポート実装、関連テストを確認した。
- PDF tests: 46 passed。
- Image tests: 34 passed。
- Orchestrator tests: 41 passed。合計121 passed。
- `compileall`: PDF、画像、root入口、orchestratorの全対象で成功。
- CLI help: root、PDF、PDF run、画像、画像 resizeの全入口で終了コード0。
- Markdown相対リンク: 13ファイルを検査し、欠落0。
- `git diff --check`: 成功。LFからCRLFへの予告だけで、空白エラーなし。
- 製品動作と依存関係は変更なし。ソースコード変更はrootとPDF CLIのhelp文だけ。
- Archify v2.14.0を `C:\Users\tn\.agents\skills\archify` へ導入した。
- Architecture validate: 9/9 showcase、構成エラー0、警告0。
- Delivery: specification SHA-256
  `a8fb3310bc27b3f127002d2cafebef15ebd954ca66568bb04498203d268844d9`、
  artifact SHA-256 `a5b66d7f2fed1505c24ac4e09afca09198eb49489be7590f534f576b2c6cf654`。
- Source evidence: Git revision `935f7bb05cc628575e314b3bcf4cff8cc4e4840e`、11参照を検証。
- Visual-check: 1440×900、1600×1000、1920×1080、2048×1320でoverflowなし。
- light/darkの最小・最大4枚を目視し、重なり、切れ、過大な下余白なし。
  visual-check後の視覚修正0回。
- コード基準の文書再監査: PDF 46、画像34、orchestrator 41、合計121 tests passed。
- root、PDF、画像の全help入口は終了コード0。修正したdry-runと`--limit`のhelp文を
  parser objectから直接照合して成功。
- PDF、画像、root+orchestratorのcompileall成功。既知の古い文言は検索結果0件。
- MANUALとREFERENCEで、旧正本の数値、status、保存先、固有名詞、不確実性46項目の
  保持を機械検査し、欠落0。
- 正本分割後の再検証もPDF 46、画像34、orchestrator 41、合計121 tests passed。
- ダブルチェックではコードとテストから既定値、qpdf使用条件、レポート失敗経路、
  画像再利用条件を再抽出し、53契約項目の文書保持を検査して欠落0。
- ダブルチェック後もMarkdown 13ファイルの相対リンク欠落0、既知の古い断定は
  文書監査の引用を除いて0、3つのcompileallと8つのCLI helpは終了コード0。
- Archify再生成後も9/9 showcase、構成エラー0、警告0。4画面サイズでoverflowなし、
  light/dark 4枚を目視して修正0回。

## Outcomes

- `MANUAL.md` をユーザー向け正本として新設した。
- `README.md` を正本への入口と最短手順へ整理した。
- `AGENTS.md` にAI向けの正本、責務、不変条件、検証入口を必要最小限で記録した。
- 3コンポーネントのREADMEを固有CLIと契約へ整理し、設計文書から正本へリンクした。
- qpdf探索順の旧文書と実装の不一致を、実装に合わせて解消した。
- Archifyで検証済みのruntime architecture JSON、対話型HTML、visual-check証拠を追加し、
  READMEと正本から図解へ到達できるようにした。
- `docs/README.md` とExecPlan索引を追加し、現行文書、補足、履歴、生成物を分類した。
- orchestrator設計の廃止済みJPEG概算、root dry-run help、画像warningの保存先、
  PDF Pilotの奇数件選択をコードどおりに修正した。
- 完了済みExecPlanへ履歴バナーを付け、削除せず検証証拠として保持した。
- `MANUAL.md` を初心者向け実行正本へ再構成し、詳細契約を
  `docs/REFERENCE.md` へ分離した。
- README、文書台帳、AGENTS.mdから読者別の正本へ到達できるようにした。
- qpdfを使用しないPDFなし・dry-run、画像エラーCSVが更新されない失敗経路、
  完成画像の寸法上限を文書へ反映し、「常に／毎回」と読める条件不足を解消した。
- 全13 Markdownを、現行、更新、作り直し、履歴、再生成可能へ再分類した。
  削除すべき現行文書はなく、完了済みExecPlanは履歴証拠として保持した。

## Remaining Issues

- 実データPilotは未実施であり、今回の文書改稿でも実施済みとはしていない。
- 変更はローカルにあり、commitとpushは実施していない。
