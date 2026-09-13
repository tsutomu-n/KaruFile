# PDFの既定スキャン圧縮と単一ファイル入力

この文書はliving documentである。2026-09-13完了。基準HEADは78c3e4e、変更は未コミット。

## Goal / Acceptance Criteria

今回のスキャンPDFを、手動コピーや個別圧縮許可なしに通常CLIの1コマンドで軽量化する。
入力原本を維持し、別出力へ保存する。文字PDFは既存処理を維持する。
実19ページを直接入力し、既定の出力・再開・dry-runまで確認した。

## Current State / Facts

- 着手時はこの計画書だけが未追跡で、他の作業ツリーはclean。既存compact中断計画は再開していない。
- 元実装はフォルダー入力のみ。画像を含む未指定PDF、text_scan内のclipを原本保護していた。
- 指定19ページの3〜15ページにclipがあり、明示text_scanでも圧縮できなかった。
- 単発ページ画像化の試験は68.77%減だったが、通常CLI機能ではなかった。
- ユーザーはスキャンPDFの自動圧縮を既定化し、文字PDFは維持する方針を選択した。

## Scope / Decision Log

- 自動対象は画像があり、全ページに文字描画/不可視OCR/vector paintがなく、画像とclipのみ。空白混在可。
- 意味のスキャン判別はしない。写真だけのPDFも対象となり、色を失うことをユーザー説明と現行文書へ明記。
- 明示preserve/text/text_scan/bilevel/photo/font_replaceが優先。safeは自動画像化を無効化。
- 原本非変更、出力のパス/identity検査、検証後のos.replace、I/O/tool失敗のERRORを維持。
- root/PDF個別CLIはPDF1冊を直接読み、周辺探索・入力コピーなし。相対名は元ファイル名。
- PDF1冊の出力省略時は`<source-parent>/<source-stem>_軽量化/files/<source-name>`。
  report/state/previewはfilesの親。明示outputおよびフォルダー入力の配置は変更しない。
- 単一PDFでは画像/Excel/動画子CLIを起動しない。PDFの処理責務はpdf-shrinkに置く。
- recipe v3、schema6の分類欄raster_scan/basis automatic_scan_rasterを使用。hash変更で旧成功は再処理。
- Pillowは既存環境にあったpikepdfの依存だが、直接利用するためpyproject/uv.lockへ明記した。
- commit/push、他形式の既定動作、全文字のOCR照合、全PDFの画像化は対象外。

## Checkpoints

### CP-001: 契約確定
- Status: Complete
- Objective: 対象・例外・保存先を確定。
- Dependencies: ユーザー回答。
- Files or components: policy/config、discovery、root、文書。
- Actions: 現行コードを確認し、上記Scopeを選択。
- Completion criteria: 既定適用対象と単一入力時の出力配置を明記。
- Validation: 実装と照合済み。
- Failure conditions: 意味分類や全PDF画像化を無断で導入すること。
- Recovery: 未確定時はdependentな実装を保留。

### CP-002: 実装・契約検証
- Status: Complete
- Objective: 1コマンドで自動圧縮し、既存の文字処理と原本を維持。
- Dependencies: CP-001。
- Files or components: raster_scan、policy、worker、config、discovery、runner、report、preview、orchestratorとテスト。
- Actions: 300 DPIグレーJPEG92候補と原本由来qpdf候補を独立生成。厳密に小さい最小候補のみ採用、同サイズqpdf優先。
- Completion criteria: 通常、dry-run、再開、clip/rotation/crop、メタデータ、失敗経路、原本維持の確認成功。
- Validation: PDF471 passed/4 skipped、orchestrator468 passed。実19ページを通常CLIで圧縮。
- Failure conditions: 欠落、入力変更、別ファイル探索、不一致reportの受理、失敗の成功扱い。
- Recovery: 品質不適合は候補を棄却、既存PDFのエラー/原本コピー契約を維持。

### CP-003: 文書・図・最終確認
- Status: Complete
- Objective: 現行手順と実装の整合。
- Dependencies: CP-002。
- Files or components: MANUAL、REFERENCE、README群、AGENTS、ガイド、architecture、validation。
- Actions: 現行文書を更新、Archifyで図を再生成し、明暗・PC/狭幅・A4を確認。
- Completion criteria: コマンド、結果、検証と限界を実測で報告可能。
- Validation: 下記の全コンポーネントpytest、全compileall、CLI help、diff check、図とガイド確認が成功。
- Failure conditions: 古いSHAや履歴検証を今回の根拠として扱うこと。
- Recovery: 現行receiptと別の目視記録を保持。履歴は履歴と明示。

