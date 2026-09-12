# 固定ピクセル上限の比較

2026-09-10、Music内の資格一覧.xlsx（28画像）を、原本から独立に350/700/1000/1400pxへ縮小した。
JPEG quality85、4:4:4、LANCZOS。Excel配置/印刷設定は不変。通常CLIではなくdeveloper toolの比較実験。

| 長辺目標 | bytes | 変更画像 | 判断 |
|---|---:|---:|---|
| 原本 | 3735742 | 0 | 比較基準 |
| 350 | 595158 | 28 | 細字の輪郭が潰れるため非推奨 |
| 700 | 1728661 | 28 | 容量は減るが横長証書の細字が弱くなる |
| 1000 | 3237096 | 9 | 今回の資料の推奨、13.35%削減 |
| 1400 | 3735742 | 0 | 全画像が元から上限以下、原本とSHA一致 |

原本SHA256: `1ce7679eadde065beebd9b75e5ceef6d99d80aee0c33707dce10c82591d57537`

1000px出力SHA256: `f6005fda0e5e12f1494508ffc579251bee8bc70f6668efe525e568a4031fdb56`

1000px案のimage18.jpgは容量/品質gateで不採用となり元の1023pxを維持した。厳密な全画像上限の保証ではない。
元から1000px以下の18画像も再圧縮しない。非変更partの展開bytes、ZIP entry順/commentを照合。

Excel16で4候補をread-only Open、保存なしでPDF出力した。原本SHAと同一の1400px案を基準に、
セル値/数式hash・30shape geometryの完全一致を確認。全4候補15ページA4、PDFのテキスト位置と
画像bbox一致、144dpiレンダーで画像bbox周辺3pxを除く領域に差分なし。

28画像概観、細字3例の同倍率比較、A4 PDF第5ページの700/1000pxを目視確認した。
紙の実印刷は未実施で、全文字の可読性/OCR精度や他資料への1000pxの一般化は保証しない。

検証: Excel suite175 passed、Excel src/tests/tools compileall、git diff --check成功。
変更は比較tool/tests/docs。通常runtime・schema・既定値に変更はない。

比較HTML、全画像、4候補xlsx/PDF、native JSONとprint-verification.jsonは
`C:/Users/tn/Music/KaruFile_Excel固定px比較_20260910/` に保存。個人情報を含む比較物はrepoに入れない。
