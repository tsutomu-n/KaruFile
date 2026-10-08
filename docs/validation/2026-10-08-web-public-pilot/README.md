# 2026-10-08 web-public Pilot・source identity共通化の検証

**実行可能なローカル作業は完了。1454 passed / 0 failed / 4 skipped。**
実写真とNAS共有・権限は未提供で、`BLOCKED_REAL_PHOTOS` / `BLOCKED_REAL_NAS`。
サイトの作業環境も未提供のため`PENDING_DOWNSTREAM`。合成fixtureを実素材・実NASの受入証拠に置き換えていない。
指定形式の結果は[FINAL_REPORT.md](FINAL_REPORT.md)、匿名ケースは[PILOT_CASES.csv](PILOT_CASES.csv)、
サイト担当向け手順は[DOWNSTREAM_HANDOFF.md](DOWNSTREAM_HANDOFF.md)に記録した。

## 対象と変更境界

- 開始/終了HEAD：`79df924a924808b4aa7601d7aa797d15ecfd4dcc`、branch `main`。今回の変更は未commit。
- 開始時の追跡差分はなし。未追跡の指示ZIPだけが存在した。
  ZIPを安全な相対path・重複・サイズ・リンクの検査後、同名の新規フォルダーへ展開した。
  `README_FIRST.md`、`01_CODEX_PROMPT.md`から指定順に手順・受入条件・テンプレートを読んだ。
- ZIP SHA-256：`008d8d9f2dd3229a3bff1b755dd0585e04c7070a2becf7eeb9d6271fe1bcc341`。
  同梱内容は指示とテンプレートで、実写真はない。
- [開始時の410追跡ファイルSHA](baseline-source-sha256.json)と[終了時の境界照合](final-boundary.json)で変更範囲を確認する。
  原本ZIP・展開した指示書、PDF/Excel/動画/orchestrator/root CLI、依存設定・lock、通常画像のrecipe、GUI本体は保全した。
- commit・push・PR・本番公開・NAS設定変更・実写真の外部送信は行っていない。新用途・プラグイン・汎用recipe/publish層も追加していない。

## 実施環境

[environment.json](environment.json)と[baseline-checks.json](baseline-checks.json)が実測値。
Windows 11 `10.0.26220`、PowerShell 7.6.6、Python 3.13.5、uv 0.11.15、pytest 9.1.1。
Pillow 12.3.0 / pillow-heif 1.5.0 / NiceGUI 3.17.1 / LittleCMS 2.19 / libjpeg 8.0 /
zlib 1.3.1.zlib-ng / libheif 1.23.1。

web-public recipe v2、manifest schema1を維持。
photo hashは`f07789345215b38e45c02de945b31ed20e8deea481422f0ec86a222fa49c4602`、
graphic hashは`5b65cf5e8b2ac52a2318e665d6279b9fcb17ab07cd395e32e3a3c2bf878e347e`。
通常resizeのstandard/compact設定と旧default JPEG hashも変更していない。

## 局所不具合と共通化

変更前の合成試験で、再利用対象のportraitが再エンコードされる問題を発見した。
3回の診断で、前回出力の読取り前後にatimeだけが変わり、SHAとdev/ino/size/mtime_ns/ctime_nsが一致することを確認した。
`SourceFingerprint`全体の等値比較はatimeも含むため、正常な再利用を拒否していた。
[初回比較失敗](baseline-synthetic.log)、[読取り前後の診断](baseline-reuse-diagnostic.log)、
[失敗テスト](reuse-red.log)を残し、`web_public_batch.py`の条件をSHA＋既存stat署名＋コピー先SHAの照合へ修正した。
[修正後25 tests](reuse-green.log)は成功。実写真/NASで発見した不具合とは報告しない。

[file_identity.py](../../../media-shrink-tool/src/media_shrink/file_identity.py)へSHA/stat/source fingerprintだけを移した。
公開APIは`SourceChangedError`、`SourceFingerprint`、`sha256_file`、`stat_signature`、
`capture_source_fingerprint`、`assert_source_unchanged`。
`utils.py`の既存path guardに依存し、image/Pillow/HEIF/NiceGUIはimportしない。
旧`image.py`の型・例外は同じclassのalias、旧private関数は薄い委譲とし、hash/capture/change-checkのmonkeypatch経路を維持した。
2つのprivate実装入口はその互換呼出しだけに使う。公開・変換の汎用基盤ではない。
`_replace_staged`や既存パス検査は移設していない。

[独立importの初回失敗](identity-red.log)から実装後の[43 tests成功](identity-green.log)まで記録した。
追加18ケースはhash中の変更、同size/復元mtime、同バイト別inode、削除、missing、root外、
実symlinkとWindowsの試験用junction、例外原因、旧alias/monkeypatch、既存出力保持を検証する。
atime再利用の1件と合わせ、imageのテストが196から215へ増えた。
[独立コードレビュー](code-review.md)では指摘0件。実素材受入やNAS保証までレビュー結果を拡張しない。

## 共通化前後の比較

