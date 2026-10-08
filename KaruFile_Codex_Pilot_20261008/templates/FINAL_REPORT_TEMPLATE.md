# KaruFile web-public Pilot 完了・引継ぎ記録

作成者: Codex CLI / 実施日: YYYY-MM-DD / 作業対象のGitブランチ: ___

## 1. 実施環境

| 項目 | 実測内容 |
|---|---|
| 開始 HEAD | |
| 終了 HEAD / 追跡差分 | |
| OS・Python・uv | |
| Pillow / pillow-heif / NiceGUI / LittleCMS | |
| KaruFile recipe / engine versions | |
| Pilotデータの持出し | なし / （ある場合は承認元・範囲） |

## 2. CPごとの結果

| CP | 状態（PASS/FAIL/BLOCKED/PENDING） | 新規証拠のパス・主な結果 |
|---|---|---|
| CP0 baseline | | |
| CP1 実写真 | | |
| CP2 実NAS | | |
| CP3 局所修正 | | |
| CP4 source identity共通化 | | |
| CP5 全回帰 | | |
| CP6 変更文書 | | |
| downstream Astro | PENDING_DOWNSTREAM / | |

## 3. Freshテスト結果

| コマンド | Exit code | passed/failed/skipped | 証拠 |
|---|---:|---|---|
| Image suites | | | |
| PDF suite | | | |
| Excel suite | | | |
| Video suite | | | |
| Orchestrator suite | | | |
| compileall / help / lock / diff | | | |

**以前の1435/4 skipの記録を今回の実行結果として転載しない。**

## 4. 実写真Pilot（集計のみ）

使用承認あり: YES/NO。対象件数: __。写真: __、図版: __、HEIC: __。
出力: JPEG __ / PNG __。成功 __、警告 __、失敗 __。原本のSHA照合: __。

- 金網/細線: __
- 空/葉/暗部: __
- 重機/工事遠景: __
- 縦写真/向き: __
- 色/ICC・透明度: __
- 見た目の問題と実施した対処: __
- 顔・看板・場所等の公開判断: 担当者確認済 / 別途必要（ソフトだけでは判定しない）

## 5. 実NAS Pilot

実NASアクセス有無: __。
UNC input: __ / output: __ / mapped drive: __。
専用試験領域のみで検証したか: __。
障害復旧: __。作業用pathを外部公開していないか: __。
実機未検証項目: __。

## 6. 共通化とリグレッション

新ファイル: __。既存private import除去: __。旧API aliases: __。
共通化前後の出力policy・画素・manifest差異: __。
過去のruns、通常resize、PDF/Excel/動画へ影響: __。

## 7. 下流サイト

生成masterの引継ぎ方式（安全な共有のみ）: __。
Astro/SharpのAVIF/WebP検証: __。
外部画像/CMS/R2からの取得可否: __。
サイト公開の承認状態: **未実施 / 明示承認済**。

## 8. 判定・次の行動

- READY_KARUFILE: YES/NO (理由)
- READY_TO_INTEGRATE: YES/NO (理由)
- READY_WEBSITE: YES/NO (理由、別担当責任)
- BLOCKED / PENDING: __
- 既知のリスク・回避策: __
- 追加開発が必要な場合の最小変更とテスト: __

### 変更ファイル一覧・差分概要

```
<git diff --statなど（機密ファイル名を含むなら伏せる）>
```

### 書込み範囲

commit: 実施/未実施（SHA） / push: 原則未実施 / 本番公開: 未実施
