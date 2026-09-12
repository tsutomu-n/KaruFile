# Excel本体による合成ブックの確認

2026-09-10、WindowsのExcel 16.0で実施。対象はroot CLIスモークで作成した
JPEG、PNG、小画像の3合成ブックについて、元と完成出力の計6ファイル。
実業務資料のPilotではない。

```powershell
powershell.exe -NoProfile -File docs/validation/2026-09-10-excel-image/excel-open-smoke.ps1 -SummaryPath docs/validation/2026-09-10-excel-image/root-smoke-summary.json -EvidenceDir docs/validation/2026-09-10-excel-image/excel-native
uv run --project pdf-shrink python docs/validation/2026-09-10-excel-image/verify-excel-pdfs.py
```

両コマンドはexit 0。入力パスは同ディレクトリのroot-smoke-summary.jsonにある一時ファイルを使用する。
再実行時に一時ファイルがなければ、先にroot-smoke.pyを実行し、その新しいsummaryを指定する。

## 結果

- 専用に起動した非表示Excel COMインスタンスで6ファイルすべてを読み取り専用で開けた。
  外部リンク更新を無効、AutomationSecurity=3、イベント無効にして、保存せず閉じた。
- Workbooks.OpenのCorruptLoadは省略時のxlNormalLoadを使用した。
  [Microsoftの仕様](https://learn.microsoft.com/en-us/office/vba/api/excel.workbooks.open)では、
  このオブジェクトモデル経由の既定動作は修復を試みない。
  DisplayAlerts=falseのため、UI警告を目視した試験とは区別する。
- 元と出力でシート数1、A1数式`=1+2`、値3、画像数1が一致。
  画像の表示寸法72×54 pt、位置left=0/top=51 ptも一致。
- 開く前後で6ファイルのSHA-256が一致。
- [Worksheet.ExportAsFixedFormat](https://learn.microsoft.com/en-us/office/vba/api/excel.worksheet.exportasfixedformat)
  によるPDF出力に成功。元/出力とも各1ページで、テキスト・文字位置・画像配置が一致。
- PDFを144 DPIで比較し、画像領域（境界1 ptを含む）外の画素差は全3組で0。
  画像内部は縮小に伴う差がある。原本保護した小画像はページ全画素が一致。
- JPEG/PNGの元/出力PNG4枚を目視し、数字・画像の欠落や位置ずれがないことを確認。

証拠は`excel-native/excel-open-summary.json`、`pdf-comparison.json`、6 PDF、6 PNG。
SHA・位置・数式の確認はスクリプト内でassert相当の比較を行った。

## 限界

元画像は写真に近い周波数成分を持つ合成ノイズであり、細かな文字や写真の意味内容の
可読性を保証する試験ではない。実業務資料、実プリンターでの印刷、Excelでの再保存、
他のExcelバージョン・他の表計算ソフトは未確認。

## 複数セル配置の追加確認

明示的な列幅・行高とCalibri 11のNormal書式を持つ合成twoCellブックについても、
元と出力を同じExcel 16.0で確認した。合計は4合成ブック、8回の読み取り専用Openとなる。

```powershell
uv run --project excel-shrink python docs/validation/2026-09-10-excel-image/grid-native-smoke.py
powershell.exe -NoProfile -File docs/validation/2026-09-10-excel-image/excel-open-smoke.ps1 -SummaryPath docs/validation/2026-09-10-excel-image/grid-native-summary.json -EvidenceDir docs/validation/2026-09-10-excel-image/excel-native-grid
uv run --project pdf-shrink python docs/validation/2026-09-10-excel-image/verify-excel-pdfs.py --directory docs/validation/2026-09-10-excel-image/excel-native-grid --cases grid
```

全コマンドexit 0。画像を420×210 pxへ縮小し、計算上の表示寸法137.25×60 ptが
Excelの元/出力双方のShapes寸法と完全一致した。数式`=SUM(1,2)`、値3、位置も一致。
SHA不変、PDF出力成功。PDFの画像領域外の144 DPI画素差は0で、元/出力のPNGを目視した。
証拠は`excel-native-grid/`以下のJSON・PDF・PNGに保存。

実行時の調整として、PowerShell 7で15引数とType.Missingを渡すCOM呼出しはbinderエラー、
Windows PowerShellでも同15引数形式はOpenエラーとなった。
Windows PowerShellで文書化された省略可能引数を省略した3引数呼出しに変更し成功した。
これは検証スクリプトのCOM呼出しの修正であり、Excel処理本体はExcel COMに依存しない。
