# KaruFile compact preset と動画処理

この文書はliving documentである。
実装中はProgress、Discoveries、Decision Log、Validation、Outcomesを継続的に更新する。

## Goal

利用者が既存の安全な `standard` 動作を維持したまま、統合CLIで
`--preset compact` を選び、PDF、静止画、対応可能な通常動画について、入力原本を
変更せず、より小さい検証済み出力を別ツリーへ得られるようにする。

## Acceptance Criteria

- 引数省略時と `--preset standard` は既存のPDF・画像動作と互換である。
- `--preset compact` はPDF配置画像候補の固定目標を各軸300 DPIとし、300未満へ拡大しない。
  検証不合格時は原本を採用する。
- compact PDFはJPEG quality 80を使い、既存JPEGの同寸法再圧縮も候補化するが、
  1-bit、soft mask、ベクター文字を保護し、検証・削減条件に失敗すれば原本を採用する。
- compact静止画は長辺1024、短辺768、JPEG quality 60、4:2:0、白背景、
  no-upscale/no-cropで、presetをまたぐ再利用を誤判定しない。
- compact動画は安全な8-bit SDR/CFR/単一映像・最大1音声だけを、拡大せず
  1280x720以内・最大30fps・SVT-AV1へ変換する。MP4系はAAC、MKV/WebMはOpusを使う。
- 動画候補は構造、全decode、duration/stream、VMAF、削減条件を検証してから
  原子的に公開する。複雑・未対応な動画は入力と同じ相対パスへ原本コピーする。
- 全processorの予定出力、状態、report、一時パスを起動前に横断検査する。
- per-file失敗後も独立ファイル・processorを継続し、必要結果の失敗は非zeroで返す。
- 対象suite、compileall、CLI help、実subprocess smoke、`git diff --check` が成功する。

## Scope

### In Scope

- 統合、PDF個別、画像個別、動画個別CLIの `standard|compact` preset。
- PDF compact、画像compact、独立 `video-shrink` processor。
- 型付き設定・結果、状態/reuse、atomic report、orchestrator集計、安全preflight。
- 実装と一致するREADME、MANUAL、REFERENCE、architecture source/生成物。

### Out of Scope

- HDR、Dolby Vision、interlace、VFR、字幕、複数映像/音声、attachments、chaptersの変換。
- FFmpeg binaryの自動download・同梱・配布。
- 入力削除、dedup、GUI、クラウド処理。
- 「全入力が必ず小さくなる」という保証。

## Current State

- `main` は `origin/main` と一致し、既存の利用者差分は
  `docs/architecture/karufile-runtime.html` だけである。
- root orchestratorはPDFと画像のみを順次subprocess実行する。
- PDFは配置実効DPI > 300のときだけlossy経路へ進み、quality 92で300 DPIへ縮小する。
- 静止画recipeは1280x960、quality 72のmodule定数である。
- 現環境のFFmpeg 9.0は `libsvtav1`、AAC、Opus、`libvmaf` を利用できるが、
  GPL機能入りbuildなので配布物には採用しない。
- baselineはPDF 52、画像34、orchestrator 41、合計127 tests成功。

## Facts

- PDF `RunConfig` はlossy optionsをconfig hashへ含める。
- qpdfはFlate再圧縮、level 9、object streams生成を既に使う。
- 画像のcompleted markerはrecipe hashを持つが、原本copy reuseと
  KaruFile生成済み入力のskipはpreset差を完全には扱わない。
- orchestratorはplanned outputだけでなくPDF SQLite sidecar/reportもpreflightする。
- 現行PDF render検査は72 DPI grayscaleのページ全体平均差である。

## Inferences

- preset配管だけでは「全対象でより強い圧縮」にならず、PDF同寸法JPEG再圧縮と
  画像cross-preset reuse修正が必要である。
- 動画を画像processorへ戻すと責務・安全契約が崩れるため独立processorが必要である。
- 動画の固定CRF無条件採用は画質事故を起こすため、品質gateと原本fallbackが必要である。

## Assumptions

- `compact` は明示opt-inで、処理時間より削減率を優先する。
- 動画toolはPATHまたは明示パスから与えられ、KaruFile自身はdownloadしない。
- MP4/M4V、MKV、WebMは入力拡張子を維持して出力し、containerに適した音声codecを使う。

