# PDF圧縮方針の調査と実データ診断

この文書はliving documentである。前半は調査時点の記録。2026-09-08に利用者から実装指示を受け、末尾の実装チェックポイントを実行中。

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

## 推奨する実装順序（未実装）

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

## Outcomes / Remaining Issues

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
- photoはJPEGの寸法縮小だけ、quality80、200未満を拡大・再圧縮しない。文字、パス、1bit、非JPEG、マスク付き画像を保持する。
- photoでは共有xrefの全配置の軸別最小DPIから寸法をceil計算し、200 DPI未満へ落とさない。既存presetの300 DPI最大値方式は維持。
- photoの採用下限は64 KiBかつ5%。既存standard/compactの閾値と256 KiB未満skipは維持。
- 非可逆候補の品質棄却・削減不足では可逆候補も比較する。構造・I/O・toolエラーを成功へ隠さない。
- reportのprofile列を必須としてrootで実行条件と照合する。候補記録を加え、config schemaを更新して古いstateを再処理する。
- PDF→HTML→PDFは今回は採用しない。PyMuPDF HTML抽出で現地写真/採取写真の先頭ページはimg3個のみ、元の47/68個のpathと右側注記を保持しないことを確認。SVG対応変換もあるが、今回の画像圧縮目的に往復変換を加える利点は確認できない。

### CP-004: 結果・state・report

- Status: In progress
- Objective: 候補値と棄却理由を再実行後も確認できる。
- Dependencies: CP-001〜003。
- Files or components: models/state/report/runner、関連テスト。
- Actions: typed candidate、additive SQLite migration、CSV診断列、理由summary。
- Completion criteria: 旧DB移行と候補の保存・再読込・CSVが成功し、実行profileを誤再利用しない。
- Validation: migration/CSV/再利用テスト。
- Failure conditions: 旧記録消失、候補と完成出力の混同。
- Recovery: 原本保持、additive migration、未完了をstate再利用しない。

### CP-005: 写真候補と検証

- Status: In progress
- Objective: 写真画像のみを縮小し、細部差を検査する。
- Dependencies: CP-004の型契約。
- Files or components: config/inspect/transform/validate/worker、関連テスト。
- Actions: opt-in recipe、共有画像保護、300 DPI領域tile比較、可逆fallback。
- Completion criteria: 284→約200、119維持、マスク/1bit/パス保持、候補棄却とtool errorの区別が確認できる。
- Validation: 代表fixture、既存PDF suite。
- Failure conditions: 対象外劣化、無制限render allocation、破損を成功扱い。
- Recovery: 原本または検証済み可逆候補を採用、実障害はERROR。

### CP-006: root CLIと契約文書

- Status: In progress
- Objective: rootから選択対象にだけ写真設定を適用し、結果を正確に集計できる。
- Dependencies: CP-004、005。
- Files or components: orchestrator、PDF CLI、MANUAL/REFERENCE/README/AGENTS。
- Actions: pattern配管、profile照合、実行例と制約更新。
- Completion criteria: 指定対象以外は従来のprofile、stale profileは拒否、helpと文書が一致。
- Validation: orchestrator suite、CLI help、文書照合。
- Failure conditions: 画像動画の動作変化、未実装CLIの文書化。
- Recovery: 既定値を維持しprofile設定をopt-inへ限定。

### CP-007: 統合検証・実資料確認

- Status: Not started
- Objective: 要求されたCLI動作と残る画質限界を確認して引き渡す。
- Dependencies: CP-004〜006。
- Files or components: 全suite、検証用出力、実資料5 PDF。
- Actions: 全suite/compile/help/diff、写真2冊の別出力Pilot、原本hashと代表箇所確認。
- Completion criteria: 必須検査成功、候補と実出力値・棄却理由を確認、未確認のOCR精度を明示。
- Validation: test counts、CSV、hash、目視記録。
- Failure conditions: 原本変化、テスト不合格、未検証を保証。
- Recovery: 原本・既存出力は維持し、問題を修正して影響範囲だけ再検証。
