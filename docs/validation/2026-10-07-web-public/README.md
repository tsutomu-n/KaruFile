# 2026-10-07 Web掲載用マスターの実装・検証

Windows上の画像専用CLI `web-public` と日本語NiceGUIを実装した。
基準HEADは `bc88f56a6aadeaa11b0cd6687c45e113ce539547`、以下は未コミットの変更を含む検証記録。
実写真の画質、NAS、後段サイトでの表示は未検証。合成画像の結果を実素材Pilotとは扱わない。

## 再レビュー後の修正・最終検証（2026-10-07 14:25 JST）

初回検証後に見つかった4件と、内部診断の不足を修正した。以下が最新の結果で、後段の174件/1413件は初回実装時の履歴。

- BMP V4/V5の色情報を直接検査。壊れたICC、外部プロファイル参照、calibrated RGB、未知宣言、
  header/画素領域と重なるICC、範囲外/過大ICCを拒否。妥当な埋め込みICCはLittleCMS変換へ渡す。
  異なるトーンカーブのRGB ICCを合成し、入力画素と異なる正しいsRGB画素になることを対照テストで確認。
- Exif ColorSpace/InteropIndexを照合し、矛盾するR03/R98、ICCなしR03、標準sRGB ICCとAdobe指定の矛盾を拒否。
- 成功後の再実行・実行全体の失敗で前回の件数/容量/出力案内を消去。
- プレビューは全タブ共通で同時1件、変換との重複も拒否。5回同時操作でもデコードは1件のみ。
  例外後は再操作可。UIタスクをキャンセルしても、進行中のデコードが終わるまで排他を保持する。
  閉じたダイアログを削除する。
- ローカルloggerに失敗段階・例外クラス等を記録。例外本文を含めず、公開画像や新規ログファイルへ持ち出さない。
- 公開用recipeをv2へ更新。v1のmanifest成功行は再利用せず原本から再生成することを試験。

修正前に新規14ケースが失敗することを確認し、修正後に成功。追加したUIキャンセルの1ケースも失敗→成功を確認。
入力保全、許可されるBMP、ICC範囲、旧recipeの再生成の対照検査を含め、初回から合計22件を追加した。

| 最終suite | 結果 |
|---|---:|
| 画像（公開用88件、既存108件） | 196 passed、24.29秒 |
| PDF | 471 passed、4 skipped、既存1 warning、44.80秒 |
| Excel | 187 passed、11.34秒 |
| 動画 | 113 passed、2.98秒 |
| orchestrator | 468 passed、12.91秒 |
| 合計 | 1435 passed、4 skipped |

コマンドは下記「自動検証」と同じ各suite。compileallはPDF/root/orchestratorを同一コマンドにまとめ、
画像/Excel/動画とあわせて全対象を実行し終了0。`web-public --help`、`uv lock --check`、`git diff --check`も終了0。
今回root/resizeのhelpは再実行せず、初回の確認記録を維持した。

最終コードでNiceGUIを再起動し、Playwright CLIでプレビューの開閉を3回、成功1枚→入出力同一指定による再実行失敗を確認。
古い成功件数なし、出力ボタン無効、閉じたdialogがDOMからなくなることを確認。consoleはerrors 0/warnings 0。
[再実行失敗時の画面](web-public-restart-error.png)を開いて確認した。
プレビュー同時投入・キャンセルは自動ハンドラー試験で確認し、実ブラウザーでのタブ切断試験とは区別する。
実写真・実NAS・後段サイトの未検証範囲は変わらない。ソースSHA snapshotを更新し、runtime境界が変わらない構成図は再生成していない。

## 実装と責務

- `media-shrink-tool/src/media_shrink/web_public.py`: 固定recipe、入力限度、向き補正、sRGB変換、横幅縮小、公開用metadata検証、原本から1回のエンコード。
- `web_public_batch.py`: 選択・path検査、実行別の中立名、SHAとrecipe/engineでの再利用、構造化結果、独立manifestの原子的確定。
- `gui.py`: 日本語操作とローカル実行状態。画像処理はバックグラウンドへ委譲。stdout解析はしない。
- `cli.py`: 専用サブコマンドを追加。通常のresize/root presetと共通helperは変更していない。
- `run-web-public.cmd`: 準備済み`.venv`を使うWindows起動。実cmdで判明した改行問題をCRLFへ修正し、`.gitattributes`で固定。
- GUI依存はoptional extra。Pillow 12.3.0、pillow-heif 1.5.0は維持し、NiceGUI 3.17.1をlock。