## Unknowns

- quality 80/60、動画CRF ladder、VMAF閾値の代表実データでの最終妥当性。
- FFmpegを将来同梱する場合の配布build・ライセンス・hash。
- 既存の生成HTML差分の意図。利用者差分を上書きせずarchitecture更新方法を決める。

## Options Considered

- 既存processorへ最小preset追加: PDF/画像には採用。既存安全境界を再利用できる。
- 動画をmedia-shrink-toolへ追加: 不採用。画像専用責務と出力検査が混在する。
- 独立video processor: 採用。probe/encode/validate/state/reportを隔離できる。
- すべてMKVへ変換: 初版では不採用。拡張子変更とfallback/stale出力契約が複雑になる。
- FFmpeg同梱: 初版では不採用。現在のローカルbuildは配布判断に使えない。

## Recommended Decision

`standard`を完全互換で残し、`compact`をopt-inとして追加する。PDF/画像は既存型付き境界を
拡張し、動画は独立processorにする。候補が小さくても品質・構造検証に失敗した場合は
採用しない。動画の複雑形式は変換せず原本を別出力へコピーする。

## Risks

- preset切替後に旧copy出力を誤再利用してcompactが適用されない。
- PDFのページ平均差または動画VMAF平均だけでは局所的な劣化を見逃す。
- FFmpeg timeout、巨大stderr、処理中source変更で不完全・古い候補を公開する。
- video output/report/stateを既存入力や別processor出力へlinkさせる経路。
- 生成architecture HTMLの既存差分を上書きする。

## Stop Conditions

- 入力変更・削除、unsafe link/hardlink、既存healthy output破壊を防げない。
- FFmpegの機能不足を誤成功として扱うしかない。
- 動画品質を検証せず公開する実装になる。
- 既存HTML差分を失わずarchitecture生成物を更新できない場合、その文書更新だけを停止し、
  コード・JSON・検証結果と必要な利用者判断を記録する。

## Checkpoints

### CP-001: Baseline と契約固定

- Status: Complete
- Objective: 現行実装、差分、テスト、依存、要求を確定する。
- Dependencies: なし。
- Files or components: Repo全体、AGENTS、既存ExecPlan、文書、toolchain。
- Actions: status、構造、設定、コード、127 tests、FFmpeg能力を確認する。
- Completion criteria: 事実・仮定・停止条件が本計画に記録される。
- Validation: git status、既存suite結果、FFmpeg/ffprobe probe。
- Failure conditions: 実Repo/指示/required toolが確認できない。
- Recovery: 編集前なので変更不要。

### CP-002: PDF preset と300 DPI不変条件

- Status: Complete
- Objective: standard互換とcompact PDF候補を実装する。
- Dependencies: CP-001。
- Files or components: `pdf-shrink/src/pdf_shrink`、tests、component README。
- Actions: typed preset、CLI、quality 80、同寸法JPEG再圧縮、検証強化、state hashを実装する。
- Completion criteria: 両presetでDPI targetが300、standard回帰、compact固有テストが成功する。
- Validation: PDF suite、compileall、実/合成PDF smoke。
- Failure conditions: 300未満への縮小、protected image変更、validation bypass。
- Recovery: compact固有flagで変更を隔離し、候補不採用時は原本copy。

### CP-003: 静止画 preset と正しい再利用

- Status: Complete
- Objective: compact画像recipeとpreset-aware reuseを実装する。
- Dependencies: CP-001。
- Files or components: `media-shrink-tool/src/media_shrink`、tests、component README。
- Actions: typed recipe factory、dynamic hash、1024x768/q60、cross-preset規則を実装する。
- Completion criteria: standard bytes/契約が互換で、compact切替と再実行が正しい。
- Validation: image suite、compileall、metadata/orientation/reuse smoke。
- Failure conditions: 二重圧縮、誤skip、原本変更、partial publish。
- Recovery: existing atomic output pathを維持し、unknown markerはfail-safe copy。

### CP-004: 独立video processor

