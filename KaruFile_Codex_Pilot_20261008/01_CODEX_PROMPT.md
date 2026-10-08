# Codex CLI 実行指示: `web-public` 実運用Pilot + 小さな共有コア整理

あなたは `tsutomu-n/KaruFile` の実装・検証担当者である。**計画を出して終了しない。** 以下の順序で、許可されたローカル作業を完了し、実環境に依存してできない部分は未検証として正確に報告する。

## 0. 最初の5分で確認すること

```powershell
git status --short
git branch --show-current
git rev-parse HEAD
git diff --stat
```

続いて `AGENTS.md`, `.agent/execplans/README.md`, `MANUAL.md`, `docs/REFERENCE.md`, `docs/WEB_PUBLIC.md`, `docs/validation/2026-10-07-web-public/README.md` を読む。実コード・tests・lockfileを優先し、指示書内の SHA を「強制checkout先」にしない。未追跡・未commitの他者作業を保存する。GitHub上の観測基準は2026-10-07 の`79df924a`。手元が新しければ、新しい事実を優先して差分を報告する。

既存の `web-public` を再作成しない。初期検証記録の `1435 passed / 4 skipped` は過去のローカル記録であり、**今回の新規実行証拠ではない**。

## 1. ゴール（今回に必要な4成果物）

**G1.** 承認を得た実際の施工写真10〜15枚で、現在の `web-public` が公開用JPEG/PNGマスターを正しく作れることを、目視と機械検証で実証する。

**G2.** 実NAS上の専用試験フォルダーで、UNC/ドライブ文字・保存・再実行・安全な障害復旧を実証する。NASへの権限・共有パスがない場合、実施を捏造せず `BLOCKED_REAL_NAS` と記録する。

**G3.** 今後画像以外の用途が増えた場合にも、`image.py`へのprivate importが増殖しないよう、**source SHA/stat/fingerprintに限った小さな共通モジュール**へ移す。旧関数名・例外型・動作・テスト互換性は維持。共通化後の regression と Pilot 比較を再実施する。大きな抽象化にしない。

**G4.** seimou.com担当が、同じマスターからAVIF優先/WebP fallbackの完成画面を検証できる引継ぎ資料を作る。KaruFileにはAVIFやCloudflareの実装を追加しない。サイトの環境が提供されていないなら `PENDING_DOWNSTREAM` とする。

## 2. 作業順序（変更内容を明確に）

- **CP0: ベースライン凍結**: 現在のbuild環境、バージョン、`web-public --help`、既存imageテスト、全suite実行結果、出力仕様を記録。実写真Pilotの対象は機密であるためGitへコミットしない。既存変更があれば何を採用するか判断して混ぜない。
- **CP1: 実写真Pilot**: `03_REAL_PHOTO_NAS_PILOT.md` に従い実素材10〜15枚（ユーザー側が許可したもののみ）を実行。写真・図版・縦横・HEIC・ICC・実写粒状/金網を含める。対象未提供ならサンプルにすり替えず `BLOCKED_REAL_PHOTOS`。
- **CP2: NAS Pilot**: 専用のテスト共有（既存原本と分離）にてUNC入力、UNC出力、割当ドライブ、複数実行、異常（安全に注入可能な範囲）を検証。接続の強制遮断など社内業務影響を伴う操作は事前に承認が必要。許可がなければ実施しない。
- **CP3: 局所不具合修正**: CP1/CP2で実際に再現された問題だけ、失敗テスト→変更→成功テスト。写真の意味・顔・看板をソフトが自動処理したと誤認させない。
- **CP4: 最小共有化**: `06_FUTURE_REUSE_BOUNDARIES.md` の`file_identity.py`への小移設を行う。今は未使用のプラグイン/汎用レシピ/GUIタブを作らない。
- **CP5: 再回帰と比較**: `04_ACCEPTANCE.md` の全条件を再実行。共通化前後で画像の向き・寸法・色・メタデータ・出力ポリシー・manifest・例外・CLI終了コードが変わっていないことを確認。
- **CP6: 文書・最終報告**: `MANUAL.md`, `docs/REFERENCE.md`, `docs/WEB_PUBLIC.md`, `AGENTS.md`, `docs/validation/...` を変更した契約の範囲だけ更新。必要なら `.agent/execplans` に実施記録を追加。サイト側への引継ぎは `05_ASTRO_AVIF_WEBP_HANDOFF.md` に従う。

## 3. 禁止事項

- 原本削除・上書き、既存正規成果物の無断削除・置換、他者の作業変更の破棄、危険なgit reset/cleanは禁止。
- 顧客・施工場所が特定できる実写真や原本、実NASのパス、認証情報をGitHub/PR/公開ログ/AI会話/クラウドテストへ無断で出さない。
- 本番 Cloudflare、Payload、R2、seimou.com の公開状態を変えない。自動push・PR作成も依頼していない。
- PDF/Excel/動画処理、通常`resize`の契約と出力挙動を変更しない。
- `web-public` の recipe v2 （写真JPEG q90/444・図版PNG・width1400・sRGB・input metadata除去・SHA reuse）を「最適化だから」という理由だけで書き換えない。変更が必要なら実画質の測定・受入差分・新recipe versionをセットで提示する。
- NICEGUIをクラウドで公開しない。localhostのローカルブラウザGUIのまま。
- `web-public`でJPEG/PNGを削除してAVIF/WebPへ置き換える変更をしない（これは後段の配信形式である）。

## 4. 判断ルール

- 実写真が `UNSUPPORTED_COLOR` で拒否された場合、まず元画像のICC/NCLX/Exifと根拠を調べる。勝手なsRGB仮定の拡大やHDRの誤変換より、**事務員が画像編集ソフトからsRGBで再書き出し**する手順を優先。継続的に多発する場合だけ仕様変更の提案をする。
- 実NASアクセスなし・KaruFile担当PCなし・サイト側環境なしは `BLOCKED` / `PENDING` と明示。合成fixtureを実環境テストの証拠にしない。
- 共通化の目的は「今すでにある通常画像とweb-publicの2者が使うfile fingerprintの依存逆転」であり、将来の拡張APIを予想で大量追加することではない。
- 途中で現行コードに重大欠陥が見つかった場合、原因と試験を残して局所修正し、無関係のモジュールまで触らない。

## 5. 完成報告（この形式で最終出力）

1. `HEAD (start/end)`、modified/new files、何を行ったか（G1〜G4各1行）。
2. fresh validation の**実行したコマンド・Exit Code・passed/failed/skipped**。
3. Pilot: 実写真の件数、種類、目視結果、エラー/警告傾向、写真を外部へ出したか（原則NO）。素材そのものは添付しない。
4. NAS: 実共有確認の可否、UNC/ドライブ文字/接続障害の検証結果。実NASでできない項目を明示。
5. 共有化: 新しい公開関数と旧aliasの互換性、影響したコード・テスト範囲。
6. AVIF/WebP: KaruFile側で完了した証明と、サイト担当へ渡した未完了項目を分離する。
7. 未検証・既知リスク、次の担当者が取るべき行動。過去のPASS件数を新たなPASSとして転記しない。

**報告書は `templates/FINAL_REPORT_TEMPLATE.md` を使用。作業をそのまま継続し、情報不足の領域のみBLOCKEDとして残す。**
