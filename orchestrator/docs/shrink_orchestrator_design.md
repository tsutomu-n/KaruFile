# KaruFile orchestrator 設計

> 利用者向けの正本は [KaruFile 利用者マニュアル](../../MANUAL.md)です。この文書は
> `orchestrator/shrink_all.py` の内部責務と、処理コンポーネントとの境界を扱います。
> 実装と矛盾する場合は、コードとテストを正とします。

## 責務

リポジトリ直下の `karufile.py` から引数を受け取り、次を担当します。

- 入力、出力、予定出力、状態DB、レポートの保存先を事前検査する。
- `pdf-shrink`、`media-shrink-tool` の順にsubprocessで実行する。
- 現在実行のレポートと標準出力を照合し、統合サマリーと終了コードを返す。

PDF・画像の変換、候補検証、状態管理、出力公開は複製しません。

```text
karufile.py
  └─ orchestrator/shrink_all.py
       ├─ pdf-shrink        PDFの唯一の処理経路
       └─ media-shrink-tool 画像の唯一の処理経路
```

## 実行順序

1. input/outputをresolveし、存在、同一、親子関係を検査する。
2. 入力を再帰走査する。シンボリックリンクとjunctionは追跡せず拒否する。
3. PDF・画像の予定出力を確定し、同名、file/directory prefix、hardlink、
   link解決後の衝突を検査する。
4. PDF状態DB、SQLite sidecar、PDFレポート、画像エラーCSVの保存先を検査する。
5. 通常実行だけ出力フォルダーを作り、予定出力と派生保存先を再検査する。
6. PDFがある場合だけ `pdf-shrink` を実行する。
7. 画像が0件の場合も `media-shrink-tool` を実行し、画像エラーCSVの更新を試みる。
8. 現在実行で更新されたPDFレポートと画像サマリーを入力集合へ照合する。
9. 取得できた値を統合サマリーへ表示し、全体の終了コードを返す。

## 結果の照合

- PDFレポートは、必須列、status、数値、行数、重複のない入力パス集合を検査する。
- 画像サマリーは、成功件数とエラー件数の合計が現在の画像件数と一致することを検査する。
- レポートまたはサマリーを取得できない、現在実行で更新されていない、または入力集合と
  一致しない場合は、過去の出力ファイルから概算しない。値を `unknown` とし、終了コードを
  `1` にする。
- 子処理の終了コードが `0` でも、レポートまたはサマリーにエラーがあれば成功にしない。

## 所有境界

- PDFと画像は、同じ出力フォルダーへ入力内の相対構造を維持して保存する。
- PDFの処理、状態DB、詳細レポートは `pdf-shrink` が所有する。
- 画像の処理、再利用判定、画像エラーCSVは `media-shrink-tool` が所有する。
- orchestratorは共通DB、worker pool、structured IPCを追加しない。
- 動画、重複削除、知覚ハッシュ、元ファイル削除は呼び出さない。

## 実行環境とdry-run

- 実行環境には `uv` と、lockfileに従って準備した各projectの依存関係が必要である。
- dry-runは完成PDF・画像とPDF一時ファイルを作らない。
- dry-runでもPDF状態DB、PDF dry-runレポート、画像エラーCSVは更新される場合がある。
