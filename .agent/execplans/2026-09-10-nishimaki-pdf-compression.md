# 西牧PDF 5冊の明示圧縮

## Goal
ユーザー指定のMusic直下5冊を原本不変で別フォルダーへ圧縮し、各冊が小さいことと検証結果を報告する。
図/写真による自動原本保護を一律に適用せず、今回許可された内容変更の範囲内で候補を作る。

## Facts / Scope
1: 340536 bytes/11p、文字と表。2: 3556324 bytes/10p、写真。
3: 588304 bytes/2p、1bit CCITT図面と文字。4: 1517266 bytes/11p、分析報告と写真。
5: 2539782 bytes/7p、写真。全41p、暗号化/フォーム/埋込添付なし。
多数の無関係な既存差分があるため実行コードは変更しない。今回限りのローカル処理。
原本削除・上書き・外部送信はしない。出力予定はMusic/西牧_PDF軽量化。

## Decision / Unknowns / Risks
文字検索・コピー維持と全ページ画像化の希望を質問したが回答なし。文字と色を保持する方針を明示し、全ページ画像化は行わなかった。
まず内容を変更しない再保存・可逆圧縮を試す。小さい報告書や既に1bitの図面は圧縮余地が限定される。
画像化は原本より大きくなる場合もある。実際に小さくなった検証済み候補だけを完成出力とする。

## CP-001 調査と候補
- Status: Complete
- Objective: 各冊の構成と許可範囲に応じて候補を作成
- Dependencies: 入力存在確認、ユーザーの画質/文字検索方針
- Files: 指定PDF5冊、タスク専用の一時候補・スクリプト
- Actions: 原本hashと構成記録、可逆候補、必要な非可逆候補
- Completion criteria: 全5冊に実際に小さい候補がある
- Validation: byte size、再オープン、ページ数、文字とページ寸法、全ページ描画
- Failure conditions: 許可範囲内で小さくできない、文字・描画破損
- Recovery: 不採用候補を公開せず、原因/選択肢を報告。原本は保持

## CP-002 公開と検証
- Status: Complete
- Objective: 圧縮結果5冊と結果一覧を用意
- Dependencies: CP-001
- Files: Music/西牧_PDF軽量化
- Actions: 検証済み候補を別出力へ公開、代表表示を確認
- Completion criteria: 原本hash不変、全冊圧縮率と残る画質影響を報告
- Validation: 原本/出力hash、全ページrender、ページ数、採用理由
- Failure conditions: 原本変更、候補破損、寸法/ページ欠落
- Recovery: 原本を保ちエラーを明記

## Validation / Outcomes

## CP-003 フォント変更追試
- Status: Complete (試行完了、字体変更は全5冊不採用)
- Objective: 前回圧縮済み5冊にWindows游ゴシック統一を試し、別出力を比較する
- Dependencies: CP-002、既存font_replace CLIとWindowsフォント
- Files: Music/西牧_PDF軽量化のPDF5冊、一時作業、新しい字体統一出力
- Actions: 全5冊を明示選択、既存候補検証、採用状態/容量/抽出差/描画を確認
- Completion criteria: 各冊の採用可否と理由、成功出力の確認結果を報告
- Validation: CLI結果、qpdf、全ページ描画、代表ページ目視、入力hash不変
- Failure conditions: 不正出力、検証不合格、未対応構造
- Recovery: 既存の原本と圧縮版を保持し、不採用や保護を明記

### CP-003 結果
既存CLIで前回出力を入力に `--font-replace-pattern '*.pdf' --workers 2` を実行、exit 0。
出力 `C:\Users\tn\Music\西牧_PDF字体統一\files`、詳細はその親のreport.csv。
全5冊PRESERVED_ORIGINAL、候補生成前の保護であり、字体統一の成功を意味しない。追加削減0 bytes。
1/4: font_replace_catalog_structure、実際にRootのStructTreeRootあり。
3: font_replace_forms_or_signatures、AcroFormあり。ただしFields=0、Widget=0で、入力欄や署名の存在を意味しない。
2/5: font_replace_no_text、置換可能なテキストなし。
前回の一時候補、前回公開PDF、今回コピーPDFのSHA256が全5冊一致。Music直下原本も前回記録SHA256不変。
同一バイトのコピーなので前回の全ページ描画検証がそのまま適用でき、再描画は行っていない。
制限を外す実装や構造削除は未実施。追加依頼は試行として完了、対応拡大は別の実装課題。

## CP-001/002 結果
## CP-004 対応拡大と再処理
- Status: Complete (限定対応拡大、残る実資料の制限を記録)
- Objective: タグ構造と空AcroFormを保持した字体変更に対応し実3冊を再処理
- Dependencies: CP-003、ユーザーの対応拡大承認
- Files: font_replace_parse.py、font_validate.py、関連テスト/文書、実3冊
- Actions: 有界解析と独立した構造保持検証を追加、失敗経路テスト、実CLI再処理
- Completion criteria: 追加構造の保持/改変検出を検証し各冊の実際の採用結果を報告
- Validation: PDF suite/compile、実PDFの構造・描画・原本hash、diff check
- Failure conditions: 構造欠落、既存テスト失敗、未対応の追加構造
- Recovery: 入力と既存結果を保持、検証不合格候補は採用せず追加課題を記録

