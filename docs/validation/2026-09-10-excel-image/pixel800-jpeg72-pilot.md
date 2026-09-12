# 800px・JPEG品質72の通常CLI検証

ユーザーが800pxと不可逆JPEG圧縮を明示許可したため、既定の処理を800px/quality72/4:4:4へ変更した。
実Musicの資格一覧.xlsxを別inputへコピーしてroot CLIで実行。通常とdry-runともexit0。

| 項目 | 結果 |
|---|---|
| 原本 | 3,735,742 bytes |
| 完成 | 1,421,684 bytes |
| 削減率 | 61.9437% |
| JPEG変更 | 28画像（15縮小、13同寸法再圧縮） |
| 最大長辺 | 800px以下 |
| 非画像part | 展開bytes一致 |
| Excel16 | read-only Open成功、セル値/数式hashと30shape配置が一致 |
| PDF | A4全15ページ、テキスト/画像bbox一致、144dpi画像領域周辺3px外に差分なし |

原本SHA `1ce7679eadde065beebd9b75e5ceef6d99d80aee0c33707dce10c82591d57537`。
完成SHA `ffb509f29ac30b24000f8f7219c21cbcd83f54345027f975ccfe5880b2a091af`。

元ファイルと過去の比較ファイルは変更していない。出力とverification.json/native JSON/PDF/比較画像は
`C:/Users/tn/Music/KaruFile_Excel800px_JPEG72_20260910/` に保存。完成xlsxはoutput配下。
代表画像3枚とPDF第5ページを目視。画質劣化はあるが、明らかな文字欠損は認めなかった。
全文字の可読性/OCR精度・紙の実印刷は保証しない。私的画像と個人情報はrepoに保存していない。

全suite: Excel186、root458、PDF450（4skipped/既存警告1）、画像64、動画113。
合計1271 passed/4 skipped。全component/root compileall、両CLI help、diff check成功。
固定pxでも配置・形式の既存保護は維持。PNGをJPEG化せずalphaを保持し、保護画像は800pxを超えて残り得る。
