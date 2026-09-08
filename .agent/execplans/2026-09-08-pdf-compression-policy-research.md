# PDF圧縮方針の調査と実データ診断

## 2026-09-08 追加比較: 写真200 DPI / 180 DPI

利用者の「比較したい」を受け、現地写真・採取写真を原本から独立して200 / 180 DPI、品質80で生成する。
50%縮小や80%下限のハイブリッドは今回実装せず、製品CLIの200 DPI固定条件も変更しない。

### CP-012: 写真DPIの独立比較

- Status: In progress
- Objective: 同じ表示寸法で容量と細部を比較し、180 DPI導入を判断できる資料を用意する。
- Dependencies: 現行photo transform、検証規則、原本2冊、既存200 DPI出力の再確認。
- Files or components: `pdf-shrink/experiments/compare_photo_dpi.py`、新規検証parent、当計画。
- Actions: 実験専用optionsで既存の対象判定・共有xref処理・ceil丸めを再利用。原本から4候補を独立生成し、全ページ比較HTMLと300 DPI写真領域を用意する。既存工程にないqpdf再最適化を加えない。
- Completion criteria: 4候補の容量・生成/検査時間・構造/描画検証結果、200 DPI再現性、原本/既存出力hash不変を記録。比較資料を目視確認する。
- Validation: `inspect_file`、`validate(enhanced=True, detail=True)`、全ページ形状/文字/paths/画像配置一致、既存200 DPIとの画素一致、実験compile、関連suite、`git diff --check`。
- Failure conditions: 検証不合格・上限超過を成功扱い、原本/既存出力変化、通常設定の無断変更。
- Recovery: 比較用新規出力だけを残し、不合格は明示。原本/既存出力への書込みと自動採用はしない。

## 2026-09-08 追加実装: JPEG可逆比較と16 KiB採用下限

利用者の追加実装計画を受領。CP-001〜008は履歴として保持する。今回開始時の作業ツリーはclean。
原本・既存出力を保持し、別parentへ候補と検証証拠を保存する。commit/pushは行わない。
既存200 DPI photo、非可逆採用条件、256 KiB未満除外、品質基準は変更しない。

### CP-009: 独立JPEG比較

- Status: 数値・完全一致検証合格。Edge表示確認待ち
- Objective: 写真2冊でjpegtranの追加利益と完全一致を測定する。
- Dependencies: 公式libjpeg-turbo 3.2.0 Windows x64配布物のhash・署名確認。
- Files or components: 独立検証スクリプト、新規検証parent、現地写真・採取写真。
- Actions: 原本からqpdf単独、baseline、progressiveを独立生成。`-copy all -optimize`、progressiveのみ`-progressive`。寸法・成分・量子化表・原寸画素一致かつstream縮小時のみ画像辞書を保持して置換。
- Completion criteria: qpdf検査、ページ形状・文字・パス・全ページRGB完全一致、代表ページEdge表示を記録。写真の少なくとも1冊でqpdf単独より16 KiBかつ2%以上小さい検証済み候補がある場合のみ組込みへ進む。
- Validation: tool version/SHA-256、候補別bytes・時間・検査結果、原本/既存出力の前後hash。
- Failure conditions: 画素差、構造/ツールエラー、原本変化。利益不足は不合格として正常に分岐。
- Recovery: 原本/既存出力へ書き込まない。利益不足ならJPEG製品機能は追加しない。

### CP-010: 合格時だけ明示CLIへ組込み

- Status: ローカル実装・自動検証済。CP-009のEdge表示確認は保留
- Objective: 既定OFFの追加可逆候補を安全に利用できる。
- Dependencies: CP-009組込み条件合格。
- Files or components: PDF config/cli/worker/transform/validate/state/report、root CLI、tests、architecture。
- Actions: root `--pdf-lossless-jpeg`/`--pdf-jpegtran-path`、PDF `--lossless-jpeg`/`--jpegtran-path`。手動準備のみ。明示path→PATH、3.2.0事前検査。dry-runは実行しない。単一DCT・8-bit DeviceRGB/Gray、mask/特殊Decode/inline等除外。xref単位streamのみ交換。20 MP/32 MiB、128M/100 scans/30秒、文書300秒協調予算。baseline/progressive独立検証、最小合格候補、tieはqpdf→baseline→progressive→lossy。ツール異常はERRORと復旧copy、画素差/予算超過は候補棄却。
- Completion criteria: 指定とreport照合、失敗経路、候補履歴、safe/dry-runが試験成功。
- Validation: 合成試験、version/hash変更による再処理、DB追加移行、旧CSV拒否。
- Failure conditions: 完全一致を緩和、既存非可逆候補を無効化、エラー隠蔽。
- Recovery: 未完成機能は公開しない。追加方式へ拡張しない。

### CP-011: 閾値・状態・文書・最終検証

- Status: 実装・自動検証・実資料検証済
- Objective: 可逆採用を16 KiBかつ2%以上へ統一し、以前棄却された3冊の採用を確認する。
- Dependencies: 閾値変更はCP-009の利益判定に独立。JPEG関連項目はCP-010実装時のみ。
- Files or components: PDF ReductionOptions/config hash、root照合、tests、manual/reference/README、当計画。
- Actions: 閾値とprocessing schema更新。JPEG追加時はrequested全CSV true/false・state追加移行・recipe/version/hashを設定hashへ反映、candidate列一次候補契約維持、ADOPTED_LOSSLESS使用。境界値/再実行/dry-run試験と実資料5冊別出力。
- Completion criteria: 全指定suite/compileall/help/diff成功。入力/既存出力hash不変、3冊可逆採用、候補・削減・時間を記録。
- Validation: 実行コマンドと実結果を末尾に追記。JPEG外部ツールを製品追加時のみArchify再生成と目視。
- Failure conditions: 必須検証失敗、未実測を成功扱い。
- Recovery: 原本・既存出力を保持し、今回変更だけ修正。未解決を記録。

### 今回の判断・証拠

- 公式release API掲載SHA-256とダウンロードしたVC x64配布物が一致: `662761d8ba8dae04aec74023ebaeceb856c2b56b9b59cfd180759d26300dda42`。
- Windows Authenticode: Valid / Signature verified、署名者SignPath Foundation、thumbprint `1C539760AE21976C7ACFF383930DCA4221BC0460`。
- 検証用配布物はOS一時領域へ取得し、既存7-Zipで展開した。インストーラーは実行せず、製品の自動取得処理も追加していない。
- 実行ファイル: `C:\Users\tn\AppData\Local\Temp\karufile-jpeg-16d9a7a3e93f41bf8eea2a49864866d6\extracted\bin\jpegtran.exe`。
  version `libjpeg-turbo version 3.2.0 (build 20260630)`、SHA-256 `671166b760a6b0e6b9888ce471fcb97c2a245db07512cd75c23ee29148d0acd0`。
