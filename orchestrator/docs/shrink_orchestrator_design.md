# KaruFile orchestrator 設計

> 利用者向けの正本は [KaruFile 利用者マニュアル](../../MANUAL.md)です。この文書は
> `orchestrator/shrink_all.py` の内部責務と、処理コンポーネントとの境界を扱います。
> 実装と矛盾する場合は、コードとテストを正とします。

## 責務

リポジトリ直下の `karufile.py` から引数を受け取り、次を担当します。

- 入力、出力、予定出力、状態DB、レポートの保存先を事前検査する。
- `pdf-shrink`、`media-shrink-tool`、明示選択時の `excel-shrink`、compact時の `video-shrink` の順にsubprocessで実行する。
- `--excel-pattern`と長辺上限/JPEG品質（既定800/72）をExcel子CLIへ渡す。明示DPIは長辺指定と排他で品質既定85。パターン無指定・選択0件では起動しない。
- compact専用の`--video-safe`/`--video-remove-audio`を動画子CLIの`--safe`/`--remove-audio`へ渡す。
  既定は両方OFF。動画CSVの`safe`/`remove_audio`と要求値の一致を検証する。
  音声除去指定時の成功は、音声codec欄が空の`ADOPTED`またはその再利用に限定する。
- `--pdf-preserve-pattern`・`--pdf-text-pattern`・`--pdf-text-scan-pattern`・`--pdf-text-scan-bilevel-pattern`・`--pdf-font-replace-pattern`を同名のPDF個別オプション（pdf-除去）へ渡す。
- フォント置換は`--pdf-font-replace-pattern`に一致したPDFだけ。通常圧縮では置換しない。
  置換先はメイリオが既定。`--pdf-font-family`を明示した場合は子CLIの`--font-family`へ渡す。
  familyだけの指定は拒否し、レポートの要求字体を省略時もMeiryo Regularとして照合する。
  游ゴシックは`--pdf-font-family yu-gothic`で明示選択する。
- `--pdf-photo-pattern`をPDF子CLIの`--photo-pattern`へ渡し、レポートのprofileを相対入力パスと照合する。
- `--pdf-photo-dpi`（150〜300、既定200）をPDF子CLIへ委譲し、photo行の要求DPIを検証する。
- `--pdf-preview`と反復`--pdf-preview-dpi`をPDF子CLIへ委譲し、独立manifestを照合する。
- `--pdf-lossless-jpeg`/`--pdf-jpegtran-path`をPDF子CLIへだけ委譲する。既定OFF、パスだけでは有効化しない。
- 現在実行の原子的レポートを入力・出力の実ファイルへ照合し、統合サマリーと終了コードを返す。

PDF・画像・Excel・動画の変換、候補検証、状態管理、出力公開は複製しません。

```text
karufile.py
  └─ orchestrator/shrink_all.py
       ├─ pdf-shrink        PDFの唯一の処理経路
       ├─ media-shrink-tool 画像の唯一の処理経路
       ├─ excel-shrink      明示選択xlsxの唯一の処理経路
       └─ video-shrink      compact動画の唯一の処理経路
```

## 実行順序

1. input/outputをresolveし、存在、同一、親子関係を検査する。
2. 入力を再帰走査する。シンボリックリンクとjunctionは追跡せず拒否する。
3. PDF・画像・指定Excel・compact動画の予定出力を確定し、同名、file/directory prefix、hardlink、
   link解決後の衝突を検査する。
4. 全対象のstable identityとSHA-256を開始時baselineとして取得する。
5. PDF/動画状態DBとSQLite sidecar、PDF/動画レポート、画像エラーCSV、normal/dry-run画像manifestの
   保存先を検査する。PDF比較指定時は`pdf-preview/`とnormal/dry-run比較manifestも検査する。
   Excel選択時はnormal/dry-run Excel reportと`.excel-work/`の保存先も検査する。
6. 通常実行だけ出力フォルダーを作り、予定出力と派生保存先を再検査する。
7. PDFがある場合、またはPDF比較を指定した場合に `pdf-shrink` を実行する。
8. 画像が0件の場合も `media-shrink-tool` を実行し、画像エラーCSVと画像manifestの更新を試みる。
9. `--excel-pattern`で選ばれたxlsxがある場合だけ `excel-shrink` を実行する。
10. compact動画がある場合だけ `video-shrink` を実行する。
11. 現在実行で更新されたPDF/画像/Excel/動画レポートを入力集合と実ファイルへ照合する。
    PDF比較指定時は独立manifestの設定・対象・HTMLのpath/hashも照合する。
12. 全入力をbaselineと再照合し、各SHA検証後に全identityを最終確認する。
13. 取得できた値を統合サマリーへ表示し、全体の終了コードを返す。

## 結果の照合

- PDFレポートは、必須列、status、数値、行数、重複のない入力パス集合を検査する。
  `profile`は必須で、保護を最優先し、photo/text/text_scan/text_scan_bilevel/font_replaceの複数一致はpreflightで拒否する。
  `requested_policy`・`classification`・`permission_basis`・`preservation_reason`・`processing_schema=6`も照合する。
  保護出力はSHA-256一致必須。文章・表・文章スキャン・字体置換は原本より小さい採用だけを許可し、
  photoは非可逆64 KiBかつ5%以上、可逆16 KiBかつ2%以上を照合する。
  全行の`lossless_jpeg_requested`は実行指定と一致し、photo行の`photo_dpi`は要求整数、他は空欄とする。
  字体要求のbool・字体名・SHA・採用出力の抽出差boolも照合し、font_replace以外の行では要求false・字体欄空を必須にする。
