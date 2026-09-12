# excel-shrink

KaruFileの独立したExcel画像処理コンポーネントです。Python 3.13以上とPillowを使用します。
利用者向け手順と安全上の制約は[MANUAL.md](../MANUAL.md)、製品契約は[REFERENCE.md](../docs/REFERENCE.md)を参照してください。

リポジトリrootから実行します。

```powershell
uv run --project excel-shrink excel-shrink run --input C:\work\reports --output C:\work\reports_small --pattern '*.xlsx' --dry-run
uv run --project excel-shrink excel-shrink run --input C:\work\reports --output C:\work\reports_small --pattern '*.xlsx' --max-side 800 --jpeg-quality 72
```

`--input`、`--output`、1個以上の`--pattern`は必須です。パターンは入力相対、大小文字を区別せず、
区切りを正規化し、`*`はディレクトリを越えて一致します。空・絶対・`..`を含む指定は拒否します。
対象は選択された`.xlsx`だけです。`~$`で始まるExcelロックファイルや非選択ファイルは出力しません。
既定は長辺800px・JPEG品質72です。`--max-side`（100〜10000）と`--jpeg-quality`（40〜95）で変更できます。
Python APIの`ExcelConfig`と`process_workbook`も、無指定なら同じ800px・品質72です。
`--dpi`（150〜300）は配置寸法方式を明示選択し、長辺指定と排他で、品質未指定時は85です。
印刷や画像内の文字の可読性を保証する値ではありません。

通常の貼り付けJPEG/PNGを長辺上限に縮小し、上限以下のJPEGも再圧縮します。色差は4:4:4です。
DPI方式だけは全配置とcropから必要画素数を求め、縮小不要のJPEGを再圧縮しません。
固定上限でも既存の配置/形式保護は維持し、保護・棄却画像は上限を超えて残る場合があります。
元の縦横比・画像形式を維持して縮小し、画像以外のZIP part内容は変更しません。
未知・複雑な構造は保護し、解析や入出力の失敗はERRORにします。
原本は変更・削除せず、相対ディレクトリを維持して別出力へ公開します。
保護されたブックはSHA-256が原本と同じコピーになります。縮小候補は検証を通り、ブック全体が
厳密に小さくなった場合だけ採用します。1ファイルの失敗後も独立ファイルを続行します。
ERRORには回復コピーを作らず、公開前の失敗では既存出力を維持します。

逐次処理で、DB・成功キャッシュはありません。再実行のたびに再検査します。
正常出力とレポートは検証済み一時ファイルから`os.replace()`で公開します。
入力と出力の一致・包含、link/junction/hard-linkの出力先、入力を指す補助パスを拒否します。
パスの検査はローカルファイル操作の誤りを防ぐもので、敵対的な同時ファイル変更に対するOS sandboxではありません。

| 用途 | パス |
|---|---|
| 通常CSV | `<output>.excel-report.csv` |
| dry-run CSV | `<output>.excel-report.dry-run.csv` |
| 一時ファイル | `<output>.excel-work/` |

dry-runは解析とCSVだけを作り、完成ブック・画像変換候補を作りません。レポート公開用の一時ファイルは使用します。
CSV schemaは`3`で、状態は`ADOPTED_LOSSY`、`PRESERVED_ORIGINAL`、`ERROR`、`DRY_RUN`、`DRY_RUN_PRESERVED`です。
max_side/dpiは選択方式の列だけを埋め、jpeg_qualityには実指定値を記録します。
`changed_parts`は変更画像part名のJSON配列です。dry-runと保護・ERRORは変更数0、配列`[]`です。
dry-runとERRORの出力サイズ・SHA欄は空欄です。全成功は終了0、必要な処理または報告の失敗は終了1です。
`images_total`は実画像数で、未取得は空欄です。`recipe_version`、`analysis_complete`、
`diagnostics_complete`、`image_diagnostics`で処理版・解析完了・診断省略の有無・画像別結果を記録します。
JSON/CSV fieldはUTF-8で2MiB、詳細は最大1000件、report全体は32MiBです。

Calibri/游ゴシックの標準11ptと確認済みの既定寸法に対応し、WindowsではGDIで数字幅と実字体を確認します。
Excel本体は不要です。非Windowsは従来のCalibri計算だけを使用し、游ゴシックは理由付き保護にします。
`creationId`と`useLocalDpi`は限定検査してXMLをそのまま保持します。未知拡張・自動行高等は保護します。
画像数は1000、累計XMLは32MiB/1,000,000ノードまで。その他の資源上限はREFERENCEを参照してください。

```powershell
uv run --project excel-shrink python -m pytest -q excel-shrink/tests
uv run --project excel-shrink python -m compileall -q excel-shrink/src excel-shrink/tests
```

自動テストの小さな合成ブックと、実Excelでの表示・印刷Pilotは別の検証です。

開発用 `tools/compare_pixel_caps.py SOURCE NEW_DIRECTORY --caps 350 700 1000 1400` は、
原本由来の固定長辺上限候補とローカル比較HTMLを作ります。上限以下は再圧縮せず、
既存の構造・画像形式・容量/品質gateを維持するため、保護画像が上限を超えて残ることがあります。
通常CLIのDPI設定は変更しません。比較HTMLのPDFリンク用には、各候補を
`tools/probe_native.py` で `native-350.json` 等へ `--pdf` 出力してください。
