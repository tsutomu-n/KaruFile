# KaruFile web-public Pilot 完了・引継ぎ記録

作成者: Codex CLI / 実施日: 2026-10-08（東京、日本） / 作業対象のGitブランチ: main

**実行可能なローカル作業は完了。全回帰1454 passed / 0 failed / 4 skipped。**
実写真・実NASは未提供で未実施、サイト側の実装・表示検証はPENDING。
実行証拠と細かな限界は[検証記録](README.md)、計画は[ExecPlan](../../../.agent/execplans/2026-10-08-web-public-pilot.md)を参照。

## 1. 実施環境

| 項目 | 実測内容 |
|---|---|
| 開始 HEAD | `79df924a924808b4aa7601d7aa797d15ecfd4dcc` |
| 終了 HEAD / 追跡差分 | 同じHEAD。今回のcode/tests/docs/生成構成図の未commit差分あり。[境界照合](final-boundary.json) |
| OS・Python・uv | Windows 11 10.0.26220 / Python 3.13.5 / uv 0.11.15 / PowerShell 7.6.6 |
| Pillow / pillow-heif / NiceGUI / LittleCMS | 12.3.0 / 1.5.0 / 3.17.1 / 2.19 |
| KaruFile recipe / engine versions | web-public v2・schema1維持。libjpeg 8.0 / zlib 1.3.1.zlib-ng / libheif 1.23.1。hash含む[実測JSON](environment.json) |
| Pilotデータの持出し | なし。実写真は未提供。合成fixtureだけをローカルで使用 |

原本ZIPを保全して同名folderへ展開し、README_FIRST→01_CODEX_PROMPTの指定順に同梱書類を読んだ。
開始時は追跡差分なし、指示ZIPだけが未追跡だった。

## 2. CPごとの結果

| CP | 状態（PASS/FAIL/BLOCKED/PENDING） | 新規証拠のパス・主な結果 |
|---|---|---|
| CP0 baseline | PASS | environment/baseline-*.json/.log、開始410 files SHA。fresh 1435/0/4 |
| CP1 実写真 | BLOCKED_REAL_PHOTOS | 提供/使用承認済み素材なし。PILOT_CASES P01..P12 NOT_RUN |
| CP2 実NAS | BLOCKED_REAL_NAS | 共有path/権限/専用試験領域なし。N01..N04 NOT_RUN、N05は模擬I/Oのみ |
| CP3 局所修正 | PASS（ローカル再現） | atime-only変化による不要な再エンコードを診断→失敗テスト→SHA/stat署名比較へ修正。reuse-red/green logs |
| CP4 source identity共通化 | PASS | 新file_identity.py、旧alias/monkeypatch互換、18新ケース。identity-green 43 passed、独立レビュー指摘0 |
| CP5 全回帰 | PASS | final-*.json/.log、1454/0/4。合成10画像の共通化前後比較一致、compile/help/lock/diff成功 |
| CP6 変更文書 | PASS | MANUAL/REFERENCE/WEB_PUBLIC/AGENTS/index/ExecPlan更新、Archify9/9・4明暗画像目視、下流手順・この報告書 |
| downstream Astro | PENDING_DOWNSTREAM | [DOWNSTREAM_HANDOFF.md](DOWNSTREAM_HANDOFF.md)。別repoの変更/build/表示は未実施 |

- G1：実写真PilotはBLOCKED_REAL_PHOTOS。合成10画像を実写真の代わりには数えていない。
- G2：実NAS PilotはBLOCKED_REAL_NAS。ローカルの模擬置換失敗と実NAS復旧は区別した。
- G3：SHA/stat/source fingerprintに限る共通化と互換・非回帰検証を完了。
- G4：AVIF優先/WebP最終fallbackの引継ぎ資料を完成。実サイトの受入はPENDING_DOWNSTREAM。

## 3. Freshテスト結果

| コマンド | Exit code | passed/failed/skipped | 証拠 |
|---|---:|---|---|
| `uv run --project media-shrink-tool --extra dev --extra gui python -m pytest -q -rs media-shrink-tool/tests` | 0 | 215/0/0 | [final-image.log](final-image.log) |
| `uv run --project pdf-shrink python -m pytest -q -rs pdf-shrink/tests` | 0 | 471/0/4 | [final-pdf.log](final-pdf.log) |
| `uv run --project excel-shrink python -m pytest -q -rs excel-shrink/tests` | 0 | 187/0/0 | [final-excel.log](final-excel.log) |
| `uv run --project video-shrink python -m pytest -q -rs video-shrink/tests` | 0 | 113/0/0 | [final-video.log](final-video.log) |
| `uv run --with pytest python -m pytest -q -rs`（cwd: orchestrator） | 0 | 468/0/0 | [final-orchestrator.log](final-orchestrator.log) |
| compileall / help / lock / diff・参照・SHA | 0 | 全check成功、pytest件数外 | [全コマンド](README.md) / [checks](final-checks.json) / [static](static-checks.json) |

今回のfresh合計は**1454/0/4**。以前の1435/4の記録は今回の結果として転載していない。
skip4件は手動準備のjpegtran 3.2.0未設定。PDFの合成widgetに既存PageCopyWarning 1件があり、baselineでも確認した。
中間の新規parameter名の環境変数上限、親子processのencoding不一致は検証側を修正し、最終実行は成功した。

## 4. 実写真Pilot（集計のみ）

使用承認あり: **NO（素材/承認とも未提供）**。対象件数: **0**。
写真/図版/端末HEIC、JPEG/PNG出力、成功/警告/失敗の実素材集計と原本SHA照合は未取得。

