# KaruFile web-public Pilot 完了・引継ぎ記録

作成者: Codex CLI / 実施日: 2026-10-08（東京、日本） / 作業対象のGitブランチ: main

**実行可能なローカル作業、commit・push・実merge、現在のWindows PCへの運用反映を完了。**
実写真・実NASは未提供で未実施。下流サイトのbuild・表示・公開はPENDING。
先行Pilotの詳細は[先行報告](../2026-10-08-web-public-pilot/FINAL_REPORT.md)、
今回のGit・運用証拠は[統合記録](README.md)を参照。

## 1. 実施環境

| 項目 | 実測内容 |
|---|---|
| 開始 HEAD | `79df924a924808b4aa7601d7aa797d15ecfd4dcc` |
| 既存実装commit | `61871c6c45edc22e280b57dc2c45ed76af3abdcc`。作業中の別更新でcommit/pushされ、保持した |
| feature / merge | `67c6b292dac0bb3a798d495c7473c450e533bf98` / `cde62c9e2d38bf9a067515260ddd0e0ad9163c66` |
| 終了 HEAD / 追跡差分 | 運用確認時HEADは上記merge。文書の最終確定は後続commit。実装source/test117 filesは試験時・merge・運用先で一致 |
| OS・Python・uv | Windows 11 10.0.26220 / Python 3.13.5 / uv 0.11.15 |
| Pillow / pillow-heif / NiceGUI / LittleCMS | 12.3.0 / 1.5.0 / 3.17.1 / 2.19 |
| KaruFile recipe / engine versions | web-public v2 / schema1維持。libjpeg8.0 / zlib1.3.1.zlib-ng / libheif1.23.1 |
| Pilotデータの持出し | なし。実写真は未提供、合成fixtureのみローカル使用 |
| 運用反映先 | ユーザー指定の現在のWindows PC checkout。既存.venvをlocked sync、cmdも同環境を参照 |

原本ZIPのSHA-256は`008d8d9f2dd3229a3bff1b755dd0585e04c7070a2becf7eeb9d6271fe1bcc341`で不変。
ZIP/展開資料は別更新の61871c6に含まれ、履歴や原本を削除せず保持した。

## 2. CPごとの結果

| CP | 状態 | 新規証拠・主な結果 |
|---|---|---|
| CP0 baseline | PASS | [先行記録](../2026-10-08-web-public-pilot/README.md)、開始410 files SHAとfresh1435/0/4 |
| CP1 実写真 | BLOCKED_REAL_PHOTOS | 実素材/使用承認未提供。P01..P12 NOT_RUN |
| CP2 実NAS | BLOCKED_REAL_NAS | 共有path/権限/専用試験領域未提供。実機操作なし |
| CP3 局所修正 | PASS | atimeのみの変化による不要な再エンコードを修正、失敗/成功テスト保存 |
| CP4 source identity共通化 | PASS | file_identity.py、旧API互換、18新ケース、独立レビュー指摘0 |
| CP5 全回帰 | PASS | 今回の統合前fresh1454/0/4、統合後117 source/test SHA一致 |
| CP6 変更文書 | PASS | 正本文書、ExecPlan、構成図再生成9/9・4明暗画像目視、下流手順・報告更新 |
| downstream Astro | PENDING_DOWNSTREAM | [下流引継ぎ](../2026-10-08-web-public-pilot/DOWNSTREAM_HANDOFF.md)。実site未提供 |
| Git統合・Windows運用 | PASS | [2親mergeとpush](integration-result.json)、[prepared環境の再確認](production-final.json) |

## 3. Freshテスト結果

| コマンド | Exit code | passed/failed/skipped | 証拠 |
|---|---:|---|---|
| Image suites | 0 | 215/0/0 | [image.log](image.log) |
| PDF suite | 0 | 471/0/4 | [pdf.log](pdf.log) |
| Excel suite | 0 | 187/0/0 | [excel.log](excel.log) |
| Video suite | 0 | 113/0/0 | [video.log](video.log) |
| Orchestrator suite | 0 | 468/0/0 | [orchestrator.log](orchestrator.log) |
| compileall / help / lock / diff | 0 | pytest件数外 | [先行checks](../2026-10-08-web-public-pilot/final-checks.json)、[運用help](production-final-help.txt)、[scope確認](scope-review.json) |