### CP-004 実装・検証結果
- タグ構造を保持して既存の有界グラフsnapshotで比較。空AcroFormを限定許可し、実フィールド/XFA/署名/Widgetは引き続き保護。
- 1冊目の透過ロゴを受け、同寸法8bit DeviceGrayの単層SMaskを解析/独立検証に追加。マスクにも既存復号量制限を適用。
- 4冊目は生成時にpikepdfがXMP PDFVersionを書換えてcatalog_mismatchとなる実不具合を確認。fix_metadata_version=Falseで原metadataを保持し、検証を緩和せず修正。レシピversion6。
- 合成テストはタグ/親対応/空フォーム/XMP/マスク改変検出と実フィールド/XFA/署名/孤立Widget/循環マスク保護を追加。
- 全suite: PDF 444 passed/4 skipped、image64、video113、excel138、orchestrator431 passed。計1190 passed/4 skipped。
  意図的な孤立Widget fixtureのpikepdf PageCopyWarningが1件。全componentとroot/orchestrator compileall、root --help成功。
- 実5冊CLI再実行の最終出力は `C:\Users\tn\Music\西牧_PDF字体統一_検証済\files`。
  4冊目のみADOPTED_LOSSY/adopted_font_replace、1473551→1138410 bytes (22.7438%追加減)、text_extraction_changed=false。
  全11pの独立構造/文字/字体/画像/144DPI描画検証とqpdf合格。第1/6ページを目視確認、元の表/写真保持。
  Music直下原本と前回圧縮版の全5冊hash不変を確認。
- 1冊目は実際にYuGothR.ttcにU+2611 (☑) がないため保護。文字を欠落させる代用はしない。
  3冊目は空フォームに加えてFreeTextCallout等の注釈が存在し未対応。注釈appearanceと編集情報の字体変更は別課題。
  2/5は引き続きno_text。全冊字体変更が成功したとの扱いにはしない。
- MANUAL、component README、REFERENCE、ガイドtemplateを更新。build-guide/check-guide成功、7節・A4 7p、console error0。
  今回変更した字体節の390px表示とA4第3ページを目視確認。ガイド全ページ再目視は未実施。

5冊を `C:\Users\tn\Music\西牧_PDF軽量化` に元のファイル名で公開済み。
1: 340536 → 273959 bytes (19.55%)、3: 588304 → 536064 (8.88%)、4: 1517266 → 1473551 (2.88%)。
この3冊はPyMuPDF garbage=4/deflate/use_objstmsで再保存し、全24ページの150 DPI RGB描画が原本と完全一致。
3はオブジェクトストリーム利用によりPDF 1.4から1.5へ変更。その他の文書metadataは保持。
2: 3556324 → 2674925 (24.78%)、5: 2539782 → 1971021 (22.39%)。
写真2冊は一時入力フォルダーで既存CLI `--photo-pattern '*.pdf' --photo-dpi 200 --workers 2` を実行。
各28/20画像を変更、ADOPTED_LOSSY、validation_reason空、text_extraction_changed=false。
写真はカラー200 DPI/JPEG品質80で画質低下を伴う。第1ページの出力画像を目視確認。
全41ページの再描画、ページ数/寸法、抽出単語と位置、リンク、目次の一致、qpdf --check (全5冊exit 0)を検証。
入力SHA256不変と公開後の候補/出力SHA256一致を確認。合計8542212 → 6929520 bytes、18.8791%減。
出力内に圧縮結果CSV、詳細JSON、写真処理詳細CSVを保存。製品コード変更なし、全体テストは未実行。
写真の細部や読取精度を保証する検証ではない。原本は保持。

## CP-005 メイリオ選択
- Status: Complete
- Objective: CLIでメイリオを選択し実1冊目を別出力へ処理
- Dependencies: CP-004、ユーザー承認、Windows Meiryo Regular
- Files: PDF config/CLI/engine/runner/report/preview、root CLI/report validation、tests/docs
- Actions: 既定Yu Gothicを維持して明示Meiryo選択、選択/実字体/SHA/hashの整合、実PDF処理
- Completion criteria: 選択をCLIから検証/レポートまで伝え、実結果のサイズと文字/描画を報告
- Validation: affected suites/full suites/compile/help、実PDF検証と原本hash、diff check
- Failure conditions: 違う字体採用、状態混同、欠字/レイアウト不正
- Recovery: 入力と前回出力を保持し不合格候補は採用しない

