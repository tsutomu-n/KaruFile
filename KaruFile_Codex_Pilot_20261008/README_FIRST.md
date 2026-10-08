# KaruFile `web-public` 実運用 Pilot・将来拡張準備 — Codex CLI 引継ぎパック

作成: 2026-10-08 / 対象: `tsutomu-n/KaruFile` / 調査方式: connected GitHub read-only

## 今回の結論

既存 `web-public` は**再実装しない**。品質・実NAS接続・下流の AVIF/WebP 表示を実証し、実用上の問題だけ直す。その後、将来の画像用途追加に備えて **source fingerprint の小さな共通化**を行い、同じ検証を再実施する。GUIや処理系のプラグイン機構は作らない。

## GitHubで確認した基準点（固定版で作業せず開始時に再確認）

- KaruFile `main`: `79df924a924808b4aa7601d7aa797d15ecfd4dcc` （2026-10-07）
- 前回の主な実装: `8899f490a3c081e2bfb3f597b518fcfc7c2d79d1`
- 既存仕様: `media-shrink-tool/src/media_shrink/{web_public.py,web_public_batch.py,gui.py,cli.py,image.py,utils.py}`
- 既存正本: `MANUAL.md`, `docs/REFERENCE.md`, `docs/WEB_PUBLIC.md`, `AGENTS.md`
- 最新保存済み検証記録: `docs/validation/2026-10-07-web-public/README.md` — **1435 passed / 4 skipped と記載**。このパックの作成者はテスト未実行。実写真・実NAS・実サイトは未検証と記載。
- seimou-com 参照 `main`: `5d48d369de9afd9eab06d2ff50e4f62241084d2b` （2026-06-02） / Astro `output:'static'`, `sharp`依存あり。**新サイト開発ブランチの状態とは限らない。**

## 読む順番

1. `01_CODEX_PROMPT.md` — Codexにそのまま渡す作業指示
2. `02_IMPLEMENTATION_STEPS.md` — 実際のコード・テストに対応した手順
3. `03_REAL_PHOTO_NAS_PILOT.md` — 実写真・NASテストと安全な操作
4. `04_ACCEPTANCE.md` — 受入条件・再確認条件
5. `05_ASTRO_AVIF_WEBP_HANDOFF.md` — 別のseimou.com担当への指示
6. `06_FUTURE_REUSE_BOUNDARIES.md` — 将来の別用途への拡張方針
7. `templates/` — Pilot結果入力テンプレート

## 実施の境界

- **KaruFile Codex**: ベースライン再検証、実写真Pilot（許可された素材だけ）、NAS実機試験（安全な専用テスト領域だけ）、発見された不具合の局所修正、最小共通化、関連テスト・文書更新を担当。
- **seimou.com Codex**: Astro/Sharp・Payload/R2の掲載経路、AVIFとWebPの配信を担当。こちらのソースは、このパックだけでは無断編集しない。
- **ユーザー/担当事務員**: 実写真・NASの試験場所と、写真を公開してよいかの判断を担当。未提供なら「未検証」と明記して止める。

## 固定方針

- 社内 NAS: 原本・編集素材の主保管先。Google Drive: 予備保管（事務員の主作業先ではない）。
- KaruFile: JPEG q90/4:4:4 または透過可能 PNG の**掲載用マスター**を生成。横幅は向き補正後1400pxまで、拡大/cropなし、sRGB化と不要メタデータの除去。
- Astro/Sharp: **同じマスターからAVIFとWebPを個別生成**。モダンブラウザー向けにAVIF優先、WebPを最終fallback。JPEG/PNGの旧ブラウザー向け配信fallbackは作らない。SVGアイコン・faviconなど写真以外の別資産をすべて廃止する要求ではない。
- Payload: 施工実績とニュース/広報のみを事務員が更新。KaruFileからの専用自動アップロードは作らない。
- 小規模会社向け。故障時の復旧可能性は守るが、過大なジョブ管理、総合プラグイン基盤、手作りDAM、権限基盤は作らない。

## 参照URL

- https://github.com/tsutomu-n/KaruFile/tree/79df924a924808b4aa7601d7aa797d15ecfd4dcc
- https://github.com/tsutomu-n/KaruFile/blob/main/docs/WEB_PUBLIC.md
- https://github.com/tsutomu-n/KaruFile/blob/main/docs/validation/2026-10-07-web-public/README.md
- https://github.com/tsutomu-n/seimou-com
- https://v5.docs.astro.build/en/reference/modules/astro-assets/
- https://v5.docs.astro.build/en/guides/images/

**このZIPは指示資料のみ。コード、NAS、Cloudflare、本番公開には変更を加えていない。**