- PDF比較manifestは通常`pdf-preview.json`、dry-run`pdf-preview.dry-run.json`を使う。
  schema 1、requested/dry_run、photo_dpi/preview_dpis、入出力root、現在の全PDF行集合と
  source/output SHA-256・PDF status、字体要求/名/抽出差、比較statusを照合する。normalのHTMLは`pdf-preview/<runid>/index.html`
  に限定し、保存先の安全性とSHA-256を確認する。古いmanifest、欠落、不整合は終了コード1。
  比較側ERRORだけで正常PDFの集計を破棄せず、完成PDF結果を保持したまま全体を失敗とする。
- 画像manifestは入力との1:1対応、予定出力、preset/recipe、source/outputの安定したsizeとSHA-256、
  action別shape、寸法上限、画像エラーCSVとの対応を検査する。統合集計はmanifestのexact totalsを
  使い、子プロセスのstdoutサマリーは使用しない。
- 動画レポートは必須列、status、行数、preset、重複のない入力パス集合に加え、入力・予定出力の
  path、size、SHA-256、削減値を実ファイルと照合する。
- Excelレポートは選択入力との1:1対応、予定出力、DPI/長辺上限/JPEG品質、statusと実ファイルのsize/SHA-256を照合する。
  `PRESERVED_ORIGINAL`は原本SHA一致、`ADOPTED_LOSSY`は原本より小さい出力だけを認める。
  `ERROR`は既存出力を成功に数えず、dry-runは完成出力や変更画像数を報告しない。
- レポートを取得できない、現在実行で更新されていない、または入力集合と
  一致しない場合は、過去の出力ファイルから概算しない。値を `unknown` とし、終了コードを
  `1` にする。
- 子処理の終了コードが `0` でも、レポートにエラーがあれば成功にしない。
- 入力baseline不一致または検証不能は、すべての集計値を `unknown` として終了コード `1` にする。

## 所有境界

- PDF、画像、指定Excel、compact動画は同じ出力フォルダーへ入力内の相対構造を維持して保存する。
- PDFの処理、状態DB、詳細レポートは `pdf-shrink` が所有する。
  写真用の候補生成、300 DPIの細部比較、可逆候補への切り替えもPDF側が担当する。
  `preview.py`と静的`preview.html`による比較資料・追加DPI候補・独立manifestもPDF側が所有する。
  比較候補は通常の採用結果・成功stateへ反映しない。HTMLは原本・完成出力・候補PDFとPNGを含む
  実行フォルダーで持ち運べ、サーバー/CDNを使わない。
- 画像の処理、再利用判定、画像エラーCSV、normal/dry-run画像manifestは `media-shrink-tool` が所有する。
- Excelの有界ZIP/XML検査、画像参照・表示寸法・cropの解析、候補と非画像パートの検証、
  normal/dry-run reportと一時領域は `excel-shrink` が所有する。Excel状態DBや成功キャッシュは持たない。
- 動画のprobe、変換、検証、state、reportは `video-shrink` が所有する。
- orchestratorは共通DB、worker pool、structured IPCを追加しない。
- standardでは動画を探索・呼び出さない。重複削除、知覚ハッシュ、元ファイル削除は呼び出さない。

写真パターンは入力相対pathを対象に大文字小文字を無視して照合し、区切り`\`を`/`へ正規化する。
`*`は`/`にも一致する。空、絶対パス、`..`を含むパターンは引数不正にする。複数指定はOR条件で、
画像・動画のpresetを変えない。内容の自動分類やDPIによるOCR要否判定は行わない。

写真用DPIの明示指定には写真パターンを要求する。previewは全PDFを対象にし、追加DPI候補は保護されていないphotoだけに生成する。preview追加DPIにはpreviewを要求し、
150〜300の整数を重複除去・降順に正規化し、5種類を超えた場合は引数不正にする。
写真用DPIは通常処理hashへ含めるが、previewの有無と追加DPIは含めない。

## 実行環境とdry-run

- 実行環境には `uv` と、lockfileに従って準備した各projectの依存関係が必要である。
- dry-runは完成PDF・画像・Excel・動画と変換用一時ファイルを作らない。
- dry-runでもPDF状態DB、dry-runレポート、画像エラーCSV、画像dry-run manifestは更新される場合がある。
- PDF比較のdry-runは要求manifestだけで、HTML・PNG・比較PDF・追加外部tool実行を行わない。
  対象PDFが0件でも比較指定時は空PDF report/stateとmanifestを用意する。normalは対象なしHTMLも作成する。
- video dry-runはstate workspace・空DBを初期化する場合があるが、通常実行の成功recordは
  読み書きしない。
- Excel dry-runは構造と処理予定を調べて専用reportを更新するだけで、完成xlsxや縮小候補を作らない。
- processorのstdout/stderrは画面へ逐次転送し、memoryには固定長tailだけを保持する。
  各processorは24時間でtimeoutし、子process treeも停止する。