### CP-005 結果
- root `--pdf-font-family {yu-gothic,meiryo}` / PDF `--font-family`を追加。既定yu-gothic。
  明示familyにはfont-replace-pattern必須。Meiryo RegularのWindows meiryo.ttc face0、family/style/埋め込み権限/SHAを確認。
  選択はconfig hash、実処理、成功/保護/dry-runのreport/state、preview、rootの要求照合まで伝達。
- 単体テストで別familyファイル偽装、要求なし指定、hash分離、Meiryo生成/独立検証、保護/dry-run metadataを確認。
  rootでMeiryoレポートと要求不一致の拒否、CLI転送を確認。previewも要求family不一致を拒否。
- PDF全suite449 passed/4 skipped、追加preview test1 passed、orchestrator439、image64、video113、excel138 passed。
  計1204 passed/4 skipped。意図的な孤立Widget fixtureのPageCopyWarning1件。
  全component/root/orchestrator compileall、root --help、git diff --check成功。
- 実1冊目を前回圧縮版から一時フォルダーへコピーしroot CLIで処理。完成PDF:
  `C:\Users\tn\Music\西牧_PDFメイリオ\files\1.現地調査報告書9340-001（西牧分遣所庁舎）.pdf`
  340536（元原本）→273959（前回）→204602 bytes。前回比25.3166%減、原本比39.9177%減。
  ADOPTED_LOSSY/adopted_font_replace、Meiryo Regular。検証済み候補を採用、text_extraction_changed=true（空白等の差）。
  全11ページの字体/文字位置/非文字構造/画像/144DPI描画とqpdf検証成功。第1/3ページの画像を目視、☑4個保持。
  元原本SHA256と前回出力bytes不変。一時入力も前回版と一致。同じroot CLIの再実行で再処理0/skip1、要求照合成功。
- MANUAL、REFERENCE、PDF_PROCESSING、各README、AGENTS、ガイドを更新。ガイドbuild/check成功、A4 7p。
  更新字体節の390pxとA4第3ページを目視。証拠 `docs/guide/validation/meiryo-update-print.png`。
- 字形・太さ・字間は変わる。検索/コピー時の推定空白差あり。3冊目の注釈は今回の対象外、未対応のまま。

## CP-006 メイリオを既定化
- Status: Complete
- Objective: 字体置換を明示したPDFの既定をMeiryoに変更
- Dependencies: CP-005、ユーザー決定
- Files: PDF/root defaults、tests、現行文書と図入りガイド
- Actions: 明示yu-gothicを残し既定を統一、旧字体レポートの要求不一致を拒否
- Completion criteria: 無指定familyの実CLIでMeiryo採用、テストと文書整合
- Validation: PDF/root suites、compile/help、実1冊とガイド表示、diff check
- Failure conditions: Yu Gothicへの誤fallback、旧状態誤採用
- Recovery: 原本/既存結果を保持し不合格候補を不採用

### CP-006 結果
- config/CLI/font discovery/root report照合の既定をmeiryoへ変更。明示yu-gothicは継続。字体変更自体は引き続きpatternで明示。
- 無指定familyと明示meiryoのhash一致、既定メイリオ実ファイル選択、游ゴシックレポートの要求不一致拒否、明示游ゴシック転送をテスト。
- PDF450 passed/4 skipped、orchestrator449、image64、video113、excel164 passed。計1240 passed/4 skipped。追加既定assertを含むfont_family5 testsも成功。
- 全component/root compileall、root --help、git diff --check成功。孤立Widget合成fixtureの警告1件。
- 無指定familyで実1冊目をroot CLI処理、Meiryo Regular・ADOPTED_LOSSY、273959→204602 bytes。
  出力Music/西牧_PDFメイリオ既定/files。前回明示meiryo版と全11ページ144 DPI RGB画素・抽出文字一致。原本SHAと前回圧縮版不変。
- 現行README/MANUAL/REFERENCE/各README/PDF_PROCESSING/AGENTS/ガイドの既定を更新。旧manual見出しanchorは互換維持。
- ガイドbuild/check成功、7節/A4 7p。390px字体節・A4第3ページを目視。証拠meiryo-default-print.png。
- 既存の字形/空白差、注釈未対応は継続。今回その他のPDFは再処理していない。

### CP-006 文書一括監査追補
ユーザーの「関連するドキュメントをすべて更新」に対応。README、MANUAL、REFERENCE、PDF_PROCESSING、
component README、orchestrator設計、AGENTS、文書索引、図入りガイドで「置換対象は明示、字体は既定メイリオ」を統一。
古い引継ぎの現在地表現を当時の到達点へ修正し、旧101p検証記録に現行手順への案内を追加。過去の実測値は変更しない。
ガイドHTML/PDF/全7p PNG/pages.jsonを再生成。build/check、リンク、文字境界、変更節の390px/A4目視、diff check成功。
文書のみでruntime suiteは再実行していない。
