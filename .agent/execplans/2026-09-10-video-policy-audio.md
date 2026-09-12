# 動画の通常変換と明示safe・音声除去

この文書はliving documentである。

## Goal / Acceptance Criteria
compact動画は欠落field_order/SARとVFRを通常の変換対象とし、safe指定で従来判定に戻せる。
統合/単体CLIから音声除去＋圧縮を選べる。無音指定の成功出力に音声が含まれず、
設定変更時に以前の出力を再利用しない。原本保護と構造/decode/VMAF/削減検証を維持する。

## Scope / Current State / Facts
video-shrink、orchestrator、関連テストと現行文書。作業開始時にPDF字体置換等の多数の
未commit差分があるため維持する。compactの旧中断計画は今回完了扱いにしない。
実2動画はfield_order/SAR不足とrate不一致があり、前ターンではFFmpeg直接処理した。
既存変換はfpsフィルターでCFRを生成し、出力構造検証はfield_order完全一致を要求する。

## Inferences / Assumptions / Unknowns
安全機構の変更は動画の保守的な入力形式判定を指す。入力・出力パス保護は対象外。
既知HDR/interlace/非正方SAR/字幕/複数映像の対応拡大は別処理が必要で今回対象外。
音声除去不成立時はERRORとし、音声付き回復コピーを作らない。既存出力は維持する。
実FFmpegのAV1出力にfield_orderが存在しない可能性を実データで検証する。

## Options / Decision Log
- 2026-09-10: 全検査撤去は採用しない。欠落メタデータ/VFR許可とsafeの追加を採用。
  全面置換や依存追加をせず既存検証パイプラインを利用できるため。
- 音声除去で不採用/未対応ならERROR。成功なのに有音コピーになる契約違反を防ぐ。
- CLI名はroot --video-safe / --video-remove-audio、単体 --safe / --remove-audio。
  compactのみ受け付け、standardで黙って無視しない。

## Risks / Stop Conditions
VFRは最大30fpsのCFRへ変換するためフレーム複製/間引きがある。VMAFは音声や動きの保証ではない。
実データ品質不合格なら診断し、検証を通すためだけに閾値を緩めない。

## Checkpoints
### CP-001: 実装
- Status: Complete
- Objective: 通常/safe/無音の契約をCLIから状態・reportまで通す
- Dependencies: 現行コード調査
- Files: video-shrink/src, orchestrator/shrink_all.py
- Actions: 設定、判定、変換、検証、hash、CSV照合を更新
- Completion criteria: 各経路を自動テストで確認できる
- Validation: 対象suite
- Failure conditions: 有音fallback、旧設定再利用、原本変更
- Recovery: 今回差分のみ修正。既存作業を巻き戻さない

### CP-002: 検証と文書
- Status: Complete
- Objective: 利用手順と実動作の一致
- Dependencies: CP-001
- Files: MANUAL, REFERENCE, component README, AGENTS, tests
- Actions: 代表回帰追加、全suite/compile/help/diff検査、実2動画の独立出力Pilot
- Completion criteria: 結果と残課題を記録し、音声なしをffprobe/decodeで確認
- Validation: AGENTS記載の全コマンドと実データ
- Failure conditions: 回帰または未解決の仕様矛盾
- Recovery: 失敗を修正し関連検証を再実行

## Progress / Discoveries
- CP-001/002完了。rootと単体CLI、入力判定、無音計画、state hash、CSV照合、失敗経路を実装。
- AV1候補のffprobeはfield_orderを省略する実例があるため、候補はAV1確認後に欠落/unknownを
  許容する。既知interlace、SAR、寸法、fps、duration、decode、VMAFの検査は継続。
- 無音候補のcontainer durationは元映像duration（存在時）を基準とし、長い音声末尾で拒否しない。
- 音声除去指定時はeligible planのaudioをNoneにし、既存encoderの明示-anと出力stream数検査を利用。
- 音声除去で未対応/不採用ならERROR、回復コピーなし。前回出力は保持する。
- DB列は増やさず両設定をhashに含める。再利用後のreportも現在の両設定を記録する。

