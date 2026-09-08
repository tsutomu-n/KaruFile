# KaruFile compact preset 再開引継ぎ

更新日: 2026-09-04（Asia/Tokyo）  
状態: 利用者指示により最終検証工程で中断  
branch / HEAD: `main` / `e9cbe0b73fdf1af5d818c2dacc09c2ae79b09a3e`

## 1. 再開時の結論

機能実装と統合smokeはほぼ完了している。最初に直すべき残件は、
`media-shrink-tool` 単体で画像manifestを公開する直前の、複数入力をまたぐ
source/output identity競合窓1件である。この修正後に既存suiteと最終静的検査を再実行し、
P1/P2だけの最終監査を通せば完了判定できる。

利用者から「TDDなどは必要最低限」と明示されている。実際の失敗経路につき代表回帰1件だけを
置換または追加し、網羅率目的のtest matrixや周辺refactorは増やさない。

## 2. 変更してはいけない既存差分

作業開始時から `docs/architecture/karufile-runtime.html` に利用者の未commit差分があった。
このファイルは上書き・整形・巻き戻ししない。現行図は別名の
`docs/architecture/karufile-runtime.compact.html` と、そのsource JSON／visual-check成果物へ
追加済みである。

commit、push、PR作成は未実施であり、実行には利用者確認が必要である。

## 3. 実装済み範囲

1. 統合CLI
   - `--preset standard|compact` を追加し、既定は `standard`。
   - compact時だけPDF、画像、動画を順次処理する。
   - 全対象の開始時identity/SHA-256 baselineと終了時再照合、結果report/manifestの厳格照合、
     bounded subprocess output、24時間timeout、子process tree停止を実装。
2. PDF
   - 全presetで縮小targetを各軸300 DPI固定。拡大しない。
   - compactはJPEG quality 80と同寸法JPEG再圧縮候補を使用。
   - 1-bit、soft mask、vector text、inline image、署名・添付検査失敗をfail-closedで保護。
   - 表示差、削減率、構造を検証し、不合格なら原本copy。
3. 画像
   - standardは1280x960/q72、compactは1024x768/q60、JPEG 4:2:0。
   - source SHAを含むv2 marker、preset-aware reuse、atomic output、normal/dry-run別all-results manifest、
     error CSV、read-only/hardlink/race保護を実装。
   - 統合CLIはstdoutではなくmanifestのexact totalsを使う。
4. 動画
   - 独立 `video-shrink` projectを追加。
   - compactで安全な8-bit SDR/CFR/単一映像・最大1音声を、最大1280x720/30fpsのAV1へ変換。
   - MP4/M4VはAAC、MKV/WebMはOpus。複雑・未対応構成は原本copy。
   - 全decode、stream/duration、VMAF mean/p5、削減条件、atomic publish、state/report/reuseを実装。
5. 文書・図
   - README、MANUAL、REFERENCE、component docs、AGENTSを現行契約へ更新。
   - compact runtime図をArchify showcaseとして別名生成。

詳細な判断とacceptance criteriaは
[`2026-09-04-compact-preset.md`](2026-09-04-compact-preset.md)を参照する。

## 4. 中断時点で残るP2

対象:

- `media-shrink-tool/src/media_shrink/image.py::_validated_manifest_rows`
- `media-shrink-tool/src/media_shrink/image.py::write_result_manifest`
- `media-shrink-tool/tests/test_image_contract.py::test_manifest_rejects_changed_files_and_preserves_previous_manifest`

現状はmanifest staging後に `_validated_manifest_rows(...)` をもう一度呼ぶが、複数行を順番に
hash検証するだけである。source Aを検証した後、source Bのhash中にAを同size/mtimeで
atomic replacementすると、古いAのfingerprintを含むmanifestを単体CLIが公開してexit 0に
できる競合窓が残る。root orchestratorは終了時の全入力barrierで失敗にできるが、
`media-shrink-tool` 単体の契約として未解決である。

最小修正:

1. 公開直前の全row hash検証後、全source/outputについて処理結果に保持したexpected
   `stat_signature` と現在値を一括再照合するfinal barrierを追加する。
2. 既存のmanifest race testを、2入力で「A検証後、B hash中にAをatomic replacement」する
   代表1件へ置換または拡張する。
3. race時に以前のmanifestとhealthy outputを保持し、非zeroになることを確認する。

実装前に現在の関数形を再確認すること。中断時点ではfinal barrierは未実装で、途中patchもない。

## 5. 確認済み検証

現在のworking treeに対して次を実行済み:

- PDF: `94 passed`
- 画像: `64 passed`
- 動画: `104 passed`
- orchestrator: `120 passed`
- 合計: `382 passed`

直前に修正して確認済みの代表経路:

- orchestratorの複数入力baselineは、全SHA確認後に全identityをもう一巡する。
- 画像manifestのnormal成功行は0-byte outputを拒否する。
- video reportは長時間検証中の同時更新を公開直前に拒否する。
- PDF report commit失敗時は旧reportを復元する。

### 統合実プロセスsmoke

fixture: `C:\Users\tn\AppData\Local\Temp\karufile-compact-final-smoke`

入力SHA-256は処理前後で一致:

