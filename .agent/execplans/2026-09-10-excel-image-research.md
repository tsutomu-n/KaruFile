# Excel内画像縮小の一次資料・OSS調査

この文書は調査・実装のliving documentである。CP-001〜003は調査履歴。2026-09-10の「実装できる？」を受け、後段のCP-004〜007で実装・検証を追跡する。

**最新状態:** [実資料への対応拡大](#excel-expansion-plan)を実装・検証済み。CP-011〜017完了。28画像ブックは4画像を縮小し4.02%減、685画像本は解析可能になったが縮小なし。初期Pilotと今回の結果を区別する。

## Goal / Acceptance Criteria

Excel内の過大画像をKaruFileで縮小する案について、一次仕様とOSSの実装・ライセンスから、推奨方式、初期対応範囲、未検証事項を説明できること。

## Scope（調査フェーズ）

- In scope: Microsoft/ECMA仕様、Starsカタログ、候補OSSのREADME・LICENSE・manifest・実装の読取り、調査記録。
- Out of scope: 機能実装、依存追加、入力資料の変更、Excel操作、commit/push、既存変更の修正。

## Current State / Facts（調査開始時点）

- 現在のroot探索はPDF・単独画像・compact動画。Excelは対象外。
- media-shrink-toolはPillowを使用する単独画像からJPEGへの変換処理。Excelパッケージの責務はない。
- 作業ツリーにPDF・動画・文書等の既存変更が多数ある。今回の調査で上書きしない。
- Stars catalog doctor --smokeはPASS、4052件、2026-08-19 snapshot（取得時約21.91日前）。カタログ情報を現在の保守状況の根拠にはしない。

## Inferences / Assumptions / Unknowns

- 仮定: Windows向けローカルCLIと原本不変・別出力契約を維持する。
- 推論（暫定）: Excelの画像参照と配置を解析し、画像part以外を保持する方法が適する。
- 未確認: 実ブックの画像占有率、anchorの分布、Excel表示・印刷互換性、実際の削減率。

## Checkpoints

### CP-001: 一次仕様と既存制約

- Status: Complete
- Objective: 画像保存・参照・配置の仕様と保護が必要な条件を確定する。
- Dependencies: なし。
- Files or components: AGENTS.md、orchestrator、media-shrink-tool、Microsoft/ECMA公開資料。
- Actions: 現行契約を読み、画像part、anchor、crop、拡張、署名を一次資料で確認。
- Completion criteria: 主要な事実に公式URLがあり、設計上の推論と区別されている。
- Validation: 公式本文を照合。コード実行検証は含めない。
- Failure conditions: 仕様根拠が取得不能、曖昧な仕様を保証として扱う必要が生じる。
- Recovery: 未確認として範囲を限定する。

### CP-002: OSS比較

- Status: Complete
- Objective: 直接利用と参考利用を区別して候補を選ぶ。
- Dependencies: CP-001の目的・制約。
- Files or components: Stars catalog、候補の公式repositoryとdocumentation。
- Actions: カタログを検索し有力候補をenrich。ユーザーのOSS一般調査依頼に基づきStar外候補も比較。
- Completion criteria: 有力候補の実装・実LICENSE・manifest・保守状況を確認し、不明点を明記。
- Validation: カタログrepo_idと現行metadataの照合、実ソースの確認。
- Failure conditions: LICENSE不明、repo_id不一致、目的の実装が確認できない。
- Recovery: 採用を確定せず、参考利用または不採用として記録。

### CP-003: 結論と最小検証案

- Status: Complete
- Objective: 前回案を再評価し、利用者が実装方針を判断できる調査結果を示す。
- Dependencies: CP-001、CP-002。
- Files or components: 本書、必要に応じた調査資料。
- Actions: 事実・判断・未検証を区別し、初期対応範囲と検証項目をまとめる。
- Completion criteria: 出典付き推奨案と実施済み/未実施の区別がある。
- Validation: 参照先とgit diff --check。runtime suiteは変更がないため対象外。
- Failure conditions: 実機未検証を互換性保証として扱う必要が生じる。
- Recovery: 保証せず次工程の検証条件を示す。

## Progress

- [x] CP-001
- [x] CP-002
- [x] CP-003

## Discoveries: 一次資料で確認した事実

調査日: 2026-09-10。ECMA本文一式の読解ではなく、Microsoftの公開仕様とISO仕様を引用する公式API資料を中心に確認した。

1. Open XMLはZIP内のpartとrelationshipからなる。画像の参照先は固定ファイル名で推測せず、relationshipから解決する。`a:blip`の`r:embed`は内部画像、`r:link`は外部画像。
   - [Open XML package構造](https://learn.microsoft.com/en-us/office/open-xml/about-the-open-xml-sdk)
   - [Blip](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.blip?view=openxml-3.0.1)
   - [OPC relationships](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/opc/relationships-overview)
2. `oneCellAnchor`は開始セルとextent、`absoluteAnchor`は位置とextent、`twoCellAnchor`は開始・終了markerを持つ。列幅は単純な画素数ではなくNormalスタイルの最大数字幅に依存する。
   - [oneCellAnchor](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.spreadsheet.onecellanchor?view=openxml-3.0.1)
   - [absoluteAnchor](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.spreadsheet.absoluteanchor?view=openxml-3.0.1)
   - [twoCellAnchor](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.spreadsheet.twocellanchor?view=openxml-3.0.1)
   - [Column](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.spreadsheet.column?view=openxml-3.0.1)
3. `srcRect`は使用する画像領域を各辺からの割合で表す。単純な内側cropでも、表示枠と元画像全体に必要な画素数は異なる。
   - [SourceRectangle](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.sourcerectangle?view=openxml-3.0.1)
4. セル内画像には`_localImage` rich valueと`_rvRel:LocalImageIdentifier`からrelationshipを引く構造がある。通常のDrawingML浮動画像だけを調べるのでは不十分。
   - [Local Image Type](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-xlsx/aac1e2a6-7072-4e66-b1de-f20b8bf63318)
   - [Rich Value Rels](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-xlsx/538fba50-f966-4ee4-9246-db304016e074)
5. 画像編集用の元画像・編集パラメータ、SVGとPNG代替表現、Camera Tool拡張も存在する。可視画像を縮めても編集用原画像が残る可能性がある。
   - [DrawingML picture拡張](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-odrawxml/7e1f1524-1569-4aa2-a6c9-aab2d855bd48)
   - [元画像と編集パラメータの例](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-odrawxml/f10da8b6-40f3-4527-9c3d-9f5c2e9cff45)
   - [Camera Tool](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-odrawxml/2eba4276-701d-4d5a-a5c6-363aeb5ddaef)
6. `defaultImageDpi`の既定値220には仕様根拠があるが、`autoCompressPictures=true`かつ`useLocalDpi=false`という適用条件がある。ExcelにはHigh fidelity設定もあり、220ppiを可読性・印刷品質の保証値とは扱えない。
   - [CT_WorkbookPr](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-xlsx/00f1eb63-1e0c-423f-96d6-f139202df390)
   - [Office画像圧縮](https://support.microsoft.com/en-us/office/graphics-visuals/reduce-the-file-size-of-a-picture-in-microsoft-office)
   - [High fidelity](https://support.microsoft.com/en-us/office/graphics-visuals/change-the-default-resolution-for-inserting-pictures-in-office)
7. 署名対象のpartを変更すると署名検証に影響する。画像だけの変更も例外とはしない。
   - [MicrosoftのOPC署名説明](https://learn.microsoft.com/en-us/archive/msdn-magazine/2009/november/application-guidelines-on-digital-signature-practices-for-common-criteria-security)

## OSS比較

候補の記述は公式README、実LICENSE、manifest、実ソース、GitHub APIを根拠とする。以下は採用承認ではない。全候補でKaruFile統合、Windowsでの動作、実Excel表示・印刷、性能は未検証。

### Excelize: reference_implementation / reference_only

- Starカタログ由来。enrichのrepo_id照合は66841911で一致、errors/missingなし。
- [README](https://github.com/qax-os/excelize/blob/c6971ba9668c15292de4be82233abcf943d73f80/README.md)、[LICENSE](https://github.com/qax-os/excelize/blob/c6971ba9668c15292de4be82233abcf943d73f80/LICENSE)、[go.mod](https://github.com/qax-os/excelize/blob/c6971ba9668c15292de4be82233abcf943d73f80/go.mod)を確認。BSD-3-Clause、調査時masterはGo 1.25.0以上。
- [picture.go](https://github.com/qax-os/excelize/blob/c6971ba9668c15292de4be82233abcf943d73f80/picture.go)のGetPictures/getPicture/getImageCellRel/drawingResizeを確認。浮動画像とrich data画像の参照解決、配置・行列寸法の扱いが参考になる。
- [公式画像API](https://xuri.me/excelize/en/image.html)はGetPicturesのFormatが全属性を取得できないと明記。AddPictureのセル内画像追加非対応を、セル内画像の読取り非対応と混同しない。実GetPicturesにはgetCellImagesの経路がある。
- 推奨: 参照解決とテスト設計の参考。画像の削除→再挿入で全属性維持を保証する方式には使わない。Goの追加運用負担を負って直接利用する根拠は現時点では弱い。
- 非archive、pushed_at 2026-09-09T02:46:18Z。HEAD c6971ba9668c15292de4be82233abcf943d73f80。最新公開releaseは[v2.11.0](https://github.com/qax-os/excelize/releases/tag/v2.11.0)、2026-07-06。masterとreleaseの実装同一性は主張しない。

### Microsoft Open XML SDK: architecture_reference / trial

- Star外候補。[README](https://github.com/dotnet/Open-XML-SDK/blob/431ab05cf160248cc3885a4a766026d4f8243792/README.md)、[LICENSE](https://github.com/dotnet/Open-XML-SDK/blob/431ab05cf160248cc3885a4a766026d4f8243792/LICENSE)、[project](https://github.com/dotnet/Open-XML-SDK/blob/431ab05cf160248cc3885a4a766026d4f8243792/src/DocumentFormat.OpenXml/DocumentFormat.OpenXml.csproj)、Directory.Build.propsを確認。MIT、C#/.NET。
- [OpenXmlPart.cs](https://github.com/dotnet/Open-XML-SDK/blob/431ab05cf160248cc3885a4a766026d4f8243792/src/DocumentFormat.OpenXml.Framework/Packaging/OpenXmlPart.cs)にGetParentPartsとFeedDataがある。part参照の探索とpartストリーム差し替えを低水準で扱える。SDKはOfficeファイルの構造検証機能を持つが、画質判定・Excelレンダリング一致を提供する根拠ではない。
- 推奨: 仕様と独立構造検証の第一候補。必要なら小さな.NET補助ツールを試す。Python-only方針との費用比較は実装時に行う。SDKで保存した場合も非対象part内容一致を別に検査する。
- 非archive、pushed_at 2026-09-09T19:38:49Z。HEAD 431ab05cf160248cc3885a4a766026d4f8243792。最新公開releaseは[v3.5.1](https://github.com/dotnet/Open-XML-SDK/releases/tag/v3.5.1)、2026-03-18。

### compress-office: code_pattern / reference_only

- Star外候補。[repository](https://github.com/cometeme/compress-office)、[LICENSE](https://github.com/cometeme/compress-office/blob/7d27326db21b26ae56c0c37e31e79a6950b3dabf/LICENSE)、[manifest](https://github.com/cometeme/compress-office/blob/7d27326db21b26ae56c0c37e31e79a6950b3dabf/pyproject.toml)、[office.py](https://github.com/cometeme/compress-office/blob/7d27326db21b26ae56c0c37e31e79a6950b3dabf/office.py)、[images.py](https://github.com/cometeme/compress-office/blob/7d27326db21b26ae56c0c37e31e79a6950b3dabf/images.py)を確認。MIT、Python。
- ZIP展開→画像の外部可逆圧縮→再梱包。DrawingML配置・crop・共有参照から画素数を算定する処理はない。画素数の縮小も行わない。
- macOS固定cacheやunzip/zip/trashに依存し、原本をtrashへ移動して候補へ置換する。メタデータ除去オプションがあるためREADMEのlosslessをメタデータ維持保証と解釈しない。
- 推奨: パッケージ内の画像を再圧縮する発想の参考。Windows/KaruFileの原本保持契約にそのまま組み込まない。
- 非archive、HEAD 7d27326db21b26ae56c0c37e31e79a6950b3dabf、HEADコミット日時2026-04-26。Python >=3.8宣言とint | None構文の整合は未実行。

### filerepack: code_pattern / reference_only

- Star外候補。[repository](https://github.com/ivbeg/filerepack)、[LICENSE](https://github.com/ivbeg/filerepack/blob/2d41e71e02cf1c1c208679087b96fbd05a8a3926/LICENSE)、[manifest](https://github.com/ivbeg/filerepack/blob/2d41e71e02cf1c1c208679087b96fbd05a8a3926/pyproject.toml)を確認。BSD-3-Clause、Python >=3.9、Alpha表記。Windows対応表記あり。
- [repack.py](https://github.com/ivbeg/filerepack/blob/2d41e71e02cf1c1c208679087b96fbd05a8a3926/filerepack/repack.py)はZIP内の形式別再圧縮と、検証・サイズ条件後のos.replaceが参考。既定は原本置換だがlibraryのoutfileで別出力を指定できる。
- [markup.py](https://github.com/ivbeg/filerepack/blob/2d41e71e02cf1c1c208679087b96fbd05a8a3926/filerepack/markup.py)ではXML等も変更対象。Excelの配置寸法・cropを解析する画像縮小ではない。
- 推奨: 一時ファイル・候補採用の参考。非対象part内容一致のKaruFile方針に既存処理をそのまま流用しない。
- 非archive、HEAD 2d41e71e02cf1c1c208679087b96fbd05a8a3926、HEADコミット日時2026-08-20、pushed_atは2026-09-09。これらの日時は同義ではない。

### 補足: openpyxlによる再保存

[現行stable tutorial](https://openpyxl.readthedocs.io/en/stable/tutorial.html#loading-from-a-file)は未対応要素とshape欠落の注意を明記。ブックを読み込み再保存する方法で任意の既存要素を維持できるとは仮定しない。今回の用途の保存エンジンとしては推奨しない。古い資料の「画像・チャートがすべて失われる」という表現を現行機能へ転用しない。

## Decision Log

### Decision-001: 画像part限定変換を試験候補にする

- Date: 2026-09-10
- Decision: PythonのZIP/XML処理と既にプロジェクトで使うPillow系の画像処理を基本候補とし、Excelizeを解析の参考、Open XML SDKを仕様照合・独立検証の候補とする。直接依存は未決定。
- Rationale: 大きな汎用Excel再保存処理を導入するより、変更範囲を画像partに制限して非対象partを比較できる利点がある。
- Alternatives: 既存の専用圧縮OSSは再圧縮の参考になるが、表示寸法による縮小・他part不変という目的を満たす完成品とは確認できなかった。SDKによる.NETコンポーネントも現実的だが、追加ビルド・配布負担がある。
- Consequences: 独自に全画像参照と配置を安全に判定する責務が残る。ZIP/XML/画像の資源上限と異常入力処理も必要。OSS利用でこの責務が消えるわけではない。

### Decision-002: 前回の220ppi案を条件付きへ修正する

- Date: 2026-09-10
- Decision: 220ppiは写真用候補値。細かい文字・印刷を含む品質の保証値ではない。Excelの圧縮設定を書き換えることと、KaruFileが実画素数を変換することを分ける。
- Calculation: cropなし幅10cmならceil(10 / 2.54 * 220) = 867px。横50%だけ使って幅10cm表示する単純cropなら全幅にceil(10 / 2.54 * 220 / 0.5) = 1733pxが必要。前回の約866pxは概算で、実装では切上げが必要。
- Consequences: 全配置の要求を満たす最大の画素数を求め、縦横比を維持して縮小率を決める。アップスケールはしない。特殊なfill、外側crop、group変換等へこの簡単な式を無条件に適用しない。

## Recommended Next Step（調査終了時点）

次工程はまず読取り専用の診断と小さな変換実験とする。これは今回実行した工程ではない。

1. 実xlsx数冊について、ブック容量、画像partの格納容量と展開後容量、画素数、全参照先、anchor種別、crop、保護理由を収集。画像が容量を占めるか、確定可能な配置がどの程度あるかを測る。
2. 初期変換は明示選択された非暗号化・非署名xlsxの通常JPEG/PNGに限定。全利用と表示寸法が確定するものだけ候補化。マクロ付き、旧形式、ベクター、セル内・特殊画像、未知の利用を持つ画像は初期保護対象。解析範囲を確定できない場合はブック単位で保護。
3. 同形式で画像partだけを変更し、セル・数式・書式・描画XML・relationship・content types等の非対象内容をバイト単位で保持。PNGの透過やJPEGの色/向き/ICC等は別途検証し、単独画像用JPEG変換をそのまま適用しない。
4. 一時候補を検査し、非対象partのSHA一致、画像参照整合性、画像デコード、配置不変、元ファイル不変、全体サイズ削減を確認して別出力へ公開。未知構造による保護とI/O/構造エラーを区別する。失敗時に既存出力を壊さない。
5. 実Excelで修復警告が出ないこと、表示・印刷・再保存時の挙動をPilot確認する。crop、共有画像、透明PNG、文字画像、twoCellの行列寸法、未知拡張、破損入力、再実行を含める。

## Validation Evidence / Outcomes（調査フェーズ）

- github-stars-oss doctor --smoke: PASS。4052件、SQLite整合と検索smokeを確認。
- 概念query3件で最大30件を探索し、Excel/openxmlに絞る言い換えを1回実施。ExcelizeをDeep Check。カタログに有力な専用Excel縮小器を発見しなかったことを、不在証明にはしない。
- enrich qax-os/excelize: PASS、repo_id一致、README/LICENSE/go.mod取得済み。
- 一次仕様担当と専用圧縮OSS担当を並行調査し、親でExcelize/SDKを照合。取得したOSSのコードは実行していない。
- webからraw GitHubの一部が取得できなかったため、公開URLをPowerShell Invoke-WebRequest/Invoke-RestMethodで読取り確認した。Stars cacheはwrapper記載のUbuntu-26.04から読み取った。
- runtimeコード・依存・MANUAL/REFERENCE・アーキテクチャは変更していない。既存の未コミット作業も変更していない。
- git diff --check: whitespaceエラーなし。既存変更を含むLF→CRLF予告は出力された。新規調査文書の末尾空白・競合マーカー・索引リンクは別途確認。runtime suite、実ブック変換、Excel Pilotは未実施。

## Remaining Issues（調査終了時点）

実ブックによる処理、Excelでの表示・印刷確認、削減率測定は今回未実施。

## 実装フェーズ（2026-09-10）

### Goal / Acceptance Criteria

root CLIで明示選択したxlsx内の過大な通常JPEG/PNGを配置寸法に応じて縮小し、原本不変・別出力・非対象part内容一致を保つ。対応外は理由付き保護、失敗はERRORとして独立ファイルを継続する。合成ブックで実変換・破損/偽装report・安全な再実行を確認し、利用手順と構成図を更新する。実Excelの表示・印刷Pilotは実施証拠がある場合だけ完了とする。

### Scope / Facts / Assumptions

- 新規excel-shrinkコンポーネント、root統合、テスト、必要文書・ignore・architectureを対象とする。commit/pushは含めない。
- root `--excel-pattern`反復指定時だけxlsx探索（`~$`ロックファイル除外）。`--excel-dpi`は150〜300、既定220、明示指定にはpatternが必要。両presetで同じrecipe。
- standalone `excel-shrink run --input DIR --output DIR --pattern GLOB [--dpi 220] [--dry-run]`。1worker、DB/cacheなし、毎回原本から評価。
- report `<output>.excel-report[.dry-run].csv`、一時作業 `<output>.excel-work/`。PDF→画像→Excel→compact動画の順。
- JPEG quality85/4:4:4、PNGは透過を維持。拡大・crop領域削除・Excelの圧縮設定変更は行わない。画像以外のZIP entry展開後内容を完全保持。
- 制限: 入力128MiB、4096 entries、ZIP中央directory4MiB、各展開part64MiB、展開合計256MiB、XML8MiB、画像500個、32MP/画像、原画像+候補decode累積200MP、協調deadline300秒。preflight超過は保護、runtime失敗はERROR。
- 既存のPDF・動画・ガイドの未コミット変更は維持する。
- 未確認: 実資料での対応率と削減率、実プリンター・再保存・他Excel版での互換性。合成4ブックについてExcel16.0の通常OpenとPDF出力を別途確認した。任意の実資料パスへの回答はなく、実業務Pilotは未実施。

### CP-004: Excel処理本体と出力契約

- Status: Complete
- Objective: 対応画像だけを縮小し非対象partを保持した候補を作れる。
- Dependencies: CP-001〜003。
- Files or components: excel-shrink/src/excel_shrink、tests、pyproject/lock。
- Actions: 有界ZIP/XML解析、全参照/配置/crop検証、画像処理、非対象part検証、型付きrunner/atomic出力/report、dry-run。
- Completion criteria: 合成xlsxが縮小し、共有/crop/透過を確認、対応外とエラーを区別し原本・既存出力を破壊しない。
- Validation: core/runner tests、compileall、standalone CLI smoke。
- Failure conditions: 不明な画像利用、寸法の不確定、非対象内容変化、出力alias、検査不通過。
- Recovery: 候補不採用または原本保護。真のエラーは非zeroとして既存出力を維持。

### CP-005: root統合

- Status: Complete
- Objective: 通常CLIから明示選択したExcelの正確な結果を集計できる。
- Dependencies: CP-004のCLI/report契約。
- Files or components: orchestrator/shrink_all.py、Excel統合tests。
- Actions: flags、選択、全出力/derived path preflight、source baseline、subprocess、独立report/ZIP照合。
- Completion criteria: disabled default不変、CLI変換成功、偽装/stale report・alias・不正flagを拒否。
- Validation: orchestrator suiteとroot help。
- Failure conditions: 実ファイルとreport不一致、既存機能回帰。
- Recovery: 非zero集計。既存機能の期待値を緩めず修正。

### CP-006: 文書とアーキテクチャ

- Status: Complete
- Objective: 実装に一致する利用方法・制限・処理境界を公開文書に残す。
- Dependencies: CP-004/005の確定契約。
- Files or components: MANUAL/REFERENCE/README/component docs/AGENTS/.gitignore、architecture JSON/compact HTML、guide。
- Actions: 影響文書更新、archify validate/deliver/visual-checkとlight/dark画像確認。
- Completion criteria: 現行手順・report場所・保護条件が一致し、生成図の検査が成功。
- Validation: 実CLI help、ignore/pathチェック、図のreceiptと目視、diff check。
- Failure conditions: 図の品質検査失敗、仕様と実コードの不一致。
- Recovery: 診断対象を修正。未実施確認を完了と記載しない。

### CP-007: 最終検証と再評価

- Status: Complete
- Objective: 変更を横断した回帰検証と独立検証から完了を判断する。
- Dependencies: CP-004〜006。
- Files or components: 全component suites、root、合成統合fixture、実資料があれば別出力Pilot。
- Actions: 全required tests/compile/help/diff、合成通常/dry-run/再実行、失敗経路review、必要修正。
- Completion criteria: 全必須自動検証通過、重要な欠陥未解決なし、実機未確認範囲を正直に報告。
- Validation: 実行コマンド・件数・exit codeを記録。
- Failure conditions: 原本/非対象part変化、既存出力破損、reportの誤集計、回帰。
- Recovery: 原因を修正し影響チェックを再実行。機能や検査を無効化して通さない。

### Progress / Validation

- [x] CP-004
- [x] CP-005
- [x] CP-006
- [x] CP-007

### Implementation Decisions

- 実装をcore、runner/output、root統合に分離。参考OSSのコードは流用せず、既存のPillowとPython標準ライブラリで限定実装する。新たなGo/.NET実行依存は導入しない。
- oneCell/absoluteの明示extent、同一セルtwoCell、限定された複数セルtwoCellに対応。後者は全通過セルの明示width/ht、customHeight、Calibri11のNormal字体とtheme、非表示/自動調整/数式表示等の除外を確認する。保存shape extentがあれば計算と完全一致を要求し、未知の既定寸法は推定しない。
  [Microsoft Column仕様](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.spreadsheet.column?view=openxml-3.0.1)の96 DPI・MDW7の式を限定適用し、Excel本体のShapes寸法と合成fixtureで一致を確認した。
- JPEGの保存で失われる未知APP・重複metadata等は画像単位保護。PNGのpHYs等の対応metadataはraw payloadを保持し、透過色キーはalphaへ変換して縮小後RGBA samplesを照合する。
- rootとprocessorそれぞれで、ZIP reader構築前に中央directoryの実record数とEOCD申告値を確認する。CSVの正しいSHAだけでは安全な内容と認定しない。

### Final Validation / Outcomes（実装フェーズ）

- 最終suite: PDF433 passed/4 skipped、単独画像64 passed、動画113 passed、orchestrator431 passed、Excel138 passed。計1179 passed/4 skipped。skipはKARUFILE_TEST_JPEGTRAN未設定の実jpegtran4試験。全実行exit0。
- 全componentとroot/orchestratorのcompileall、root/Excel CLI help、git diff --checkに成功。検証スクリプトもcompileall確認。
- 最終suite後のroot CLI追試: standard通常、dry-run、compact再実行のexit0、破損xlsx＋保護対象の混在は想定exit1。原本SHA、非変更partのbytes一致、画像1200×900→220×165、dry-runで通常report/出力不変、ERRORで既存出力維持と独立ファイル継続をassertした。
- Excel16.0の専用COMインスタンスで合成4ブックの元/出力計8ファイルを読み取り専用・通常Open。数式と画像位置/寸法、開封前後のSHA一致。Excel PDF出力も成功し、144 DPI比較で画像領域外の画素差0。JPEG/PNG/twoCellの比較PNG6枚を目視した。
- 詳細コマンド・ログ: [回帰記録](../../docs/validation/2026-09-10-excel-image/regression-summary.md)、[Excel本体確認](../../docs/validation/2026-09-10-excel-image/excel-native-review.md)。実入力xlsxを公開資料へ含めず、合成生成スクリプトと出力検証証拠を保存した。
- MANUAL/REFERENCE/README/AGENTSと各component文書を実装に合わせて更新。入門ガイドは7節・A4全7ページ、104リンク、5画面幅/200%/offlineの検査に成功。構成図はArchify9/9、errors/warnings0、light/dark最小/最大4画像の目視成功。最終23ソース/依存設定のsnapshot SHAを親でも照合した。[図の確認記録](../../docs/architecture/karufile-runtime.compact.review.md)、[ガイド確認記録](../../docs/guide/REVIEW.md)を参照。
- 独立レビューで見つかったPNG getexifの先行decode、pHYs消失、未知JPEGmetadata、未知共有画像参照、NUL名、中央directoryの遅い上限確認を修正し、失敗経路の回帰testを追加。未解決の重要な欠陥は確認されていない。

### Remaining Uncertainty（実装完了時点）

- 実業務資料の対応率・削減率と、細かい文字/写真内容の可読性は未確認。220 DPIは品質保証値ではない。
- 既定の列幅/行高や未知構造に依存するtwoCell、セル内画像、マクロ付き/旧形式等は対応外。保護理由をreportし、明示選択xlsxで変換不能なら原本コピーを保持する。
- Excelでの再保存、物理プリンターでの印刷、別バージョン・別表計算ソフトは未試験。
- commit/pushは行っていない。既存の無関係な未コミット作業を保持した。

### CP-008: ユーザー指定実資料のPilot

- Status: Complete
- Objective: 提供された実xlsx 1冊について、現行実装の処理結果・原本保護・画像配置と表示を確認する。
- Dependencies: CP-004〜007。ユーザーからローカルファイルを指定済み。
- Files or components: 指定xlsx、Excel CLI、Excel16.0、検証用の別フォルダー。
- Actions: SHA/サイズ採取、構造診断、指定1冊だけのコピーを作りroot dry-run/通常実行、非対象ZIP内容比較、Excel読み取り専用Openと必要な表示比較。
- Completion criteria: 容量/画像数/採用または保護理由を特定し、原本SHA不変と完成出力の整合を検証できる。削減がない場合も事実と制約を明記する。
- Validation: 実CLI report、独立ZIP比較、実Excel geometry/数式内容比較、PDF表示比較。
- Failure conditions: 原本変化、非対象part変更、出力破損、表示/数式不一致、処理失敗。
- Recovery: 原本を保持、未検証候補を配布しない。実装欠陥なら根拠から必要最小限を修正し影響テストを実施する。
- Privacy: 実資料・PDF・画像・セル内容はDownloads以下のローカル検証フォルダーに置き、リポジトリへコピーしない。文書には集計値と保護理由を記録する。
- Outcome: 503107B→503107B、原本保護。全6 JPEGが449×337px、実Excel寸法から約96〜98DPIと確認し、220DPI縮小の余地がない。現行実装の直接の保護理由はnonvisual_picture_extension。未知拡張を強制許可せず、runtime変更なし。
- Evidence: 通常/dry-run終了0、原本/出力SHAと全32part内容一致。Excel16で全5シートのセル/数式ハッシュ・画像配置一致。Excel出力PDF全4ページの144DPI画素完全一致。[実資料Pilot記録](../../docs/validation/2026-09-10-excel-image/real-workbook-pilot.md)を参照。
- Remaining: 原本保護Pilotは完了したが、実資料の画像縮小成功・画質評価は引き続き未検証。既定の品質や保護条件を変更していない。

### CP-009: 2冊目の指定実資料のPilot

- Status: Complete
- Objective: 追加指定された23,170,522Bのxlsxを現行実装で処理し、原本保護・削減結果・表示整合を確かめる。
- Dependencies: CP-004〜008、ユーザーの明示的なローカルファイル指定。
- Files or components: 2冊目の指定xlsx、root/Excel CLI、ローカル検証用コピーと出力。
- Actions: 原本SHAと構造集計、孤立inputでdry-run/通常処理、全非変更part比較、必要なExcel読み取り専用確認。
- Completion criteria: 採用/保護理由と削減率を特定し、原本不変と完成出力の整合を確認する。
- Validation: 実report、SHA、ZIP part内容、Excelの数式/配置/表示。
- Failure conditions: 出力破損、原本変化、表示/数式変更、検証不通過。
- Recovery: 原本と前回出力を保持し、未検証の候補を完成品として扱わない。
- Privacy: 資格証を含むため、人名・番号・セル内容・画像をリポジトリや外部サービスへ送らない。詳細証拠はDownloadsの専用フォルダーに置く。
- Outcome: 23,170,522B→同サイズ、削減0%。画像685個が500個上限を超えimage_count_limitで全体保護。画像格納22,729,476B（98.1%）、JPEG609/PNG76。数上限以外にもcreationId・multi-cell字体・パレット画像の保護が残る。縮小不要と判定したものではない。
- Validation: 通常/dry-run終了0、原本/input/output SHA一致、全873 ZIP partの内容一致。バイト完全一致の保護出力なのでExcel再表示/PDF出力は追加しなかった。runtime/上限変更なし。[2冊目の記録](../../docs/validation/2026-09-10-excel-image/real-workbook-pilot-2.md)。
- Remaining: 今回依頼された現行実装の試行は完了。この資料の軽量化は大量画像・配置等の対応追加が必要で、未達。

### CP-010: 3冊目の指定実資料を処理

- Status: Complete
- Objective: Music配下の指定xlsxを原本不変・別出力で処理し、結果と原因を確認する。
- Dependencies: CP-004〜009、ユーザーの明示的なファイル指定。
- Files or components: 指定xlsx、孤立inputコピー、root CLI、CSV、ZIP比較。
- Actions: 元SHA採取、通常CLI実行、個人内容を出さない構造診断、原本・出力比較。
- Completion criteria: 実行結果、削減率、採用/保護理由、原本不変を確認する。
- Validation: 通常exit0、原本/output SHA一致、全41ZIP part内容/順序/comment一致。
- Failure conditions: 原本変化、出力破損、非対象part変更。
- Recovery: 原本保持、未検証候補を完成品扱いしない。
- Outcome: 3,735,742B→同サイズ、PRESERVED_ORIGINAL。JPEG28個/30配置、画像容量99.45%。全画像がnonvisual_picture_extensionで保護、字体条件にも未対応。画像数上限には達していない。
- Evidence: [3冊目の記録](../../docs/validation/2026-09-10-excel-image/real-workbook-pilot-3.md)。実資料・詳細証拠はMusic配下の専用フォルダーに保持し、個人内容はrepoへ含めない。
- Remaining: 現行処理の試行は完了、軽量化は未達。原本と完全一致のためExcel再表示は追加せず、runtimeも変更していない。

<a id="excel-expansion-plan"></a>

## 実資料への対応拡大計画（2026-09-10）

### 今回の依頼範囲と到達目標

当初は**計画立案**の依頼だった。その後の「つづけて」で実装・実資料検証へ進む承認を得た。以下は計画時の条件と、末尾の実行証拠を併せて読む。
実装時の目標は、通常のExcelが付加する識別用拡張と、游ゴシック等のNormal字体を使う配置を正しく解釈し、
過大な画像を持つ実資料を原本不変・別出力で軽量化できることである。

最初の対象は28画像・30配置の小さいブック。寸法と縮小の妥当性を確認してから685画像へ広げる。
低解像度だった最初の6画像ブックは、拡大・不要な再圧縮をしない対照資料として使う。
「保護でexit0になった」「例外が出なくなった」だけを対応完了としない。

### 現在確認できる事実

| 実資料 | 画像part / 配置 | 容量と状況 | 対応拡大の意味 |
|---|---|---|---|
| 1冊目 | 6 / 6 | 503107B、画像449×337px、実Excelで約96〜98DPI | 220DPI基準では縮小不要。保護/無変更の対照 |
| 2冊目 | 685 / 画像685・一般shape22 | 23170522B、画像が98.1%、image_count_limit | 枚数と他の未対応条件を分離して評価 |
| 3冊目 | 28 / 30 | 3735742B、画像が99.45%、nonvisual_picture_extension | 小さな最初の実資料Pilot |

- `drawing.py:_picture_placement`はnonvisual内のextLstを一律保護する。一方`useLocalDpi`は既に限定許可している。
- `grid.py:GridResolver`はCalibri11・明示width/ht等に限定。creationIdを許可しても游ゴシック系では次の保護に進む。
- `package.py`はContent Typesに基づく画像partを500個に制限する。rootの`_excel_adopted_package_matches`にも別の500個制限があり、現状はxl/media内ファイル数を数えるため定義が一致していない。
- 上限保護がPackage完成前に起きると、core結果のimages_totalが0になる。実685個と「未取得」を区別できていない。
- `Package.parts`、変換済みreplacements、候補再読込みのPackageがbytesを保持する。画像デコード自体は逐次処理。
- 685画像本の展開後総量は24,908,212B、XML合計1,947,496B・65,645ノード。最大画像約1.06MP、全画像合計約110.03MP。
  この実例だけでは全面的なstreaming再設計を先行させる根拠はない。
- rootは変更part集合、非変更bytes、画像形式・非拡大、DPIの要求値等を独立に検証するが、配置からDPIを再計算する独立レンダラーではない。

現在のコードと過去の結果を照合して上記を再確認した。1179 passed/4 skippedは初期実装時の証拠で、
対応拡大後の検証結果ではない。計画立案時はruntime suiteを再実行していない。後続の実装時検証は末尾参照。

### 一次資料・OSSからの判断

1. `creationId`はdrawing要素の識別情報で、型は子要素なし・任意のid属性（GUID）だけ。
   [`CT_CreationId`](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-odrawxml/7b70d634-1469-4275-bc1f-f77375d39641)、
   [SDKの型とGUID検査](https://github.com/dotnet/Open-XML-SDK/blob/431ab05cf160248cc3885a4a766026d4f8243792/data/schemas/schemas_microsoft_com_office_drawing_2014_main.json)で確認した。
   URI `{FF2B5EF4-FFF2-40B4-BE49-F238E27FC236}`との対応は今回Microsoft本文で確認できず、実Excel生成物の具体形を根拠とする。
   仕様上の意味と実ファイルのURI観測を混同しない。
2. `useLocalDpi`は現在の表示寸法を示す値ではない。保存時の画像圧縮設定に関わる既存情報として保持する。
   [要素とURI](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-odrawxml/c05c287f-f63e-4fa9-8163-e3e106b4105f)、
   [Boolean型・省略時true](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-odrawxml/2d5944fe-ef10-4a1e-8c47-3bcee2917930)。
3. 列幅はNormal字体の最大数字幅（MDW）に依存する。defaultColWidthとbaseColWidthの単位・paddingは異なり、
   defaultRowHeightはpt単位の継承値。MDWを求めても自動行高の再現は解決しない。
   [Column](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.spreadsheet.column?view=openxml-3.0.1)、
   [SheetFormatProperties](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.spreadsheet.sheetformatproperties?view=openxml-3.0.1)。
4. GDIは指定した論理字体を利用可能な字体へmappingするため、要求名を渡すだけでは実字体を保証できない。
   数字0〜9を個別に計測し、実face・サイズ・計測条件を検証する。
   [CreateFontW](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-createfontw)、
   [GetTextExtentPoint32W](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-gettextextentpoint32w)。
   GDIとExcelの同等性はまだ未確認で、実測比較を採用条件にする。
5. Excelの[Shape.Width](https://learn.microsoft.com/en-us/office/vba/api/excel.shape.width)はpt単位。
   開発時に別系統の比較値として使う。通常runtimeをExcel依存へ変える根拠とはしない。
6. Excelizeを同目的で再確認した。HEAD `696050fbf14e74e96a58eef2b16aaf72f381a6a8`、BSD-3-Clause、Go1.25.0以上。
   [col.go](https://github.com/qax-os/excelize/blob/696050fbf14e74e96a58eef2b16aaf72f381a6a8/col.go#L659)はMDW8固定、
   [rows.go](https://github.com/qax-os/excelize/blob/696050fbf14e74e96a58eef2b16aaf72f381a6a8/rows.go#L1033)は別の丸め式、
   [picture.go](https://github.com/qax-os/excelize/blob/696050fbf14e74e96a58eef2b16aaf72f381a6a8/picture.go#L690)は保存extentを使う。
   参照解決や既定値の探索順は参考にするが、任意字体でのExcel寸法一致の根拠として流用しない。追加依存・コード流用は予定しない。

### 採用方針と比較した代案

| 方式 | 判断 |
|---|---|
| 現状維持 | 原本保護は成立するが、今回の対応拡大目標を満たさない |
| 既知拡張の限定許可＋Windows字体計測 | 第一候補。現在のZIP/画像part限定変換を維持できる。Excelとの差を先に検証する |
| 保存xfrm/extを無条件採用 | 不採用。1冊目で実Excel寸法との差が観測されており、現在の表示寸法とは限らない |
| 500を1000へ変えるだけ | 不採用。拡張・字体・累積画素・root側制限は残る |
| Excel COMを通常処理の必須依存にする | 初回scope外。インストール・プロセス管理・外部接続等の責務が増える。開発時の独立検証に使う |
| openpyxl/Excelize等でブック全体を再保存 | 不採用。非対象part内容不変の現契約を失う必要がない |
| 全partのstreaming化を先行 | 保留。代表685画像本は展開約25MB。計測で必要になった箇所の部分置換から行う |

Excelを必須にしない前提を維持する。新CLIフラグは増やさず、`--excel-pattern`/`--excel-dpi`、
既定OFF・220DPI・両preset共通・逐次処理・DB/cacheなしを維持する。
Windows以外や使用字体が不明な環境では、既存の確定可能な配置だけを処理し、追加の字体計測を必要とする画像は理由付き保護とする。

### 変更後の契約案

**拡張:** `cNvPr/extLst/ext/a16:creationId`の既知の位置・namespace・URI・要素構造だけを許可する。
idがあれば仕様のGUID字句を検査し、任意属性という仕様も明記する。XMLは書き換えない。
`useLocalDpi`も同じ小さなvalidatorへ寄せ、既知のBoolean/既定値だけを扱う。
未知のwrapper属性、子・非空text、重複extLst/ext、既知と未知の併存を検査する。
imgProps、svgBlip、cameraTool、外部リンク、編集履歴、未知拡張、AlternateContentは継続保護する。
影響する画像が複数配置で共有される場合、一配置の未知利用を画像part全体へ反映する。

**寸法:** 既存gridのNormal style/theme解決を切り出し、Windows標準APIによる`font_metrics.py`（予定）を追加する。
最初は実資料で使われる游ゴシック系とCalibriの確認済みface/sizeに絞り、任意字体対応を一度に保証しない。
0〜9を個別に計測する。要求字体の欠落・代替、曖昧なtheme、font file/faceの不一致は保護し、MDW7へのfallbackをしない。
字体の同梱・ダウンロード・書換え・ブックの字体置換は行わない。
実face・字体データのfingerprint・サイズ・96DPI計測条件・recipe版を記録し、計測cacheはrun内だけとする。

列幅は明示col.width、適用可能なdefaultColWidth、仕様どおりのbaseColWidth計算を区別する。
行高は明示ht/customHeightとsheetFormatPrの固定された既定行高を区別する。
autoFit、wrap/字体混在等で自動高さが変わる行、非表示・折畳み、数式表示、RTL、未検証の表示条件は初期対応に含めない。
実28画像ブックにこれらがあるかはCP-011で確認し、ある場合は未達範囲を明示する。
保存extentとの不一致を一律に無視しない。差の原因と誤差の上限を独立に確認できた条件だけを採用する。
単にテストを通すために許容差を広げたり、根拠なく数%大きい値を選んだりしない。

**画像数と資源:** 画像inventoryの次段階上限を1000個にする。685個を含む有限の対応範囲であり、1000個の全画像を必ず縮小する保証ではない。
定義はContent Typesでimage/*に分類される画像partの数とし、参照数・一般shape数とは分ける。
rootとprocessorでこの定義と上限を同期する。128MiB入力、4096entry、4MiB中央directory、64MiB/part、
256MiB展開総量、8MiB/XML、32MP/画像、原画像＋候補の累積200MP、協調300秒は維持する。
原画像合計110MPでも候補込みで200MP以下とは限らず、配置から必要な候補寸法を算定して確認する。
累積超過は現行どおり全体保護。予算内の画像だけを選ぶ部分採用や、制限の無効化は今回行わない。

累計XML32MiB・1,000,000ノードを追加上限案とする。実685画像本の約17倍/15倍の余裕であり、
イベント解析中に止めて巨大DOM生成後の拒否を避ける。per-partの既存上限も維持する。
685画像・実際に縮小する1000画像合成ケースについて、wall time、PeakWorkingSet64、Private Bytes、
一時ディスク量を計測する。代表685画像ケースのピーク512MiB以下を暫定の受入目標とし、単一32MP境界も別計測する。
超えた場合は候補検証のpart単位読込みから部分置換する。都合よく目標を上げず、変更理由を記録する。
画素数上限はプロセスメモリ上限ではなく、300秒は強制killによる厳密な実時間保証でもない。

**診断とschema:** Excel CSVをschema2へ更新する。パスと既存statusは維持し、次を追加/変更する。

| フィールド | schema2の意味 |
|---|---|
| images_total | 確定した実画像part数。未取得は空欄/None、真の0と区別 |
| recipe_version | 今回の固定処理版。rootの期待版と一致させる |
| analysis_complete | 全画像について許可/保護/解像度等の必要な判定が完了したか。全画像を許可したという意味ではない |
| diagnostics_complete | 表示用の詳細診断を省略せず収録できたか。解析の完了とは区別 |
| image_diagnostics | 画像partごとの形式/画素数、配置数、寸法根拠、要求pixel、段階別理由、採用結果のJSON |

JSONは画像ごとの集約とし、XML・セル・画像・資格情報を複製しない。part重複禁止、最大1000件、
最大深さ8、UTF-8で2MiB/fieldを上限案とする。part名等の長い値を切り詰めて別partのように表示しない。
詳細が収まらない場合は省略を明示し、集計値は保持する。診断を続行できても変換許可の不足を埋めた扱いにはしない。
childの一時CSV読戻しとroot parserの双方で、同じ有限のcsv field上限とJSON上限を検査する。
既存のreport全体32MiB上限は維持。最終report容量の問題を可能な範囲で公開前に検出する。

ADOPTED_LOSSYにはanalysis_complete=trueが必要。dry-runのimages_changed=0、changed_parts=[]、
完成出力size/SHA空欄を維持し、変更予定は診断側へ記録する。ERRORにも得られた診断を残す。
診断不能と既知の対応外を混同せず、真のtool/structure/I/O失敗を成功に変えない。
rootはschema1の古いreport、未知recipe、型/件数/part/要求の不一致を拒否する。
ExcelにDB/cacheはないためDB移行は不要。各実行で新しいreportを生成する。

### 実装チェックポイント

#### CP-011: 寸法の独立照合と最初の対象範囲の確定

- Status: Complete
- Objective: 28画像ブックの30配置で、何が解決すれば縮小判定できるかを確定する。
- Dependencies: CP-008〜010の実測記録とユーザー指定原本。
- Files or components: ローカル検証script、grid.py、Windows字体計測の小さな試験、合成fixture。
- Actions: 原本SHAを再確認し、拡張・字体・通過する行列の明示/既定/自動条件を構造として記録。GDI候補値、保存XML、Excel COMの行/列/Shape寸法を比較する。
- Completion criteria: 全30配置の差を分類し、対象とするfont/size/行列条件、丸め方法、縮小対象数と候補込みMPを確定する。数%の推測で済ませない。
- Validation: 独立Excel16、Calibri対照、実使用游ゴシック、字体欠落/代替、複数列、固定既定行高とautoFit差のfixture。
- Failure conditions: GDIで実字体を特定不能、実Excelとの差を説明不能、全対象が未対応のまま。
- Recovery: 該当条件を保護。通常runtimeへCOMを黙って追加せず、Excel補助方式を採る場合は依存・起動/停止・対応付けを含む次の設計判断として計画を改訂する。独立計測で縮小対象が0と分かった場合は再圧縮で成果を作らず、縮小不要の結果を記録し、実縮小の検証に必要な資料条件とPilot計画を改訂する。

#### CP-012: 正確なinventoryとschema2の診断契約

- Status: Complete
- Objective: 保護されても画像数と処理を妨げる条件が分かる。
- Dependencies: CP-011の分類項目。schemaは候補変換を増やす前に確定する。
- Files or components: package.py、models.py、core.py、runner.py、report.py、orchestrator/shrink_all.py、双方のtests。
- Actions: bounded索引/Content Typesから画像数を得る。未知数はNone、既知数は例外/結果へ運ぶ。schema2の型付き診断とroot独立照合、CSV/JSON上限を実装する。
- Completion criteria: 685画像の上限保護で685を報告し、画像なし0と解析不能を区別。既知/未知拡張・字体・形式の複数理由を可能な範囲で提示する。
- Validation: CSV標準131072文字超え、2MiB境界、32MiB全体、深さ/件数/重複part/boolean偽装、stale schema1、dry-run、ERROR途中診断。
- Failure conditions: 診断を変換許可へ流用、未知数を0へ潰す、レポート欠落を正常集計する。
- Recovery: report不正は非zero。元と既存出力を保持し、root/child同時修正で契約を一致させる。

#### CP-013: 識別用拡張の限定許可

- Status: Complete
- Objective: creationIdだけが理由で通常画像を保護する状態を解消する。
- Dependencies: CP-011の実構造、CP-012の診断。
- Files or components: drawing.py（必要なら小さなdrawing_extensions.py）、test_review.py等。
- Actions: 親位置・QName・URI・GUID/Boolean・子/属性/text・重複を検査する専用関数を導入。creationIdと既存useLocalDpiだけを扱い、bytesは変更しない。
- Completion criteria: 正しい識別拡張を持つ画像が次の寸法判定へ進む。未知の混在や画像参照を持つ拡張は保護される。
- Validation: optional属性、GUID/Boolean不正、偽namespace/URI、複数extLst、known+unknown、編集履歴/SVG/外部link、共有画像の一箇所だけ未対応。
- Failure conditions: namespace一括許可、識別情報削除、未知共有利用の見落とし。
- Recovery: 影響する画像partを保護。原本や他の独立した適格画像は壊さない。

#### CP-014: 確認済み字体と既定寸法へのgrid拡張

- Status: Complete
- Objective: 游ゴシックを理由に一律保護せず、確定した配置から必要画素数を求める。
- Dependencies: CP-011の採用可能な計測方式、CP-012/013。
- Files or components: grid.py、予定font_metrics.py、drawing.py、config/diagnostic、grid/runner/root tests。
- Actions: Normal/theme解決、実字体同定、run内metrics cache、列幅/行高の優先順・丸め、保存extentとの差の説明を実装。全共有配置とcropの最大要求を使い、縦横比/切上げ/非拡大を維持する。
- Completion criteria: CP-011で対応可能と判定した配置の全件が未対応理由で停止せず、独立Excel値に基づく必要pixelを下回らない。30配置中の対象数と対象外理由を明記し、根拠のない一律paddingも加えない。
- Validation: 字体差替え/欠落、theme、空行とwrap/autoFit、既定と明示混在、hidden/RTL/数式表示保護、複数列、crop/共有、片軸だけ縮小可能な画像。
- Failure conditions: 代替字体で続行、autoFitを固定行高扱い、保存extentを無条件採用、説明不能な誤差。
- Recovery: 不明な範囲を保護して原因を記録。28画像ブックの通常root Pilotをこの時点で実施し、縮小可能画像があるのに未達なら685画像へ進む前に原因を解消する。

#### CP-015: 1000画像inventoryと資源制限の整合

- Status: Complete
- Objective: 多数の小画像を持つブックを、有限の資源で検査・処理できる。
- Dependencies: CP-012の集計定義、CP-014の必要pixel診断。準備テストは並行作成できる。
- Files or components: package.py、core.py、rootの独立ZIP検証、資源測定script、両suite。
- Actions: root/processorを同じ1000画像定義へ更新。累計XML制限を追加し、代表685画像/1000画像と単一32MPケースのtime/memory/tempを測定する。
- Completion criteria: 500/501/685/1000画像の適格ケースが枚数だけで保護されず、1001と他の資源上限は正しく保護/ERROR。200MP計算と実decode消費が一致する。
- Validation: 共有画像と一般shapeの区別、未参照/不正Content Types、境界±1、累計XML/画素超過、timeout、ディスク不足、report公開失敗、既存出力保護、再実行。
- Failure conditions: 685画像を通すための200MP無効化、rootの500固定値残存、メモリ増大を測らず安全とする。
- Recovery: 未達の上限拡大を採用せず、測定で問題になった候補検証のpart単位読込みなど必要箇所だけを改める。大規模streamingは後段へ分離する。

#### CP-016: 実3冊の再Pilotと全回帰検証

- Status: Complete
- Objective: 合成fixtureだけでなく実資料で、対応範囲・削減・品質と原本保護を確認する。
- Dependencies: CP-014/015。
- Files or components: 現行root CLI、実3冊の独立コピー、Excel本体、比較画像/JSON、全component suites。
- Actions: 元から通常/dry-run/再実行。全source SHA・非変更part bytes・変更画像decode/寸法を確認。実Excelで通常Open、数式/セル/Shape配置を比較し、保存せず終了する。
- Completion criteria: 28画像ブックでCP-011が縮小可能とした画像の処理結果を説明し、採用候補があれば厳密に小さくなる。685画像本は数上限で停止せず解析結果を得る。6画像の低DPI対照は拡大・不要再圧縮しない。
- Validation: 全自動画像検証、Excelの文字・画像位置、変更画像を含むPDFの代表ページと資格証の小文字/番号をローカル比較。比較した範囲/倍率/未確認領域を明記する。
- Failure conditions: データ/配置変化、修復が必要、文字が読みにくい、元不変違反、実資料がなお全て未対応保護で終わる。
- Recovery: 失敗候補は不採用。220DPI/品質85の既定を勝手に下げず、必要なら既存300DPI指定で再評価。実資料の縮小が未確認なら実用対応完了とは記載しない。

#### CP-017: 利用手順・構成図・完了判定

- Status: Complete
- Objective: 実装と手順・制限・結果説明を一致させて引き渡す。
- Dependencies: CP-012〜016。各契約を変えるCPでも影響文書を同時更新する。
- Files or components: MANUAL/REFERENCE/README、component docs、AGENTS、ExecPlan索引、guide、architecture JSONとcompact生成物。
- Actions: schema2、画像数と未知数、追加字体の条件、保護理由、実Pilot範囲を更新。runtime境界/依存/パスが変わる場合はarchifyで再生成・visual-checkし、最終source snapshotを更新する。
- Completion criteria: help・文書・実reportの整合、図とガイドの検査、全必須テスト・compile・diff成功。実装範囲と実資料未達を分けて記録する。
- Validation: 下記コマンド、パス/CSV例、light/dark目視、実3冊の採用/保護内訳。
- Failure conditions: 未実施Pilotを完了扱い、schema/制限の記載漏れ、過去テストを新結果として報告。
- Recovery: 計画状態を実態に合わせて戻し、未達を残す。commit/pushは今回の計画に含めない。

### 初回に含めない項目

- パレットPNG29個の対応は独立した後続候補。保護が画像単位なら、他の適格JPEG/PNGの処理を妨げない。
  対応する場合はPLTE/tRNSと1/2/4/8bitを検査し、PのままresizeせずRGB/RGBAへ展開してからPNGへ保存する。
  再量子化はせず、透過/ICC/gamma/metadata・画素比較・サイズ増加拒否を別recipeとして検証する。
- 大規模な全part遅延読込み/streaming、任意字体/任意autoFit、Excel COMを使う通常処理、画像の単なる再圧縮、
  JPEGの可逆最適化、セル内画像、回転/group/特殊描画、旧xls/xlsm、未知拡張の一括許可。
- Excel保存/修復、原本削除、フォント置換/同梱、外部OCR/アップロード、GUI追加。

### 検証コマンドと実機試験の扱い

```powershell
uv run --project excel-shrink python -m pytest -q excel-shrink/tests
uv run --project pdf-shrink python -m pytest -q pdf-shrink/tests
uv run --project media-shrink-tool --extra dev python -m pytest -q media-shrink-tool/tests
uv run --project video-shrink python -m pytest -q video-shrink/tests
Push-Location orchestrator
uv run --with pytest python -m pytest -q
Pop-Location
uv run --project excel-shrink python -m compileall -q excel-shrink/src excel-shrink/tests
uv run --project pdf-shrink python -m compileall -q pdf-shrink/src pdf-shrink/tests
uv run --project media-shrink-tool python -m compileall -q media-shrink-tool/src media-shrink-tool/tests
uv run --project video-shrink python -m compileall -q video-shrink/src video-shrink/tests
uv run --project pdf-shrink python -m compileall -q karufile.py orchestrator
uv run --script karufile.py --help
git diff --check
```

字体の実計測とExcel比較はWindowsの専用統合試験とし、通常のunit testsは型付きmetricsのfixtureで行う。
実機試験をskipした場合はその理由を表示し、Windows/Excel検証を実施したことにしない。
Excel COMは専用instance、read-only、UpdateLinks=0、通常Open、保存なしとし、元SHAを前後確認する。
マクロ/埋込・外部接続等はOpen前の構造検査で排除し、ユーザーが開いているExcelプロセスには接続/終了しない。
[AutomationSecurity](https://learn.microsoft.com/en-us/office/vba/api/excel.application.automationsecurity)のForceDisableだけでは
Excel4マクロを無効化しないという制約も検証helperに反映する。実資料の画像・人名・資格番号はrepoへ保存しない。

### 計画立案の検証と残る不確実性

- package/core、drawing/grid、root/reportの3視点で独立レビューした。runtimeの編集・変換・新しいテスト実行は行っていない。
- creationIdの意味、列幅/既定行高、GDIの字体mapping、Excel幅取得を一次資料で再確認した。
- GDIと実Excelの一致、実30配置のautoFit依存、28画像本の実縮小余地、685画像本の候補込み200MP適合は未確認。
  これらをCP-011の採用条件に置き、都合のよい仮定で実装へ進めない。
- 7チェックポイントの計画と索引を更新した。現行コード/実Pilotの参照先10件の存在を確認し、文書の空白/競合マーカー検査とgit diff --checkが成功した。
  CP-011〜017をCompleteにするのは、それぞれの実行証拠がそろった後とする。


### 対応拡大の実行記録（2026-09-10、CP-011〜017）

- ユーザーの「つづけて」で実装へ進んだ。今回サブエージェントは起動していない。
- CP-011: GDIでCalibri11 MDW7、游ゴシック11 MDW8を確認。不存在字体のGDI代替も試験し、runtimeでは要求名・実字体・style/size/charset・MDWを確認する。字体データSHAを診断に残す。
- 実30配置のExcel16幅/高さとgrid計算の最大差は0.0000212598425pt。COM Single精度の丸め内で、保存XMLとgrid extentは全30配置で完全一致。比較の許容値をruntimeへ導入していない。
- Calibri/游ゴシック×既定幅/明示既定幅/bestFit幅の合成6ブックは、Excel16の幅・高さと計算が完全一致。
- 実28画像は4画像が300 DPI、残り24画像は220 DPI相当で、ceil・縦横比維持により4画像だけ候補。原画像+候補のデコードは200MP以内。
- CP-012: schema2、unknown画像数と0の区別、段階別の画像診断、2MiB field・深さ8・1000件・CSV32MiB、rootの独立Content Types検査を実装。131072文字超のCSV、偽Boolean/recipe/画像数、重複JSONキー・深さ超過・未完了採用を検証。
- CP-013: creationIdの限定許可とuseLocalDpiのwrapper/既定Boolean検査を追加。既知情報を削除せず、未知混在/URI/QName/属性/子/text/GUID異常は保護。
- CP-014: GDI計測、themeのLatin/EA/Jpan照合、確認済み既定幅、空行の既定行高を追加。実28画像の全30配置を解決し、通常rootで4画像を採用。
- CP-015: root/childの画像数上限を1000へ同期。XML累計32MiB/1Mノードを構築中に制限。500/501/685/1000/1001画像と既知数/未知数、累計XML/画素制限を検証。128MiB ZIP、200MP、300秒等は維持。
- CP-016: 実3冊の通常/dry-run/再実行がexit0。全原本SHA不変。28画像本は3,735,742→3,585,710B、150,032B（4.0161%）減。非変更37partsの展開bytes一致、変更4画像も形式・寸法・metadata/画質基準を検証。
- Excel16で原本/出力を読み取り専用・通常Open・保存なしで開き、数式/セル値hash・30shapeの配置が完全一致。PDF15ページのうち描画差は2/3/14/15ページだけ。全変更4画像の比較と代表14ページを目視し、小文字・罫線・番号に明らかな欠損を認めなかった。全閲覧ソフト・再保存・OCR精度の保証ではない。
- 685画像本は23,170,522Bの原本コピー。534画像は自動行高等、117画像は省略fillRect、3画像は複雑な効果、1画像はextent不一致、30画像は縮小不要。パレットPNG等の追加理由も画像別診断へ記録。枚数で止まらないことを確認したが、この本の縮小成功とは記載しない。
- 6画像本は503,107Bの原本コピーで、不要な拡大・再圧縮なし。
- CP-017: MANUAL/REFERENCE/AGENTS/component READMEを更新。guideは該当記述に矛盾なし、check-guide成功。Archifyの既存Excel nodeへWindows GDIを追記し、validate/deliver9/9・errors/warnings0、visual-check4画面・light/dark4枚目視を完了。

#### 実測に基づく計画変更

1. baseColWidth一般式の無条件採用をやめ、base=8・MDW7/8でExcelが8px境界へ切り上げる限定recipeを採用。明示defaultColWidthとは分離し、任意base/字体へ一般化しない。根拠は上記の独立実測。
2. bestFitそのものを一律に除外せず、保存widthとcustomWidth=trueがある列は固定された保存寸法として扱う。実ファイルも合成6ケースも検証した。自動行高さは引き続き保護。空行はdefaultRowHeightを使用できることを確認し、セル/個別ht/非標準styleがある行へ広げていない。
3. 685画像本でfillRect省略を発見した。[Microsoft SDKのnullable FillRectangle](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.stretch.fillrectangle?view=openxml-3.0.1)を確認し、必須要素欠落ERRORから未対応画像の保護へ訂正。省略時の変換許可までは追加していない。
4. メモリの実測は下記の範囲に収まり、全面streaming化を追加しなかった。

| 変換用合成ブック | 実変更画像 | 処理秒 | PeakWorkingSet bytes | PeakPagefile bytes | 候補ディスク bytes |
|---|---:|---:|---:|---:|---:|
| 685画像（320×160） | 685 | 1.5021 | 67452928 | 57630720 | 5273768 |
| 1000画像（320×160） | 1000 | 2.2968 | 86777856 | 77348864 | 7697593 |
| 32MP単一画像 | 1 | 0.4386 | 304558080 | 295272448 | 4439 |

生成を別プロセスで済ませ、新規Pythonプロセスの変換を測定した。Private BytesもJSONへ保存。685画像の暫定512MiB目標内。全入力の最大メモリ保証ではない。1000画像は通常rootでも全件採用・report独立照合までexit0。

#### 検証証拠と残る範囲

- 自動検証: 最終Excel suite 164 passed、root449 passed、PDF450 passed/4 skipped、画像64 passed、動画113 passed。合計1240 passed/4 skipped。PDFの既存widget fixtureでPageCopyWarning1件。全componentとrootのcompileall、root help成功。
- source/output/dry-run CSV、原本SHA、native geometry/value/formula hash、PDFと比較画像は `C:/Users/tn/Music/KaruFile_Excel対応拡大_20260910/`。画像・人名・資格番号はrepoへ複製していない。
- 集約記録は `docs/validation/2026-09-10-excel-image/expansion-pilot.md`。通常の出力は同ローカルディレクトリのoutput配下。
- 自動行高、未知拡張、パレットPNG、省略fillRect、任意字体等は未対応。685画像本の多くはここに該当する。この後続対応は今回の限定実装の完了と区別する。
- commit/push・原本上書き・外部送信は行っていない。

最終確認: git diff --check成功。原本3冊のSHA、通常/dry-runの画像数・出力欄、再実行後の28画像本の完成SHAを再照合し一致。CLIフラグは不変。

## 固定ピクセル上限の比較（2026-09-10）

ユーザーはA4・Excel設定倍率による印刷方式を検討後、固定長辺上限も許容し、350pxは例示で「比較して上限を決める」と指定した。先に原本由来の350/700/1000/1400px候補を比較し、通常CLIの既定値変更とExcel runtime依存追加はこの比較では行わない。

### CP-018: 実画像の固定上限比較

- Status: Complete (比較・推奨値の判断。通常CLIへの組込みは別作業)
- Objective: 資格一覧.xlsxの文字と容量から、この資料に適した固定上限を判断できる。
- Dependencies: CP-017、ユーザーの比較指定。
- Files or components: excel-shrink/tools、ローカル比較フォルダー、検証記録。
- Actions: 同じJPEG quality85/4:4:4で4候補を各々原本から作り、画像以外の全part不変を検証。元寸法以下のみ縮小。既存の構造保護は維持。Excel read-only PDF出力でページ数・配置・セル値/数式の一致を確認し、細字を同倍率で目視比較する。
- Completion criteria: 4候補の容量・変更数・原本SHA・保存構造の検証結果と、目視に基づく推奨上限/限界が記録され、比較物をユーザーが開ける。
- Validation: 比較toolの境界テスト、Excel suite/compileall、実28画像全体の比較、native PDF/geometry検証、git diff --check。
- Failure conditions: 原本変更、非画像part変更、画像破損、Excel読込失敗、個人情報のrepo混入。
- Recovery: 原本不変の別フォルダーだけを使い、検証に失敗した候補は推奨しない。

判断: A4印刷のための300ppi案とは別の実験とする。固定上限は文字可読性を保証せず、350pxを既定値に採用したとは扱わない。現在の資料で1400px以下なら1400px候補は無変換になることも結果として示す。

### CP-018の結果

- 開発用 `tools/compare_pixel_caps.py` を追加。元画像から各候補を独立作成し、既存の画像metadata/encoder/構造検証を再利用。既存フォルダーへの上書きは拒否する。製品CLI・220dpi既定値・runtime依存関係は変更していない。
- 28画像本の原本3,735,742Bに対し、350px=595,158B/28変更、700px=1,728,661B/28変更、1000px=3,237,096B/9変更、1400px=原本とSHAまで同一/0変更。
- 1000px案をこの資料の推奨とした。350pxは細字が潰れ、700pxは横長の証書の細字が弱くなる。全28画像の概観、細字3例の同倍率比較、A4 PDF第5ページの700/1000pxを目視した。原本自体に薄い/不鮮明な文字があり、全文字の可読性・OCR精度・紙の実印刷は保証しない。
- 1000pxでimage18.jpgは既存の容量/品質gateにより未採用。1023pxを維持するため「全画像を強制的に1000px以下にした」とは表現しない。上限以下の18画像も再圧縮しない。
- 4候補をExcel16でread-only Open/保存なしPDF出力。セル値・数式hash・30shape geometryが完全一致。全候補15ページのA4、PDFテキスト/画像bbox一致、144dpiレンダーの画像bbox+3px外に差分なし。1400px案の原本SHA一致を基準に独立照合した。
- 自動検証175 passed（既存164+追加11）、Excel src/tests/tools compileall成功、git diff --check成功。変更はdeveloper tool/tests/docsのみで、無変更componentのsuiteは再実行していない。
- 原本SHA不変。比較HTML・全28画像・4候補xlsx/PDF・native JSON・print-verification.jsonは `C:/Users/tn/Music/KaruFile_Excel固定px比較_20260910/`。私的画像・人名・番号はrepoに保存していない。
- A4印刷寸法推定のruntime追加、および固定上限の通常CLI採用は未実施。今回はユーザーが指定した比較と資料別推奨値の決定を完了した。

## 800pxとJPEG再圧縮の製品化

ユーザーが800pxを選択し、さらにJPEG圧縮と不可逆劣化を明示許可した。CLIの既定を800px/JPEG品質72にし、明示DPIによる従来方式も残す。PNGは形式/alphaを保持し、JPEGのみ上限以下でも再圧縮する。既存構造保護・画像品質gate・小さい候補だけ採用・非画像part不変は維持する。固定上限でも未対応構造の検査を迂回しない。

### CP-019: 通常CLIの800px/JPEG対応

- Status: Complete
- Objective: root/単独CLIで800pxとJPEG再圧縮を使え、結果を独立検証できる。
- Dependencies: CP-018、800px/不可逆JPEGの明示許可。
- Files or components: excel core/config/cli/report、root validator、tests、契約文書。
- Actions: max-side/quality引数、CLI既定800/72、schema3、同寸法JPEG再圧縮の限定許可、DPIとの排他、要求値照合、原本からの実800px版作成。
- Completion criteria: CLI通常/dry-runで設定通り処理され、偽設定/不正寸法を拒否し、実Excelの配置・数式・セル値不変を確認できる。
- Validation: 対象/全component suite、compileall/help、通常CLI実Pilot/native PDF、diff check。
- Failure conditions: 原本/非画像part変更、拡大、偽レポート受理、可読性の重大な欠損。
- Recovery: 候補は別出力、失敗時は既存出力を維持。原本に戻す操作は不要。

### CP-019の実行結果

- root/単独CLIは既定800px/JPEG品質72。明示DPI150〜300は長辺指定と排他、品質未指定時85。
  長辺100〜10000、JPEG品質40〜95。Python低水準APIの既存既定220/85は互換維持し、CLIで方式を明示して渡す。
- 固定pxでは小さいJPEGも再圧縮、PNGは縮小だけ。alpha/形式、4:4:4・metadata検査、既存構造保護とサイズ/品質gateを維持。
- CSV schema3・recipe grid2-pixel-jpeg-v2。max_side/dpiは排他、jpeg_qualityは常時記録し、rootが要求との一致を確認。
  同寸法変更は固定px方式のJPEGだけ。rootは実画像の目標寸法、画像bytes縮小、非画像part不変を独立検査。
- 通常rootとdry-runがexit0。原本3,735,742B→1,421,684B、61.9437%減。全28JPEG変更、15画像縮小/13画像同寸法再圧縮。全出力画像の長辺800px以下/4:4:4を確認。
- 原本SHA `1ce7679eadde065beebd9b75e5ceef6d99d80aee0c33707dce10c82591d57537` 不変。
  完成SHA `ffb509f29ac30b24000f8f7219c21cbcd83f54345027f975ccfe5880b2a091af`。
- Excel16 read-only Open/保存なしPDF出力が成功。30shape配置・セル値/数式hashが原本と一致。
  A4全15ページでPDFテキスト/画像bbox一致、144dpi画像領域+3px外の差分なし。代表3画像と第5ページを目視し明らかな文字欠損なし。画質劣化はあり、全文字/OCR/紙の実印刷は未保証。
- 全suite: Excel186、root458、PDF450（4skipped/既存PageCopyWarning1）、画像64、動画113。合計1271 passed/4 skipped。
  全component/root compileallと両CLI help成功。初回2失敗は新引数を受けない故障注入mockのsignatureを更新し、元の例外検証を維持して解消。
- MANUAL/REFERENCE/AGENTS/README群・guideを更新。Archify validate/deliver9/9、errors/warnings0。
  4画面containment・最小/最大light/dark4枚目視を確認。guide build/check/render-print成功、Excel節PC/狭幅とA4全7ページ目視確認。
- ローカル成果物/証拠は `C:/Users/tn/Music/KaruFile_Excel800px_JPEG72_20260910/`。完成xlsxはoutput配下。
  入力原本、過去の比較成果物は変更せず、個人情報はrepoへ保存していない。commit/pushなし。
- 不確実性: 固定上限でも未対応の自動行高・未知描画等は保護される。A4倍率解析・Excelのruntime依存は追加していない。

### CP-020: Python APIも800px/JPEG劣化許容を既定化

- Status: Complete
- Objective: CLI/ExcelConfig/process_workbookの無指定がすべて800px/品質72になる。
- Dependencies: CP-019、ユーザーの既定化再指定。
- Files or components: recipe/config/core、既存DPIテスト、新既定値テスト。
- Actions: 未指定設定の解決を共通化し、明示DPIだけ従来方式へ分岐。既存のDPI寸法テストにはその前提を明示する。
- Completion criteria: 無指定と明示800/72の実出力bytesが一致し、既存保護/失敗系のテストも通る。
- Validation: Excel suite、compileall、root既定値テスト。既存CLIの実800/72 PilotはCP-019を再利用。
- Failure conditions: 暗黙220への復帰、明示DPIの破損、原本変更。
- Recovery: 既存原本/出力は変更せず、独立した合成fixtureで確認する。

結果: resolve_recipeでCLIと内部設定の既定を800px/品質72へ統一。CP-019に記録したPython APIの220/85互換既定は撤廃し、明示DPI時だけ従来方式を残した。
無指定と明示800/72の完成xlsx bytes一致、小さいJPEGの再圧縮を検証。従来DPIの寸法/cropテストはdpi=220を明示し、元の期待寸法を維持。
Excel187 passed、root Excel133 passed、Excel src/tests/tools compileallとgit diff --check成功。CLI動作はCP-019から不変で、実Pilot成果物は再生成していない。
AGENTS/component READMEとarchitectureのworktree source SHAを更新。原本・既存出力に変更なし。
