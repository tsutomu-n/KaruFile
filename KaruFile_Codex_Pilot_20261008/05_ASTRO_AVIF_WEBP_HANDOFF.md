# seimou.com担当Codexへの引継ぎ: AVIF優先 / WebP最終fallback

**このファイルはKaruFile担当者が実装しない、別リポジトリの作業指示です。**

## ソースの状態と制約

2026-10-08に参照した `tsutomu-n/seimou-com` GitHub `main` は `5d48d369de9afd9eab06d2ff50e4f62241084d2b` （2026-06-02）。`astro.config.mjs` は `output:'static'`。`package.json` には Astro `~5.16.11` と Sharp `^0.34.5`。`src/components/common/ProjectImage.astro`には、文字列パスを通常の `<img>` で表示する経路がある。**実際の新サイト開発作業は別ブランチ/別実装かもしれないため、これを最新の設計正本として盲目的に変更しない。**

公式参照:
- https://v5.docs.astro.build/en/reference/modules/astro-assets/
- https://v5.docs.astro.build/en/guides/images/

## 1. フォーマット仕様

- 配信用写真: **AVIF preferred → WebP final fallback**。JPEG/PNGの旧ブラウザー向け配信fallbackは不要。
- 図版・透過画像: AVIF/WebP対応。半透明・細線・文字について、WebP losslessとAVIFを画質比較して最終選択する。
- 同一JPEG/PNG masterからAVIFとWebPを**別々に生成**する。`JPEG → WebP → AVIF`の連鎖再圧縮は禁止。
- マスター画像はKaruFileの width<=1400。Site上の本体画像の表示幅/生成幅を、masterを超えて**自動拡大しない**。1980pxのサイト最大幅は画像表示幅を1980pxに引き伸ばす命令ではない。
- 高密度端末で1400px幅の写真が多少柔らかく見えるのは、現在の「軽量さ優先・master1400」の受容済みトレードオフ。新用途で必要になった時だけ再協議。

## 2. Astro実装例（API名の検証を行うこと）

Astro v5の`<Picture>`では、`formats`の順番がsource優先順位、`fallbackFormat`は`<img>`の最終形式。

```astro
---
import { Picture } from 'astro:assets';
import photo from '../assets/pilot/photo-master.jpg';
---
<Picture
  src={photo}
  formats={['avif']}
  fallbackFormat="webp"
  widths={[360, 720, 1080, 1400]}
  sizes="(max-width: 900px) 100vw, 1400px"
  alt="施工現場の様子"
/>
```

これは**確認用の概念例**。元画像の横幅が小さい場合、`widths`をmaster固有幅以下に絞る。視覚によるcropは必要に応じ派生だけに適用し、KaruFile masterをcropしない。実際の最終HTMLで以下が成立することを確認する。

```html
<picture>
  <source srcset="...avif" type="image/avif">
  <img src="...webp" alt="施工現場の様子">
</picture>
```

`formats={['avif','webp']}`かつ`fallbackFormat='webp'`でもよいが、WebPが`<source>`と`<img>`の両方へ冗長出力される可能性があるため、最初は`formats={['avif']}, fallbackFormat='webp'`を優先する。

## 3. CMS/R2画像を使用する場合に注意

- `src/assets`にimportした画像と、CMS/R2のリモートURLでは**最適化経路が異なる**。
- Astroの`<Picture>`は、未許可のremote URLを渡しても自動最適化されない。`image.domains`や`image.remotePatterns`で**必要な配信元だけ許可**し、HTTP側アクセス・build時認証・cache制御を確認。
- 静的生成はbuild時にリモート画像へアクセスできる必要がある。非公開R2の認証情報をHTMLへ埋め込まない。必要ならbuild工程で短時間だけ権限を持つ取得経路を設計する。
- `public/`へJPG/PNGを単に置いただけではAstroのSharp変換を通らない。文字列`<img>`経路の既存コンポーネントを検査。
- Sharpの二重再圧縮や別の`optimize.ts`処理との重複を確認してから変更する。新サイト側の実ブランチで適合確認。
- `News`のデフォルト共通画像も、表示するならAVIF/WebPの配信方針に合わせる。画像なしのNewsで機械的に無関係な施工写真を使用しない。

## 4. サイト検証の現実的な最小セット

1. **合成・公開可素材**でstatic buildがPASS。MasterからAVIF/WebPが実際に生成される（拡張子だけ変えない）。
2. 出力HTMLの`<source type='image/avif'>`、`<img src='*.webp'>`、alt、width/height、srcset、sizesを検査。
3. DevTools/networkでChrome、Edge、Firefox、Safari、Android代表環境を確認。AVIF選択、WebP fallback、デコード失敗・404・空表示なし。
4. 施工事例の前・中・後、News画像あり/なし、透過PNG由来図版を確認。
5. ビルド失敗時、既存本番サイトを置き換えない仕組みをテスト。公開操作から反映完了/失敗はSEに確認可能。
6. 実写真の**公開テスト**は事前の公開許可が必要。許可されなければローカルだけで表示確認し、`PENDING_PRODUCTION_VISUAL`を記録。

## 5. 別途決めるが、今回の失敗要因にしないもの

- OGP/social botはブラウザーと対応状況が異なる場合がある。**OGP用画像形式はブラウザー表示画像とは別**に確認・定義する。今回の「ブラウザー向けJPEG/PNG fallback不要」を、サイト内のfaviconやOGP/SVGまで一括禁止と誤解しない。
- Cloudflare Imagesへ将来切り替える場合も、まずこの静的Astro方式の実測ビルド時間/配信量に問題があることを確認。現在はCloudflare Imagesを必須追加しない。

## 完了・引継ぎ

`A-01..A-07`を実行・記録する。KaruFile担当へは、生成画像に起因した問題だけ、再現可能な**公開可能fixture**と入力/出力の構造化差分で報告。顧客写真の無断共有はしない。
