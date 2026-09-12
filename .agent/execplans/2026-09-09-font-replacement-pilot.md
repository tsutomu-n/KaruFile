# 日本語フォント統一の1ファイル実験

この文書は2026-09-09〜10の独立した1冊試験を記録した履歴資料。この試験の範囲では、通常のKaruFileのフォント非置換契約を変更しなかった。本文の「未変更」「製品実装は範囲外」は当時の範囲を示す。

その後の「実装して」に基づく通常CLIへの機能化は完了している。現行の実装・検証結果は
[2026-09-10の製品実装計画](2026-09-10-windows-font-replacement.md)を参照する。

## Goal / Acceptance criteria

ユーザーが明示許可した「共通の日本語フォントへ置換し、必要な文字だけ埋め込む」方法を写真管理要領1冊で実測する。原本を残し、文字内容・配置・図表を検証した別名の試験PDFと、容量・検証範囲を届ける。製品機能としての対応完了は主張しない。

## Facts / Inferences / Assumptions / Unknowns

- Facts: 対象はDownloadsの群馬県建設工事必携（R5年版）内の`Ⅱ-7_群馬県土木工事写真管理要領（R7.10改定）【最新版】.pdf`、101ページ、7,436,386 bytes。元のフォントを保つ整理候補は4.874%減だった。
- Facts: 既存の未コミット変更は白黒スキャン機能等。今回の1ファイル実験への明示指示は、通常契約の非置換方針に対する実験範囲での例外を許可する。
- Inferences: 個々のPDFフォント辞書を保っても、字体データを共有すれば容量を減らせる可能性がある。
- Assumptions: 字体の変化を許容し、文字内容、ページ数、元の配置、画像・図形・リンク等を維持する。対応できない文字を推測で置き換えない。
- Facts (実験後): Noto Serif JPのローカルcmapに「岸」がなく停止し、Noto Sans JPへ切り替えた。42フォント資源を共通のstatic TTFへ置換。963種類の文字、980幅別glyph、TTF 242,344 bytes。PDFは4,068,905 bytes、45.2838%減。
- Unknowns: 実機印刷・全ビューアー互換性、他のPDF構造への一般化。今回は全字の人手校正は行っていない。

## Options / Risks / Stop conditions

元内容streamを保つフォント資源置換を優先。全ページの文字削除・再描画や全体画像化は不必要な変更が広い。共通TTFのglyphは文字と元advance幅の組ごとに生成し、PDF幅とフォント幅の整合を保つ。曖昧なUnicode、非対応符号化、欠字、原本変化があれば候補を採用しない。入力・既存出力の削除、外部送信、commit/push、製品全体への実装は範囲外。

## Checkpoints

### CP-001: 対象と字体方式
- Status: Complete
- Objective: 元の文字コードと配置を保持できる方式を確定。
- Dependencies: 元PDF、既存分析、ローカルのフォント、PyMuPDF。
- Files or components: 元PDFread-only、独立試験script、fontTools一時環境。
- Actions: 全フォント辞書・CMap・幅・共有資源を確認。独立技術レビュー。
- Completion criteria: 対応範囲、未対応文字、置換対象を具体化できる。
- Validation: 実物のマッピングとtarget glyphの存在を照合。
- Failure conditions: 対応が曖昧、対象外の複雑構造。
- Recovery: 対象fontを維持、または候補不採用として報告。

### CP-002: 1冊の候補作成
- Status: Complete
- Objective: 使用文字を共通の埋込字体へ対応させた別PDFを生成。
- Dependencies: CP-001。
- Files or components: 既存output-parentの`font-replacement-trial/`。
- Actions: 必要glyphだけのTTF、幅対応、CMapを生成。原本由来の別候補をqpdfで整理。
- Completion criteria: 再読込可能な1冊の候補とサイズ結果がある。
- Validation: qpdf check、全mapped glyph、参照、幅一致。
- Failure conditions: 欠字、構造エラー、処理中の原本変化。
- Recovery: 原本維持。実験候補のみで止める。

### CP-003: 検証と配布
- Status: Complete (1冊の試験版として)
- Objective: 内容・配置・表示と容量の結果を確認して届ける。
- Dependencies: CP-002。
- Files or components: 検証JSON、PNG、試験PDF、実験script。
- Actions: 全ページのtext/文字原点/geometry/content streams/画像等を比較。全ページレンダー、代表拡大を目視。別rendererも可能な範囲で確認。
- Completion criteria: 欠字・配置破綻を検出する検証結果、目視証拠、容量、未検証範囲がそろう。
- Validation: source SHA前後、独立レビュー、script compile、diff-check。
- Failure conditions: 文字欠落・明確なはみ出し等。
- Recovery: 修正または不採用。試験版の限界を明記。

