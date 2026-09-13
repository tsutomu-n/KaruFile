# ExecPlan 索引

このディレクトリの完了済みExecPlanは、当時の判断、変更範囲、検証結果を残す履歴資料です。
現行の利用手順や製品契約は [MANUAL.md](../../MANUAL.md)、文書の役割は
[文書ガイド](../../docs/README.md)を参照してください。

| 計画 | 状態 | 内容 |
|---|---|---|
| [2026-09-13-default-scan-compression.md](2026-09-13-default-scan-compression.md) | 完了・未コミット | スキャンPDFの既定300 DPIグレー圧縮、単一PDF直接入力、実19ページ68.77%減、1303 passed/4 skipped |
| [2026-09-10-nishimaki-pdf-compression.md](2026-09-10-nishimaki-pdf-compression.md) | メイリオ既定化まで完了 | 指定5冊圧縮、分析報告を字体変更。メイリオ選択を追加し1冊目を前回比25.32%減、☑保持。1240 tests成功/4 skipped。既定メイリオの実1冊成功、3冊目の注釈は未対応 |
| [2026-09-10-excel-image-research.md](2026-09-10-excel-image-research.md#excel-expansion-plan) | 800px/JPEG圧縮まで完了 | CP-019完了。ユーザー指定800px・JPEG品質72をCLI既定化、schema3。実28画像すべて圧縮し61.94%減、全1271 tests成功/4 skipped。未対応配置の保護は維持 |
| [2026-09-10-video-policy-audio.md](2026-09-10-video-policy-audio.md) | 完了 | 動画の通常変換、任意safe、音声除去＋圧縮、実2動画Pilot |
| [2026-09-10-windows-font-replacement.md](2026-09-10-windows-font-replacement.md) | 完了 | 明示指定PDFのWindows游ゴシック統一、schema6、独立検証、101p通常CLIで42.64%減、再開/dry-run/Pilot検証 |
| [2026-09-09-font-replacement-pilot.md](2026-09-09-font-replacement-pilot.md) | 同じ1冊で2字体の試験完了・履歴 | Noto版45.28%減、Windows游ゴシック版42.57%減。検索/コピーの推定空白差あり。製品化は9月10日の別計画 |
| [2026-09-09-gunma-compression-diagnosis.md](2026-09-09-gunma-compression-diagnosis.md) | 調査完了・未実装 | 実18冊の容量分析とqpdf5.23%減の限定実験、検証制約と小さな対応拡大の判断 |
| [2026-09-09-document-scan-compression.md](2026-09-09-document-scan-compression.md) | 完了・履歴 | 白黒スキャンの明示二値化、間接Length修正、実資料90.66%削減 |
| [2026-09-09-karufile-guide.md](2026-09-09-karufile-guide.md) | 9月10日追補完了・履歴 | 事務の仕事の例と2図の単独HTML。字体統一・動画圧縮/無音化を追加し、6節・オフライン閲覧・A4全6ページを検証 |
| [2026-08-15-karufile-v1.md](2026-08-15-karufile-v1.md) | 完了・履歴 | KaruFile v1の実装と安全性検証 |
| [2026-08-16-karufile-user-manual.md](2026-08-16-karufile-user-manual.md) | 完了・履歴 | 正本マニュアル、図解、文書監査 |
| [2026-08-20-pdf-300dpi-placed-images.md](2026-08-20-pdf-300dpi-placed-images.md) | 完了・履歴 | PDF配置画像を300DPIへ縮小 |
| [2026-09-04-compact-preset.md](2026-09-04-compact-preset.md) | 中断・再開待ち | compact presetと安全な動画処理 |
| [2026-09-04-compact-preset-handoff.md](2026-09-04-compact-preset-handoff.md) | 再開用 | 中断時点、残るP2、検証証拠、再開手順 |
| [2026-09-08-pdf-compression-policy-research.md](2026-09-08-pdf-compression-policy-research.md) | CP-017/018完了、CP-019/020実装・自動検証/Pilot完了／比較HTMLブラウザー目視のみツールpolicyで停止 | PDF原本保護、文章・罫線表・300 DPIグレースキャン候補、写真DPIと静的HTML比較 |

PDF責務分離の完了記録は
[pdf-shrink側のExecPlan](../../pdf-shrink/.agent/execplans/2026-08-13-refactor-responsibilities.md)にあります。
