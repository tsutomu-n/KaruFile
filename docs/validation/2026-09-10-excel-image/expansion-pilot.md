# Excel画像処理の対応拡大・実資料検証

2026-09-10。通常処理はExcel非依存のまま、Windows GDI字体計測、既定寸法、creationId限定許可、schema2診断、1000画像に対応した。原本は変更していない。

| 実資料 | 画像part | 変更 | 原本 B | 完成 B | 結果 |
|---|---:|---:|---:|---:|---|
| Musicの資格一覧 | 28 | 4 | 3735742 | 3585710 | 150032B、4.02%減 |
| Downloadsの資格証一覧a | 685 | 0 | 23170522 | 23170522 | 自動行高等を保護。枚数上限による停止は解消 |
| 最初の野帳 | 6 | 0 | 503107 | 503107 | 原本コピー、不要な再圧縮なし |

通常/dry-run/再実行と統合レポート照合はexit0。全原本SHA不変、コピー2冊はファイル全体のSHAと展開bytesが一致。
28画像本は37個の非変更partが展開bytes一致。changed_partsはimage4.jpg/image6.jpg/image16.jpg/image18.jpgのみ。

Excel16の通常Openを読み取り専用・リンク更新なし・保存なしで実施。原本/出力の数式・セル値hash、30shapeの寸法・位置・回転が完全一致。
PDF15ページを144DPIで全比較し、変更画像のある2/3/14/15ページだけ描画差。
全変更4画像の原本/出力比較と代表14ページを目視し、小文字・罫線・番号に明らかな欠損なし。
全viewer・OCR・再保存後の同一性や、元から薄い文字の可読性を保証する検査ではない。

GDIはCalibri11 MDW7、游ゴシック11 MDW8を確認。
両字体の既定幅/明示既定幅/bestFit幅、合成6ブックはExcelの寸法と計算が完全一致。
実30配置の最大差は0.0000212598425pt（COM Singleの丸め内）。保存XML extentと計算は全件完全一致。

685画像本の保護理由内訳: 自動行高等534、省略fillRect117、複雑な効果3、extent不一致1、縮小不要30。
パレットPNG等の追加理由も画像別診断へ保存。自動行高や省略fillRectを変換可能にしたという意味ではない。

変換処理の資源測定（fixture生成は別プロセス）:

| 合成入力 | 実変更 | 秒 | PeakWorkingSet B | PeakPagefile B | 候補 B |
|---|---:|---:|---:|---:|---:|
| 685画像 | 685 | 1.5021 | 67452928 | 57630720 | 5273768 |
| 1000画像 | 1000 | 2.2968 | 86777856 | 77348864 | 7697593 |
| 32MP単一 | 1 | 0.4386 | 304558080 | 295272448 | 4439 |

1000画像は通常rootでも全変更・独立report照合成功。上記メモリ値は全入力の保証ではない。
通常CLIの指定/既定220DPI/150〜300範囲は不変。200MP累計・300秒協調期限等は維持。

ローカル証拠は `C:/Users/tn/Music/KaruFile_Excel対応拡大_20260910/`。
元/完成.xlsx、通常/dry-run CSV、native JSON、PDF、比較画像、benchmark JSONを保存。
個人名・番号・画像・セル内容はrepoへ保存していない。

検証ツール: `excel-shrink/tools/probe_native.py` / `probe_native.ps1`、`benchmark.py`。
実装・自動検証の全記録は[ExecPlan](../../../.agent/execplans/2026-09-10-excel-image-research.md#excel-expansion-plan)。

28画像本の変更4画像は原本+候補合計4,647,101 pixels。

自動検証はExcel164、root449、PDF450（4 skipped）、画像64、動画113、合計1240 passed。全compileall・help・git diff --check成功。PDFの既存widget fixtureで警告1件。
