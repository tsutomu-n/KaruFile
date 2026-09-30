# compact残件の修正・最終検証（2026-09-30）

基準HEADは`c483d9c`、着手時の作業ツリーはclean。
検証JSONの機械固有の絶対パスは、公開用記録では `<repo-root>` / `<temp-root>` に正規化した。
9月4日のcompact計画を再開し、画像manifestの最後の複数入力間競合と、実CLIで見つけた
既存出力ありのdry-run失敗を修正した。処理recipe、CSV schema、runtime境界、出力パス、依存関係は変更しない。

## 修正と代表回帰

- 全行のSHA-256・寸法検証後、manifestの`os.replace()`直前に全source/outputの
  dev/inode/size/mtime/ctimeを処理時snapshotと再照合する。
- 既存回帰を2入力に拡張。先行source/outputを後続sourceのhash中に同size/mtimeで
  atomic replacementすると、修正前はexit 0、修正後はexit 1。
  旧manifestと正常出力を保持し、一時CSVを回収する。修正前2 failed、修正後2 passed。
- dry-runでは完成JPEG・原本コピーの通常reuseを通らず、既存validatorが要求するdry-run行を返す。
  既存回帰へ通常処理後の2経路を追加し、完成出力と通常manifestのbytes/mtime保持を検証した。
  修正前1 failed、修正後成功。テスト件数は増やしていない。

## pytest

| 対象 | 最終結果 | pytest表示時間 | 根拠 |
|---|---|---|---|
| PDF | 471 passed / 4 skipped | 49.00秒 | pdf-pytest.log / pdf-pytest-result.json |
| 画像 | 64 passed | 2.20秒 | image-final-result.json（ツール出力の記録） |
| Excel | 187 passed | 11.14秒 | excel-pytest.log / excel-pytest-result.json |
| 動画 | 113 passed | 2.75秒 | video-pytest.log / video-pytest-result.json |
| 統合CLI | 468 passed | 11.57秒 | orchestrator-final-pytest.log / orchestrator-final-pytest-result.json |

合計**1,303 passed、4 skipped**。最初の全suite後にdry-run不具合を発見したため、
修正後は影響する画像・統合CLIを再検証した。PDF・Excel・動画の実装は変更していない。
image-pytest.logとorchestrator-pytest.logはdry-run修正前の最初のsuite結果を保持する。
画像の最終結果は実ツール出力から記録し、完全ログを後から再構成していない。

4 skipは`KARUFILE_TEST_JPEGTRAN`未設定による任意jpegtran 3.2.0の実物テスト。
PDFの孤立Widget合成fixtureによる既存PageCopyWarningが1件。検査の無効化・閾値緩和は行っていない。

## 実compact CLIの合成スモーク

リポジトリrootから次を実行した。

```powershell
uv run --project pdf-shrink python docs/validation/2026-09-30-compact-final/compact-smoke.py
```

旧スモーク用フォルダーは空だったため、変更せず新しいOS一時ディレクトリに入力・出力を作成した。
スクリプトは毎回新しい合成PDF・PNG・MP4を作成し、user mediaを読まない。
同じ検証スクリプトの再実行時には、このディレクトリのnormal/resume/dry-runログとsummaryを更新する。

| 実行 | 結果 |
|---|---|
| 通常compact | exit 0。PDF ADOPTED_LOSSY/raster_scan、画像CONVERTED、動画ADOPTED |
| 同設定再実行 | exit 0。PDF状態再利用、画像・動画SKIPPED_COMPLETE |
| 再実行後dry-run | exit 0。完成出力を生成・変更しない |

入力SHA/mtime、再実行・dry-run前後の完成出力SHA/mtime、dry-runでの通常PDF/画像manifest/動画report保持、
manifest・report各1件、画像エラー0、一時ファイルなしをassertした。
画像エラーCSVは通常/dry-run共通で、dry-runでも更新する既存契約を維持する。
数値・SHA・コマンド・実行時間・statusは[compact-smoke-summary.json](compact-smoke-summary.json)、
stdout/stderrはnormal.log、resume.log、dry-run.logに保存した。
初回のdry-run失敗と、その前の通常・再利用成功のログはattempt-1-*に保持した。

## 静的検証・差分確認

[static-checks.json](static-checks.json)の全11コマンドはexit 0。
全processorとroot/orchestrator・スモークスクリプトのcompileall、4 projectのuv lock --check、root/画像CLI helpを含む。
専用lint・型検査の設定を新規追加していない。
P1/P2に絞って最終差分を確認し、今回の範囲で追加の未解決所見はない。
git diff --checkはexit 0。変更文書のローカル参照先89件に欠落なし。
JSON証拠ファイルもすべてparse成功。参照検査はdocument-links.jsonに保存した。

## 限界

合成データでの統合確認であり、広範な実資料・印刷・全viewerの画質保証ではない。
入力ロックを導入していないため、最終検査後のあらゆる外部同時更新を防ぐ保証ではない。
VMAF JSONの64 MiB上限が生成完了後の検査である既存制約は変更していない。
runtime境界やパスは変わらないため、architecture HTML・snapshotは再生成していない。
この検証記録を作成した時点ではcommit/push/PR作成を実行していなかった。