- Status: Complete
- Objective: 対応動画の安全なcompact変換とunsupported原本copyを提供する。
- Dependencies: CP-001。
- Files or components: 新規 `video-shrink/` projectとtests。
- Actions: discovery、typed probe、config/state/report、FFmpeg transform、validation、atomic publish、CLI。
- Completion criteria: eligible/complex/error/dry-run/reuseの観測可能な結果がテストされる。
- Validation: unit/integration tests、compileall、real FFmpeg synthetic smoke。
- Failure conditions: stream欠落、decode/duration/quality未検証、source変更後publish。
- Recovery: staged candidateを破棄し、既存healthy output維持または原本copy。

### CP-005: Orchestrator統合

- Status: Complete
- Objective: compact時だけ動画を起動し、全processorを安全に集計する。
- Dependencies: CP-002〜CP-004。
- Files or components: `orchestrator/shrink_all.py`、tests、root entry。
- Actions: CLI伝播、video discovery、cross-type path/derived path検査、atomic report照合、summary/exit更新。
- Completion criteria: stale/malformed/mismatched resultを成功扱いせず、standard互換が保たれる。
- Validation: orchestrator suite、root subprocess smoke、help。
- Failure conditions: processor起動後の衝突検出、missing resultの成功扱い。
- Recovery: preflightとreport照合をprocessor起動前/終了後へ分離する。

### CP-006: 文書とarchitecture

- Status: Complete
- Objective: 実装と利用者契約・構成図を一致させる。
- Dependencies: CP-002〜CP-005。
- Files or components: README、MANUAL、REFERENCE、component docs、architecture JSON/生成物。
- Actions: 正確な数値、対象外、tool要件、report/state、statusを更新し、archifyで図を生成・検証する。
- Completion criteria: 文書が実CLI/実装と一致し、利用者HTML差分を失わない。
- Validation: doc diff review、architecture validation/visual-check。
- Failure conditions: 未検証保証、手編集HTML、既存差分上書き。
- Recovery: architecture生成物だけ停止し、JSONとblockerを明記する。

### CP-007: 全体検証と再評価

- Status: Paused by user
- Objective: 要求動作と回帰、安全失敗経路を最終確認する。
- Dependencies: CP-002〜CP-006。
- Files or components: Repo全体。
- Actions: 全suite、compileall、help、lock、smoke、diff reviewを実行し計画へ証拠を記録する。
- Completion criteria: 必須検証成功、残課題とPilot未実施範囲が明示される。
- Validation: AGENTS記載commandと実FFmpeg smoke。
- Failure conditions: 必須suite失敗、入力hash変化、temp残留、誤成功。
- Recovery: 失敗checkpointへ戻り、原因を修正して対象検証から再実行する。

## Progress

- [x] CP-001
- [x] CP-002
- [x] CP-003
- [x] CP-004
- [x] CP-005
- [x] CP-006
- [~] CP-007

2026-09-04、利用者指示によりCP-007途中で停止した。中断時点の正確な状態、残るP2、
検証済み結果、再開commandは
[`2026-09-04-compact-preset-handoff.md`](2026-09-04-compact-preset-handoff.md)に固定した。

## Discoveries

- 異なる合成動画probeでは大幅削減できてもVMAFが約65.5〜94.7と変動し、
  固定CRFの無条件採用が不適切だと確認した。
- PDFの配置bboxだけから単一DPIを求めると、非等方配置の一方の軸が300 DPIを超えても
  見逃す。配置transformのX/Y基底を軸別に扱い、縮小寸法はfloorする必要があった。
- size/mtimeだけの完了判定は、同値metadataを持つ内容差替えを誤再利用する。PDF、画像、動画で
  source/output SHA-256とdev/inode/size/mtime/ctimeの安定性を公開・再利用境界へ追加した。
- video reportは行数・pathだけでなく、実ファイルSHA、削減値、preset、status固有のcopy/adopted
  形状まで照合しなければ、不正な子resultを成功扱いできた。
- FFmpeg stdout/stderrを一時ファイルへ無制限に書く方式はdisk枯渇経路になるため、2本のpipeを
  同時にdrainし、固定長tailだけをmemoryへ残す方式へ変更した。

## Decision Log

### Decision-001

- Date: 2026-09-04
- Decision: PDF候補のDPI targetは全presetで300固定とする。
- Rationale: 利用者の明示条件であり、印刷用途を保ちつつqualityとcodec側で追加削減するため。
- Alternatives: compactだけ150/200 DPIへ下げる。
- Consequences: 追加削減はJPEG再圧縮と他mediaのpixel/fps削減で得る。

