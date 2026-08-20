# PDF placed images to 300 DPI

この文書はliving documentである。
実装中はProgress、Discoveries、Decision Log、Validation、
Outcomesを継続的に更新する。

## Goal

利用者がKaruFileでPDFを処理したとき、ページ上の配置サイズから見た画像実効DPIが
300を超える画像は300DPIへ縮小され、ベクター文字は残り、入力原本は変更されない。
`C:\dev\docs` の600DPIスキャンPDFで、出力画像の実効DPIが約300になり、
`ADOPTED_LOSSY` または検証失敗時の明示的な非採用になることで完成を確認する。

## Acceptance Criteria

- 配置実効DPIが300超の画像を300DPIへ縮小する。JPEGのxres/yresメタデータは使わない。
- 拡大しない。
- 可視テキストを含むPDFでも、超過DPIの画像があれば非可逆候補を作る。
- ベクター文字はラスター化しない。
- 単独画像の1280×960 recipeは変更しない。
- 合成テストで縮小後の実効DPIが約300である。
- 既存の安全性・検証・公開契約を維持する。
- 影響する文書を同じ変更で更新する。

## Scope

### In Scope

- `pdf-shrink` のlossy候補生成とlossy判定
- 対応テストと正本・リファレンス
- 実データ `C:\dev\docs` での再実行

### Out of Scope

- ページ全体のラスター化
- 単独画像を300DPI化すること
- 1bit/bitonal、soft mask画像の縮小
- 動画、GUI、入力削除
- Archify図（実行時境界は変わらない）

## Current State

lossy経路は `Document.rewrite_images(dpi_threshold=450, dpi_target=300, quality=92)` に
依存している。群馬県スキャンPDFは配置600DPIだがJPEGメタデータは96DPIで、
rewrite_imagesは画像を触れず `UNCHANGED` になった。

## Facts

- 対象PDFは11ページ、各ページDeviceGray JPEG 4938×6992、bboxから約600DPI、
  `image_info.xres/yres` は96。
- `inspect_pdf._effective_image_dpi` はbboxとpixelから実効DPIを計算する。
- `rewrite_images` 実行後もpixel寸法は4938×6992のままだった。
- 候補は4197 bytes（0.01%）しか減らず、lossy採用条件（256KiBかつ5%）未満。
- 単独画像recipeは長辺1280、短辺960。
- `config_hash` はlossyオプション値を含むが、実装差し替えだけでは変わらない。

## Inferences

- PyMuPDFのimage rewriterは配置実効DPIではなく画像メタデータDPIを見ている。
- 「文章も300DPI」はベクター文字のラスター化ではなく、文字付きPDFの超過画像も
  300DPIへ落とすことを指すのが、現行のテキスト検証契約と両立する。
- 単独画像の300DPI化は印刷サイズが無いため1280×960と矛盾する。

## Assumptions

- ユーザーの主目的はPDFページ画像を実際に300DPIへ落とすことである。
- 1bit/soft-maskは今回スキップし、原本のまま残す。

## Unknowns

- 全PDFのForm XObject・共有xref・CMYKでの `replace_image` 成否。
  失敗時は既存どおり `ERROR` のあと原本コピーを試みる。

## Options Considered

1. `rewrite_images` の閾値だけ下げる。メタデータ96DPIでは誤って拡大しうる。不採用。
2. 全ページを300DPIでラスター化する。検索可能な文章を壊し、text検証が失敗する。不採用。
3. 配置実効DPIで画像を差し替える。採用。
4. 新規OSSを追加する。既存PyMuPDFで足りる。不採用。

## Recommended Decision

配置実効DPIが `dpi_target`（300）を超える画像をJPEG quality 92へ縮小して差し替える。
判定も「スキャンページ80%」だけでなく、超過DPI画像の有無を使う。
`LossyOptions.algorithm` を `placed-effective-dpi-v2` にして再開ハッシュを更新する。
`Page.replace_image` は未使用画像を資源に残すため、既存xrefへJPEGを直接書く。

## Risks