統合前に新規実行した合計は**1454 passed / 0 failed / 4 skipped**。
正確なcommandと実行時間は[README](README.md)に記録。
skip4は手動準備のjpegtran3.2.0未設定。PDFの既存PageCopyWarning1件はbaselineにも存在した。
統合でruntime変更はなく、merge treeの一致と117 source/test SHAで試験対象との一致を確認した。

## 4. 実写真Pilot（集計のみ）

使用承認あり: **NO（素材/承認未提供）**。対象件数: **0**。
実素材の写真/図版/HEIC、JPEG/PNG出力、成功/警告/失敗、原本SHAの集計は未取得。

- 金網/細線、空/葉/暗部、重機/工事遠景、縦写真/向き、色/ICC・透明度: 実写真では未実施。
- 見た目の問題と対処: 実写真由来の問題は未確認。合成fixtureの検証は実写真受入に数えない。
- 顔・看板・場所等の公開判断: 担当者の別途確認が必要。

## 5. 実NAS Pilot

実NASアクセス有無: **未提供**。UNC input/output、mapped drive、専用試験領域は未実施。
障害復旧はローカル模擬manifest置換失敗の終了1・旧manifest/旧run保持を確認した範囲のみ。
実NASの権限失敗、切断、復旧後再実行、再利用は未実施。NAS path/認証情報を外部公開していない。

## 6. 共通化とリグレッション

新ファイルはmedia-shrink-tool/src/media_shrink/file_identity.py。
SHA/stat/source fingerprintだけを共通化し、web_public/batchのsource identity private importを除去した。
旧imageの型・例外aliasとhash/capture/assertのmonkeypatch互換を保持。
Pillow/HEIF/NiceGUI非依存の単独importを統合後も確認した。

共通化前後は同じ合成10入力で寸法・画素・色・metadata・出力policy・manifestの意味が一致。
前run/再利用バイト/原本SHA/dry-runと通常resize standard/compactを確認。
PDF/Excel/動画/orchestratorのsourceとlock/configは不変、全suite成功。
未使用のplugin基盤、recipe追加、GUI拡張は作成していない。

## 7. 下流サイト

生成masterの引渡しは実素材未提供で未実施。許可済みrunのJPEG/PNGだけを安全な共有へ渡す手順を記載。
Astro/Sharp AVIF/WebP、外部画像/CMS/R2アクセス、実build/ブラウザー表示は**PENDING_DOWNSTREAM**。
サイト公開は**未実施・承認なし**。今回の「本番反映」は現在のWindows PCのKaruFileと指定された。

## 8. 判定・次の行動

- READY_KARUFILE: **YES**。ローカル契約の自動検証と、指定Windows環境のsource/import/help確認が成功。
- READY_TO_INTEGRATE: **NO（実写真/NAS受入基準）**。その受入は未完了。ユーザーの追加承認により検証済みソースのGit統合・ローカル運用反映は実施済み。
- READY_WEBSITE: **NO**。別siteの受入/build/表示は未実施。
- BLOCKED / PENDING: REAL_PHOTOS / REAL_NAS / DOWNSTREAM / PRODUCTION_VISUAL。
- 既知のリスク・回避策: 実素材画質/色、NAS機種/認証/切断復旧は未検証。同時編集を避け、原本を保持する。
- 次の行動: 使用許可済み写真10〜15枚と専用NAS試験共有で受入手順を実行。下流担当が実siteでAVIF/WebPを確認。
- 追加開発: 現時点では不要な拡張を追加しない。発見された問題を公開可能fixtureで再現し、必要な局所修正だけを行う。

### 変更ファイル一覧・差分概要

Runtimeはfile_identity新設とimage/web_public/batchの移行・atime修正、testsは18+1ケース追加。
正本文書・構成図・計画・Pilot証拠を更新。67c6b29は公開用証拠と運用記録の54 filesを確定。
正確なstaged pathsは[scope-review.json](scope-review.json)、実mergeのtree/parentsは[integration-result.json](integration-result.json)。
この最終追記は文書と検証証拠だけを対象とする。
構成図JSONはLFへ固定、生成HTMLはGit改行変換を無効にし、checkout後も生成receiptのSHAを保つ。

### 書込み範囲

commit: **実施**（61871c6保持、67c6b29、cde62c9） / featureとmain push: **実施** / merge: **実施（2親）**。
本番反映: **現在のWindows PCのKaruFileへ実施**。外部サイト公開: **未実施**。PR: **未実施**。
既存GUIは稼働していなかったため停止/restart不要。原本・無関係な変更・Git履歴を破壊していない。

運用確認日時: **2026-10-08 15:27（東京、日本）**。
