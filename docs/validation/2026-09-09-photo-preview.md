# 写真DPI CLI・比較HTMLの検証記録

2026-09-09、revision `4e5f135360c179aa08d15bf2b9a5831475f901f4`に今回のworking tree変更を加えた状態で検証。
実装の経緯は[ExecPlan](../../.agent/execplans/2026-09-08-pdf-compression-policy-research.md)のCP-014〜016を参照。

## 自動検証

PDF290、画像64、動画104、統合CLI230、合計688テスト成功（skipなし）。規定のcompileall、root/PDF CLI help、git diff --check成功。
wheel/sdist build成功、wheel内のpreview.py/preview.htmlはソースとbyte一致、sdistにもHTML同梱。

## 実資料と再実行

実資料5冊を別出力へ処理し、写真2冊のみ150 DPI/quality80を指定。写真の出力は1,588,343 / 1,228,846 bytes、残り3冊は可逆採用。
5冊合計8,542,212→5,145,151 bytes（39.7679%削減）。この資料での実測値であり、別資料の削減率保証ではない。

| 実行 | 秒 | 結果 |
|---|---:|---|
| 通常150 DPI | 14.949 | exit0、5冊出力 |
| 原本/完成出力比較を追加 | 14.730 | exit0、既存5冊を再利用 |
| 200/180/150 DPI比較を追加 | 94.431 | exit0、既存5冊を再利用 |
| 別出力でdry-run比較 | 2.283 | exit0、完成PDF/HTMLなし |

再利用2回とも完成PDFのSHA-256・mtimeとDB全行（processed_at含む）が不変。
原本5冊と以前の出力548ファイル、計553ファイルのSHA-256がbaselineと一致。
原本から独立生成した150 DPI候補と実際の完成出力で、全65表示領域のPNG SHA-256が一致。

機械可読のコマンド・ログ・時間・入出力hash・DB snapshotは、ローカル検証フォルダー
`C:\Users\tn\Downloads\KaruFile_DPI_CLI検証_20260909\summary.json`に保存。

## 表示と操作

[実際の比較HTML画面（1500×1000）](2026-09-09-photo-preview.png)。元HTMLのSHA-256は
`7690d88dd3b89520512c47498cc0c78c7594b48f0c459a51097e09f5c4cdceeb`、スクリーンショット取得前後で不変。

- Chromeで2資料×2範囲×4候補×3倍率（50/100/250%）、計48条件を切替。全条件で左右画像の寸法・上端が一致し、画像ロード成功。
- 17ページ+48画像配置領域、全65viewを実際に切替・ロード成功。
- 250%拡大で左右のスクロール位置一致を確認。desktopと狭い画面（実測innerWidth502px）でページ全体の横overflowなし。
- 原本と実際の出力、比較専用200/180/150 DPIの区別を目視確認。
- 外部JavaScript、CDN、サーバーなし。比較フォルダー全体を保存してオフラインで開く。

接続ブラウザーにはfile URLのorigin制限に関するconsole errorが1件あった。画像ロードや操作の失敗は再現せず、console無エラーとは記録しない。
この検証は全PDF viewerの互換性やOCR精度を保証しない。写真2冊の150 DPI許容は利用者の先行比較で確認された判断。
