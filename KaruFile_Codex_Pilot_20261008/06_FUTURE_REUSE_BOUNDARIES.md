# 将来の別用途を増やすための拡張ルール — YAGNIを維持する

## 目標

現在は「会社Webサイトの掲載用JPEG/PNG master」が唯一の`web-public`用途。将来SNS・採用・社内素材・図版など別用途が実際に必要になった際、**同じ原本保護・source identity・失敗検出・出力検査を再利用**し、無駄な全コード複製を防ぐ。

**今回作らないもの:** 動的プラグインローダー、設定DSL、任意Pythonコード登録、一般ユーザー向けレシピ編集、画像処理SaaS、独自CMS、PDF/Excel/動画のGUI。

## 既存の責務境界

```text
media_shrink
├─ utils.py               # path/link guard, staged_path 既存
├─ image.py               # 通常resize、既存marker CSV契約
├─ web_public.py          # web master recipe v2、色・寸法・metadata・検証
├─ web_public_batch.py    # image選択、runとmanifest、reuse
├─ gui.py                 # 現在の画像専用NiceGUI
└─ cli.py                 # resize/web-public/gui コマンド入口
```

変更後（最小追加）は以下。

```text
media_shrink
├─ file_identity.py       # NEW: SHA/stat fingerprint + source-unchanged
├─ utils.py               # KEEP: path/link guard + staged_path
├─ image.py               # KEEP: 通常resize, 旧API aliasesを維持
├─ web_public.py          # KEEP: master変換のみ、identityは上記から
├─ web_public_batch.py    # KEEP: run/manifest、identityは上記から
├─ gui.py                 # KEEP: ページは現在のまま
└─ cli.py                 # KEEP: コマンド追加なし
```

## 今回共通化するもの

sourceファイルのSHA-256計算、安定したstat fingerprint、処理前後の同一性確認だけを `file_identity.py` へ抽出する。既存の`image.py` import名はalias/薄いwrapperで維持。`web_public`はこの新moduleを直接利用する。

**共通化後も、別用途の都合でsourceファイルを破壊的に変更してはいけない。**

## 将来、実用途が必要になった時の追加手順

1. **用途の具体的な入出力を先に決める。** 例: 「採用ページ画像」「SNS用サムネ」「高精細図版」。必要な最大寸法、画角、透過、metadata、Webへの公開先をそれぞれ定義。
2. **既存モードとの違いを表で確認する。** 同じレシピなら新機能を作らず`web-public`を再利用する。
3. **既存画像コアを無条件に一般化しない。** 新用途で異なる必要がある部分（サイズ/画像format/色/metadata）のみ別の不変recipeで表現。
4. **同じAPI/型の処理が本当に2か所以上で重複してから**共通moduleへ抽出。今、未来の用途数を仮定した多階層プラグインフレームワークは作らない。
5. **GUIは用途が増えて初めて画面分離。** 今は`gui.py`をそのまま保つ。2つ目の実画面が必要になったら `gui_web_public.py`等の別ページへ切り出し、`gui.py`を起動・ルーティング責務にする。既存NiceGUIのLocal-only制限は全用途に継承する。
6. **recipe version / hash / manifestを分ける。** 別用途で保存形式や公開policyが変わるなら、旧runの再利用を禁止し、schema/recipe互換性を明示。色/metadataの安全性検査を迂回しない。
7. **個別コンポーネントの責任を守る。** PDF/Excel/動画は既存moduleのまま。将来UIを追加するなら、CLI契約に関わらない薄いadapter/ページを追加し、root CLIの既定挙動を変更しない。

## 拡張しても守る契約

- 原本非破壊、入力/出力分離、link/junction/hardlink拒否、原子的置換、source/output SHA照合
- 未対応入力は安全に拒否。原本を公開用filesへ“fallbackコピー”しない
- metadata policyが違う用途を混同しない。公開用と社内用を同じ暗黙の設定へまとめない
- 顧客写真・住所・機密パスなどをログ/manifestから外部へ出さない
- 既存CLI、ドキュメント、schema、testsを後方互換に保つ

## 共通化を次回に延期すべき条件

`file_identity`抽出のために`image.py`全体の大規模改造、PDF/Excel/動画の変更、既存testsの意味変更が必要になった場合、今回はPilot優先で保留。将来の機能拡張余地を一度に全部作る必要はない。

## 推奨する継続改善のトリガー

- 実運用で同じ画像用途を毎月何度も手作業で設定し直す → 用途固定recipe追加
- Web写真の許容できない画質劣化が頻繁に発生 → 画質設定/元画像寸法の実測検討
- 2人以上が異なるPCでKaruFileを運用しセットアップが負荷になる → 配布方式だけ改善
- 過去runの容量が運用上の問題になる → 安全な保存期間/手動整理機能を検討（勝手な削除禁止）
- 2つ以上のGUI画面が必要になる → UIルーティングを分離

**実際の症状が発生する前に汎用化しない。**