| 入力 | bytes | SHA-256 |
|---|---:|---|
| `clip.mp4` | 8,326,391 | `59fc0164a9f18ec5225cf2f2e6789d03653d14ef977e9cf189f7ebb7b8280211` |
| `photo.jpg` | 1,253,266 | `a5d98f258bb6425cc11c700eaa1ceee9df35198139529c0be62f94d295f85b9a` |
| `scan.pdf` | 1,256,835 | `9e14c696f4a23343d7df4fce2a94c555f2b150859ddc58d142f6b932230fe7bb` |

初回compact実行はexit 0、削減率97.77%:

- PDF: `ADOPTED_LOSSY`、38,620 bytes、配置画像 `(300.0, 300.0)` DPI。
- 画像: `CONVERTED`、60,313 bytes、JPEG RGB `1024x768`。
- 動画: `ADOPTED`、142,933 bytes、AV1/AAC、`1280x720`、30fps、progressive、SAR 1:1、
  full decode成功、VMAF mean `94.973082` / p5 `93.756574`。

同じcommandの2回目もexit 0。画像と動画は `SKIPPED_COMPLETE`、PDFはstate再利用により
`Files to process: 0, skipped: 1` となった。

これは合成fixtureによる統合smokeであり、代表実データPilotではない。

### Architecture受入結果

- artifact: `docs/architecture/karufile-runtime.compact.html`
- showcase: 9/9 checks、composition errors 0、warnings 0
- 1440x900、1600x1000、1920x1080、2048x1320でoverflowなし
- specification SHA-256: `119954b4890595f79096e7e162419189cb3a8ca2b3439c4580dfd307677334b2`
- artifact SHA-256: `f6fec38944f96c1b4e39fee4c6cd50b61882fc903a5f7d70f729cb857a1b006b`

## 6. 再開手順

1. 状態確認

   ```powershell
   git status --short
   git diff --check
   ```

2. 上記画像manifest final barrierと代表test 1件だけを実装。

3. 影響範囲を先に確認。

   ```powershell
   uv run --project media-shrink-tool --extra dev python -m pytest -q media-shrink-tool/tests
   Push-Location orchestrator
   uv run --with pytest python -m pytest -q
   Pop-Location
   ```

4. 全suiteと最終静的検査。

   ```powershell
   uv run --project pdf-shrink python -m pytest -q pdf-shrink/tests
   uv run --project media-shrink-tool --extra dev python -m pytest -q media-shrink-tool/tests
   uv run --project video-shrink python -m pytest -q video-shrink/tests
   Push-Location orchestrator
   uv run --with pytest python -m pytest -q
   Pop-Location

   uv run --project pdf-shrink python -m compileall -q pdf-shrink/src pdf-shrink/tests
   uv run --project media-shrink-tool python -m compileall -q media-shrink-tool/src media-shrink-tool/tests
   uv run --project video-shrink python -m compileall -q video-shrink/src video-shrink/tests
   uv run --project pdf-shrink python -m compileall -q karufile.py orchestrator

   uv lock --project pdf-shrink --check
   uv lock --project media-shrink-tool --check
   uv lock --project video-shrink --check
   uv run --script karufile.py --help
   git diff --check
   ```

5. 最終code reviewは要求範囲に直結するP1/P2だけを再監査する。P3、網羅率目的のtest、
   周辺refactorへ広げない。

6. final barrier修正後、上記fixtureで同じcompact commandを1回再実行し、exit 0、入力hash不変、
   manifest/report一致を確認する。既存出力の再利用経路でよい。

   ```powershell
   uv run --script karufile.py --preset compact `
     -i 'C:\Users\tn\AppData\Local\Temp\karufile-compact-final-smoke\input' `
     -o 'C:\Users\tn\AppData\Local\Temp\karufile-compact-final-smoke\output' `
     --pdf-workers 1 --image-workers 1 --video-workers 1
   ```

7. 全条件成功後にExecPlanのCP-007、Progress、Validation Evidence、Outcomesを完了へ更新する。
   commit/pushは利用者から明示承認を得てから行う。

## 7. 残存fixtureと後片付け

次のtest用一時directoryが残っている。再検証に使えるため、再開前には削除しない。

- `C:\Users\tn\AppData\Local\Temp\karufile-compact-final-smoke`
- `C:\Users\tn\AppData\Local\Temp\karufile-image-manifest-20260904-a7c14f3b`

最終検証後に削除する場合は、resolveした絶対pathが
`C:\Users\tn\AppData\Local\Temp` 直下の上記exact nameであることを確認してから、
PowerShellの `Remove-Item -LiteralPath` を使う。

## 8. 受容済み残リスク

- PDFの72 DPI表示検査は閾値より細かい局所劣化を見逃し得る。
- 動画のCFR/HDR入口判定とVMAFは、時間軸の滑らかさ・音声品質・metadata欠落時のSDR性を
  完全には保証しない。
- 動画reuse時はlocal stateとoutput hashを信頼し、full decode/VMAFを再実行しない。
- VMAF JSONの64 MiB上限は生成後検査であり、異常実行中の一時disk消費余地がある。
- preset閾値は代表実データPilot未実施。
- architectureのrepository evidenceは未commit実装ではなく上記HEADを指す。