- 数値・完全一致gate合格を受けてCP-010をローカル実装した。Edge検証を代替検証だけで合格扱いにはせず、全体完了は保留。
- `jpegtran -version`はstderrに版情報を出す。通常成功でも空白だけの進捗消去文字がstderrへ出るため、非空白警告と区別した。
  最初の2回はこの検証スクリプト側の判定で停止し、出力を上書きせず`run3`で完走した。
- 合成試験のPyMuPDF生成画像はColorSpaceが間接参照だった。対象仕様に合わせた直接DeviceRGB/Grayのfixtureを作成し、製品の対象判定は緩めていない。
  小さなGray画像はprogressiveで増大したため、実際に不採用となることを検証した。
- 2026-09-08 18:55頃のGit再確認で、別操作によってHEADが開始時`2a529fc09eeb3e20f12ebea8a2a48e95911eb834`から
  `3d98c66df6eb936c2c5bffbfdb0111b4e40ebb9f`へ進み、実装の一部がcommit済みと確認。担当agentはcommit/pushを実行していない。
  履歴は変更せず、残る文書・qpdf警告処理・検証を現在のコードへ反映した。

### CP-009 比較結果

独立スクリプト: `pdf-shrink/experiments/compare_lossless_jpeg.py`。
保存先: `C:\Users\tn\Downloads\KaruFile_JPEG比較_20260908_run3`。
`comparison.json`に全JPEGのxref・元/候補bytes・header/画素一致・置換有無、PDFごとのhash・全ページ検証・時間を記録。
各候補を原本から独立生成。PyMuPDF 1.28.2、qpdf 12.3.2、固定jpegtran 3.2.0を使用。

| PDF | 原本bytes | qpdf単独bytes | baseline bytes | progressive bytes | progressiveの対qpdf削減 |
|---|---:|---:|---:|---:|---:|
| 現地写真 | 3,556,324 | 3,550,522 | 3,346,775 | 3,294,592 | 255,930 / 7.2082% |
| 採取写真 | 2,539,782 | 2,534,216 | 2,407,212 | 2,344,904 | 189,312 / 7.4702% |

全6完成候補でqpdf exit 0、ページ形状・抽出文字・描画パス一致、全ページ72/300 DPI RGB完全一致。
両写真の全28/20 JPEGはbaseline/progressiveとも寸法・成分・量子化表・原寸画素一致。
時間（生成＋検証）: 現地写真 qpdf 2.50秒/baseline 4.15秒/progressive 5.11秒、採取写真 2.18/3.28/4.18秒。
baselineも対qpdfでそれぞれ203,747 bytes（5.7385%）、127,004 bytes（5.0116%）削減し、数値gate合格。

### CP-010/011 実装と検証

- `lossless_jpeg.py`に手動tool検出、JPEG header/画素検証、xref stream専用置換、文書共通予算、完全描画検査を分離。
- root/PDFの明示オプション、16 KiBかつ2%の照合、schema3/hash、状態追加移行、全CSVの要求bool、候補tie順を実装。
- qpdf追加JPEG工程では警告exit3もERRORとして扱い、既存qpdf単独の挙動は維持。
- 全suite: PDF **180 passed**、画像 **64 passed**、動画 **104 passed**、orchestrator **157 passed**、合計**505 passed**。
  AGENTS.md指定コマンドを使用し、PDF試験時だけ`KARUFILE_TEST_JPEGTRAN`へ上記手動準備pathを指定。追加実tool試験4件もskipせず実行。
- AGENTS.md指定の4つのcompileall成功。PDF experimentsも追加compile成功。root `--help`とPDF `run --help`成功。
- 最終`git diff --check`成功。改行正規化のGit通知のみで、空白エラーなし。
- 合成試験: baseline/progressive、Gray/RGB、低DPI・共有xref、対象外属性、破損・画素差・増大、同サイズ優先順、
  tool欠落/版不一致/変更/警告/失敗/timeout/I/O、予算棄却、復旧ERROR、primary診断維持、閾値前後・一致、DB移行・CSV往復、旧CSV拒否、root要求照合。

### 実資料5冊の最終Pilot

保存先: `C:\Users\tn\Downloads\KaruFile_JPEG実装検証_20260908`。各caseは独立parentの`files`へ出力。
全caseの入力は`C:\Users\tn\Downloads\西牧分遣所アスベスト調査報告書`。
写真指定は`--pdf-photo-pattern '2.*.pdf' --pdf-photo-pattern '5.*.pdf'`。

| case | 条件 | 合計削減bytes / 率 | 時間 | 結果 |
|---|---|---:|---:|---|
| standard | JPEG有効、写真指定なし | 647,383 / 7.58% | 29.38秒 | 5冊ADOPTED_LOSSLESS |
| photo | JPEG有効、写真指定あり | 1,640,933 / 19.21% | 43.11秒 | 3冊可逆、写真2冊非可逆 |
| threshold-only | JPEG無効、写真指定あり | 1,568,304 / 18.36% | 23.78秒 | 3冊可逆、写真2冊非可逆 |
| dry-run | JPEG要求、存在しないtool path、写真指定あり | 出力なし | 2.35秒 | 3件DRY_RUN_LOSSLESS、2件DRY_RUN_LOSSY |

時間は単発観測であり、photoとthreshold-onlyは一部同時実行のため速度比較のbenchmarkではない。
standard再実行はPDF 0件処理・5件再利用、PDF子処理0.52秒、root成功。要求trueと全診断履歴を維持。
PDF単体`--safe --lossless-jpeg --limit 1`も別case `safe/files`で成功（選択された分析報告書、候補progressive、112,082 bytes削減、処理6.96秒）。

| PDF | standard出力bytes / 採用候補 | photo出力bytes / 採用候補 | threshold-only出力bytes / 採用候補 |
|---|---:|---:|---:|
| 1 現地調査報告書 | 279,191 / lossless | 279,191 / lossless | 279,191 / lossless |
| 2 現地写真 | 3,294,592 / jpeg_lossless_progressive | 2,674,925 / photo | 2,674,925 / photo |
| 3 試料採取箇所 | 570,958 / lossless | 570,958 / lossless | 570,958 / lossless |
| 4 分析報告書 | 1,405,184 / jpeg_lossless_progressive | 1,405,184 / jpeg_lossless_progressive | 1,477,813 / lossless |
| 5 採取写真 | 2,344,904 / jpeg_lossless_progressive | 1,971,021 / photo | 1,971,021 / photo |

