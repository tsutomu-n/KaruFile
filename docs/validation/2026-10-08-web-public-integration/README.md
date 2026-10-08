# 2026-10-08 web-public修正のGit統合・運用反映

ユーザーの「コミット、プッシュ、マージ。本番反映」と、反映先「このWindows PCの現在のKaruFile」に基づく後続作業。
先行Pilotの未commit記録とは時点を区別する。実写真/NAS/下流サイトのBLOCKED/PENDINGは維持する。

## Preflightと対象

[preflight.json](preflight.json)のread-only APIとfetchで、開始HEAD/origin mainが
`79df924a924808b4aa7601d7aa797d15ecfd4dcc`、main保護なし、ruleset/CI/deployment/release/environmentなしを確認した。
開始時worktree1個、stash/tag/他branchなし。元ZIPと展開した指示書は保全する。
既存コードのrecipe/schema/CLIは維持し、source identityとatime修正、tests、docs、検証証拠だけを統合する。

## 統合前のfresh全回帰

以下は今回の統合作業で再実行した結果。先行報告の件数を新規実行の代わりに使っていない。
UTF-8環境変数2つを設定。orchestrator以外はroot、orchestratorだけそのdirectoryから実行。

| command | exit | passed/failed/skipped | 秒 | 証拠 |
|---|---:|---|---:|---|
| `uv run --project media-shrink-tool --extra dev --extra gui python -m pytest -q -rs media-shrink-tool/tests` | 0 | 215/0/0 | 22.01 | [log](image.log) / [run](image.json) |
| `uv run --project pdf-shrink python -m pytest -q -rs pdf-shrink/tests` | 0 | 471/0/4 | 46.57 | [log](pdf.log) / [run](pdf.json) |
| `uv run --project excel-shrink python -m pytest -q -rs excel-shrink/tests` | 0 | 187/0/0 | 11.82 | [log](excel.log) / [run](excel.json) |
| `uv run --project video-shrink python -m pytest -q -rs video-shrink/tests` | 0 | 113/0/0 | 3.93 | [log](video.log) / [run](video.json) |
| `uv run --with pytest python -m pytest -q -rs`（cwd: orchestrator） | 0 | 468/0/0 | 12.60 | [log](orchestrator.log) / [run](orchestrator.json) |
| 合計 | 0 | **1454/0/4** | — | 上記 |

skip4は手動準備のjpegtran 3.2.0未設定、PDFのwarning1件は既存合成widget由来。
先行compile/help/lock/合成比較の証拠と限界は[Pilot記録](../2026-10-08-web-public-pilot/README.md)に保持する。

## 公開記録の扱い

作業者固有のrepo/temp/home pathを`<repo-root>`/`<temp-root>`/`<user-home>`へ置換した。
元ログはGit外のローカル領域へ保管し、legacy CP932 helpは内容をUTF-8へ変換した。
実行commandの意味・件数・SHAは保持する。[public-normalization.json](public-normalization.json)
実写真、実NAS path、認証情報は公開しない。
作業中15:00:25の別更新で、実装と元ZIP/展開資料がmainの61871c6へcommit/pushされていた。
こちらから履歴を改変したり、その資料を削除したりせず、同commitを保持して残る差分を統合する。
構成図sourceの統合前snapshotも[別名で保管](pre-integration-architecture.worktree.json)した。

## Git結果と運用反映

commit・feature push・main merge/pushは作業中。終了時に実際のSHA/tree/parentsを追記する。
反映先は現在のWindows PC checkoutと明示指定された。
[運用preflight](production-preflight.json)では対象GUIプロセスと8080 listenerは0件で、稼働中GUIの停止は不要。
main統合後、lockを変えずGUI/dev環境を同期し、prepared Pythonのimport元・public API・help・起動経路を確認する。

既存実装commit61871c6の運用確認として、`uv sync --locked --project media-shrink-tool --extra gui --extra dev`はexit0。
prepared Pythonを`-I -B`で起動し、外部PYTHONPATHなしでidentity/image/web-public/batch/guiがこのcheckoutのsourceを読むこと、
旧alias/公開import、NiceGUI3.17.1、cmdのprepared環境参照、web-public help exit0を確認した。
[production-runtime.json](production-runtime.json)に記録。実写真/NASの変換やGUI画面の手動操作は行っていない。
統合後も実装のGit blobと運用sourceを再照合する。

構成図は実装commit61871c6へ根拠を更新して再生成。validate/deliver9/9、errors/warnings0、
4viewport containmentと最小/最大light/dark4画像の目視が成功した。

記録日：2026-10-08（東京、日本）。
