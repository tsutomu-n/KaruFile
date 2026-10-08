# seimou.comへの引継ぎ：AVIF優先・WebP最終fallback

状態は **PENDING_DOWNSTREAM**。KaruFile側ではJPEG/PNGマスターの生成契約とsource identity共通化を検証した。
実写真は未提供で、マスターの実素材引渡し・別サイトの変更・build・ブラウザー表示・公開は未実施。
この文書はサイト担当者が実際の作業ブランチで検証するための手順である。

## 受け渡すものと開始時の確認

- 使用・公開を担当者が許可した、今回の`runs/<run-id>/files/`内の完成JPEG/PNGだけを安全な共有へ渡す。
  原本、内部manifest、NASパス、認証情報、顧客情報をGitHubや公開ログへ送らない。
- KaruFileのphotoはJPEG q90/4:4:4/progressive、graphicは透過対応PNG、横幅最大1400px・拡大/cropなし、8bit sRGB。
  表示の詳しい契約は[技術リファレンス](../../REFERENCE.md#web-public掲載用マスター)を参照する。
- 同梱ZIPはseimou-comの観測値としてmain `5d48d369de9afd9eab06d2ff50e4f62241084d2b`、
  Astro `~5.16.11`、Sharp `^0.34.5`、static構成を記載している。これは今回ローカル確認したサイトの現状ではない。
  開始前に実作業のroot・branch・HEAD・status・package/lock・Astro設定・画像コンポーネントを確認する。
- 既存の文字列`<img>`や独自画像最適化処理と重複して再圧縮しない。新サイト側の実装を正とし、未commit作業を保存する。

## 同一マスターから2形式を生成する

同じJPEG/PNGからAVIFとWebPをそれぞれ生成し、`JPEG → WebP → AVIF`等の連鎖再圧縮はしない。
AVIFを`<source>`の優先候補に置き、`<img>`の最終fallbackはWebPにする。
このブラウザー表示方針ではJPEG/PNG fallbackを追加しない。OGP・favicon・SVG等の用途は別に確認する。

Astro v5の`Picture`では`formats`がsourceの順番、`fallbackFormat`がimgの形式を決めるため、
WebPを明示する。[Astro v5 assets API](https://v5.docs.astro.build/en/reference/modules/astro-assets/)

```astro
---
import { Picture } from 'astro:assets';
import master from '../assets/pilot/approved-master.jpg';

const widths = [...new Set(
  [360, 720, 1080, 1400, master.width].filter((width) => width <= master.width)
)].sort((a, b) => a - b);
---
<Picture
  src={master}
  formats={['avif']}
  fallbackFormat="webp"
  widths={widths}
  sizes="(max-width: 900px) 100vw, 1400px"
  alt="担当者が確認した画像の説明"
/>
```

これは公式APIを照合した概念例であり、このサイトでbuild済みのコードではない。
importパスと`sizes`は実レイアウトに合わせ、CSSの表示幅もmaster固有幅以下にする。
1400px未満のマスターに大きな派生幅を要求しない。サイト全体の幅が1980pxでもマスターを引き伸ばさない。
高密度端末での柔らかさはmaster1400の制約として評価し、必要になった用途だけ別途協議する。
図版は透過・半透明・細線・文字を人が比較し、必要なら同じPNGからWebP losslessも比較する。

最終HTMLと実ファイルを検査し、拡張子だけの変更でないことを確認する。

```html
<picture>
  <source type="image/avif" srcset="...avif">
  <img src="...webp" alt="担当者が確認した画像の説明">
</picture>
```

## CMS/R2・静的生成の境界

`src/assets`のimport画像と、`public/`の画像やremote URLは同じ最適化経路ではない。
`public/`はそのまま配信されるため、JPEG/PNGを置くだけでAVIF/WebP化済みとしない。
remote最適化には必要な配信元だけを`image.domains`/`image.remotePatterns`で許可する。
static build時に画像を取得できることを確認する。[Astro v5画像ガイド](https://v5.docs.astro.build/en/guides/images/)

非公開R2の認証情報をHTML・画像URL・公開ログへ埋め込まない。必要な取得経路はサイト側で設計し、
今回KaruFileにPayload/R2/Cloudflare Images連携やアップロードを追加しない。
Cloudflare Imagesへの移行は、現行のビルド時間・配信量に実測上の問題がある場合に別途判断する。

## 次担当の受入項目

| ID | 実際のサイトで実施すること | 今回の状態 |
|---|---|---|
| A-01 | 同一マスターからAVIF/WebPを独立生成し、デコードと寸法を確認 | PENDING_DOWNSTREAM |
| A-02 | AVIF sourceが先、imgのsrcがWebP。alt・width/height・srcset・sizesを検査 | PENDING_DOWNSTREAM |
| A-03 | Chrome/Edge/Firefox/Safari/Android対象端末で表示・networkを確認。AVIF不可時のWebP fallback、404/デコード失敗なし | PENDING_DOWNSTREAM |
| A-04 | 写真・透過図版・細線の同サイズ/等倍比較。必要ならWebP lossless比較 | PENDING_DOWNSTREAM |
| A-05 | 生成幅/表示幅がmasterを超えない。local/remote各経路を実測 | PENDING_DOWNSTREAM |
| A-06 | 画像生成失敗でbuild/deployが失敗し、現在の公開サイトが維持される | PENDING_DOWNSTREAM |
| A-07 | 公開許可済み素材だけを公開し、非公開Pilot写真をcommitしない | PENDING_DOWNSTREAM |

施工事例の前・中・後、News画像あり/なし、共通画像、透過図版を確認する。
News画像なしに無関係な施工写真を自動割当しない。
AVIFに対応しない実環境でWebP fallbackを確認し、HTMLだけの検査でブラウザー互換をPASSにしない。
障害試験・本番公開はサイト側の許可範囲で行う。公開許可がない場合はローカル表示に留め、
**PENDING_PRODUCTION_VISUAL**を記録する。今回の公開承認・本番変更はなし。

KaruFile生成画像に起因する問題は、公開可能な再現fixtureと入力/出力の構造化差分で戻す。
顧客写真を無断共有せず、サイト側の実行結果・HEAD・日時を別の受入証拠へ残す。

作成・公式API照合日：2026-10-08（東京）。
