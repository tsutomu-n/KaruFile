# Windowsフォント置換の実装・検証記録（2026-09-10）

> この文書は游ゴシックを使った当時の検証記録です。現在は、置換対象の明示指定が必要で、
> 置換先はメイリオが既定です。通常圧縮での自動置換はしません。
> [現行マニュアル](../../MANUAL.md#日本語英語のpdfをメイリオへ統一する)と
> [メイリオ検証・既定化記録](../../.agent/execplans/2026-09-10-nishimaki-pdf-compression.md)を参照してください。


通常のKaruFileに、Windows搭載の游ゴシックRegularへ字体を統一する明示機能を実装した。
この記録は今回の未コミット作業ツリーを検証したもので、公開版・全PDFへの保証ではない。

## 実データPilot

対象は `Ⅱ-7_群馬県土木工事写真管理要領（R7.10改定）【最新版】.pdf`、101ページの1冊だけ。
既存原本から別の検証入力へコピーして通常CLIを実行した。

| 項目 | 実測 |
|---|---|
| 原本 | 7,436,386 bytes |
| 採用出力 | 4,265,318 bytes |
| 削減 | 3,171,068 bytes、42.642595% |
| 判定 | `ADOPTED_LOSSY / adopted_font_replace` |
| qpdf単独候補 | 7,156,384 bytes、検証合格・非採用 |
| 要求字体 | `Yu Gothic Regular`、インストール済み `YuGothR.ttc` face 0 |
| schema / recipe | 6 / 5 |
| 抽出差 | `text_extraction_changed=true` |
| 通常CLI所要時間 | 79.70秒、終了コード0 |
| 再実行 | 処理0件・既存結果1件、状態・出力SHA・更新時刻が不変、終了コード0 |
| dry-run | `DRY_RUN_LOSSY`、候補なし、通常出力・通常reportが不変、終了コード0 |
| 原本保持 | 元23件・既存通常出力18件・旧試験2件・Windows字体1件の計44件でサイズ/SHA一致 |

入力SHA-256: `c30a37d01d88358956753bb206ba3aa005be8644a9a52446468d29b722e878f8`

出力SHA-256: `edcc4f3d7caedb3d8adf6e9cc1871cb26171ca054ccfdeb776ab400d76efb132`

実行場所はリポジトリroot。検証用入力/出力の親は
`C:\Users\tn\Downloads\群馬県建設工事必携（R5年版）_軽量化\font-replacement-cli-pilot`。
ローカルPCまたはそのコピーへのアクセスが必要。次の`<pilot>`はこの親を表す置き場所の表記であり、文字どおり実行しない。

```powershell
uv run --script karufile.py -i "<pilot>\input" -o "<pilot>\output" --pdf-font-replace-pattern "*.pdf" --pdf-workers 1
```

同じコマンドで再開を確認し、続いて`--dry-run`を付けた。
`--pdf-preview`は別の100ページ上限があるため、この101ページPilotには指定していない。
比較機能との統合は合成fixtureで検証した。

## 検証と限界

製品の独立validatorは原本と各候補の文字コード・Unicode・文字原点・描画順、非文字命令、
画像、ページ形状、metadata、字体の輪郭・hmtx・権限等を確認し、全101ページを144 DPIで描画した。
qpdf候補は描画画素も一致した。字体候補の画素一致は採用条件ではない。

別途PDFium 5.13.0でも採用出力101ページを144 DPI描画した。
非空白41,835文字の順序は一致し、原点最大差は0.000030517578125 pt。
推定空白が異なるページは11ページ。検索・コピーの完全互換を保証しない。
採用出力と、以前に目視確認した游ゴシック試験版はMuPDF 1.28.2の144 DPI描画で全101ページの画素が一致した。
今回の採用出力も代表部分を300 DPIで視覚確認し、字体・太さ・字間の違いを残したまま、欠字や大きな崩れの有無を確認した。
rootが4/12/48ページ、独立担当が27/49/91/92ページを確認。91/92ページではRegular化により原本の太い本文・見出しの強調が弱まっている。
全字校正・実機印刷・全ビューアー検証ではない。

初回の区分情報の過剰保護、非UTF8 PDF Nameの誤読、ASCII CMapのhex大小文字による誤拒否は修正して回帰テストを追加した。
途中の保護・ERROR・qpdfだけの採用記録はPilotフォルダーの`attempt-*`に残した。
PDF1.3→1.5への格納形式昇格をmetadata消失と誤判定する問題も、実生成から独立検証への合成テストで発見・修正した。

## 自動検証

次の結果は実行済みの値。任意jpegtran実物テスト4件は環境条件によりskip。
画像・動画には並行した別作業の変更が存在し、字体機能の変更として扱っていない。

| suite | 結果 |
|---|---:|
| PDF `uv run --project pdf-shrink python -m pytest -q pdf-shrink/tests` | 433 passed、4 skipped |
| 画像 `uv run --project media-shrink-tool --extra dev python -m pytest -q media-shrink-tool/tests` | 64 passed |
| 動画 `uv run --project video-shrink python -m pytest -q video-shrink/tests` | 113 passed |
| orchestrator内 `uv run --with pytest python -m pytest -q` | 321 passed |

各processorのsrc/testsとroot/orchestratorのcompileall、root/standaloneのCLI help、`git diff --check`も確認した。
詳細な上限・非対応構造・履歴列の正本は[REFERENCE](../REFERENCE.md)、利用手順は[MANUAL](../../MANUAL.md)。
数値・SHA・描画・目視の機械可読証拠とPNGは[同名フォルダー](2026-09-10-windows-font-replacement/pilot-evidence.json)に保存した。