- 72DPI表示差が5%を超えると検証失敗し原本コピーになる。
- 1bitスキャンは縮小されない。

## Stop Conditions

- `replace_image` が合成600DPI JPEGで縮小できない。
- テキスト検証またはqpdf検査が通常のスキャンPDFで系統的に失敗する。

## Checkpoints

### CP-001: Inspect uses placed DPI for lossy mode

- Status: Done
- Objective: 超過配置DPIがあれば文字が多くてもLOSSY
- Dependencies: none
- Files or components: `inspect_pdf.py`, `worker.py`
- Actions: max effective DPI > dpi_target ならLOSSY。scan_page_ratioの定義は維持。
- Completion criteria: 文字付き600DPI画像PDFがLOSSY、300DPIと文字のみはLOSSLESS
- Validation: pytest
- Failure conditions: 文字のみPDFがLOSSYになる
- Recovery: 判定を画像DPIだけに戻す

### CP-002: Transform downsamples placed images

- Status: Done
- Objective: rewrite_imagesを配置実効DPIの差し替えへ置換
- Dependencies: CP-001
- Files or components: `transform.py`, `config.py`
- Actions: xrefごとの最大実効DPIで縮小。拡大しない。algorithmをハッシュへ含める。
- Completion criteria: 600DPI JPEGが約300DPIになる。JFIF 96でも縮小する。
- Validation: pytest
- Failure conditions: pixel寸法が変わらない
- Recovery: 失敗xrefはスキップし他を継続

### CP-003: Documents and real PDF

- Status: Done
- Objective: 正本を更新し `C:\dev\docs` を再実行する
- Dependencies: CP-002
- Files or components: MANUAL, REFERENCE, README, AGENTS, execplan index
- Actions: 契約文を更新し、実PDFを再処理する
- Completion criteria: 文書がコードと一致し、実PDFの出力実効DPIが約300
- Validation: 指定の検証コマンドと実PDFレポート
- Failure conditions: 実PDFが再びUNCHANGEDで600DPIのまま
- Recovery: 原因をExecPlanへ記録し、採用しない理由を隠さない

## Progress

- [x] CP-001
- [x] CP-002
- [x] CP-003

## Discoveries

- 群馬県PDFのJPEG `xres/yres` は96、配置は約600DPI。
- `Document.rewrite_images` はこのメタデータDPIを見るため、600DPI配置画像を触れない。
- `Page.replace_image` は新しい画像資源を残し、11ページで約50MBのまま削減率1.7%になった。
- 既存xrefへJPEGを直接書くと 25,393,544 bytes、50.84%減、検証成功、配置DPI約300。

## Decision Log

### Decision-001

- Date: 2026-08-20
- Decision: ページ全体のラスター化はせず、配置画像だけ300DPIへ縮小する。
- Rationale: ベクター文章とNFCテキスト検証を維持できる。
- Alternatives: 全ページラスター化、rewrite_imagesの閾値変更
- Consequences: 1bit画像は未対応。単独画像recipeは据え置き。

## Validation Evidence

- `uv run --project pdf-shrink python -m pytest -q pdf-shrink/tests` → 52 passed
- `uv run --project media-shrink-tool --extra dev python -m pytest -q media-shrink-tool/tests` → 34 passed
- orchestrator pytest → 41 passed
- `compileall` と `karufile.py --help` と `git diff --check` 成功
- `C:\dev\docs` 再実行: status=`ADOPTED_LOSSY`、入力 51,650,153 → 出力 25,393,544、削減 50.84%、11ページすべて配置DPI 300.0、pixel 2469×3496、入力未変更

## Outcomes

配置実効DPIが300超のPDF画像を300DPI JPEGへ縮小し、ベクター文字は残す。群馬県スキャンPDFは採用済み。単独画像の1280×960は変更していない。

## Remaining Issues

- 1bit画像とsoft mask付き画像は縮小しない。
- 単独画像は印刷300DPIではなく長辺1280・短辺960。
- ベクター文字そのものを300DPIラスターにはしない。
