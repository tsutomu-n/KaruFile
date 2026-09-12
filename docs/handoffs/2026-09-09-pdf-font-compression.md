# 引継ぎ：KaruFileのPDF圧縮とWindowsフォント統一機能

> **現行仕様への更新（2026-09-10追補）**：フォント置換は明示したPDFだけに適用し、置換先はメイリオが既定です。
> `--pdf-font-replace-pattern`だけでメイリオを使い、`--pdf-font-family yu-gothic`で游ゴシックを選べます。
> 下記の101ページ・游ゴシックの数値は当時の検証記録です。メイリオの実1冊・既定化は
> [西牧PDFの記録](../../.agent/execplans/2026-09-10-nishimaki-pdf-compression.md)、
> 現行手順は[マニュアル](../../MANUAL.md#日本語英語のpdfをメイリオへ統一する)を参照してください。


作成日：2026-09-09。最終更新：2026-09-10。**参照可能な会話範囲に基づく引継ぎ**であり、会話の全履歴を取得したものではない。現行作業ツリー、実物の試験記録、その後の「実装して」の指示に基づく。

**当時の到達点：通常CLIのWindows游ゴシック置換機能を実装・検証済み。同じ101ページ1冊を通常CLIで7,436,386 → 4,265,318 bytes（42.64%減）にし、原本保持・再開・dry-runも確認した。明示指定だけに適用する。字体・太さの変更とコピー・検索の推定空白差は残る。全18冊への字体置換は実施していない。**

## 1. 目的と固定条件

目的は、利用者のPDFを原本を残して小さくすること。直近の具体的対象は「群馬県建設工事必携（R5年版）」フォルダー内のPDFと、そのうちの1冊を使ったフォント置換試験である。他案件の開発履歴や動画・画像ツールの改修は本書の対象外。

- 原本を変更・削除せず、別の出力に保存する。既存の完成出力や未コミット変更も維持する。
- 最初の承認は**1ファイルの試験**。その後の「実装して」で通常CLI機能化も承認された。通常profileの非置換を維持し、`--pdf-font-replace-pattern`で明示したPDFだけ字体変更を許可する。
- 字体の変化を伴うため、今回の試験版を可逆圧縮や原本と同じ見た目の成果と表現しない。
- commit、push、PR、外部公開、原本削除の承認はない。本書の作成依頼も、それらや追加圧縮を許可するものではない。
- 本書は通常のUTF-8 Markdown。専用のCodex状態形式や独自writer／validatorの契約を採用したものではない。

対象冊子の正確な名前は **`Ⅱ-7_群馬県土木工事写真管理要領（R7.10改定）【最新版】.pdf`**、101ページ。フォルダー名の「R5年版」と、実際のファイル名の「R7.10改定」を混同しない。フォルダー全体の版を一律にR5と判断したり、異版を重複として扱ったりしていない。

## 2. 利用者の決定とAI提案の区別

| 事項 | 現在の扱い・理由・条件 |
|---|---|
| 指定フォルダーの圧縮 | 利用者の依頼。通常CLIを実行したが、18 PDFすべて原本保護となった。 |
| 共通の日本語フォントへ統一し、必要な文字だけ埋め込む試験 | AIの提案に対し、利用者が「それで試してみよう。ためしに1ファイルだけ」と明示承認。写真管理要領で実施した。 |
| Noto Sans JPという具体的な字体 | 必要文字の対応を確認したうえでのAIの実験上の選択。利用者が既定フォントとして指定したものではない。 |
| 試験版の利用者による採用 | ファイルは納品済みだが、利用者が見た目を確認して正式採用した発言は参照範囲にない。 |
| 游明朝、MS明朝などへの変更 | 利用者は「Noto Sans JP以外にはないの？」と質問。候補を回答しただけで、追加生成や特定字体の選択は未決。 |
| Windows 11搭載フォント、日本語・英語への限定 | 利用者の条件。游ゴシックRegularで同じ1冊を試し、その後の実装指示により、明示置換profileの既定字体にした。 |
| qpdfだけを実行する経路の追加、候補許可と検証予算の分離 | 調査後のAI提案。利用者の採用決定や製品実装はない。 |
| 通常CLIへの製品機能化 | 利用者が「実装して」と明示指示。明示patternによる置換、未対応時の原本保護、独立検証・状態記録を実装。 |
| 18冊すべてのフォント置換、自動的な字体変更 | 未実施。製品化の承認を一括再圧縮へ拡張しない。 |

引継ぎ文書の作成だけを理由に新しい設計判断は追加していない。9月10日の追記は、その後の利用者の指示に基づく游ゴシックの独立試験と、続く「実装して」に基づく製品実装・通常CLI Pilotの記録である。

## 3. 実装・実験・検証の状態

### 3.1 指定フォルダー全体の診断

対象フォルダーは23ファイル：18 PDF、3 DOCX、2 XLSX。PDF合計は1,317ページ、46,057,953 bytes。Office文書5件は今回のPDF処理対象外。

通常CLIの結果は18件すべて `PRESERVED_ORIGINAL`。完成出力18件は原本とSHA-256が一致し、削減は0%。記録された最初の保護理由はdrawing 12件、optional_content 2件、page_limit 4件だった。これは早期終了時の理由であり、特徴が重ならない18冊の分類ではない。

容量分析では、圧縮済みフォントstreamが26,407,995 bytes（全PDF容量の57.34%）、画像が10,706,038 bytes（23.25%）。フォント303個はすべてFlate圧縮済み、300個にはサブセット名が付いていた。この内訳は削減可能量ではなく、PDF全体を厳密に分割した値でもない。

次の候補は**診断用に生成しただけで、通常CLIの完成出力へは採用していない**。MBは10進表記。

| 試した範囲 | 原本 | 実験候補 | 状態 |
|---|---:|---:|---|
| 18冊すべて、qpdfのみ | 46,057,953 bytes | 43,650,936 bytes、5.226%減 | 全1,317ページの通常状態72 DPI描画・文字位置等が比較範囲で一致。非表示レイヤー等は未検証。 |
| 最大の管理・検査編577ページ、字体を保つsubset＋cleanup＋qpdf | 22,072,646 bytes | 20,259,949 bytes、8.212%減 | 通常状態72 DPI等の限定検証。未採用。 |
| 写真管理要領101ページ、字体を保つsubset＋cleanup＋qpdf | 7,436,386 bytes | 7,073,937 bytes、4.874%減 | 同上。後述のフォント置換試験とは別候補。 |

qpdf試験では原本2冊のcheckが終了コード3となった。確認した警告は高速表示用のlinearization hint tableに関するもので、別試験として測定した。警告を一律無視する設定は使っていない。最終候補18冊のcheckは0。ただしcheck成功を文書機能全体の同一性とは扱っていない。

診断時には、100ページ上限だけでなく、候補間で共有する600 MPの検証予算も大冊の障害と分かった。A4相当の72/300 DPI比較は1候補でも約32ページ分。上限解除だけで解決するという案や、既に行っているタイル描画を新しい解決策として繰り返すことには根拠がない。既存の通常文章profileではこれらの条件を変更していない。後から追加した`font_replace`は別の200ページ・144 DPI検証予算を使い、条件は3.5節に記載する。

### 3.2 2026-09-09のNoto Sans JP試験

| 項目 | 確定結果 |
|---|---|
| 対象 | 写真管理要領、101ページ |
| 出力名 | `写真管理要領_フォント統一_試験版.pdf` |
| サイズ | 7,436,386 → 4,068,905 bytes |
| 削減量・率 | 3,367,481 bytes、45.283838% |
| 字体 | Noto Sans JPのRegular相当を基にしたゴシック体。明朝系も置換される。 |
| 方式 | 42個のフォント資源を、963種類のUnicode文字・980個の幅別字形を持つ共通の埋込TTFへ対応させる。TTFは242,344 bytes。 |
| 保持したもの | 元のページ描画命令、文字コード対応・字送り・文字原点、画像に焼き込まれた文字。空白だけを担当する非埋込Times New Roman資源1個も維持。 |

字形は元の字送りに合わせて横方向にも調整している。単にフォント名を書き換えたり、元のフォントファイルを削除したりした処理ではない。Noto Sans JPだけの性能を測定した結果でもなく、字体の共通化・使用文字の限定・qpdfによる整理を合わせた結果である。

**保存済みの検証結果：**

- 全101ページで抽出文章が完全一致。文字Unicode列、原点、方向、サイズ、色、描画方式、線幅等も一致し、原点の最大差は0 pt。
- ページgeometry、展開後content stream、図形、画像配置、リンク、しおり、metadata等が比較範囲で一致。
- 最終PDFの文字対応漏れ、GID0、範囲外GIDなし。元PDFの幅、最終PDFの幅、TTFの字送り幅が一致。独立したフォント検証はPASS。
- 画像20点の展開後データと辞書propertiesはすべて一致。6点の圧縮済みbytesはFlate再圧縮で変わり、合計181,612 bytes減少した。画像raw bytesがすべて同じという結果ではない。
- MuPDF 1.28.2とPDFium（pypdfium2 5.13.0）で全101ページを144 DPIで描画。PDFiumでも文字と原点を照合し、不一致なし。
- 全101ページの一覧、4・12・49ページの全体、4・12・27・49ページの300 DPI部分比較を目視。見た範囲で文字抜け、重なり、表のはみ出しは見つからなかった。
- qpdf check、実験scriptのcompile、当時の `git diff --check` は成功。

全字を人が校正したものではない。実機印刷、全ビューアーの互換性、全101ページの300 DPI目視は未実施。他のPDFのレイヤー・注釈・縦書きなどへの一般化も未検証。

**9月9日の本書作成時の再確認：** 出力PDFの存在・サイズ・SHA-256が保存記録と一致。元フォルダーの23ファイルと、通常CLIの完成出力18 PDFもinventoryのSHAと一致。この引継ぎ作成時には描画試験や全製品テストを再実行していない。

### 3.3 2026-09-10のWindows游ゴシック試験

同じ101ページの1冊を `font-replacement-yugothic-trial/写真管理要領_游ゴシック統一_試験版.pdf` へ保存。4,270,674 bytes、3,165,712 bytes削減、42.570571%。前回Noto版より201,769 bytes大きいが、Windows搭載フォントという条件での実測値である。

Windows `YuGothR.ttc` face 0（游ゴシックRegular）をサブセット埋込。963 Unicode、964 glyph、547,444 bytes。埋込fontの輪郭・hmtx・fsType=8をWindows実体と独立照合して一致。前回の字形再構築は使わず、游ゴシック本来の字面を保ち、PDFのTJ数値で元の字送りを維持した。42資源を共通化し、空白だけの非埋込Times New Roman 1資源は保持。

初回の小数W候補は、ビューアーがWを整数として読み取るため長い空白列に最大0.135864 ptのずれが発生し、不採用。PDF幅を自然幅の最寄り整数にし、同じ値からTJ補正を計算する修正で解消した。fontの輪郭・hmtxは変えていない。小数WがPDF仕様で禁止という意味ではない。初回候補・不合格記録も残している。

**検証済み：** 同じ構造validatorと0.02 pt基準で全101ページ合格、51,471描画文字（fill/strokeの重複を含む）のUnicode順序・位置・サイズ・色・方向が一致。原点最大差0.0001220703125 pt。Tj/TJ以外の全演算子、図形、幾何、リンク、metadata等が一致。20画像の展開後データと画素が一致。全101ページをMuPDF/PDFiumで144 DPI描画し、全ページ一覧と4/12/27/48/49/91/92ページの代表箇所を300 DPIで確認した。確認範囲で欠字・大きな崩れ・字画接触なし。全字の人手校正・実機印刷・全ビューアー保証ではない。

**残る制限：** PDF内の描画文字列は元の空白も含め一致するが、抽出器の推定空白・改行は完全一致しない。MuPDFは14ページで空白・改行差。PDFiumは11ページで生成空白が原本側15個省略・候補側4個追加、非空白41,835文字は全101ページで順序一致。具体例は4ページの `30fps程度` が `30f ps程度` と抽出されること。元の検索語・コピー文字列の完全互換を保証しない。この不一致をPASSへ書き換えていない。

最終集約は同フォルダーの `result.json`、状態 `ONE_FILE_WINDOWS_FONT_TRIAL_SAVED_WITH_EXTRACTION_DIFFERENCES`。最終PDF SHA-256は `e143fe71d6427ed159c40de6f5faaabbfa514aaa9377e9fa434eb626170b1805`。原本23件・通常出力18 PDF・前回Noto版・Windowsフォントの43件は作業前後SHA一致。通常runtime/lockfileは変更しておらず、実データ検証と試験scriptのcompile、diff-checkを実施。全製品テストは再実行していない。

### 3.4 現行リポジトリと前段の実装

KaruFileはWindowsのCLIで、通常入口は `karufile.py`、PDF処理の所有者は `pdf-shrink/`。前節までの2試験は独立script。その後の製品実装ではfontTools 4.64.0とpikepdf 10.13.0.post1をPDFの通常依存・lockfileへ追加した。pypdfium2は製品依存に加えていない。qpdfは手元の12.3.2を使用。

作業ツリーは未コミット。白黒スキャン対応のコード・テスト・文書変更が前段から残っている。これをフォント試験の新規runtime変更と誤認したり、まとめて巻き戻したりしない。

前段では、スキャン画像だけの見積書に明示的な二値化候補を加える `--pdf-text-scan-bilevel-pattern`（PDF単体CLIは `--text-scan-bilevel-pattern`）を実装済み。実資料は425,789 → 39,777 bytes、90.658%減だった。この削減率は写真管理要領や一般の文字PDFに適用できない。前段の記録ではPDF 343 passed／4 skipped、画像64 passed、動画104 passed、統合CLI250 passed、合計761 passed／4 skipped。skipは任意jpegtran実物テストの環境条件によるもの。本書作成時の再実行結果ではない。

製品実装前の前段時点では、作業ツリーの変更は主にroot/PDF/orchestratorの文書、PDFのconfig・policy・worker・text_optimize・CLI・preview、対応テスト、ExecPlan索引だった。当時は未追跡として白黒スキャン用テストと3本の関連ExecPlanが存在した。これは前段の記録であり、現行作業ツリー全体の一覧ではない。既存の無関係な変更を整理する許可はない。

### 3.5 2026-09-10の製品実装と通常CLI Pilot

入口はrootの`--pdf-font-replace-pattern`、PDF個別CLIの`--font-replace-pattern`。反復できる入力相対globで、preserve指定が最優先、他の処理許可との重複と`--safe`併用はエラー。無指定の既存profileでは字体を変えない。

Windowsの`YuGothR.ttc` face 0、游ゴシックRegularを使う。原本からqpdf単独と字体置換＋qpdfを独立生成・検証し、原本より小さい候補だけ採用。同サイズはqpdf優先。字体置換採用は`ADOPTED_LOSSY`。欠字・未対応構造は一冊を原本保護、構造破損・tool/I/O失敗は復旧コピーできても`ERROR`にする。

対応は水平符号化のTrueType（Type0/Identity-Hと単純ASCII WinAnsi）が中心。正の直交回転や描画を変えない限定的な区分情報は保持する。縦書き符号化、Form、注釈、レイヤー、特殊構造等は保護。画像化された文字の置換・OCRはしない。

現行schema 6、recipe 5。DB加算移行で旧行を残し、要求の有無・字体名・Windows字体SHA・採用出力の抽出差を全CSV/DB行へ記録。字体内容・recipe・関連library版を再開hashへ含める。上限は200ページ、原本128 MiB、字体256、表示文字と全字体mappingが各100万、本文の展開合計32 MiB、事前展開合計256 MiB、144 DPIで原本と候補合計600 MP/候補、最大2候補、共有300秒の協調的期限。通常の比較HTMLは別に100ページ上限を維持する。正確な個別stream上限はREFERENCEに記載した。

**通常CLI Pilot結果：** 101ページで`ADOPTED_LOSSY/adopted_font_replace`、4,265,318 bytes、3,171,068 bytes削減、約79.70秒。再実行は処理0件・再利用1件で状態・出力SHA・更新時刻が不変。dry-runは`DRY_RUN_LOSSY`、候補なし・通常report/出力不変。元23件、既存通常出力18件、旧試験2件、Windows字体1件の計44件はサイズ/SHA不変。

採用出力SHA-256：`edcc4f3d7caedb3d8adf6e9cc1871cb26171ca054ccfdeb776ab400d76efb132`。
保存先は診断親の`font-replacement-cli-pilot/output/`、ファイル名は原本と同じ。以前の試験版・通常出力18件は置換していない。

製品validatorに加えPDFiumでも全101ページを144 DPI描画。非空白41,835文字の順序一致、原点最大差0.000030517578125 pt。PDFium推定空白差は11ページ。MuPDF描画は以前の游ゴシック試験版と全101ページで画素一致。今回も4/12/27/48/49/91/92ページの代表部分を視覚確認した。確認範囲で欠字・大きな崩れなし。ただしRegular化で元の太字や見出しの強調が弱まる。全文校正・印刷・全ビューアー保証ではない。

最終自動検証はPDF433 passed/4 skipped、画像64 passed、動画113 passed、orchestrator321 passed。4skipは任意jpegtran実物テストの環境条件。compileall、CLI help、差分検査も成功。途中で並行作業の動画変更が現れたため保持したが、字体機能の変更とは扱わない。詳しい証拠は`docs/validation/2026-09-10-windows-font-replacement.md`と同名フォルダー。commit・pushはしていない。

## 4. 訂正・未決事項・記録を読む際の注意

### 圧縮効果の説明を訂正した点

「この資料は数％しか減らない」という説明は、字体を保つ試験範囲に限定する。字体変更を許容した1冊では45.28%減った。逆に、この1冊の値を18冊全体や別字体の予測値に使わない。

汎用のPDF意味同値検証器を新設する案は、qpdfのみで全体5.23%という効果に対して過大とAIが再評価した。これを利用者が採用した設計として再開しない。

### Noto Serif JPの「岸」に関する正確な状態

当初の「字形がない」「欠字」という表現は不正確だった。本書作成時に再確認したローカルの `NotoSerifJP-VF.ttf` は `Version 2.02;241114204555;non-release`。通常のUnicode cmap（format 4・12）には `U+5CB8`（岸）の対応がない。一方、format 14には `U+5CB8 + U+E0100 → glyph04859` がある。

したがって、今回の単一Unicode文字を対応させる処理では扱えなかったが、字形自体が一切ないわけではない。Noto Serif JP全般が利用不能と判明したわけでもない。別配布版は未確認。既存の試験READMEやExecPlanには短縮した「欠字」表現が残っているが、本書ではこの最新の実確認を採用する。既存資料は今回書き換えていない。

### 別フォントの候補

游明朝、MS明朝、IPA明朝、BIZ UD明朝、MSゴシック、メイリオは手元にあり、今回必要な963種類の文字が通常の文字対応表にあることを確認済み。前の候補調査では游ゴシック、BIZ UDゴシック等も確認した。

「原本の雰囲気を残すなら游明朝」というのはAIの提案で、利用者の選択ではない。この101ページ資料については、游ゴシック以外のWindows字体候補は出力生成・容量比較・配置/描画検証が未実施。文字収録の確認だけで、既存実験scriptがその字体にそのまま対応するとは言えない。

### 中間記録のstatus

以下は9月9日のNoto試験フォルダーの記録。9月10日の游ゴシック版は前節の別フォルダーと最終statusで区別する。

- `generation.json` の `CANDIDATE_PENDING_VALIDATION` は生成時点。
- `render-validation.json` の `RENDERED_AWAITING_VISUAL_REVIEW` は目視前。
- `structural-validation.json` の `STRUCTURAL_CHECKS_MISMATCH_NOT_ADOPTED` は画像raw bytesの差を厳密に残した初回判定。後続の `image_recompression_diagnosis` で全20点の展開後一致を確認した。
- 最終集約は同じ試験フォルダーの `result.json`、状態は `ONE_FILE_FONT_REPLACEMENT_TRIAL_DELIVERED`。中間statusだけで「未検証のまま納品」または「全バイト同一」と判断しない。

### 再実行上の注意

`replace_fonts.py` は1冊専用で、入力・出力・ローカル字体・qpdfへのパスを含み、既存の試験版PDFがあると停止する。通常の汎用CLIではない。別字体を試すために既存成果物を削除したり、停止条件を無条件に外したりしない。

Poppler CLIは試験環境になく、pdftopngの導入はビルド失敗した。実際に使った描画系はMuPDFとPDFiumであり、Popplerで検証済みとはしない。

## 5. 次の作業

依頼された製品実装と1冊の検証は完了。決定済みの追加処理はない。次に利用する場合はMANUALの明示pattern指定を使い、字体・太さ・抽出空白の変化を出力で確認する。全18冊の追加変換、別字体への切替、commit・公開はこの作業に含めない。

## 6. 必要な参照先とアクセス条件

本文には再開判断に必要な結果・条件を含めた。以下の実物は、利用者のWindowsファイルシステムまたはそのコピーへアクセスできる場合に再検証用として参照する。次の担当者が利用者PC、ローカルCLI、全会話へ到達できることは仮定しない。アクセスできない場合は本文の記録と実物未確認を区別する。

**作業リポジトリ：** `C:\Users\tn\c_projects\KaruFile`。Pythonプロジェクトは各processorに分かれ、rootに通常のPythonプロジェクトがある構成ではない。

**入力フォルダー：** `C:\Users\tn\Downloads\群馬県建設工事必携（R5年版）`。

**診断・出力の親フォルダー：** `C:\Users\tn\Downloads\群馬県建設工事必携（R5年版）_軽量化`。以下はこの親フォルダーからの相対名。

| 資料名・版 | 必要な内容 |
|---|---|
| `font-replacement-cli-pilot/output/`内の原本と同名PDF（2026-09-10製品Pilot） | 通常CLIによる最終採用4,265,318 bytes。 |
| `font-replacement-cli-pilot/`直下の`result.json`、`normal.log`、`resume.log`、`dry-run.log` | 製品Pilotの採用結果、再開・dry-run・44件原本保持。 |
| `font-replacement-cli-pilot/independent-render-validation.json`、`font-replacement-cli-pilot/visual-check-agent/`、repoの`docs/validation/2026-09-10-windows-font-replacement/` | 今回の採用出力の全ページPDFium確認と代表部分の目視証拠。 |
| `font-replacement-yugothic-trial/写真管理要領_游ゴシック統一_試験版.pdf`（2026-09-10独立試験版） | 製品実装前のWindowsフォント試験版、4,270,674 bytes。原本保護とは別の試験出力。 |
| 同`result.json`、`README.md`、`generation-integer-widths.json` | この独立試験の最終判断、制限、生成結果。 |
| 同`font-program-validation-integer-widths.json`、`structural-validation-integer-widths.json`、`render-validation-integer-widths.json`、`pdfium-extraction-diagnosis.json` | font/構造の合格と、全文抽出不一致の診断を分けた証拠。 |
| 同`visual-check-integer-widths/`、`visual-review-primary.json`、`visual-review-agent.json`、`baseline.json` | 全ページ描画、代表箇所の確認、43ファイルの原本等保持。 |
| `font-replacement-trial/写真管理要領_フォント統一_試験版.pdf`（2026-09-09試験版） | 利用者へ納品した1冊。4,068,905 bytes。 |
| `font-replacement-trial/result.json`、同README.md | 1冊試験の最終集約、制約、原本保持。 |
| 同`font-validation.json`、`structural-validation.json`、`render-validation.json`、`visual-check/` | フォント対応、文字・構造、描画、目視用PNGの証拠。中間statusの扱いは前節参照。 |
| 同`replace_fonts.py`、`validate_fonts_independent.py`、`structural-validation.py`、`render_validation.py`、`image-recompression-validation.py` | 既存の実験・検証script。通常runtimeではなく、再実行前に環境・固定パスを確認する必要がある。 |
| `input-inventory.json`、`files/`、`report.csv` | 入力23件のhash、通常CLIの完成出力18件、原本保護の結果。 |
| `anatomy-analysis.json`、`compression-diagnosis.json`、同.md | 18冊の容量・構造診断と、字体を保つ試験の判断材料。 |
| `qpdf-study/results.json`、同`warning-input-candidates/results.json`、`font-study/results.json`、同`validation.json` | 未採用のqpdf・字体保持候補の実測と限定検証。 |

当時の製品化計画は `.agent/execplans/2026-09-10-windows-font-replacement.md`。過去の関連記録は `2026-09-09-font-replacement-pilot.md`（9月10日の追加試験を追記）、`2026-09-09-gunma-compression-diagnosis.md`、`2026-09-09-document-scan-compression.md`。過去の作業記録を新しい全製品テスト結果に読み替えない。現行の製品契約は `AGENTS.md`、`MANUAL.md`、`docs/REFERENCE.md`、実装・テストで確認する。

2026-09-09のNoto Sans JP試験版SHA-256：`7be6d46d4cb44f1cc416eddc89776db27a760b8f9a08968c264db5dc823ee979`

試験対象の原本SHA-256：`c30a37d01d88358956753bb206ba3aa005be8644a9a52446468d29b722e878f8`

9月9日の引継ぎ作成だけでは新しい候補を生成していない。その後、明示された続行指示で9月10日の游ゴシック独立試験を実施し、さらに「実装して」の指示に基づく製品実装・通常CLI Pilotの結果を追記した。既存の原本・前回試験結果・保存先は維持している。