## Progress / Decisions / Validation / Outcomes

## 2026-09-10: Windows 11 游ゴシック版の追加1冊試験

利用者は既定候補をWindows 11にあるフォント、日本語・英語に絞り、同じ1冊を游ゴシックで確認する説明に対して「つづけて」と指示した。追加承認はこの1冊の試験。製品への組込み、他の冊子への適用は含めない。出力は既存の兄弟ディレクトリ `font-replacement-yugothic-trial/` とし、前回Noto試験を残す。

Facts: 游ゴシックはこのPCに存在し、前回必要な963 Unicode文字に対応。TTC、2048 units/em、fsType=8。前回scriptは1000 units/em、fsType=0に限定し、字形と幅を再構築するためそのまま流用できない。Microsoft公式FAQは文書埋込の許可とfont改変を区別する。新試験では通常subsetで使用glyphを限定し、輪郭・hmtx・埋込権限を保つ。元字送りとの調整はPDF側の描画命令で行い、変更範囲を独立検証する。未検証の削減率を前回45.28%から推測しない。

### CP-004: 游ゴシック版の生成
- Status: Complete
- Objective: Windowsフォント実体の輪郭・幅を加工せず、同じ1冊の別候補を作る。
- Dependencies: CP-001〜003の実物、Windowsインストール済フォントと埋込権限。
- Files or components: 新しい独立試験ディレクトリ、既存PyMuPDFと一時fontTools/pikepdf環境。
- Actions: fontをサブセット埋込し、PDF幅と配置命令を調整。qpdf整理とcheck。
- Completion criteria: 原本/旧試験が不変で、再読込可能な候補と生成記録がある。
- Validation: fsType/輪郭/hmtx保持、文字対応とPDF幅を独立照合。入力SHA。
- Failure conditions: 欠字、曖昧な対応、想定外のPDF命令、フォントの権限制限、原本変化。
- Recovery: 原本と旧試験を維持。新候補を完成扱いにしない。

### CP-005: 游ゴシック版の検証・納品
- Status: Complete (試験版として。検索・コピーの推定空白差は既知の制限)
- Objective: 文字内容と配置・図表を保った試験版と実測値を届ける。
- Dependencies: CP-004。
- Files or components: 新試験の構造/font/render検証JSON、PNG、最終PDF。
- Actions: 全101ページの文字Unicodeと原点（最大差も記録、許容0.02 pt）、非文字描画命令・画像decoded pixels・geometry・リンク等を比較。全ページを2 rendererで描画し、一覧と代表拡大を目視。
- Completion criteria: 欠字・配置破綻・図表変更がなく、小さくなった候補のSHA付き検証結果と限界がそろう。
- Validation: 検証済候補を別名へatomic保存しSHA再照合。原本・旧試験・既存完成出力のSHA。script compile、git diff --check。
- Failure conditions: 文字欠落、原点許容超過、画像変化、明確な重なり等。
- Recovery: 原因修正または試験不採用として報告。期待値や許容値を安易に緩和しない。

Decision: 全ページ画像化や文字削除・再描画を避け、既存の文字コード対応を活かしてtext-show命令だけを調整する。通常CLIの非置換契約とruntime/lockfileは変更しない。初期のNoto試験記録は以下に保持する。

2026-09-10生成前レビュー: 原本にはTr=2（fill+stroke）がある。文字ごとのTz変更は1回の描画を分割し重なり順を変える懸念があるため採用しない。元Tj/TJの単位を保ち、自然幅と元幅の差を同じTJ配列に挿入して字送りだけを補正する。Tf/Tz/Tc/Twを維持し、游ゴシック本来の字形・字面幅を使用する。これは前回Notoの横幅フィットとは異なるため、文字原点と文字列の一致に加え、はみ出しや重なりを表示検証で確認する。

2026-09-10初回不合格と修正: 小数Wをそのまま書いた候補4,273,688 bytesは、72ページの長い空白列で最大0.135864 ptの累積ずれがあり不合格。MuPDF/PDFiumがWを整数として読み取ることを一次ソースで確認。フォントの輪郭/hmtxはそのまま、PDF Wを1000em単位の最寄り整数へ変換し、その同じ値からTJ補正を計算する互換性修正を実施した。PDF仕様が小数Wを禁止するという理由ではない。旧候補・検証記録・生成scriptを保持。