### Decision-002

- Date: 2026-09-04
- Decision: 動画は独立project、入力container family維持、external FFmpegとする。
- Rationale: 画像責務を維持し、出力path/fallbackを決定的にし、配布ライセンス判断を分離する。
- Alternatives: media processorへ統合、全MKV化、binary同梱。
- Consequences: MP4はAAC、MKV/WebMはOpusとなり、複雑動画は原本copyする。

### Decision-003

- Date: 2026-09-04
- Decision: 300 DPIは非可逆PDF候補の固定targetとし、検証不合格時は原本へfallbackする。
- Rationale: 利用者指定のtargetを守りつつ、表示検証を迂回して品質事故を起こさないため。
- Alternatives: 画質gateに失敗しても300 DPI候補を強制採用する。
- Consequences: 最終出力には入力由来の300 DPI超画像が残る場合がある。

### Decision-004

- Date: 2026-09-04
- Decision: 画像markerをv2へ更新しsource SHA-256を持たせ、PDF/video stateもoutput SHA-256を
  再利用条件にする。旧recordは一度再処理する。
- Rationale: 同じsize/mtimeの内容差替えや同サイズ出力破損を誤再利用しないため。
- Alternatives: metadataだけで高速に再利用する。
- Consequences: 初回だけ旧結果を再生成するが、以後は内容同一性を検証できる。

### Decision-005

- Date: 2026-09-04
- Decision: 既存の利用者変更済みarchitecture HTMLは上書きせず、現行図を
  `karufile-runtime.compact.html` として追加して文書リンクを切り替える。
- Rationale: 利用者差分を保持しながら現行runtime図を提供するため。
- Alternatives: 既存HTMLを生成物で置換する、図更新を完全に停止する。
- Consequences: 旧HTMLは未リンクで残り、現行図は別名になる。

## Validation Evidence

- Baseline: PDF 52 passed、image 34 passed、orchestrator 41 passed。
- PDF feasibility probe: 600 DPI sourceをquality 92で41,369 bytes、quality 80で34,873 bytes。
  両方300 DPIで既存validation成功。
- Image feasibility probe: 2048x1320 PNGをstandard 61,258 bytes、compact案34,328 bytes。
- Video feasibility probe: FFmpegで720p/30fps AV1変換、全decode、duration、VMAF commandを実行できた。
- Orchestrator preset/video統合の中間検証: 47 passed。
- PDF preset/非等方DPI/output SHA検証: 76 passed（source race最終修正前）。
- Image preset/reuse/source race検証: 54 passed、compileall成功。
- Video processor初期実装とstate/subprocess強化: 88 passed（source race最終修正前）。
- Orchestrator report/status/SHA race検証: 64 passed。
- Architecture: showcase 9/9、errors 0、warnings 0、4 viewportでoverflowなし。現行artifact
  SHA-256は `f6fec38944f96c1b4e39fee4c6cd50b61882fc903a5f7d70f729cb857a1b006b`。
- 中断前の全suite再確認: PDF 94、画像64、動画104、orchestrator 120、合計382 passed。
- 合成PDF・画像・動画の統合compact smoke: 初回exit 0、削減率97.77%、入力SHA不変。
  2回目もexit 0で画像・動画reuse、PDF state skipを確認した。

## Outcomes

compact preset、独立video processor、統合CLI、文書、現行architecture生成物を実装し、
全suiteと実subprocess統合smokeまで成功した。画像standalone manifestの最後のbatch競合窓を
修正する直前に利用者指示で停止したため、CP-007は未完了である。

## Remaining Issues

- 画像standalone manifestは、複数rowの最終hash検証後に全source/output identityを一括再照合する
  barrierが未実装。詳細と最小修正は再開引継ぎを参照する。
- 代表実データPilotは未実施。
- VMAF JSONの64 MiB上限は生成完了後に検査するため、異常なlibvmaf実行中はvalidation timeoutまで
  一時diskを消費し得る。
- architectureのrepository evidenceは変更前commitを指す。今回の未commit実装をGitHub上の
  revisionへ固定するには、利用者承認後のcommit後に図を再生成する必要がある。
- 既存 `karufile-runtime.html` の利用者差分は保持し、現行図を別名で追加した。
