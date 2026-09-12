# 実xlsx 1冊の原本保護Pilot

2026-09-10、ユーザー指定の実資料1冊を現行実装で処理した。
実資料と画像・PDF・セル内容はリポジトリに含めず、Downloads以下のローカル検証フォルダーへ保存した。

## 処理結果

| 項目 | 結果 |
|---|---|
| 元 / 出力サイズ | 503,107 B / 503,107 B |
| 削減 | 0 B、0% |
| 通常status | PRESERVED_ORIGINAL |
| dry-run status | DRY_RUN_PRESERVED |
| 通常 / dry-run終了 | ともに0 |
| 画像数 / 変更数 | JPEG 6枚 / 0枚 |
| 画像寸法 | 全6枚449×337 px、RGB、Orientation=1 |
| 画像格納容量の合計 | 458,575 B、ブック全体の約91.15% |
| 原本 / 出力SHA-256 | be11ffc9c019f1c57958fa7e02862f5f9bb4a650426e2a68f2f6a25f2a3a1994 |

通常reportの理由は`no_resize_candidate; nonvisual_picture_extension=6`。
全画像のnonvisual拡張は`a16:creationId`。既存の限定実装では未知拡張として保護する。
さらにtwoCellのNormal字体はYu Gothic 11であり、現行のCalibri 11限定のセル寸法算定にも該当しない。
保護条件を回避したり、画像を強制再圧縮したりしていない。

## 独立した寸法確認

Excel16.0のShapesから表示寸法を実測した。6枚ともトリミングなし、通常stretch、回転・反転なし。
実効解像度は横95.96〜96.31 DPI、縦95.89〜97.88 DPIとなった。
220 DPIを満たす画素数は約1026〜1030×758〜774 pxであり、元の449×337 pxより多い。
したがって、この資料は画像の過大な画素数を減らす変換の確認には使えない。

保存済みxfrm extentからの計算では96 DPIちょうどだったが、Excel本体の実寸法は少し異なった。
未知の字体や行列寸法について、保存extentを現行表示寸法と無条件に扱わない判断を裏付ける例となった。

## 検証

- 指定ファイルだけを検証用inputへコピーし、root CLIを`--excel-pattern`の完全ファイル名で実行。
  dry-runと通常実行はともに成功。ほかのDownloads内ファイルは処理していない。
- ユーザー原本・検証用input・出力は同じSHA-256。全32 ZIP partの展開後bytesも完全一致。
- 専用の非表示Excel COMで元と出力を読み取り専用Open。
  AutomationSecurity=3、UpdateLinks=0、EnableEvents=false、CorruptLoadは既定xlNormalLoad。
  全5シートのUsedRange.Formula / Value2のハッシュと、全画像の位置・表示寸法が一致。
- 元と出力をExcelからPDFへ出力し、生成された各4ページを比較。
  全ページでテキスト位置と144 DPIのRGB画素が完全一致。
- 画像のある3ページを96 DPI PNGにして目視し、写真と表の配置を確認。
- 検証後も原本SHAは不変。Excelは保存せず終了。

証拠のローカル保存先は`C:\Users\tn\Downloads\KaruFile_Excel検証_20260910-162257`。
`pilot.json`、通常/dry-run CSV、`normal.log`、`native-check.json`、`verification.json`、
検証用スクリプト、元/出力のPDFと比較PNGを保存した。
PowerShell5によるJSON読み取りではUTF-8を明示して再実行し、文字化けしたパス参照を修正した。

この追加確認ではruntimeコードを変更していない。文書の`git diff --check`を実行し、
前段で成功したruntime suiteを意味なく再実行していない。

## 残る範囲

実資料の**原本保護**と読み取り・表示整合のPilotは完了。
実資料で実際に画像を縮小するケース、再保存、物理印刷、別Excel版・別ソフトは未検証。
単なるJPEG再圧縮は今回の「過大な画素数を減らす」機能とは別の変更になるため追加していない。