整数W候補は4,270,674 bytes（42.570571%減）、SHA-256 `e143fe71d6427ed159c40de6f5faaabbfa514aaa9377e9fa434eb626170b1805`。独立検証で963 Unicodeの輪郭/hmtx/fsType=8をWindows実体と厳密比較して一致。4,073 CID対応のWは最寄り整数と一致し、自然幅との差は最大0.23046875/1000em。構造validatorと0.02pt閾値は初回から変更せず、全101ページ・51,471描画文字（fill/strokeを含む）で合格、原点最大差0.0001220703125pt。20画像のdecoded pixels、Tj/TJ以外の全演算子、図形/幾何/リンク/metadata等も一致。全101ページをMuPDF/PDFiumで144 DPI描画。

文字抽出の診断完了: 元PDFの描画文字列は半角空白も含め一致するが、字体の字面変更により抽出器の空白・改行推定が変わる。MuPDF get_textは14ページで空白・改行差（非空白文字は全101ページ一致）。PDFiumは11ページで生成空白の省略15個・追加4個、非空白41,835文字は全ページ一致。4ページの`30fps程度`が`30f ps程度`となる実例あり。その不一致をrender記録から消さず`pdfium-extraction-diagnosis.json`へ保存。文字消失とは区別し、検索・コピー結果の完全一致を保証しない。

CP-005完了: 全ページ一覧、4/12/27/48/49/91/92ページの代表300 DPI拡大とPDFium代表画像を2担当で確認し、確認範囲に欠字・大きな崩れ・字画接触なし。検証済候補を`写真管理要領_游ゴシック統一_試験版.pdf`へ一時ファイル＋os.replaceで保存し、SHA一致。原本23件・既存完成18 PDF・旧Noto版・Windows fontの計43件のSHA不変。最終状態は`ONE_FILE_WINDOWS_FONT_TRIAL_SAVED_WITH_EXTRACTION_DIFFERENCES`。試験script compileとgit diff --check成功（既存LF/CRLF警告のみ）、通常runtime未変更のため全製品テスト未再実行。通常機能の実装完了や利用者による正式採用とは扱わない。

- PDFとexecplanスキルを適用。PDF authoring markerを成功させてから候補生成を開始。
- CP-001: 全Type0はIdentity-H/CIDFontType2、ToUnicodeは単一BMP文字。simple17個はASCII WinAnsiで同じ旧TTFを共有。残るTimes New Romanは非埋込の空白だけ。Form/OCG/annotation/widgetなし。共有字形をUnicode＋元advanceの組で生成し、Wとhmtxを整合させた。
- CP-002: Shift-JISのFontName/CMapNameを含む原本を厳密なmapping部分と分けて処理。Noto Serif JPで欠字を検出して候補生成前に停止し、Sansへ切替。原本由来のcandidateをqpdfで整理し、check成功。製品runtimeとlockfileは変更なし。
- CP-003: 全101ページの文章、Unicode、文字原点（差0 pt）、方向、サイズ、色、描画方式等が一致。元content streams・geometry・paths・画像配置・links・toc・metadata等も一致。最終font mapping・GID・W/hmtx・原幅を独立検証してPASS。画像raw6点の差は圧縮方式の変更で、20点全件decoded一致を別途確認。最初のstrict raw MISMATCH記録を消さず、最終result.jsonで判断を記録した。
- 全101ページをMuPDF/PDFiumの2系統、144 DPIでレンダーし、PDFiumの文字・原点にも不一致なし。全ページcontact sheet、4/12/49ページ全体、4/12/27/49ページの300 DPI拡大を目視。確認範囲で文字抜け・重なり・表の破綻なし。Poppler CLIは未導入でpdftopngのbuildも失敗したため、MuPDF/PDFiumを使用。
- 原本23件・既存出力18 PDFのSHA一致。検証した候補を別名`写真管理要領_フォント統一_試験版.pdf`として一時ファイル経由で保存し、SHA再一致。試験出力は1冊のみ。
- 証拠: `C:/Users/tn/Downloads/群馬県建設工事必携（R5年版）_軽量化/font-replacement-trial/`内のREADME.md、result.json、generation.json、font-validation.json、structural-validation.json、render-validation.json、visual-check/。
- 検証scriptのcompileと`git diff --check`は成功（GitのLF/CRLF警告のみ）。通常runtimeの変更がないため全製品テストは再実行していない。