## Discoveries / Re-evaluation

1. 元のページ寸法へceil済み画像をfitすると端数により細線が再標本化され、局所差分検査で拒否された。
   画像を300 DPIの画素格子に正確に合わせて配置し、余りは元のページboxで切り抜く方式に修正。
2. 局所20%基準では合成の細文字消去を検出できなかったため、基準を10/255へ厳格化した。
   実資料の最終配置は局所最大2.586/255、ページ平均最大0.768/255。消去テストも拒否できた。
3. qpdf候補はページ全体のRGB300 DPI完全一致と構造で検証。画像化候補も全ページ300 DPIで比較。
   任意表示倍率や文字単位の同一性を意味しない。
4. 新規raster_scan.pyは基準commitに存在しない。図のソースリンクは既存policyを示し、
   新規実装はworktree snapshotのローカルSHAで記録。架空GitHubリンクは作らない。

## Validation Evidence

実行したコマンド（root以外のcwdは明記）:

```powershell
uv run --project pdf-shrink python -m pytest -q pdf-shrink/tests
uv run --project media-shrink-tool --extra dev python -m pytest -q media-shrink-tool/tests
uv run --project excel-shrink python -m pytest -q excel-shrink/tests
uv run --project video-shrink python -m pytest -q video-shrink/tests
# cwd=orchestrator
uv run --with pytest python -m pytest -q
# cwd=root
uv run --project pdf-shrink python -m compileall -q pdf-shrink/src pdf-shrink/tests
uv run --project media-shrink-tool python -m compileall -q media-shrink-tool/src media-shrink-tool/tests
uv run --project excel-shrink python -m compileall -q excel-shrink/src excel-shrink/tests
uv run --project video-shrink python -m compileall -q video-shrink/src video-shrink/tests
uv run --project pdf-shrink python -m compileall -q karufile.py orchestrator
uv run --script karufile.py --help
git diff --check
```

- pytest合計1,303 passed、4 skipped。内訳PDF471、root468、画像64、Excel187、動画113。
  PDF合成フォームのpikepdf PageCopyWarningが1件。既存の4 skippedは今回無効化した検査ではない。
- 上記compileall、help、diff checkは成功。
- Archify: runtimeとguide図2をvalidate/deliver/visual-check。各9/9、errors/warnings0、4画面サイズoverflowなし。
  それぞれ小/大light/dark計4枚を目視し欠け・重なりなし。
- node docs/guide/build-guide.mjs、node docs/guide/check-guide.mjs、uv run --project pdf-shrink python docs/guide/render-print.py が成功。
  5幅、目次/リンク、単独オフライン、A4全7ページ。PC/390pxの変更節、A4一覧と3ページ目を目視。
- 実資料: `uv run --script karufile.py -i "C:\Users\tn\Documents\解体工事共通仕様書R4_Copy.pdf"` がexit0。
  72,852,452→22,752,869 bytes、68.76856%減、ADOPTED_LOSSY/raster_scan、19ページ。
  再実行exit0・処理0件/再利用1件。dry-run exit0。いずれも原本/完成PDFのSHA・出力mtime不変。
  通常レポートはdry-run前後不変。
- [数値・SHA・候補・再開・dry-runの証拠](../../docs/validation/2026-09-13-default-scan.json)。
  実PDF/画像/ログはDocuments配下の専用出力に保存し、リポジトリに取り込まない。
  全19ページ概要と3/10/19ページ300 DPI拡大比較で目立つ欠落や読みにくさなし。

## Outcomes / Remaining Issues

当初の1コマンド処理と既定化は完了。原本維持と文字PDFの既存処理も確認した。
OCR付き・文字画像混在・vector paint入りは従来の明示profileが必要。写真のみもグレー化される。
実資料は1冊のPilotであり、全スキャンの画質・OCR精度・実印刷・全viewerを保証しない。
入力ロックなしと300秒の協調的期限は既存と同様。commit/pushは未実施。