[compare_synthetic.py](compare_synthetic.py)は、横長JPEG、縦PNG、Orientation、幅上限未満、
Lab ICC TIFF、合成HEIC、alpha、細線、未知CMYK、破損JPEGの**合成10画像**を使う。
同じ入力からphoto/graphicの初回・再利用・dry-run、通常resize standard/compactの初回・再利用を実行した。

比較の「前」はatimeの局所修正後・identity移設前であり、元HEADの再利用バグまで同一と主張するものではない。
[baseline-synthetic.json](baseline-synthetic.json)と[final-synthetic.json](final-synthetic.json)は全体が一致する。
寸法・decoded pixel SHA・形式・mode・色・metadata・容量・actions・警告/エラー・recipe/hash/engines・
manifestの意味を比較し、ランダムrun/pathと新ICCの日時/IDは正規化した。
各再利用は前回画像と実バイトSHAが一致し、原本SHA・古いrun・比較前の出力は不変だった。
dry-run書込みなし、CLI終了コード0/1/2も実行した。[comparison.json](comparison.json)

比較の再現例（専用の新しいローカルworkspaceで実行し、実写真を使わない）：

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$comparisonRoot = Join-Path $env:TEMP ('KaruFile-public-comparison-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $comparisonRoot -ErrorAction Stop | Out-Null
uv run --project media-shrink-tool --extra dev --extra gui python docs/validation/2026-10-08-web-public-pilot/compare_synthetic.py $comparisonRoot baseline (Join-Path $comparisonRoot 'baseline.json')
# 対象の変更後、同じworkspaceを指定する
uv run --project media-shrink-tool --extra dev --extra gui python docs/validation/2026-10-08-web-public-pilot/compare_synthetic.py $comparisonRoot final (Join-Path $comparisonRoot 'final.json')
```

Python 3.11としてのAST構文検査は成功したが、3.11実行環境でのruntime試験は行っていない。
実端末HEICの色・向き、金網/葉/空等の実写真画質はこの比較からは保証しない。

## Fresh全回帰

以下はすべて今回新規に実行した結果。10月7日の1435/4を転載していない。
今回の変更前baselineも全suiteを実行し、196/471/187/113/468、合計1435 passed / 4 skippedだった。
`baseline-*.json/.log`に個別のcommand・開始/終了・exitを保持する。
最終実行はUTF-8環境変数を2つとも設定し、rootから実行した。orchestratorだけcwdを同directoryへ変更した。
`-rs`は既存skip理由を表示するために付けた。

| コマンド | Exit | passed / failed / skipped | 秒 | 証拠 |
|---|---:|---|---:|---|
| `uv run --project media-shrink-tool --extra dev --extra gui python -m pytest -q -rs media-shrink-tool/tests` | 0 | 215 / 0 / 0 | 20.47 | [log](final-image.log) / [run](final-image.json) |
| `uv run --project pdf-shrink python -m pytest -q -rs pdf-shrink/tests` | 0 | 471 / 0 / 4 | 44.23 | [log](final-pdf.log) / [run](final-pdf.json) |
| `uv run --project excel-shrink python -m pytest -q -rs excel-shrink/tests` | 0 | 187 / 0 / 0 | 11.22 | [log](final-excel.log) / [run](final-excel.json) |
| `uv run --project video-shrink python -m pytest -q -rs video-shrink/tests` | 0 | 113 / 0 / 0 | 3.45 | [log](final-video.log) / [run](final-video.json) |
| `uv run --with pytest python -m pytest -q -rs`（cwd：orchestrator） | 0 | 468 / 0 / 0 | 12.54 | [log](final-orchestrator.log) / [run](final-orchestrator.json) |
| 合計 | 0 | **1454 / 0 / 4** | — | 上記5 logs |

4 skipは`KARUFILE_TEST_JPEGTRAN`に手動準備したjpegtran 3.2.0を指定する実ツール試験で、未設定のため実行されていない。
自動取得・新規導入・skip解除はしなかった。
PDFの1 warningは既存の合成widget fixtureのpikepdf `PageCopyWarning`で、baselineにも存在する。

## compile・help・lock・静的検査

| 実行コマンド | Exit | 証拠 |
|---|---:|---|
| `uv run --project pdf-shrink python -m compileall -q pdf-shrink/src pdf-shrink/tests` | 0 | [log](compile-pdf.log) / [run](compile-pdf.json) |
| `uv run --project media-shrink-tool python -m compileall -q media-shrink-tool/src media-shrink-tool/tests` | 0 | [log](compile-image.log) / [run](compile-image.json) |
| `uv run --project excel-shrink python -m compileall -q excel-shrink/src excel-shrink/tests` | 0 | [log](compile-excel.log) / [run](compile-excel.json) |
| `uv run --project video-shrink python -m compileall -q video-shrink/src video-shrink/tests` | 0 | [log](compile-video.log) / [run](compile-video.json) |
| `uv run --project pdf-shrink python -m compileall -q karufile.py orchestrator` | 0 | [log](compile-root-orchestrator.log) / [run](final-checks.json) |
| `uv run --project media-shrink-tool python -m media_shrink web-public --help` | 0 | [help](final-web-public-help.txt) |
| `uv run --project media-shrink-tool python -m media_shrink resize --help` | 0 | [help](final-resize-help.txt) |
| `uv run --script karufile.py --help` | 0 | [help](final-root-help.txt) |
| `uv lock --check --project media-shrink-tool` | 0 | [log](final-lock.log) |
| `git diff --check` | 0 | [静的検査](static-checks.json) |
| `media-shrink-tool/.venv/Scripts/python.exe -B docs/validation/2026-10-08-web-public-pilot/verify_final.py` | 0 | [検査script](verify_final.py) / [静的検査](static-checks.json) / [境界](final-boundary.json) |

初回help保存と最終helpでは端末encodingが異なったため、そのままのbyte比較はしなかった。
不変の開始HEADからmedia_shrinkのsourceだけを一時directoryへ読み出し、同じ準備済みPython・UTF-8設定でhelpを再実行した。
checkout/HEADは変更していない。[baseline-help-replay.json](baseline-help-replay.json)と
[web-public UTF-8 baseline](baseline-web-public-help.utf8.txt) / [resize UTF-8 baseline](baseline-resize-help.utf8.txt)が最終helpとbyte一致した。

途中の新規テストでは巨大bytes parameter名がWindows環境変数の上限を超えてsetup error 2件となった。
parameterに短いidsを付けて解決した。[identity-initial-errors.log](identity-initial-errors.log)は要点を保存した記録である。
また共通化前の1実行で、子processだけUTF-8、親processがcp932となるreader warningが6件出た。
親子とも`PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8`へ合わせ、最終image/orchestratorはwarningなしで成功した。
これらは検証環境の不整合として分離し、製品コードやテストの検査を無効化していない。

## 構成図と関連文書

AGENTS/MANUAL/REFERENCE/WEB_PUBLIC/docs index/ExecPlanを更新した。
利用者操作に内部helper名を混ぜず、MANUALには実素材/NAS提供後の確認手順、REFERENCEにはAPI/署名/互換を記載した。
構成図の安全カードへ画像SHA/statの共有を追記し、JSONからArchifyで再生成した。
通常root経路と画像専用経路の責務・パスは維持し、旧`karufile-runtime.html`は変更していない。

```powershell
node C:/Users/tn/.agents/skills/archify/bin/archify.mjs validate architecture docs/architecture/karufile-runtime.architecture.json --repo-root . --quality showcase --json
node C:/Users/tn/.agents/skills/archify/bin/archify.mjs deliver architecture docs/architecture/karufile-runtime.architecture.json docs/architecture/karufile-runtime.compact.html --repo-root . --quality showcase --json
node C:/Users/tn/.agents/skills/archify/bin/archify.mjs visual-check docs/architecture/karufile-runtime.compact.html --json
```

すべてexit0。validate/deliverは9/9、errors/warnings 0。4 viewportでoverflowなし。
最小1440×900/最大2048×1320のlight/dark計4画像を開き、文字・カード・矢印の欠けや重なりなしを確認した。
今回の追加修正roundは0、HTML手編集なし、目視`visual_review: passed`。
自動receiptの`visualReview: pending`は自動判定の境界として維持する。
[構成図review](../../architecture/karufile-runtime.compact.review.md)、
[snapshot](../../architecture/karufile-runtime.compact.worktree.json)、
[visual-check](../../architecture/karufile-runtime.compact.visual-check.json)でSHAと表示を照合できる。

## 未実施と次の受入

| 対象 | 状態 | 必要な次の行動 |
|---|---|---|
| 実写真10〜15枚・端末HEIC・人による細部/公開判断 | BLOCKED_REAL_PHOTOS | 使用許可済みコピーをローカル提供し、MANUALの受入手順を実行 |
| 実NASのUNC入力/出力・割当ドライブ・再利用・許可範囲の切断/復旧 | BLOCKED_REAL_NAS | 専用試験共有/権限と障害試験範囲を用意して実機確認 |
| OSフォルダー選択・Explorer・今回のGUI実操作 | NOT_RUN_THIS_SESSION | 担当Windows PCで確認。10月7日画面証拠と区別 |
| 模擬I/O failure | PASS_LOCAL_SCOPE | manifest置換失敗時の終了1・旧manifest/旧run保持をfresh suiteで確認。実NAS復旧は未実施 |
| Astro/Sharp build・AVIF/WebP実表示・CMS/R2取得 | PENDING_DOWNSTREAM | 下流手順のA-01..A-07を実サイトのbranchで実行 |
| 実サイト公開表示 | PENDING_PRODUCTION_VISUAL | サイト担当の実装検証とユーザーの公開承認後に別途確認 |

判定はローカルK/R契約がPASSのためREADY_KARUFILE=YES。
実素材/NAS受入とサイトbuild/表示は完了していないためREADY_TO_INTEGRATE=NO、READY_WEBSITE=NO。
不足する実環境を理由に共通化・回帰・文書作業を途中で止めず、依頼済みの実行可能範囲を完了した。

記録日：2026-10-08（東京、日本）。最終時刻とHEAD/書込み範囲はFINAL_REPORT.mdを参照。
