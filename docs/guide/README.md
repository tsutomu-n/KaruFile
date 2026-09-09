# 入門ガイドの編集と検証

利用者に渡すファイルは [KARUFILE_GUIDE.html](../KARUFILE_GUIDE.html) です。
本文・CSS・2図をすべて含み、単独でオフライン閲覧できます。操作の正本は [MANUAL.md](../../MANUAL.md) です。
マニュアルの相対リンクはリポジトリ内の配置を前提とし、単独配布先には同梱されません。

## 編集するもの

| ファイル | 役割 |
|---|---|
| [guide.template.html](guide.template.html) | 本文、スタイル、印刷用改ページ、図の代替テキスト |
| [copies.architecture.json](copies.architecture.json) | 図1のフォルダーとファイルの対応 |
| [pdf-choices.architecture.json](pdf-choices.architecture.json) | 図2のPDF内容と処理結果の対応 |
| [build-guide.mjs](build-guide.mjs) | 検証済みArchify HTMLの正規PNG書出しを埋め込み、ガイドを生成 |
| [check-guide.mjs](check-guide.mjs) | Chromeで表示、目次、リンク、単独オフライン、A4出力を確認 |
| [chrome.mjs](chrome.mjs) | 上記2スクリプト専用の一時ChromeプロファイルとDevTools接続 |

図の `*.html` と `../KARUFILE_GUIDE.html` は直接編集せず、各正本から再生成します。
アプリの処理コードや依存関係は変更していません。文書の生成・表示確認にはNode.jsとローカルChromeが必要です。
Chromeの自動検出先以外を使う場合は `GUIDE_CHROME` に実行ファイルのパスを指定します。

## 再生成

リポジトリのルートから実行します。以下のArchifyパスはこの作業で使用した配置です。
各 `validate` がshowcaseの9項目を通過し、errors/warningsが0であることを確認します。

```powershell
$archifyCli = Join-Path $env:USERPROFILE '.agents\skills\archify\bin\archify.mjs'
foreach ($diagramName in @('copies', 'pdf-choices')) {
    node $archifyCli validate architecture "docs/guide/$diagramName.architecture.json" --quality showcase --json |
        Set-Content -Encoding utf8 "docs/guide/$diagramName.validation.json"
    if ($LASTEXITCODE -ne 0) { throw "validate failed: $diagramName" }
    node $archifyCli deliver architecture "docs/guide/$diagramName.architecture.json" "docs/guide/$diagramName.html" --quality showcase --json |
        Set-Content -Encoding utf8 "docs/guide/$diagramName.delivery.json"
    if ($LASTEXITCODE -ne 0) { throw "deliver failed: $diagramName" }
    node $archifyCli visual-check "docs/guide/$diagramName.html" --json
    if ($LASTEXITCODE -ne 0) { throw "visual-check failed: $diagramName" }
}
node docs/guide/build-guide.mjs
node docs/guide/check-guide.mjs
git diff --check
```

本文だけを変更した場合はArchifyの再生成を省略し、`build-guide.mjs`以降を実行できます。
ビルドは図JSON・HTML・検証receiptのSHA-256を照合してから、明色の正規PNGを書き出します。
PNGは2080×1136で、ガイドにはdata URLとして埋め込みます。読む側にNode.jsやChrome固有APIは不要です。

`check-guide.mjs`は機械検査と証拠作成だけを行います。ガイドの縦スクロールは意図した動作です。
完了判断には、画面PNGと `validation/guide.a4.pdf` 全ページの目視確認を別途行い、
[REVIEW.md](REVIEW.md)を更新してください。機械receiptの `visualReview: pending` は目視確認を意味しません。

## 実装との照合元

照合時のリポジトリHEAD: `292a9e7f694cdd8e58ef512051db97cd26ded851`（実行コードの変更なし）。

| ガイドの説明 | 読んだ実装・テスト |
|---|---|
| 別出力、標準の対象外形式・動画、出力省略時の名前 | `orchestrator/shrink_all.py` の `main`、`collect_files`、拡張子集合、`orchestrator/test_shrink_all.py` の `test_standard_keeps_v1_behavior_and_does_not_start_video` |
| 図・画像PDFの保護、文章とスキャンの許可 | `pdf-shrink/src/pdf_shrink/policy.py` の `classify`、`pdf-shrink/tests/test_protection_text.py` |
| 文章の白黒候補と採用条件 | `pdf-shrink/src/pdf_shrink/text_optimize.py`、`MANUAL.md`、`docs/REFERENCE.md` |
| 画像の白背景、先頭フレーム、原本維持 | `media-shrink-tool/src/media_shrink/image.py`、`media-shrink-tool/tests/test_image_contract.py` |
| PowerShellの入口・PDF比較 | `karufile.py`、root CLI help、`MANUAL.md` のPDF比較節、`orchestrator/test_photo_preview.py` |

テストは説明の根拠として読みました。実行機能の変更がないため、処理系のpytest・compileallは実行していません。
このガイドの検証は、実資料の圧縮品質や削減率のPilotではありません。

## 証拠

- [図1の検証](copies.validation.json)・[deliver receipt](copies.delivery.json)・[明暗画像](copies.visual-check.html)
- [図2の検証](pdf-choices.validation.json)・[deliver receipt](pdf-choices.delivery.json)・[明暗画像](pdf-choices.visual-check.html)
- [図とガイドのSHA-256・バイト数](guide.build.json)
- [ブラウザーとリンクの検査](guide.verify.json)
- [PC表示](validation/guide.1440.png)・[狭い画面](validation/guide.390.png)
- [A4の印刷結果・4ページ](validation/guide.a4.pdf)
- [目視確認と受入結果](REVIEW.md)