閾値変更だけで1/3/4の61,345 / 17,346 / 39,453 bytesの可逆候補を実際に採用（計118,144 bytes）。
独立検証スクリプト`pdf-shrink/experiments/verify_lossless_jpeg_pilot.py`は全CSVと入力/出力hash・bytes・selectedを照合し、
採用可逆PDFはさらに全ページ72/300 DPI RGB完全一致を検査した。photo採用PDFはページ形状・文字・パス一致を検査し、RGB完全一致とは扱わない。
比較開始時の入力・既存出力/補助情報の**279ファイル**はSHA-256不変。結果は検証parentの`pilot-verification.json`に保存。

### 構成図

Archifyでarchitecture JSON更新→validate→deliver→visual-check。showcase9/9、errors/warnings0。
4viewport（1440×900、1600×1000、1920×1080、2048×1320）でoverflowなし。
最小/最大viewportのlight/dark4画像を主agentが目視し、jpegtran表示、切れ・重なりなしを確認。
`visualReview: pending`は自動receiptの仕様のまま保持し、この段落を目視記録とする。
source SHA-256 `bb725f32617734b458849b994e473625b7db8085b5b08efa22bdea33e2b23918`、
HTML SHA-256 `fc68f6fdec72ede1585a11628de7bf3cdd698e2bf7faaa68b24330495ce9f8f2`。
source基準commitは`3d98c66df6eb936c2c5bffbfdb0111b4e40ebb9f`、未commit修正を含むことを図中に明示。

### 未解決事項・停止条件

- Edgeの接続は`Browser is not available: edge`、Windows操作は`Computer Use native pipe is unavailable ... os error 2`。
  headless EdgeのPDF screenshotは灰色だけで、表示成功の証拠にできなかった。
  利用者へ`photo-2/progressive.pdf`と`photo-5/progressive.pdf`のEdge先頭ページ表示結果を照会中。
  **Edge表示確認を完了扱いにしない。CP-009と全体の最終受入はこの確認待ち。**
- 全ビューアー互換性、OCR精度、画像中の文字の読取り精度は未保証。比較検査をその保証へ言い換えない。
- JPEG単独の5冊合計削減は7.58%。既存200 DPI写真候補を併用した19.21%は非可逆2冊を含む。
- 実資料・既存出力を削除/上書きせず、HTML/OCR/JPEG2000等の別方式は追加していない。

この文書はliving documentである。前半は調査時点の記録。2026-09-08に利用者から実装指示を受け、末尾の実装チェックポイントと実資料検証まで完了した。

## Goal

利用者が、standardで削減できなかった5 PDFについて、理由と実測に基づき、文字の可読性と容量削減を両立するプログラム改善方針を選べるようにする。

## Acceptance Criteria

- 現行コード、既存テスト、対象PDFの画像構成を照合する。
- 「300 DPI以下ならOCR不要」という仮説を一次資料で検証する。
- 原本を変更せず、既存エンコーダによる画像候補の削減量を測る。
- 実装済み動作、提案、未検証の画質・OCR精度を区別して報告する。

## Scope

### In Scope

- PDFだけの読み取り診断、メモリ上のJPEG候補生成、代表ページの表示確認。
- OCRと圧縮の一次資料調査、現在のcompactとの比較、最小改善順序の提案。
- この調査記録の作成。既存のcompact実装計画は別目的のため変更しない。

### Out of Scope

- 実行コードの変更、新プリセットの実装、既存出力の上書き、OCR依存の導入。
- 原本の変更・削除、文書内容の外部送信、commit/push。

## Current State / Facts

- 作業ツリーにはPDF・画像・動画・文書の既存変更多数。保持する。
- standard実行は5件すべてlossless/UNCHANGED。64 KiBかつ2%の削減条件未達。
- compactは300 DPI以下でもJPEG quality 80で同寸法再圧縮する。画像streamで5%以上、文書で256 KiBかつ5%以上の削減が必要。
- 既存の抽出文字照合はOCRを実行せず、画像中の文字を評価しない。表示比較は72 DPI、compactはRGBの全体平均と最大32pxタイル差。
- 原本の配置画像: 1はFlate 1個・画像stream比2.00%、2はJPEG28個・97.36%・約284 DPI、3はCCITT2個・82.51%・300 DPI、4はJPEG35個・65.52%・約119-129 DPI、5はJPEG20個・93.96%・約284 DPI。
- 2と5は全ページで可視・不可視文字オブジェクトの文字数が0。他3文書には文字オブジェクトがある。この事実だけでは画像やパスに文字がないとは判定できない。
- q90/q85/q80の同寸法JPEG候補では全83 JPEGで画像streamの5%削減条件を満たさなかった。これは文書全体のcompact実行結果ではない。

## Inferences

- 今回のcompactによる大幅削減は期待しにくい。写真主体資料の低解像度候補も比較する必要がある。
- OCRの成否とOCRの必要性は別問題。低解像度の画像内文字は、劣化を許容する根拠にならない。

## Assumptions / Unknowns

- 主用途を利用者へ確認中。回答がなければ文字・数値を読み取れる画面閲覧用コピーを想定する。
- JPEG品質値は実装依存であり、今回の値を他エンコーダへ一般化しない。
- 候補streamのサイズ比較だけでは最終PDFサイズ・採用結果・OCR精度は確定しない。

## Options Considered

1. 現状維持: 品質維持には適するが今回の容量を減らせない。
2. 既存compact: 最小操作だが今回のJPEG再圧縮測定では効果が見えない。
3. 候補・棄却理由を可視化し、用途と画像の内容に応じて限定的に圧縮候補を増やす: 推奨方向。
4. OCR必須化や全ページ画像化への全面置換: 依存・時間・可読性の負担があり現段階では不採用。

## Risks / Stop Conditions

- 文書に既存テキストがあっても、画像内の数値、注記、細線は別途保護が必要。
- 解像度変更は現行の全preset 300 DPI固定契約を変更するため、実装段階で明示的な仕様整理と関連文書更新が必要。
- 画質の許容を実測で評価できない場合、削減量だけで候補を推奨出力としない。

## Checkpoints

### CP-001: 実装と一次資料の確認

