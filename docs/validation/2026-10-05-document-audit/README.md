# 情報資産監査の修正と検証（2026-10-05）

基準は`main` / `f71cf514dd9716eeafdbebc13a762c82d56ebedd`、開始時の作業ツリーはclean。
読み取り専用監査で確定したUPDATE 5群を、後続の利用者指示「実装」に基づき修正した。
さらに「終了したら、コミット、プッシュ」で検証完了後のcommit/pushが承認された。

## 変更範囲

- ガイド本文の正本templateへPNG/WebP・EXIF設定を反映して再生成。写真だけのPDFの既定画像化と
  EXIF以外の情報が残り得る注意事項も同じtemplateで整合させた。
- 構成図JSONのソースリンクを収録済みの基準commitへ固定し、正規生成・検証・snapshotを更新。
- ExecPlan索引の画像機能を`f71cf51`収録済みへ更新。9月30日の計画本文は当時の履歴を保持。
- PDFの検証方式を候補種別で説明し、自動スキャンの300 DPIと独立予算を追加。
- 画像内部仕様に形式/EXIFを含むhash式と`--format`/`--strip-exif`を追記。

runtime・依存設定・ignore規則は変更していない。古い計画・ログ・図の削除や移動はない。
生成途中の8ページ目のPNGは今回だけの未追跡中間生成物で、最終7ページPDFの証拠に含めない。

## 実行したコマンド

リポジトリrootから実行。ArchifyのJSON出力は対応するvalidation/delivery receiptへ保存した。

```powershell
node C:/Users/tn/.agents/skills/archify/bin/archify.mjs validate architecture docs/architecture/karufile-runtime.architecture.json --repo-root . --quality showcase --json
node C:/Users/tn/.agents/skills/archify/bin/archify.mjs deliver architecture docs/architecture/karufile-runtime.architecture.json docs/architecture/karufile-runtime.compact.html --repo-root . --quality showcase --json
node C:/Users/tn/.agents/skills/archify/bin/archify.mjs visual-check docs/architecture/karufile-runtime.compact.html --json
node docs/guide/build-guide.mjs
node docs/guide/check-guide.mjs
uv run --project pdf-shrink python docs/guide/render-print.py
git diff --check
```

## 結果と証拠

- Archify validate/deliverは終了コード0、showcase9/9、errors/warnings0。
- visual-checkは終了コード0。1440×900、1600×1000、1920×1080、2048×1320のcontainment成功。
- 小/大画面のlight/dark計4画像を目視し、文字・線・カードの欠けや重なりなし。
- 基準commit、仕様/HTMLのSHA、74ローカルファイルのSHAを
  [snapshot](../../architecture/karufile-runtime.compact.worktree.json)へ記録。
- ガイドbuild/check/render-printは終了コード0。5画面幅、目次7項目、参照6件、200%相当、
  単独オフライン、画像読込み、外部リクエスト0、console例外0を確認。
- ガイドPC/390pxの変更段落4画像とA4全7ページを目視。本文境界検査も全ページ成功。
- 生成元とHTML、build/verifyとHTML、印刷PDFとpages JSON、図のreceipt/snapshotと現物SHAを独立照合。
  Markdown参照先・アンカー、JSON解析、runtime差分なしを最終確認し、
  [static-checks.json](static-checks.json)にその結果を保存した。
- Markdown49ファイルの参照先233件・アンカー27件に欠落なし。JSON53件の解析、
  snapshot74件のSHA、生成元/HTML/receiptの一致、runtime/設定差分なし、git diff --check成功。

詳細目視結果は[構成図review](../../architecture/karufile-runtime.compact.review.md)と
[guide REVIEW](../../guide/REVIEW.md)を参照。機械receiptの`visualReview: pending`は目視判断へ書き換えていない。

## 修正中の発見と限界

注意事項を追補した最初の生成では、第1節の最後の段落だけが次ページへ流れて8ページになった。
表の説明を短くし、写真だけのPDFの詳細は第6節へ置くことで最終7ページへ戻した。
存在しないexampleファイルを読む最初の操作は失敗したが、ファイル一覧から実在するArchify exampleを読み直した。

文書と生成物だけの変更なので、AGENTSの方針に従いruntime pytest/compileallは実行していない。
実プリンター、実利用者データPilot、全viewer互換性は検証していない。
秘密情報の除外方針は判断保留を維持し、過去の承認境界・失敗記録も保持する。
