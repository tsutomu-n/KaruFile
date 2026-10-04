# JPEG・PNG・WebP出力とEXIF除去の検証

2026-09-30 12:01 JST。基準commit `6c0ebcc97057a8f24b07c1c3181acdb248ec5689` に対する未コミット実装。
入力は一時ディレクトリの合成画像のみ。実利用者データのPilotは実施していない。

## 要件と証拠

| 要件 | 現在の実装・検証 |
|---|---|
| 3形式を選択可能 | root `--image-format`、画像resize `--format`、ImageConfig.output_format。実CLIで3形式×2presetを実行 |
| EXIF除去 | root `--image-strip-exif`、画像resize `--strip-exif`。JPEG/PNG/WebP入力から各出力へ相互変換し、Artist・GPS・Orientationを検査 |
| 表示方向 | Orientation6を持つ60×40入力が40×60となり、Orientationタグが消えることを確認 |
| PNG/WebP透過 | 1600×1200 RGBA入力のalpha100を1280×960出力でも保持 |
| 除去指定の確実な変換 | 小さなJPEGでも変換を採用。EXIF保持出力から除去設定へ変えると再変換 |
| 除去失敗を公開しない | encoderへEXIFを故意に混入し、候補検証が拒否、既存完成出力bytesが不変 |
| 入力保護 | 相互変換と実root CLIの前後で原本bytes一致。既存のpath/link/原子的公開のsuiteも成功 |
| 再実行 | 3形式すべてでsourceとrecipe一致時にSKIPPED_COMPLETE |
| dry-run | root実CLIと画像CLIで完成出力不変、別dry-run manifest |
| 出力衝突 | 同名・file/directory prefixの衝突を全形式でhash解消。rootと子の計画一致 |
| エラー継続 | encoder失敗はERROR、独立画像はCONVERTED。要求外の原本コピーをしない |
| manifest | output_format/strip_exif/recipe hashを要求と照合。除去設定不一致はrootが拒否 |
| 既定互換 | 既定JPEG/EXIF保持の既存recipe hashと既存画像64 testsを維持 |

追加テストは [test_output_formats.py](../../../media-shrink-tool/tests/test_output_formats.py)。

## 実行した検証

リポジトリルートから実行（統合suiteのみorchestratorへ移動）。

| コマンド | 結果 |
|---|---|
| `uv run --project pdf-shrink python -m pytest -q pdf-shrink/tests` | 471 passed、4 skipped、1 warning、44.43秒 |
| `uv run --project media-shrink-tool --extra dev python -m pytest -q media-shrink-tool/tests` | 108 passed、12.44秒 |
| `uv run --project excel-shrink python -m pytest -q excel-shrink/tests` | 187 passed、10.79秒 |
| `uv run --project video-shrink python -m pytest -q video-shrink/tests` | 113 passed、3.04秒 |
| `uv run --with pytest python -m pytest -q`（orchestrator内） | 468 passed、11.20秒 |
| `uv run --project media-shrink-tool --extra dev python -m pytest -q media-shrink-tool/tests/test_output_formats.py` | 最終調整後44 passed、9.92秒 |

全suite合計 **1347 passed、4 skipped**。再実行44件は合計へ二重加算していない。
PDF warningは合成widget fixtureに対するpikepdf PageCopyWarning。
最初の追加root CLIテストはテストコードの `-i` 欠落で6件失敗した。実CLI仕様に合わせて修正後、すべて成功した。

次も終了コード0を確認した。

```powershell
uv run --project pdf-shrink python -m compileall -q pdf-shrink/src pdf-shrink/tests
uv run --project media-shrink-tool python -m compileall -q media-shrink-tool/src media-shrink-tool/tests
uv run --project excel-shrink python -m compileall -q excel-shrink/src excel-shrink/tests
uv run --project video-shrink python -m compileall -q video-shrink/src video-shrink/tests
uv run --project pdf-shrink python -m compileall -q karufile.py orchestrator
uv run --script karufile.py --help
uv run --project media-shrink-tool python -m media_shrink resize --help
git diff --check
```

