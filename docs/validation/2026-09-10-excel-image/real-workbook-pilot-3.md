# 実xlsx 3冊目: 画像拡張と配置の対応不足

2026-09-10、ユーザー指定の3冊目を現行root CLIで通常処理した。
原本を専用inputへコピーし、`--excel-pattern`に完全ファイル名を指定した。
個人の資格情報・セル値・画像はこの記録へ含めない。

| 項目 | 結果 |
|---|---|
| 元 / 出力 | 3,735,742 B / 3,735,742 B |
| 削減 | 0 B、0% |
| status / exit | PRESERVED_ORIGINAL / 0 |
| report reason | no_resize_candidate; nonvisual_picture_extension=28 |
| 原本 / 出力SHA-256 | 1ce7679eadde065beebd9b75e5ceef6d99d80aee0c33707dce10c82591d57537 |
| ZIP検証 | 全41partの展開後bytes、entry順序、commentが一致 |

画像はRGB JPEG28個、30配置。画像格納容量3,715,095 Bは全体の約99.45%。
長辺752〜1156 px、中央値829.5 px。500〜999 pxが18個、1000 px以上が10個。
最大面積は1137×722 px。合計13,061,951画素。

全30配置がtwoCellAnchor、トリミングなし。全配置にcreationIdとuseLocalDpiの拡張がある。
現行の直接の保護理由はnonvisual_picture_extensionで、候補0。
拡張の条件とは別に、Normal書式がCalibri 11ではないため、限定的なgrid寸法算定でも保護する。
画像数上限には達しておらず、今回も「画像が小さく縮小不要」という判定ではない。

原本・出力がバイト単位で同一であることを独立に確認したため、Excelでの再表示や
PDF出力・画質評価を追加していない。runtimeや保護条件は変更していない。

詳細のローカル証拠は`C:\Users\tn\Music\KaruFile_Excel検証_20260910-171735`以下の
`pilot.json`、`normal.log`、`output.excel-report.csv`、`verification.json`、検証用スクリプトに保存した。
変更は検証記録とExecPlanのみ。文書の差分・空白検査を実施した。

このブックの軽量化は未達。実資料3冊の試行で、現行の画像拡張・字体依存の配置解析が
一般的なExcelファイルに対して狭すぎることが具体化した。上限だけの変更や、
未知構造の一律許可では解決しないため、対応拡大には別途、意味と寸法の検証が必要。
