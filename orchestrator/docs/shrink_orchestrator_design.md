# KaruFile orchestrator 設計

> 利用者向けの正本は [KaruFile 利用者マニュアル](../../MANUAL.md)です。この文書は
> `orchestrator/shrink_all.py` の内部責務と、処理コンポーネントとの境界を扱います。
> 実装と矛盾する場合は、コードとテストを正とします。

## 責務

リポジトリ直下の `karufile.py` から引数を受け取り、次を担当します。

- 入力、出力、予定出力、状態DB、レポートの保存先を事前検査する。
- `pdf-shrink`、`media-shrink-tool`、compact時の `video-shrink` の順にsubprocessで実行する。
- `--pdf-photo-pattern`をPDF子CLIの`--photo-pattern`へ渡し、レポートのprofileを相対入力パスと照合する。
- `--pdf-lossless-jpeg`/`--pdf-jpegtran-path`をPDF子CLIへだけ委譲する。既定OFF、パスだけでは有効化しない。
- 現在実行の原子的レポートを入力・出力の実ファイルへ照合し、統合サマリーと終了コードを返す。

PDF・画像・動画の変換、候補検証、状態管理、出力公開は複製しません。

```text
karufile.py
  └─ orchestrator/shrink_all.py
       ├─ pdf-shrink        PDFの唯一の処理経路
       ├─ media-shrink-tool 画像の唯一の処理経路
       └─ video-shrink      compact動画の唯一の処理経路
```

## 実行順序

1. input/outputをresolveし、存在、同一、親子関係を検査する。
2. 入力を再帰走査する。シンボリックリンクとjunctionは追跡せず拒否する。
3. PDF・画像・compact動画の予定出力を確定し、同名、file/directory prefix、hardlink、
   link解決後の衝突を検査する。
4. 全対象のstable identityとSHA-256を開始時baselineとして取得する。
5. PDF/動画状態DBとSQLite sidecar、PDF/動画レポート、画像エラーCSV、normal/dry-run画像manifestの
   保存先を検査する。
6. 通常実行だけ出力フォルダーを作り、予定出力と派生保存先を再検査する。
7. PDFがある場合だけ `pdf-shrink` を実行する。
8. 画像が0件の場合も `media-shrink-tool` を実行し、画像エラーCSVと画像manifestの更新を試みる。
9. compact動画がある場合だけ `video-shrink` を実行する。
10. 現在実行で更新されたPDF/画像/動画レポートを入力集合と実ファイルへ照合する。
11. 全入力をbaselineと再照合し、各SHA検証後に全identityを最終確認する。
12. 取得できた値を統合サマリーへ表示し、全体の終了コードを返す。

## 結果の照合

- PDFレポートは、必須列、status、数値、行数、重複のない入力パス集合を検査する。
  `profile`は必須で、各入力が写真選択パターンに一致すれば`photo`、それ以外はpresetの値に
  一致する必要がある。photoの非可逆採用は64 KiBかつ5%以上、他は256 KiBかつ5%以上の削減を
  実出力に照合する。一次候補の診断値は完成出力の集計に使用しない。
  可逆採用は16 KiBかつ2%以上。全行の`lossless_jpeg_requested`が`true`/`false`で実行指定に
  一致することを要求し、旧CSVの欠落、不正表記、不一致は拒否する。
- 画像manifestは入力との1:1対応、予定出力、preset/recipe、source/outputの安定したsizeとSHA-256、
  action別shape、寸法上限、画像エラーCSVとの対応を検査する。統合集計はmanifestのexact totalsを
  使い、子プロセスのstdoutサマリーは使用しない。
- 動画レポートは必須列、status、行数、preset、重複のない入力パス集合に加え、入力・予定出力の
  path、size、SHA-256、削減値を実ファイルと照合する。
- レポートを取得できない、現在実行で更新されていない、または入力集合と
  一致しない場合は、過去の出力ファイルから概算しない。値を `unknown` とし、終了コードを
  `1` にする。
- 子処理の終了コードが `0` でも、レポートにエラーがあれば成功にしない。
- 入力baseline不一致または検証不能は、すべての集計値を `unknown` として終了コード `1` にする。

## 所有境界

- PDF、画像、compact動画は同じ出力フォルダーへ入力内の相対構造を維持して保存する。
- PDFの処理、状態DB、詳細レポートは `pdf-shrink` が所有する。
  写真用の候補生成、300 DPIの細部比較、可逆候補への切り替えもPDF側が担当する。
- 画像の処理、再利用判定、画像エラーCSV、normal/dry-run画像manifestは `media-shrink-tool` が所有する。
- 動画のprobe、変換、検証、state、reportは `video-shrink` が所有する。
- orchestratorは共通DB、worker pool、structured IPCを追加しない。
- standardでは動画を探索・呼び出さない。重複削除、知覚ハッシュ、元ファイル削除は呼び出さない。

写真パターンは入力相対pathを対象に大文字小文字を無視して照合し、区切り`\`を`/`へ正規化する。
`*`は`/`にも一致する。空、絶対パス、`..`を含むパターンは引数不正にする。複数指定はOR条件で、
画像・動画のpresetを変えない。内容の自動分類やDPIによるOCR要否判定は行わない。

## 実行環境とdry-run

- 実行環境には `uv` と、lockfileに従って準備した各projectの依存関係が必要である。
- dry-runは完成PDF・画像・動画と変換用一時ファイルを作らない。
- dry-runでもPDF状態DB、dry-runレポート、画像エラーCSV、画像dry-run manifestは更新される場合がある。
- video dry-runはstate workspace・空DBを初期化する場合があるが、通常実行の成功recordは
  読み書きしない。
- processorのstdout/stderrは画面へ逐次転送し、memoryには固定長tailだけを保持する。
  各processorは24時間でtimeoutし、子process treeも停止する。
