# 受入基準・判定マトリクス

この文書は**実証可能な条件**を定める。コードレビューのみで「実NAS検証済み」「実サイト表示済み」と報告しない。

## A. KaruFile不変条件（すべて必須）

| ID | 対象 | 合格判定 |
|---|---|---|
| K-01 | 原本保護 | 入力SHA/size一致、入力の変更/削除なし。変換失敗も同様 |
| K-02 | photo | JPEG・q90・4:4:4・progressive・ICC=sRGB。透明画素がある場合は拒否、勝手に白背景にしない |
| K-03 | graphic | PNG・RGB/RGBA・半透明を保持、色変換のあと適切にα適用 |
| K-04 | サイズ | 向き補正後 `width <= 1400`、拡大/cropなし、縦画像の高さは1400を超えても可 |
| K-05 | 色 | 既知ICCはLittleCMSでsRGB化。不明/HDR/矛盾/壊れたICCは安全な拒否。ICCなしのsRGB仮定は警告 |
| K-06 | metadata | 完成画像へ元EXIF/GPS/XMP/IPTC/comment/KaruFile markerを入れない。新sRGB ICCのみ必要に応じ保持 |
| K-07 | run分離 | 新runを作成。前runの画像が今回の`files`へ混入しない。旧runに無断変更なし |
| K-08 | 再利用 | source SHA+size、recipe v2+hash、engine versions、output SHA+寸法+形式+再検査を満たすときだけ再利用 |
| K-09 | manifest | `manifest.web-public.json`を正規結果でatomic確定。失敗時は旧manifest保持、成功表示にしない |
| K-10 | CLI | 引数/0枚→2、変換/保存/manifest失敗→1、警告のみ→0。`resize`の既存stdout等を維持 |
| K-11 | GUI | 画像用途2択、選択・処理進捗・成功/警告/失敗の表示、二重実行防止、出力フォルダー案内 |
| K-12 | root分離 | PDF/Excel/動画はweb-public実行で一切処理しない。通常`standard/compact`を変更しない |
| K-13 | dry-run | public modeのdry-runは入力root・出力root・manifest・reportに書込みを行わない |

## B. 実写真 Pilot（ユーザー提供で実施）

| ID | 対象 | 合格判定 |
|---|---|---|
| P-01 | 現場写真10〜15枚 | 処理件数、画像種別、警告・失敗理由を記録。原本SHA不変 |
| P-02 | 視覚品質 | 金網、樹木、岩、作業遠景、空、重機の代表作を入力と出力で同サイズ比較。許容不可があれば症状を記録 |
| P-03 | 縦横/向き | 意図した向き、幅上限、画角・比率を確認。縦写真を長辺1400と誤縮小しない |
| P-04 | 実HEIC | 端末由来HEICが提供された場合、向き・色を確認。合成HEICだけなら未検証 |
| P-05 | 図・透過 | PNG alpha維持、CAD等の細線・文字可読性を人が確認 |
| P-06 | 非公開情報 | 公開可能か人が確認。EXIF除去だけを「看板や顔の消去」と誤認させない |

## C. NAS Pilot（安全な独立試験共有で実施）

| ID | 対象 | 合格判定 |
|---|---|---|
| N-01 | UNC input | 実NASの専用copyから読める。SHA不変 |
| N-02 | UNC output | 実NASの独立outputへ正常保存・確認できる |
| N-03 | mapped drive | Windows割当ドライブが許可されている場合、NASと同等に動く |
| N-04 | 再実行 | 新run分離、reuse、manifest整合、旧run不変 |
| N-05 | 失敗復旧 | 模擬I/Oエラーおよび許可範囲の権限・切断試験で未完了/ERROR表示→接続復旧後再実行 |
| N-06 | OS連携 | フォルダー選択とExplorer起動は実機で確認。自動テストで代替しない |

## D. 共通化の非回帰

| ID | 対象 | 合格判定 |
|---|---|---|
| R-01 | module依存 | `file_identity.py` が `image.py` に依存しない。`web_public` はidentity関数を新moduleから取得 |
| R-02 | 旧API | `SourceChangedError/SourceFingerprint/_capture_source_fingerprint/_assert_source_unchanged`等の旧importが維持できる |
| R-03 | 既存image tests | 既存テストでsourceの変更検知、case-collision、原子的保存、コピー/再利用がPASS |
| R-04 | web-public tests | 形式、metadata、色、安全、CLI/GUI、manifest、再利用がPASS |
| R-05 | 他component | PDF/Excel/動画/orchestratorのfresh suiteがPASSし、想定外の変更なし |
| R-06 | Pilot差分 | 共通化前後で寸法/色/metadata/画像品質/出力policy/manifestの意味が不変 |

## E. Astroへ引継ぐ完成条件（**KaruFileだけではPASSにしない**）

| ID | 対象 | 合格判定 |
|---|---|---|
| A-01 | 画像ソース | JPEG/PNG masterを同一ソースとしてAVIFとWebPを別々に生成。KaruFileでAVIFを作らない |
| A-02 | HTML | `<source type="image/avif">` を上、`<img src="...webp">`を下。`<img src>`の最終fallbackがWebP |
| A-03 | 互換 | 対応対象Chrome/Edge/Firefox/Safari/Androidブラウザーで画像が見える。AVIF不可環境はWebPに落ちる |
| A-04 | 図版 | 透過の保持と、図面/細線の可読性を表示上確認。必要に応じWebP losslessを比較 |
| A-05 | 画像最適化 | 生成サイズがmasterを超えて拡大されない。`public/`や未許可remote URLを置いただけで最適化済みとしない |
| A-06 | 失敗 | 画像生成が失敗するとbuild/deployは失敗し、現在の公開サイトを維持。新HTMLが画像なしで公開されない |
| A-07 | 公開境界 | Pilotの実写真は公開・GitHub commitしない。公開はユーザー承認した素材のみ |

## 判定ルール

- **READY_KARUFILE:** `K-*`と`R-*` PASS。`P-*`/`N-*`は実提供があった項目についてPASS。
- **READY_TO_INTEGRATE:** 上に加え実写真・実NASのPilotがPASSまたは文書化した運用回避策でPASS_WITH_LIMITATIONS。
- **READY_WEBSITE:** seimou.com担当が`A-*`を実サイトのコード・ビルド・ブラウザでPASSと記録。
- **BLOCKED/PENDING:** 入力・NAS権限・サイトのワークツリーがない場合。代替できないことを明記。
- どこか1件でも重要な安全性・原本保護・出力内容の誤りがある場合は FAIL。曖昧な「大丈夫そう」でPASSにしない。

### 実機Pilotの途中失敗とコアのコード品質は混同しない

「synthetic tests 1435 pass」はG1/G2/G4のPASSを意味しない。実写真がないときは`BLOCKED_REAL_PHOTOS`、実NASがないときは`BLOCKED_REAL_NAS`、別リポジトリ未接続なら`PENDING_DOWNSTREAM`。