- Status: Complete
- Objective: 原因・OCR仮説・現行安全条件を確定する。
- Dependencies: なし。
- Files or components: inspect_pdf.py、transform.py、validate.py、worker.py、既存テスト、Tesseract/OCRmyPDF/Adobe資料。
- Actions: 読み取り、既存テスト、一次資料を確認。
- Completion criteria: 各結論に現行コードまたは一次資料の根拠がある。
- Validation: ソース行・テスト結果・参照URL。
- Failure conditions: 外部資料と現行コードを混同する。
- Recovery: 未確認点を切り分ける。製品コードは変更しない。

### CP-002: 実データの局所診断

- Status: Complete
- Objective: 5 PDFの削減余地と文字リスクを把握する。
- Dependencies: CP-001で候補生成関数を確認。
- Files or components: 入力PDF5件、メモリ上のJPEG候補、閲覧用ページレンダリング。
- Actions: DPI・画像stream比・文字層を集計し、品質と縮小を独立比較する。
- Completion criteria: 候補生成条件と数値、評価の限界を記録できる。
- Validation: 原本SHA-256前後一致、候補streamサイズ、代表ページ目視。
- Failure conditions: 原本または既存出力の変更、画質未確認を合格と表示。
- Recovery: 読み取り診断へ戻す。候補を完成出力へ公開しない。

### CP-003: 改善順序と提案の整理

- Status: Complete
- Objective: 実装可能な最小改善と受入条件を利用者へ提示する。
- Dependencies: CP-001、CP-002。
- Files or components: 本文書と回答。
- Actions: 用途、OCR、画像分類、候補比較、検証、レポートを分けて提案。
- Completion criteria: 既存動作・提案・残る判断が明確。
- Validation: 実測と提案の整合、git diff --check。
- Failure conditions: 固定値やOCR精度を根拠なく保証する。
- Recovery: 仮説へ戻し、未検証項目を明記。

## Progress

- [x] CP-001
- [x] CP-002
- [x] CP-003

## Discoveries / Decision Log

- 2026-09-08: 300 DPIはOCR可否の境界に使わない。文字サイズ、傾き、ノイズなどにも依存する。
- 2026-09-08: 既存compactの提案だけでは今回の問題への根拠が不足。同寸法JPEG候補の計測を先行した。
- 2026-09-08: 用途の回答がない段階では、文字・数値を読める閲覧用コピーを想定。既存のstandard/compactの数値を変更したとは扱わない。
- 2026-09-08: 「現地写真」「採取写真」の先頭ページは、写真3枚の画像配置と、右側の文字を含むパス描画に分かれる。右側は抽出可能な文字オブジェクトではないが、ページ全体を画像化せず画像xrefだけを変更すれば維持できる。採取写真の黒板文字は写真の画素に含まれるため別途保護が必要。
- 2026-09-08: 「試料採取箇所」1ページ目は細線と寸法を持つ図面。「分析報告書」2ページ目は顕微鏡写真。低DPI・写真という分類だけで劣化許容とは判断しない。

## 実測した候補比較

PyMuPDF 1.28.2と現行 `_jpeg_bytes_for_xref` を使用。元画像から各候補を独立生成した。
縮小では各軸の配置DPIから寸法を切り捨て計算し、拡大しない。各JPEG streamが5%以上縮む
画像だけを集計する現行の条件で比較した。値は `sum(original_stream - candidate_stream) / source_pdf_size`。
完成PDFのサイズ・採用結果ではない。qpdf構造検証・全ページ画質検証・OCR検証は行っていない。

| 元PDF | 同寸法 q80 | 同寸法 q60 | 同寸法 q50 | 240 DPI q80 | 200 DPI q80 | 150 DPI q80 |
|---|---:|---:|---:|---:|---:|---:|
| 2.現地写真 | 0.00% | 0.38% | 3.55% | 0.00% | 24.81% | 55.45% |
| 4.分析報告書 | 0.00% | 5.52% | 15.11% | 0.00% | 0.00% | 0.00% |
| 5.採取写真 | 0.00% | 0.00% | 1.10% | 0.00% | 22.75% | 51.98% |

- 200 DPI q80の削減stream bytes: 現地写真882,377、採取写真577,676。
- 150 DPI q80の削減stream bytes: 現地写真1,971,840、採取写真1,320,278。
- 分析報告書の画像は元から約119-129 DPIなので、上記150/200/240への縮小は行われない。
- JPEG品質値はエンコーダ依存。品質値だけから元JPEGの品質、劣化率、OCR精度を推定しない。
- 採取写真1ページ目の黒板を、原本／200 DPI q80／150 DPI q80それぞれ300 DPI表示で比較した。
  200でも細部に軟化があり、150では文字・罫線の荒れが目立つ。1領域の目視で全20画像の読取性は保証しない。
- PopplerはPATHで見つからなかったため、既存依存PyMuPDFで読み取り表示を行った。
- 診断PNGのみを `C:\Users\tn\AppData\Local\Temp\karufile-pdf-policy-6555af2e829a447d988220aa13d3b893` に生成。
  PDFの再出力は行っていない。

## 一次資料と設計上の解釈

確認日: 2026-09-08。リンク先の最新仕様を、そのままKaruFileの依存バージョンの仕様とは扱わない。

1. [Tesseract: Improving the quality of the output](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html)
   - 300 DPI以上を推奨するが、OCR可否の閾値ではない。ノイズ・傾き・二値化・字形にも依存する。
   - 解釈: 認識困難はOCR不要を意味せず、劣化許容の根拠にもならない。
