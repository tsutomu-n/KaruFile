# web-public修正のGit統合・運用反映

この文書はliving document。コミット・push・実際のmerge・運用先の更新を別々に検証する。

## Goal / Acceptance Criteria

検証済みのsource identity共通化とatime再利用修正をGitHub mainへ統合し、指定されたKaruFile運用先へ反映する。
feature commitと2親merge commit、remote mainの一致、反映先で使われるsource/環境を証拠で確認する。
実写真/NAS/サイトの未実施項目をPASSへ変更しない。

## Scope / Current State

- 開始HEAD/branch：79df924a924808b4aa7601d7aa797d15ecfd4dcc / main。
- origin：tsutomu-n/KaruFile。fetch後にHEADとorigin/mainが一致。public repo。
- 2026-10-08 14:54頃のGitHub確認：main保護なし、ruleset/workflow/run/open PR/deployment/releaseなし。
- 開始時worktreeは1個、stash/tag/他branchなし。ZIPと展開資料は保全する。
- 直前の1454/0/4とsource SHAを照合済み。統合前の全suiteも新規実行して記録する。
- ユーザーの「コミット、プッシュ、マージ。本番反映」で、今回のGit書込みと運用反映を明示承認。
  先行報告の「未実施」はその報告時点の履歴として保持する。

## Facts / Inferences / Assumptions / Unknowns

- Facts：KaruFileはWindowsローカルCLI/GUI。GUI cmdは同checkoutの準備済み.venvを呼ぶ。
  リポジトリ内にサーバーdeploy設定、GitHub Actions、既存Release配布はない。
- Inferences：branchをpushし、local mainへno-ff merge後pushすれば、PRや新CIを追加せず実際のmergeを記録できる。
- Assumptions：対象変更は先行依頼で作成したcode/tests/docs/evidence。未使用基盤や別サイトを追加しない。
- Facts (追加回答)：本番反映先は「このWindows PCの現在のKaruFile」。対象GUI/8080 listenerは0件。
- Unknowns：実写真/NAS/サイトの受入環境は先行作業と同じく未提供。

## Options / Decision

mainへの直接commitだけではmergeを行ったことにならないため、作業branch→push→2親merge→main pushを選ぶ。
作業中の別更新で実装がmainの61871c6へcommit/pushされていたため、このcommitを保持し、
残る公開用証拠・commit根拠・運用記録をbranchで完成させてmergeする。
force push、履歴改変、不要なPR/Release/CI追加は行わない。
検証記録のユーザー/temp pathは公開用表記へ置換し、原ログはローカル別領域へ保管する。

## Risks / Stop Conditions

remote変更・unexpected差分・検証失敗は調査して解決する。保護設定は緩和しない。
運用先が未指定なら本番操作だけ待つ。既存変換中プロセスを状態不明のまま停止しない。
原本、既存run、ZIP、他のcheckout/serviceを上書き・削除しない。

## Checkpoints

### CP-001: Git/GitHub/運用経路のpreflight
- Status: Complete
- Objective: root・HEAD・ref・worktree・stash・tag・保護・CI・deployの現状を確定。
- Dependencies: 先行検証と最新ユーザー承認。
- Files: repo refs/config、README/MANUAL/cmd、GitHub metadata。
- Actions: fetch、read-only GitHub API、運用先のasync質問、原ログのローカル保管。
- Completion criteria: main一致、書込み対象と未指定の運用先を分離。
- Validation: preflight.json、先行verify_final exit0。
- Failure conditions: 認証不可、root不一致、無関係な差分混入。
- Recovery: 対象を再確認し、無関係な変更を保全。

### CP-002: 公開用証拠と統合前検証
- Status: Complete
- Objective: 機密を含めず、統合treeの検証を確認。
- Dependencies: CP-001。
- Files: 対象code/tests/docs、公開用evidenceとこのplan。
- Actions: path正規化、fresh全suite、source/lock保全、staged差分確認。
- Completion criteria: tests成功、必要なskip説明、元ZIP/原本保全、想定pathだけをstage。
- Validation: integration suite logs/JSON、staged diff check、source SHA。
- Failure conditions: test失敗、秘密/実写真/個人pathの公開混入、誤stage。
- Recovery: 原ログ保持の上で局所修正。source変更なら影響suiteを再実行。

### CP-003: commit・push・merge
- Status: In progress
- Objective: feature commitをpushし、mainに実際のmergeを作って同期。
- Dependencies: CP-002。
- Files: Git index/refsとorigin。
- Actions: scoped commit、feature push、main no-ff merge、main push、remote SHA再照合。
- Completion criteria: mergeのparent数2、merged treeが検証済みtreeと一致、remote main一致。
- Validation: commit/tree/parents、ls-remote、公開sourceのSHA。
- Failure conditions: remote競合、拒否、unexpected tree差異。
- Recovery: fetchして差分調査。force pushはしない。

### CP-004: 運用反映・最終証拠
- Status: Not started (反映先は確定)
- Objective: 指定運用先に新source/環境が使われることを確認。
- Dependencies: CP-003と反映先指定。
- Files: 指定checkout/.venv、構成図・文書のcommit根拠、integration evidence。
- Actions: 対象の安全な更新、import/help等の確認、実装commitに合わせた構成図の生成/目視、結果記録。
- Completion criteria: sourceと運用先の実測が一致。未提供の実写真/NAS/サイトは未実施のまま。
- Validation: 反映先path/commit/import、GUI起動経路、必要な環境同期、remote再照合。
- Failure conditions: 反映先/権限未提供、変換中で安全にrestartできない、別製品を誤指定。
- Recovery: Git統合を完了し、反映先の不足情報を具体的に報告。

## Progress

- [x] CP-001
- [x] CP-002
- [ ] CP-003
- [ ] CP-004

## Discoveries / Decision Log

- 2026-10-08：Release latestは404、release一覧/deploy履歴は空。自動デプロイを想定しない。
- 2026-10-08：public repoのため新規検証記録のpathを正規化し、元ログをGit外へ保存。
- 2026-10-08：実際のmergeが要求されているため、main直接commitだけで完了と報告しない。
- 2026-10-08：ユーザーが現在のWindows PC checkoutを運用反映先に指定。GUI/8080 listenerなし。
- 2026-10-08：統合前fresh全suiteは1454 passed/0 failed/4 skipped。既存PDF warning1件。
- 2026-10-08 15:00:25：こちらのcommit操作前に別更新でmain/remoteが61871c6へ進んだ。
  112 filesの実装/検証資料とZIP/展開資料が含まれる。原本・履歴を保全し、commitを上書きしない。
- 2026-10-08：公開用ログの改行変換によるdouble CRを検出し、UTF-8/LFと末尾paddingを正規化。
  原ログは保管済み、117 Python sourceのSHAはfresh試験時から不変。

## Validation Evidence / Outcomes / Remaining Issues

証拠はdocs/validation/2026-10-08-web-public-integration/に保存する。
作業中。Git統合と指定運用先の状態を実行後に追記する。
実写真/NAS/下流サイトは先行報告どおりBLOCKED/PENDING。