- 金網/細線、空/葉/暗部、重機/工事遠景：実写真の目視は未実施。
- 縦写真/向き、色/ICC・透明度：実素材では未実施。合成fixtureの機械検証だけ実施。
- 見た目の問題と実施した対処：実写真由来の問題は未確認。未対応色情報はsRGBで別名再書出しする運用を文書化。
- 顔・看板・場所等の公開判断：担当者の別途確認が必要。EXIF除去だけでは判断できない。

[PILOT_CASES.csv](PILOT_CASES.csv)のP01..P12はすべて未実施。実写真を会話・Git・クラウドへ送信していない。

## 5. 実NAS Pilot

実NASアクセス有無: **未提供**。
UNC input / output / mapped drive: すべて未実施。
専用試験領域: 未提供、業務共有への操作なし。
障害復旧: 模擬manifest置換失敗の終了1・旧manifest/旧run保持だけfresh suiteで確認。
実NASでの権限失敗・切断・復旧後再実行、NAS経由再利用は未実施。
フォルダー選択・Explorerの今回の実機確認も未実施。作業用NAS pathや認証情報の外部公開なし。

## 6. 共通化とリグレッション

新ファイルは[media_shrink/file_identity.py](../../../media-shrink-tool/src/media_shrink/file_identity.py)。
`SourceChangedError/SourceFingerprint/sha256_file/stat_signature/capture_source_fingerprint/assert_source_unchanged`を公開する。
web_publicとbatchのsource identity private importを除去し、新moduleから取得する。
旧imageの型・例外aliasと`_sha256_file/_stat_signature/_capture_source_fingerprint/_assert_source_unchanged`は維持。
薄い委譲で既存hash/capture/change-checkのmonkeypatch経路を保った。
既存path guardとstaged replaceは元の責務に残した。Pillow/HEIF/NiceGUI非依存のimport試験が成功。

共通化前後の比較はatime修正後の同じ合成10入力で行い、寸法・画素・色・metadata・出力policy・manifestの意味が一致。
原本SHA・前run・再利用バイトは不変、photo/graphicのdry-runは書込みなし、CLI exit 0/1/2を確認。
通常resize standard/compactの比較も一致し、PDF/Excel/動画/orchestratorはsource SHA不変かつfresh suite成功。
将来用途へ再利用できるファイル検証だけを切り出し、未使用のplugin/recipe/GUI拡張は追加していない。

## 7. 下流サイト

生成masterの引継ぎ方式: 実素材未提供のため引渡し未実施。許可済みの今回files内JPEG/PNGだけを安全な共有へ渡す手順を記載。
Astro/Sharp AVIF/WebP検証: **PENDING_DOWNSTREAM**。公式Astro v5 APIを照合した概念例とA-01..A-07を資料化。
同一masterから独立生成、AVIF source優先、img WebP fallback、master以上に拡大しないことを受入条件にした。
外部画像/CMS/R2取得可否: 未検証。実サイトのbuild時アクセス・必要な配信元だけの許可・秘密保持を担当者が確認する。
サイト公開の承認状態: **未実施・承認なし**。PENDING_PRODUCTION_VISUAL。

## 8. 判定・次の行動

- **READY_KARUFILE: YES** — ローカルK/R契約の自動検証と共通化がPASS。実素材/NAS/新規OS操作の受入済みという意味ではない。
- **READY_TO_INTEGRATE: NO** — 実写真・実NASのPilotが未実施。
- **READY_WEBSITE: NO** — 別サイトのA-01..A-07、build/ブラウザー表示が未実施。サイト担当責任。
- BLOCKED / PENDING: REAL_PHOTOS / REAL_NAS / DOWNSTREAM / PRODUCTION_VISUAL。
- 次の行動: 使用許可済み写真10〜15枚と専用NAS試験共有を用意し、MANUALの受入手順を実施。
  サイト担当は実branch/HEAD/config/lockを確認して下流手順を実行。公開には別途明示承認が必要。
- 既知の制約: 実端末HEIC、実写真画質、NAS機種/認証/切断復旧、全ブラウザーの色/透過は未検証。
  ファイルをロックしないため同時編集を避ける。UNSUPPORTED_COLORは原本を残してsRGB別名書出しを優先する。
- 追加開発: 現時点では不要な拡張を追加しない。新しい問題は公開可能fixtureで再現し、失敗テストと局所修正を行う。

### 変更ファイル一覧・差分概要

| 区分 | 変更 |
|---|---|
| Runtime | 新file_identity.py、image.pyのalias/委譲、web_public.py/batchの公開import、batchのatime再利用修正 |
| Tests | 新test_file_identity.py（18ケース）、test_web_public_cli.py（1ケース追加） |
| 正本文書 | AGENTS.md、MANUAL.md、docs/REFERENCE.md、docs/WEB_PUBLIC.md、docs/README.md |
| 計画 | 新2026-10-08-web-public-pilot.mdとExecPlan索引 |
| 構成図 | architecture JSON、生成compact HTML・receipts・visual-check画像、worktree snapshot・review |
| 証拠 | 本folderの実行logs/JSON、再現script、CSV、下流引継ぎ、この報告書 |
| 保全 | 元ZIP、展開した指示書、無関係な追跡ファイル。実写真は保存/追加なし |

正確なmodified/new pathsとSHAは[final-boundary.json](final-boundary.json)に記録。

### 書込み範囲

commit: **未実施**（開始/終了HEAD同一） / push: **未実施** / PR: **未実施** / 本番公開: **未実施**。

最終検証日時は[final-boundary.json](final-boundary.json)の`captured_jst`に記録（東京、日本）。

後続のcommit/push/mergeと現在のWindows PCへの運用反映は追加の明示承認を受けた。
上記の未実施記述は先行報告時点の履歴で、最新結果は[統合記録](../2026-10-08-web-public-integration/README.md)を参照。