## Validation Evidence
実行したsuite（実行時のworking tree、他作業のPDF変更も含む）:
- `uv run --project pdf-shrink python -m pytest -q pdf-shrink/tests`: 379 passed, 4 skipped。
- `uv run --project media-shrink-tool --extra dev python -m pytest -q media-shrink-tool/tests`: 64 passed。
- `uv run --project video-shrink python -m pytest -q video-shrink/tests`: 最終113 passed。
- orchestrator cwdで`uv run --with pytest python -m pytest -q`: 最終321 passed。
- `uv run --project pdf-shrink python -m compileall -q pdf-shrink/src pdf-shrink/tests karufile.py orchestrator`: exit 0。
- 画像/動画projectでも各src/testsのcompileallを実行しexit 0。
- `uv run --script karufile.py --help`: 新2オプション表示、exit 0。
- `git -c core.safecrlf=false diff --check`: exit 0（safecrlfはCRLF警告表示だけを抑制）。

実動画Pilot（個人ファイル内容は外部送信していない）:
- 入力 `C:\Users\tn\Downloads\Photos-1-001 (5)` の2本。
- 単体compact --remove-audio: `_実装検証_無音` へ2本ADOPTED、exit 0。
- root compact --video-remove-audio: `_実装検証_統合無音` へ2本ADOPTED、exit 0。
  20260819_135016.mp4: 8,689,305 → 621,359 bytes、VMAF mean 98.900860/p5 95.229889。
  20260819_135033.mp4: 14,846,694 → 1,645,912 bytes、VMAF mean 99.262229/p5 93.800755。
  合計23,535,999 → 2,267,271 bytes、90.37%削減。404x720/AV1、音声streamなし。
  ffprobeで映像1本/206・345frames、ffmpeg -xerror全decode exit 0、原本SHAはreportと一致。
- 単体compact通常（音声保持）: `_実装検証_音声保持` へ2本ADOPTED、22.45 → 2.39 MiB、exit 0。
- 単体compact --safe --dry-run: `_実装検証_safe.video-report.dry-run.csv` に
  2本ともprogressive明示不足によるwould SKIPPED_COMPLEX。完成出力なし、exit 0。
- 無音出力を同設定で再実行してexit 0、再利用を確認（CSV確認も実施）。

図の更新: topology/pathは不変、動画の任意safe/無音化tagと基準commitを更新。
- `archify validate architecture ... --quality showcase --repo-root . --json`: 9/9、0 errors/warnings。
  初回repo-root省略は拒否されたため、正しいrootを指定して再実行。
- `archify deliver architecture ... docs/architecture/karufile-runtime.compact.html --quality showcase --repo-root . --json`: exit 0。
- specification SHA256: b1d1ab250df0b1316589d58cd89013ce5a0da251b892346e86364d134a1f5603
- artifact SHA256: fd3c700482a270e12e04a15aec931cfb34436781be30d55e534a1310227e299a
- `archify visual-check ... --json`: 4 viewport containment pass。
  1440x900/2048x1320 light/dark PNGを全4枚目視確認。visual_review: passed、correction_rounds: 0。
  図のソースリンクはce7f4bdca6ec36f8ebc8df5c9eee97b5ba426e36を基準とし、未commit変更ありを図内に明記。

## Outcomes / Remaining Issues
今回要求の通常変換・任意safe・音声除去＋圧縮は実装と実データ検証を完了。
全安全機構は撤去していない。原本保護、危険な出力先拒否、品質・削減・全decode検証は常時有効。
既知HDR/interlace/非正方SAR/字幕/複数映像等の変換は未対応。
VFRはCFR化される。前ターンの手動720x1280とは違い、製品既存recipeでは縦動画404x720になる。
2本のPilotを他動画の画質保証やcompact旧中断計画全体の完了としない。
実行環境は音声除去時も既存の全FFmpeg capability（AAC/Opusを含む）を要求する。
commit/push未実施。無関係なPDF等の既存変更は保持。