利用手順は[MANUAL](../../../MANUAL.md#web掲載用マスターを作る)、厳密な契約は[REFERENCE](../../REFERENCE.md#web-public掲載用マスター)。

## 自動検証

すべてリポジトリrootから実行。orchestratorのみ作業ディレクトリを変更。

| 対象 | 結果 |
|---|---:|
| 画像（既存108件、新規66件、GUI extraを含む） | 174 passed、19.47秒 |
| PDF | 471 passed、4 skipped、1 warning、47.11秒 |
| Excel | 187 passed、11.11秒 |
| 動画 | 113 passed、2.91秒 |
| orchestrator | 468 passed、12.94秒 |
| 合計 | 1413 passed、4 skipped |

PDFのskipとPageCopyWarningは既存のsynthetic fixtureに由来する。今回PDFコードは変更していない。

```powershell
uv run --project media-shrink-tool --extra dev --extra gui python -m pytest -q media-shrink-tool/tests
uv run --project pdf-shrink python -m pytest -q pdf-shrink/tests
uv run --project excel-shrink python -m pytest -q excel-shrink/tests
uv run --project video-shrink python -m pytest -q video-shrink/tests
Push-Location orchestrator
uv run --with pytest python -m pytest -q
Pop-Location
uv run --project pdf-shrink python -m compileall -q pdf-shrink/src pdf-shrink/tests
uv run --project media-shrink-tool python -m compileall -q media-shrink-tool/src media-shrink-tool/tests
uv run --project excel-shrink python -m compileall -q excel-shrink/src excel-shrink/tests
uv run --project video-shrink python -m compileall -q video-shrink/src video-shrink/tests
uv run --project pdf-shrink python -m compileall -q karufile.py orchestrator
uv run --project media-shrink-tool python -m media_shrink resize --help
uv run --project media-shrink-tool python -m media_shrink web-public --help
uv run --script karufile.py --help
uv lock --check --project media-shrink-tool
git diff --check
```

compileall、help、lock整合、差分の空白検査はいずれも終了0。

### 新規テストで確認した境界

- 横幅上限1400、縦写真の寸法、Orientation 2〜8、拡大なし、半端な高さの丸め。
- JPEG品質90/4:4:4設定、PNG画素/alpha、透明写真の拒否、全不透明RGBAの許可。
- Lab ICCからの実変換、ICCなしの警告、破損ICC・CMYK・高bit深度・明示HDRの拒否。
- 合成HEICの実保存/読込み、ICCとOrientationの一度だけの適用。端末由来HEICの画質証拠ではない。
- EXIF/GPS/XMP/IPTC/comment/PNG textの除去。JPEG scan後の禁止metadataと分割不正ICCの拒否。
- PNG cICPのPQ/HLG、mDCv、壊れたiCCPを原データから検出。Pillowがタグを無視してもsRGB仮定で通さない。
- バイト/画素/フレーム制限、エンコード失敗、入力の途中変更、不正な候補を確定しないこと。
- dry-run前後の無書込み、選択外の除外、相対path逸脱・link/hardlinkの拒否、同名画像の衝突回避。
- 実CLI終了0/1/2、混合成功/失敗、旧markerを根拠に省略しないこと。
- 再利用時のエンコーダ非呼出し、完成バイト一致、新run、source/output/recipe/engine改変による再生成。
- 破損manifestからの再生成、manifest保存失敗時の旧manifest保持、最終SHA照合で同サイズ/同mtime改変を検出。
- GUIからの用途/選択の一致、二重start拒否、manifest失敗時の出力案内抑止、同じエラーの連続表示。
- Windowsの日本語・空白pathから実cmd起動、ポート競合案内。CLI importでNiceGUIを読み込まないこと。

## 実ブラウザーとWindowsでの確認

NiceGUIを`127.0.0.1:8080`で起動し、Playwright CLIでChromiumを操作した。
テスト用のローカル一時フォルダーだけを使用。実NASや個人写真は使用していない。

1. 日本語・空白を含む入力pathを貼り付け、正常2枚と不正1枚を一覧・全選択。
2. 写真用途で処理し、成功2枚（うち警告2枚）、失敗1枚、処理済3/3、部分失敗の文言と今回のrunを確認。
3. 選択画像の縮小プレビューと拡大操作を確認。不正画像のチェックを外し、図版用途で2枚を処理。
4. 成功2枚/失敗0枚、容量増加の警告を確認。実出力はPNG RGBの1400×840と300×600で、infoは新規ICCのみ。
5. 6000×4000の合成ノイズJPEGを6枚（合計130,666,602 bytes）処理。実行ボタンがdisabledになることを確認し、変換中にページを再読み込み。
   再読込み後も0/6の処理中表示が応答し、その後6/6・成功6枚/失敗0枚になった。
   manifestと実ファイルを照合し、runは1個、全6件CONVERTED、全出力幅1400を確認。
   入力一覧はページ再読込みでクリアされるが、実行状態と結果はPythonプロセス内に保持される。
6. ブラウザーconsoleはerrors 0、warnings 0。サーバーに残る404 warningは検証時にSocket.IOのURLを誤指定した1件。
   実際の`/_nicegui_ws/socket.io/?EIO=4&transport=polling`へ修正し、接続検査をやり直して成功した。
7. HTTPページとSocket.IO polling handshakeの両方で、ローカルOriginは200、外部Originは403を確認。

保存した画面（各画像を開いて確認済み）:

- [写真の部分失敗](web-public-partial.png)
- [選択画像の縮小プレビュー](web-public-preview.png)
- [図版用PNGの完了](web-public-graphic.png)
- [大画像の変換中・ページ再読込み後](web-public-running.png)

Nativeフォルダー選択ダイアログとExplorerで開く操作自体の手動確認は未実施。今回確認した入力操作はpath貼付け。
出力を開く対象の選定・manifest失敗時の拒否は自動テストで確認。

## 独立レビューと修正

独立エージェントがcore/batch/CLI/GUI/testsを読取りレビュー。
PNGのcICP無視、壊れたiCCPの欠落扱い、最終stat照合だけでは検出できない改変、GUIの同一エラー再表示の4件を指摘した。
前3件は再現テストの失敗を確認して修正。GUIも回帰テストを追加し、全体174件で修正後の成功を確認した。
修正後の独立再レビューを実施済みとは扱わない。
また、実画面で見つかったNiceGUI Table APIの差異と、実cmdで見つかったLF改行問題を修正し再確認した。

## 構成図

通常のroot経路と画像専用web-public経路を別の行に配置し、入力・処理・出力の境界をJSONへ反映。
Archifyのvalidate/deliverは9/9、errors/warnings 0。visual-checkは4 viewportでoverflowなし。
1440×900と2048×1320のlight/dark計4枚を開き、文字と矢印の欠け・重なりがないことを確認。
最初の配置のはみ出しと行間を2回調整した。HTMLを手編集していない。
[確認記録](../../architecture/karufile-runtime.compact.review.md)と[取得時点のSHA](../../architecture/karufile-runtime.compact.worktree.json)を参照。

## 未検証の実環境

- 許可済み実写真10〜15枚の画質・色・処理時間、端末由来HEIC、実図版の可読性。
- UNC入力/出力、割当ドライブ、NAS切断と再接続。ローカルI/O失敗テストをNAS実機確認の代替とはしない。
- 後段Astro/SharpのAVIF/WebP最終表示。今回、その環境や依存は追加していない。
- OSプロセス強制終了中の実機試験。候補の原子的確定と再実行は自動テストで確認。

commit、push、PR作成、公開は実施していない。
検証用ブラウザーとGUIサーバーは終了した。自動承認レビューが一時ファイル削除を含む片付けコマンドを
`blocked by policy`で拒否したため、作業用`.playwright-cli/`と`output/playwright/`は未追跡のまま残している。
公開する検証証拠はこのディレクトリへコピー済み。
記録日: 2026-10-07（東京、日本）。