## 構成図

archifyの `validate` / `deliver`（architecture、showcase、`--repo-root .`）と `visual-check` を実行。
生成HTMLは手編集していない。9/9 checks、0 errors、0 warnings。
最初のvalidateは `--repo-root` 不足を検出し、ローカルcheckoutを明示した後に成功した。

- diagram_type: architecture
- output: [karufile-runtime.compact.html](../../architecture/karufile-runtime.compact.html)
- specification_sha256: `19811768ff18f7d6f1c7fdc98d97bcc319e087dd0d4d6a7b93a2834943b1dca6`
- artifact_sha256: `0f997f3f4b0e614ff7745b8381020b157e1169f09720a2753e8a33f9299141e3`
- visual_review: passed
- correction_rounds: 0
- 1440×900 / 1600×1000 / 1920×1080 / 2048×1320のcontainment成功。
- 1440×900と2048×1320のlight/dark、計4画像を目視し、画像形式のラベルと線・文字の収まりを確認。
- 自動receiptの `visualReview: pending` は仕様どおり保持し、画像を開いて確認した結果はこの記録に分離。

## 制約

1回の実行で1出力形式。PNGはリサイズ後の可逆保存、JPEG/WebPは非可逆。
EXIF以外のXMP・ICC・コメント等の除去は保証しない。過去形式の出力は自動削除しない。
PDF/Excel内画像は本設定の対象外。入力原本の変更・削除なし。コミット・外部公開なし。

## PNGのEXIF保持・除去の再検証（2026-09-30 14:12 JST）

本依頼の開始時点で、上記の実装とテストは未コミットの作業ツリーに存在した。
既存差分を引き継いでソースを確認し、利用者向け手順をPNGの2パターンとして明記した。
実データの指定はないため、原本への処理は合成画像のみで検証した。

[png-exif-smoke.py](png-exif-smoke.py) を次で実行した。

```powershell
uv run --project media-shrink-tool python docs/validation/2026-09-30-image-formats/png-exif-smoke.py
```

- 入力: JPEG・PNG・TIFF・BMPの計4枚。うち2枚はサブフォルダー。画像以外の1ファイルも配置。
- EXIF保持・全除去の各設定で、通常・再実行・dry-runを実root CLIから計6回実行。終了コードはすべて0。
- 通常処理は各4件CONVERTED、再実行は各4件SKIPPED_COMPLETE、dry-runは各4件DRY_RUN。
- 保持時は合成JPEGのArtist・DateTimeOriginal・GPSを維持し、Orientation6を画素へ適用して60×40から40×60へ変更。
- 除去時は全PNGの `info` にEXIFが存在せず、`getexif()`も空。
- 1600×1200の透過PNGは1280×960となり、alpha100を保持。全画像で既存のstandard寸法上限を確認。
- 全入力のSHA-256・mtimeは全実行で不変。再実行とdry-runで全出力のSHA-256・mtimeも不変。
- dry-runで通常manifestのSHA-256・mtimeが不変。画像出力先に一時ファイルの残存なし。
- 機械可読結果: [png-exif-smoke.json](png-exif-smoke.json)。

最初の合成TIFF作成は、PillowへJPEG用GPS辞書を直接渡したためCLI実行前に失敗した。
TIFFのfixtureを対応する `tiffinfo` に変更した後、全検証が成功した。製品コードの修正は不要だった。

最新の作業ツリーに対して全suiteを再実行した。

| 対象 | 結果 |
|---|---|
| 画像 | 108 passed、17.37秒 |
| 統合 | 468 passed、13.20秒 |
| PDF | 471 passed、4 skipped、1 warning、50.85秒 |
| Excel | 187 passed、12.74秒 |
| 動画 | 113 passed、3.99秒 |

合計1347 passed、4 skipped。PDFのskipは任意の実jpegtran検証、warningは既存の合成widget fixture。
上記の5組のcompileall（検証scriptも含む）と両CLI helpも終了コード0。
最終の文書更新後の `git diff --check` は終了コード0。追加文書の参照先とJSONの解析も成功した。
