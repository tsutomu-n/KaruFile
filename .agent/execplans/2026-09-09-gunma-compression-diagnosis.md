# 図表・レイヤー・大冊PDFの圧縮方針再検討

この文書はliving document。今回は設計判断のための調査・実測であり、製品の保護条件は変更しない。

## Goal / Acceptance criteria

全18 PDFが原本保護になった実資料について、容量の支配要因、qpdf単独の実削減余地、変換別に必要な保護と検証、実装優先順位を実物から判断する。原本と既存出力を維持し、未検証の実験候補を完成出力として扱わない。

## Facts / Inferences / Assumptions / Unknowns

- Facts: 前の実CLIは18冊46057953 bytes、全件PRESERVED_ORIGINAL。drawing12、optional_content2、page_limit4。原本23件（非PDF5件含む）のSHA一致を確認済み。既存未コミット変更は前段の白黒スキャン機能。
- Inferences: 現行の文書単位の保護は、qpdf構造再圧縮と画素/フォント/色の変更を同じ条件で止めている可能性がある。
- Assumptions: 今回は色・図形・文字・機能を保持する方針の妥当性を評価し、資料整理・重複削除・画像劣化を勝手に行わない。
- Facts (調査後): フォントraw streams 57.34%、画像23.25%。全18冊のqpdf実験候補は合計43,650,936 bytes（5.226%減）。最大577ページのsubset+cleanup+qpdf候補は8.212%減。
- Unknowns: 全300 DPI照合、非表示レイヤー・注釈等の全機能、候補全オブジェクトの意味同値、製品対応の実装費用。今回の通常表示一致では保証しない。

## Options / Risks / Stop conditions

比較対象は現状維持、qpdf専用経路、フォント/重複資源の整理、画像の選択加工。全面画像化、資料削除、一律の制限解除は対象外。qpdfの成功や一部ページの一致だけで文書機能全体の同一性を主張しない。異常・予算超過の実験候補は採用しない。課金・外部送信・公開はしない。

## Checkpoints

### CP-001: 容量と保護の診断
- Status: Complete (診断のみ)
- Objective: 今回の支配要因を見極める。
- Dependencies: 前のinventory、現行code/tests。
- Files/components: policy/worker/validate、入力PDF（read-only）。
- Actions: 独立監査、unique stream別容量、図形の実体を確認。
- Completion criteria: 数値と制約に根拠を示せる。
- Validation: 実物から集計し推定上限と実削減を区別。
- Failure conditions: 原本変化、推定値の断定。
- Recovery: 読取りのみ。実資料をGitへ入れない。

### CP-002: qpdf単独の限定実験
- Status: Complete (実験候補・未採用)
- Objective: 最初の推奨の効果を測る。
- Dependencies: CP-001の安全な入力確認、既存qpdf。
- Files/components: 出力parent内の独立experimentディレクトリ。
- Actions: 固定の既存qpdfオプションで別候補、check、構造/内容/表示の明示した範囲を比較。フォントが支配的と分かったため、最大577ページと101ページの2冊はcleanupのみ／subset+cleanupも独立測定。
- Completion criteria: 18冊の実サイズ、改善/増大/異常、検証範囲が記録される。
- Validation: 原本SHA前後、終了コード、ページ/内容等の比較。未評価機能を明記。
- Failure conditions: エラー・不一致・予算超過。
- Recovery: 原本と正式出力を変更せず実験候補を未採用扱い。

### CP-003: 推奨と実装順序
- Status: Complete (設計判断のみ)
- Objective: 本当に必要な変更と期待できない効果を示す。
- Dependencies: CP-001/002、qpdf一次資料。
- Files/components: この記録、ローカル診断資料。
- Actions: 文書分類/変換許可/検証予算を分け、費用対効果と失敗経路を評価。
- Completion criteria: 実測と限界を伴う具体的な推奨。
- Validation: 独立監査と実測を照合、diff-check。
- Failure conditions: 実測に反する推奨、無根拠の圧縮率/保証。
- Recovery: 後続の実装判断資料として留める。

## Progress / Decisions / Validation / Outcomes

- CP-001: 独立監査と実PDF分析を完了。303埋め込みフォントは全件Flate、300個にsubset名。上位4冊が全容量89.58%。保護理由は早期returnで重なる特徴を隠す。罫線の塗りつぶしやclipもdrawingに含まれた。
- CP-002: 18候補のqpdf checkは0。原本2冊のcheckはlinearization hint table警告で3のため、別の限定実験として記録。一律警告無視は使用しない。全1,317ページの72 DPI RGBとgeometry/text/位置/content streams/link/toc/metadataが比較範囲で一致。subset+cleanup2候補は全678ページの72 DPIとgeometry/text/位置/link/toc/metadata等が比較範囲で一致。300 DPI・隠れたレイヤー・全注釈機能等は未検証。すべて候補のまま未採用。
- CP-003: 汎用意味同値検証器の新設は今回5.23%の効果に対して過大。既存qpdfだけの小さな経路を試作範囲とし、未検証機能は保護継続。現在の共有600 MPはA4の72/300 DPI比較で約32ページ／1候補なので、ページ上限だけの解除や単なるタイル化は不十分。候補許可と有限の検証予算の扱いを先に定める。フォント処理拡張は追加効果に照らして後順位。
- 原本23件のSHA-256をinventoryと再照合。既存完成出力18 PDFも原本とSHA一致。今回の変更は調査記録のみでruntime変更・commit・pushなし。前段の未コミット白黒スキャン実装は維持。
- 証拠: `C:/Users/tn/Downloads/群馬県建設工事必携（R5年版）_軽量化/compression-diagnosis.md`、同`.json`、`anatomy-analysis.json`、`qpdf-study/results.json`、`qpdf-study/warning-input-candidates/results.json`、`font-study/results.json`と`validation.json`。
- 調査完了は圧縮経路の製品実装完了を意味しない。runtimeテストは今回再実行していない（実行動作の変更なし）。ローカル文書リンク18件の存在確認と`git diff --check`は成功。GitのLF/CRLF変換警告のみで差分エラーなし。