2. [OCRmyPDF: PDF optimization](https://ocrmypdf.readthedocs.io/en/stable/optimizer.html)
   - 可逆と非可逆の最適化レベルを分け、OCR後に最適化する設計を説明する。
   - 解釈: OCRが必要な場合は高品質の入力から先に文字を取得し、保存用画像の圧縮を後に行う。
     OCR文字層を残せても、見た目や認識の正しさを保証するものではない。
3. [OCRmyPDF: Introduction](https://ocrmypdf.readthedocs.io/en/stable/introduction.html)
   - PDFには画像・文字・ベクターが混在し、全体ラスタライズや画像からの再構成で情報を失う可能性を説明する。
   - 解釈: 今回の右側のパス文字・罫線は維持し、画像だけを候補化する現行の境界を残す。
4. [Adobe: PDF optimizer settings](https://helpx.adobe.com/acrobat/desktop/create-documents/optimize-pdfs/pdf-optimizer-settings.html)
   - 画像のダウンサンプリングとJPEG品質を別設定とし、階調画像と平坦な線画で圧縮方式を分ける。
   - 解釈: DPIだけではなく、用途・画像内容・実際の削減量で候補を選ぶ。
5. [qpdf: Running qpdf / Optimizing File Size](https://qpdf.readthedocs.io/en/stable/cli.html#optimizing-file-size)
   - Flate再圧縮とobject streams、およびJPEG再圧縮を説明。qpdf自体は画像を再サンプリングしない。
   - 解釈: 現行の可逆最適化だけで写真の大幅縮小を狙うのは難しい。

## 推奨する実装順序（調査時点では未実装）

### 1. 判定と候補の見える化

- `UNCHANGED`だけでなく候補bytes、削減率、適用画像数、選択・棄却理由をtyped result、state、CSVへ伝える。
- 理由を「対象画像なし」「再圧縮が大きい／小さな削減」「文書削減閾値未達」「画質不合格」「実処理エラー」に分ける。
- state schema・config/algorithm hashと再利用条件、orchestratorのreport契約を同じ変更で更新する。
- 代表的な受入: 小さくなったが閾値未達のファイルで、実際の候補値と理由がCSVに残る。

### 2. 用途を明示した閲覧用候補

- standardとcompactの現在の契約を維持し、明示的な閲覧用設定を検討する。
- 最初は利用者が写真中心と指定した対象に限定し、200 DPI q80を検証候補とする。これは今回の実測からの提案であり普遍的な最適値ではない。
- 150 DPIを自動既定にしない。図面・文字画像・細部を評価する写真・不明は保護する。
- 全ページをJPEGにせず既存文字とパス描画を維持する。画像内の黒板・細字は文字層とは別に扱う。
- 原本、可逆候補、限られた非可逆候補を比較する。各候補は原本から生成し、前候補の再圧縮はしない。
- 共有xrefは全配置へ影響するため、1箇所でも厳しい条件なら保護する。将来の複製・領域分離は別段階。
- 不合格の非可逆候補から可逆候補へ戻せるようにする。I/Oや構造エラーを無視して成功にはしない。

### 3. 検証と採用閾値の見直し

- 72 DPI全体平均だけで文字保持を判定しない。変更画像領域を高解像度でも比較し、黒板・数字・細線の代表箇所を確認する。
- OCRが要件なら原本と候補の同じ領域に対して評価する。OCR confidenceや「検出文字なし」を安全判定に使わない。
- OCR精度保証には正解テキストと比較した評価が必要。既存の文字層一致はそれと区別する。
- 現行の非可逆採用は256 KiBかつ5%以上。500 KiBのPDFでは51.2%必要となる。絶対量の固定下限を画像ごと／文書ごとに混同せず、ログと用途を見て小文書に適した閾値を設計する。
- 画質基準と削減基準は別に評価し、削減不足解消のために画質検査を緩めない。

### 4. OCR・自動分類は必要性が確認されてから

- 現行KaruFileはOCRを実行しない。容量を減らすためだけに必須依存へ加える必要はない。
- 検索可能にするなら原本からOCRし、得た文字層と既存ベクターを維持し、その後に表示画像を圧縮する。
- ページに文字層があるだけで全画像の文字が網羅されているとみなさない。
- 将来の画像分類は写真・文字／線画・混在・不明を扱い、DPIからOCR不要を推測しない。
- 単純な全面二値化や図面の不可逆文字パターン置換は今回の最小改善に含めない。

## Validation Evidence

- 2026-09-08: 5件のメタデータとq90/85/80候補測定、exit 0、原本SHA-256全件不変。
- 2026-09-08: q70/60/50、240/200/150 DPI q80候補測定、exit 0、対象3 PDFの原本SHA-256不変。
- 2026-09-08: 2・3・5の1ページ目、4の2ページ目の表示確認と、5の黒板領域比較。完全な実データPilotではない。
- 2026-09-08: 独立監査で関連既存テスト41件成功（test_lossy_placed_dpi.pyとtest_pdf_shrink.py計30件、refactor契約のOCR/scan/DPI/preset関連11件）。
- 2026-09-08: `git diff --check` exit 0。既存ファイルのLF/CRLF警告はあるがwhitespace errorなし。

## Outcomes / Remaining Issues（調査段階）

調査・設計提案は完了。実行コード・元PDF・既存の完成出力は変更していない。
追加した追跡用ファイルは本調査記録のみ。代表ページと画像候補の診断から、写真2冊の200 DPI候補を次の限定Pilotに推奨する。
全ページの完成PDF検証、実OCR精度、使用目的に対する画質受入、新プリセットの実装は未実施。

## 実装段階（2026-09-08、利用者承認済み）

### Goal / Scope

判定・候補の記録、明示選択した写真PDFの閲覧用200 DPI候補、細部検証と可逆fallbackを実装し、CLIから実資料で検証する。
既存standard/compactと画像・動画のpresetは維持する。OCR導入・意味による写真の自動判別・HTML経由再構成は対象外。
入力と既存完成出力は保持し、実資料検証は別の検証出力を使う。commit/pushはしない。

### Decisions

- 開始時点はclean、HEAD `7069b0a`。前回調査以降の利用者commitを基準とする。
- root `--pdf-photo-pattern PATTERN`、PDF単体 `--photo-pattern PATTERN` を反復指定し、一致した相対パスだけprofile=photoへ切り替える。
- globはslash正規化・大文字小文字を区別せずfnmatch、`*`は`/`も含む。空・絶対・親参照を拒否。
- photoはJPEGの寸法縮小だけ、quality80。200 DPI以下の軸は寸法を維持し、両軸とも縮小余地がない画像は再圧縮しない。一方の軸だけを縮小する場合もJPEG全体は再符号化される。文字、パス、1bit、非JPEG、マスク付き画像を保持する。
- photoでは共有xrefの全配置の軸別最小DPIから寸法をceil計算し、200 DPI未満へ落とさない。既存presetの300 DPI最大値方式は維持。
- photoの採用下限は64 KiBかつ5%。既存standard/compactの閾値と256 KiB未満skipは維持。
- 非可逆候補の品質棄却・削減不足では可逆候補も比較する。構造・I/O・toolエラーを成功へ隠さない。
- reportのprofile列を必須としてrootで実行条件と照合する。候補記録を加え、config schemaを更新して古いstateを再処理する。
- PDF→HTML→PDFは今回は採用しない。PyMuPDF HTML抽出で現地写真/採取写真の先頭ページはimg3個のみ、元の47/68個のpathと右側注記を保持しないことを確認。SVG対応変換もあるが、今回の画像圧縮目的に往復変換を加える利点は確認できない。

### CP-004: 結果・state・report

- Status: Complete
- Objective: 候補値と棄却理由を再実行後も確認できる。
- Dependencies: CP-001〜003。
- Files or components: models/state/report/runner、関連テスト。
- Actions: typed candidate、additive SQLite migration、CSV診断列、理由summary。
- Completion criteria: 旧DB移行と候補の保存・再読込・CSVが成功し、実行profileを誤再利用しない。
- Validation: migration/CSV/再利用テスト。
- Failure conditions: 旧記録消失、候補と完成出力の混同。
- Recovery: 原本保持、additive migration、未完了をstate再利用しない。

### CP-005: 写真候補と検証

- Status: Complete
- Objective: 写真画像のみを縮小し、細部差を検査する。
- Dependencies: CP-004の型契約。
- Files or components: config/inspect/transform/validate/worker、関連テスト。
- Actions: opt-in recipe、共有画像保護、300 DPI領域tile比較、可逆fallback。
- Completion criteria: 284→約200、119維持、マスク/1bit/パス保持、候補棄却とtool errorの区別が確認できる。
- Validation: 代表fixture、既存PDF suite。
- Failure conditions: 対象外劣化、無制限render allocation、破損を成功扱い。
- Recovery: 原本または検証済み可逆候補を採用、実障害はERROR。

### CP-006: root CLIと契約文書

- Status: Complete
- Objective: rootから選択対象にだけ写真設定を適用し、結果を正確に集計できる。
- Dependencies: CP-004、005。
- Files or components: orchestrator、PDF CLI、MANUAL/REFERENCE/README/AGENTS。
- Actions: pattern配管、profile照合、実行例と制約更新。
- Completion criteria: 指定対象以外は従来のprofile、stale profileは拒否、helpと文書が一致。
- Validation: orchestrator suite、CLI help、文書照合。
- Failure conditions: 画像動画の動作変化、未実装CLIの文書化。
- Recovery: 既定値を維持しprofile設定をopt-inへ限定。

### CP-007: 統合検証・実資料確認

- Status: Complete
- Objective: 要求されたCLI動作と残る画質限界を確認して引き渡す。
- Dependencies: CP-004〜006。
- Files or components: 全suite、検証用出力、実資料5 PDF。
- Actions: 全suite/compile/help/diff、写真2冊の別出力Pilot、原本hashと代表箇所確認。
- Completion criteria: 必須検査成功、候補と実出力値・棄却理由を確認、未確認のOCR精度を明示。
- Validation: test counts、CSV、hash、目視記録。
- Failure conditions: 原本変化、テスト不合格、未検証を保証。
- Recovery: 原本・既存出力は維持し、問題を修正して影響範囲だけ再検証。

### Implementation Progress / Discoveries

- [x] CP-004: candidateの型、SQLite追加移行、CSV診断、状態再利用を実装・検証。
- [x] CP-005: 明示photo、約200 DPI候補、300 DPI細部検査、原本から生成した可逆候補との比較を実装・検証。
- [x] CP-006: root CLI、profile照合、help、各契約文書と構成図を更新・検証。
- [x] CP-007: 必須テスト・compile・help・実資料Pilot・再実行・代表箇所目視を完了。
- 独立監査で、同じ画素digestを持つ複数xref（未描画resourceを含む）があると、PyMuPDFの配置xref照合が曖昧になることを再現した。photoでは全resourceを照合して曖昧な画像群を除外し、低DPI配置を誤って縮小する経路を回帰テストで保護した。
- 最初の全PDFテストで旧config hashの固定値期待が失敗した。診断・候補選択変更のため`processing_schema=2`で旧結果を意図的に無効化する契約に合わせ、期待値と理由を更新。検査自体を無効化していない。
- 非可逆候補の後は、品質合格でも原本由来の可逆候補を比較する。合格した最小候補を採用し、同サイズなら可逆を優先する。
- 仕上げ時にHEADが`640165bd82cbb6160e49e642ccfc11a0d38cc144`へ進み実装がcommit済みであることを確認した。この作業ではcommit/pushを実行していない。以降は検証記録だけを追記した。

### Implementation Validation Evidence

2026-09-08、リポジトリルートから実行。合計438 tests passed。

| 検査 | 結果 |
|---|---|
| `uv run --project pdf-shrink python -m pytest -q pdf-shrink/tests` | 131 passed |
| `uv run --project media-shrink-tool --extra dev python -m pytest -q media-shrink-tool/tests` | 64 passed |
| `uv run --project video-shrink python -m pytest -q video-shrink/tests` | 104 passed |
| `orchestrator`内で`uv run --with pytest python -m pytest -q` | 139 passed |
| AGENTS.md指定の4つの`compileall` | 全てexit 0 |
| root CLIとPDF CLIの`--help` | exit 0、写真パターン指定を確認 |
| `git diff --check` | exit 0 |

`archify`でJSON検証・HTML再生成・visual-checkを実施。showcase 9/9、errors/warnings 0。
1440×900、1600×1000、1920×1080、2048×1320でoverflowなし。
最小・最大viewportのlight/dark計4 PNGは担当agentと主agentが目視し、切れ・重なり・読めないラベルなし。
自動visual-check JSONの`visualReview: pending`はツール出力のまま維持し、この段落を目視完了記録とする。
JSON SHA-256は`c8c215ca9cc570d2cf6cef77639dd1179ec726aa4fd977ad90587378ab2e9a46`、
HTMLは`8c3d74c75dac346994fcd5b9f82472477606242af4716f69e70d6451726980d8`。
生成時のsource基準は`7069b0a0b740ab47d6f83e28aefbb3dabe7cae0a`であり、写真機能は当時の作業ツリー実装、ソースリンクは変更前commitと図中に明記した。旧`karufile-runtime.html`は変更していない。

### Real-data Pilot

入力: `C:\Users\tn\Downloads\西牧分遣所アスベスト調査報告書`。
既存通常出力とそのreport/stateを保持するため、新規の別parentへ出力した。

```powershell
uv run --script karufile.py -i 'C:\Users\tn\Downloads\西牧分遣所アスベスト調査報告書' -o 'C:\Users\tn\Downloads\KaruFile_写真検証_20260908\西牧分遣所アスベスト調査報告書_軽量化' --pdf-photo-pattern '2.*.pdf' --pdf-photo-pattern '5.*.pdf'
```

- 初回exit 0、16.22秒。写真2件採用、3件原本採用。5件合計8,542,212 → 7,092,052 bytes、1,450,160 bytes（16.98%）削減。
- 同じコマンドの再実行exit 0、0.77秒。処理対象0・再利用5。CSVのprofile・候補診断も保持。
- 別parent `C:\Users\tn\Downloads\KaruFile_写真検証_20260908\dry-run\files` への同じ写真指定付き`--dry-run`もexit 0、2.19秒。写真2件だけ`photo / DRY_RUN_LOSSY`、残る3件は`standard / DRY_RUN_LOSSLESS`。完成PDFと`files`ディレクトリは作成されず、全行output_size空。入力5件および既存通常Pilot配下12ファイルの実行前後SHA-256が全て一致。新規作成は別parent内のstate DBとdry-runレポート類のみ。
- report: `C:\Users\tn\Downloads\KaruFile_写真検証_20260908\report.csv`。

| PDF | profile / 結果 | 原本bytes | 出力bytes | 非採用時の候補bytes / 採用時の削減率 |
|---|---|---:|---:|---:|
| 1.現地調査報告書 | standard / UNCHANGED | 340,536 | 340,536 | 279,191（削減61,345 bytesで64 KiB未達） |
| 2.現地写真 | photo / ADOPTED_LOSSY | 3,556,324 | 2,674,925 | 24.78% |
| 3.試料採取箇所 | standard / UNCHANGED | 588,304 | 588,304 | 570,958（削減17,346 bytesで64 KiB未達） |
| 4.分析報告書 | standard / UNCHANGED | 1,517,266 | 1,517,266 | 1,477,813（削減39,453 bytesで64 KiB未達） |
| 5.採取写真 | photo / ADOPTED_LOSSY | 2,539,782 | 1,971,021 | 22.39% |

写真2冊はそれぞれ28/20画像が変更され、出力の配置DPIは約200.000〜200.210。
5件全てで入力SHA-256とreportのsource hash、出力SHA-256とreportのoutput hashを照合して一致。
全ページの抽出テキストと`get_drawings()`の比較も原本と一致した。これはOCR精度の検証ではない。
完成PDFの写真2冊の先頭ページと採取写真の黒板領域を描画して目視し、右側注記・罫線と確認した黒板文字を確認した。
診断PNG（`2-output-page1.png`、`5-output-page1.png`、`board-output.png`）は検証parent内に残した。

### Implementation Outcomes / Remaining Limits

- 実装・統合検証・限定実資料Pilotは完了。入力と既存完成出力を変更・削除していない。
- HTML往復は不採用。今回確認したPyMuPDF HTML抽出ではpath注記が欠け、公式資料もフォント・配置の制約を説明する。SVG対応を含む全ての変換器が失敗すると一般化はしない。
  参照: [PyMuPDF HTML品質の制約](https://pymupdf.readthedocs.io/en/latest/app1.html#controlling-quality-of-html-output)、[pdf2htmlEX](https://github.com/pdf2htmlEX/pdf2htmlEX)。
- 写真対象は利用者によるファイルパターンの明示選択。図面、分析写真、画像内文字を意味で自動判別しない。300 DPI以下をOCR不要とは判断しない。
- 200 DPI q80は今回の閲覧用候補であり、普遍的な最適値や全ての細字の可読性を保証しない。OCRは未実施。提出・印刷などの用途別受入は原本との比較が必要。
- 300 DPI細部検査には80,000,000 pixels、120秒、10,000配置の予算上限がある。時間上限は描画呼出し間で確認し、単独のMuPDF呼出しを強制停止するものではない。予算超過は候補棄却として扱う。

## 追加調査: HTML以外の方式（2026-09-08）

利用者の「ではやめる。べつの方法を検討してほしい」はHTML案の取り下げと別方式の調査依頼として扱う。
製品コード、既存PDF、設定、依存関係は変更しない。調査記録だけを追記する。

### CP-008: 解像度変更以外の候補比較

- Status: Complete
- Objective: 既存200 DPI方式とは別の改善を、適用範囲・削減根拠・可読性リスクで比較できる。
- Dependencies: CP-007の候補診断と現行コードを再確認する。
- Files or components: qpdf/config/worker/root、Pilot CSV、GitHub Stars catalog、一次資料。
- Actions: 可逆候補採用条件、JPEG係数の可逆最適化、領域別/MRC、別PDFエンジンを比較する。
- Completion criteria: 実測済みと未測定を区別し、最小の次の検証案を提案する。
- Validation: 現行コード行、CSV数値、現在の公式資料、git diff --check。
- Failure conditions: 未測定の削減率保証、画素変換を可逆と誤称、未承認の製品変更。
- Recovery: 読取り調査に限定し、実装や出力を変更せず未確認点を明示する。

### CP-008 Findings / Decision

新しい圧縮方式として最初に試すのは、JPEGのDCT係数を変更しない可逆符号化最適化。
低コストで別途改善できるのは、検証済み可逆候補の採用閾値。大幅削減の仮説は、保護領域を明示した画像内ROI圧縮。
今回はどの方式も製品へ実装・導入していない。

1. **JPEG可逆最適化（次の試験候補）**
   - 現行はJPEGを画素へ展開してJPEG再符号化する。候補として`jpegtran`のentropy最適化／progressive再構成を追加すれば、量子化係数と画像寸法を変更しない経路を分離できる。
   - MozJPEG公式READMEとmanpageはこの可逆処理を説明している。`cjpeg`での再量子化や品質変更とは異なる。
   - 最初の実験では原JPEG、baseline最適化、progressive最適化を独立比較。色関連markerを含むmetadataとPDF画像辞書を保持し、算術符号化・グレースケール化・切抜き・回転は使わない。小さくなる保証はない。
   - DCT係数保持に加え、同一decoderでの画素比較、全ページ描画、画像色空間、既存文字・パス、qpdf検証、Reader/Edgeでの表示・印刷を確認する。一般的なJPEG対応と全PDF閲覧環境の互換性を同一視しない。
   - `jpegtran`/`cjpeg`は現在PATHに見つからなかった。実ファイルでの追加削減率と実行時間は未測定、依存追加なし。
   - 根拠: [MozJPEG README](https://github.com/mozilla/mozjpeg/blob/master/README.md)、[jpegtran manpage](https://github.com/mozilla/mozjpeg/blob/master/jpegtran.1)。[LICENSE](https://github.com/mozilla/mozjpeg/blob/master/LICENSE.md)はIJG/BSD系の適用範囲と通知条件を区別する。[BUILDING](https://github.com/mozilla/mozjpeg/blob/master/BUILDING.md)も確認したがWindows配布物の選定・再配布承認は未実施。

2. **可逆候補の採用閾値（新コーデックではない、小さな改善）**
   - 現行`ReductionOptions`とroot照合は64 KiBかつ2%。Pilot CSVを現在読み直し、1・3・4はそれぞれ61,345 / 17,346 / 39,453 bytes、18.0142 / 2.9485 / 2.6003%の可逆候補があり、64 KiB条件だけで棄却されている。
   - 例えば16 KiBかつ2%なら3候補とも採用条件を満たす。追加118,144 bytes（115.375 KiB、全入力の1.3831%）。既存200 DPI出力に追加した場合の合計削減率は算術上18.3595%だが、新しい完成出力は生成していない。
   - 「現地調査報告書が18%減る」と「全5冊が18%減る」を混同しない。単独の閾値変更だけで全体の大幅削減にはならない。
   - 実装する場合はconfigだけでなくrootの採用結果照合、state/config hash、テスト、仕様を同時更新する。画質検証基準は緩めない。

3. **画像内の領域別圧縮（ROI、次段階の仮説）**
   - 黒板・細字等の利用者が指定した領域を元の復号画素で別画像として保持し、それ以外の許可領域だけ強く圧縮する。既存のページ文字・パスは変更せず、OCR結果から文字を描き直さない。
   - 全ページを文字/背景へ再分離するMRCとは区別する。既に文字・線・写真が分離しているPDFをラスタライズして再構成する案は優先しない。
   - 保護漏れ、座標変換、境界の色差/継ぎ目、マスクと共有画像、保護画像追加による容量増を確認する必要がある。初期は明示矩形だけ、分析・顕微鏡写真や意味不明の細部を自動で圧縮許可しない。
   - この資料でのサイズ・品質は未測定。手間に見合う追加削減がなければ採用しない。
   - [ABBYYのMRC説明](https://support.abbyy.com/hc/en-us/articles/360016544840-How-highly-compressed-MRC-PDF-export-works-in-FineReader-Engine-12)は層別圧縮の参考。説明中の背景除去や文字テンプレート化はその実装の処理であり、MRC一般の必須条件とは扱わない。

### その他の比較候補と優先度

- **JPEG2000/JPX**: 寸法を保った画像だけのcodec比較は可能。可逆モードでも元JPEGより小さくなる保証はなく、非可逆なら細部・色は変わり得る。PDF 1.5以降の機能と閲覧・印刷互換性を検証する必要がある。JPEG可逆最適化より後の試験候補。[Adobe仕様](https://opensource.adobe.com/dc-acrobat-sdk-docs/library/pdfcreation/PDF_Create_UsingSettings.html)
- **Ghostscript pdfwrite**: 原則ベクター出力だが、元のPDF内部構造を維持するものではない。描画以外の情報の保持と色変換等を別検証する必要があり、今回の最小案にはしない。新規JPX圧縮には非対応で、既存JPXのpass-throughとは異なる。既存Windows PATHにgs10.05.1があることだけ確認し変換は行っていない。[公式](https://ghostscript.readthedocs.io/en/latest/VectorDevices.html)
- **Flate/Zopfli**: 現行qpdfは既にFlate level9・再圧縮・object stream生成を使用。Zopfliには時間増と小さな追加圧縮のtradeoffがあり、JPEG本体を最適化する代替ではない。ローカルqpdf12.3.2の`--zopfli`はexit1、`zopfli support is not enabled`。新build導入は見送る。[qpdf公式](https://qpdf.readthedocs.io/en/stable/cli.html#zopfli-compression-algorithm)
- **JBIG2**: MRCと非可逆JBIG2は同義ではない。OCRmyPDF現行公式は文字置換リスクにより非可逆JBIG2を削除し、可逆方式を説明している。数値を扱う本資料で文字テンプレート置換を提案しない。[公式](https://ocrmypdf.readthedocs.io/en/latest/jbig2.html)

### OSS catalog確認

`github-stars-oss doctor --smoke` PASS。4,052件、snapshot2026-08-19、約20日前。
PDF圧縮/JPEG可逆/層別圧縮の概念語で検索後、1回だけcodec名とqpdf等で絞り直した。
低レベルJPEG候補は検索で発見できなかったため、主agentの判断でStar外のMozJPEG公式も比較した。
カタログ内で見つからないことをStarの不在証明にしない。
3件をenrichしrepo_id一致・非archived・README/実LICENSE/manifestを確認、直接導入なし。

| repository / repo_id | usage_mode / 判断 | 根拠・適合性 | ライセンス・未確認/リスク |
|---|---|---|---|
| libjxl/libjxl / 340219494 | reference_implementation / reference_only | [README](https://github.com/libjxl/libjxl/blob/main/README.md)は既存JPEGの可逆JXL化とJPEG復元を説明、CMake実装 | [BSD-3-Clause](https://github.com/libjxl/libjxl/blob/main/LICENSE)と[PATENTS](https://github.com/libjxl/libjxl/blob/main/PATENTS)確認。通常PDFへのJXL埋込互換性は未確認。元JPEGに復元して戻すだけでは縮小効果が残らない |
| Stirling-Tools/Stirling-PDF / 594155488 | reference_implementation / reference_only | [圧縮仕様](https://docs.stirlingpdf.com/Functionality/Compress/)のrecipe参考、Java/Spring Bootの追加アプリ導入はしない | [root LICENSE](https://github.com/Stirling-Tools/Stirling-PDF/blob/main/LICENSE)に例外、[engine LICENSE](https://github.com/Stirling-Tools/Stirling-PDF/blob/main/engine/LICENSE)は独自条件。実資料効果・利用条件適合は未検証、一律MIT扱いしない |
| gotenberg/gotenberg / 126493684 | standalone_tool / reject | [README](https://github.com/gotenberg/gotenberg/blob/main/README.md)はGo/Docker変換API。既存PDF圧縮改善を裏付ける証拠不足 | [本体MIT](https://github.com/gotenberg/gotenberg/blob/main/LICENSE)、外部engineは別途確認が必要。追加サービス運用に見合う削減未確認 |

### CP-008 Validation / Outcome

- 現行コードとPilot CSVを再読込し数値再計算。独立agentが入力5件と出力5件の現在SHA-256をCSVと照合し全て一致。
- 製品コード・依存関係・PDF出力は変更なし。JPEG/JPX/MRC/Ghostscriptの追加実行結果はない。過去438テスト成功を今回の新方式の検証成功とは扱わない。
- 調査記録の`git diff --check`成功。次の最小行動は写真2冊のJPEG可逆最適化を原本から独立試験し、元画像と一致かつ実際に小さい候補だけを評価すること。実装依頼はまだ受けていない。
