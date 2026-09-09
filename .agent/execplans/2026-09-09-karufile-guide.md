# KaruFileを仕事の例と図で説明する

この文書はliving documentである。実装と表示検証に合わせて更新する。

## Goal

事務の仕事をする人が、単独で渡されたHTMLをオフラインで読み、「用途・原本の扱い・結果確認」の3点を説明できるようにする。

## Acceptance Criteria

- `docs/KARUFILE_GUIDE.html`に仕事の例、原本と出力の図、PDFの扱いの図、注意点、3つの確認事項を収録する。
- 本文・図を外部通信や別ファイルなしで読める。目次・既存マニュアルへの相対リンクが正しい。
- Archifyの図はshowcase検証・deliver・visual-checkを行い、明暗画像を目視確認する。
- ガイドをブラウザーとA4印刷で確認し、横はみ出し・欠け・読めない図を残さない。
- 実行機能を変更せず、文書差分検査を通す。

## Scope

In Scope: ガイド、2図のJSONと生成物、再生成手順、表示検証証拠、MANUALと文書索引からの案内。
Out of Scope: 実行コード、既存アーキテクチャ図、compact作業の再開、commit・外部公開。

## Current State / Facts

- 開始時のGit作業ツリーはclean。確認したHEADは`292a9e7f694cdd8e58ef512051db97cd26ded851`。
- `karufile.py`はPowerShellから使う入口で、orchestratorへ委譲する。
- `orchestrator/shrink_all.py`はPDF・対応画像を探索し、動画はcompact時だけ探索する。出力省略時は入力の兄弟`<入力名>_軽量化`。
- `pdf-shrink/src/pdf_shrink/policy.py`は文字だけを自動許可し、未指定の画像・描画入り文書を保護する。文章スキャンは明示許可が必要。
- `media-shrink-tool/src/media_shrink/image.py`は先頭フレームだけを使い、透明部分を白にする。
- MANUALの注意・出力・PDF比較の説明と以上のコードは、このガイドの範囲で整合する。

## Inferences / Assumptions / Unknowns

- 入門用の説明は通常設定を基準とし、追加設定のコマンド詳細はMANUALに委ねる。
- 「会議資料」は架空の例。削減容量や実資料の成功実績は載せない。
- 単独HTMLの本文・図は完結させる。マニュアルリンクはリポジトリ同梱時用と明記する。
- Unknowns: ブラウザーの日本語フォント・印刷改ページ・図の可読性はCP-003で確認済み。実プリンター、他OS、読者による読解テストは未実施。

## Options / Decision

生成Archify HTMLをそのまま2枚iframeで読む方式は、入門読者に操作UIが多く印刷にも不向き。検証済み図を静的に埋め込み、本文は読みやすい独立HTMLとする。JSONと生成HTMLを保持して再生成可能にする。アプリ依存関係は追加しない。

## Risks / Stop Conditions

細部・色の保持や容量削減を保証する誤読を避ける。表示検証が利用不能なら未確認と記録する。許可のない外部公開や機能改変が必要になれば停止する。

## Checkpoints

### CP-001: 現行仕様を照合

- Status: Complete
- Objective: 原稿の主張を実装と突き合わせる。
- Dependencies: なし。
- Files or components: AGENTS、MANUAL、REFERENCE、orchestrator、PDF policy、画像処理、関連テスト。
- Actions: Git状態、説明、実行分岐を読む。
- Completion criteria: 用途・原本保護・対象外形式・例外を説明できる。
- Validation: ソース照合。Evidenceは後述。
- Failure conditions: 仕様の重大な矛盾。
- Recovery: ガイドの記述を実装に合わせ、影響文書も更新する。

### CP-002: ガイドと図を作成

- Status: Complete
- Objective: 4節と2図を単独HTMLに収める。
- Dependencies: CP-001。
- Files or components: docs/KARUFILE_GUIDE.html、docs/guide、MANUAL、docs/README、ExecPlan索引。
- Actions: 図の候補を作成・validate・deliverし、静的な図を埋め込む。
- Completion criteria: 必須の説明・図・導線が存在し、外部リソースを必要としない。
- Validation: Archify showcase 9項目、文書リンクとHTML構造。
- Failure conditions: 図の検証失敗、現行仕様と不一致。
- Recovery: 診断対象に絞って修正・再検証。既存生成図を変更しない。

### CP-003: 閲覧と印刷を検証

- Status: Complete
- Objective: 図と本文の可読性、オフライン、目次、リンク、印刷を確認する。
- Dependencies: CP-002。
- Files or components: ガイドと図、docs/guide検証証拠。
- Actions: visual-check、ブラウザー画面と印刷PDFの確認、git diff --check。
- Completion criteria: 明暗の図、PC・狭い画面、A4印刷に欠けがなく、リンクが正しい。
- Validation: サイズ・通信・リンクの機械検査とスクリーンショット目視。
- Failure conditions: クリップ、図の小さすぎる文字、リンク切れ。
- Recovery: ガイドCSSまたは図JSONを修正して該当検証を再実行。

## Progress

- [x] CP-001
- [x] CP-002
- [x] CP-003

## Discoveries

「写真入りPDFは通常そのまま」と「単独写真は縮小・圧縮」を別に示す必要がある。画像の複数ページ先頭のみはPDFのページ処理と混同させない。

## Decision Log

2026-09-09: 通常設定の入門ガイドを新規作成。ユーザー提示計画の範囲内で、静的な埋込図と説明文を併記する。

2026-09-09: workflowの固定行高では4行の図がPC画面から縦にはみ出した。元／出力の構成を表すarchitecture形式へ変更し、フォルダーの枠を明示。最終2図はshowcaseと画面内収容検査に合格した。

2026-09-09: 印刷確認で図の文字が小さかったため、文字サイズを落とさず箱・間隔を整理した。本文との重複説明も短くし、A4全4ページで可読性と欠けを再確認した。

## Validation Evidence

詳しくは [docs/guide/REVIEW.md](../../docs/guide/REVIEW.md) と生成receiptを参照。

- `node .../archify.mjs validate architecture <各JSON> --quality showcase --json`: 最終2図とも9/9、errors 0、warnings 0。
- `node .../archify.mjs deliver architecture <各JSON> <各HTML> --quality showcase --json`: 2図ともexit 0。JSON/HTMLのSHA-256とバイト数を各delivery receiptに保存。
- `node .../archify.mjs visual-check <各HTML> --json`: 2図ともexit 0。4サイズの横・縦はみ出しなし。最小・最大サイズの明暗8画像を目視確認。
- `node docs/guide/build-guide.mjs`: exit 0。各図を2080×1136の正規PNGで書き出し、ガイドに埋込。最終HTMLは687,015 bytes、SHA-256 `8875820fd8dcf7b399879128c6e7ff192640ca719a52449975b9d168af6fa6c9`。
- `node docs/guide/check-guide.mjs`: exit 0。PC・狭い画面5サイズ、目次4項目、先頭リンク、マニュアル3リンクを確認。単独HTMLを別ディレクトリへ移してofflineで4節・2図を表示、外部HTTP(S)要求0。
- Chrome `Page.printToPDF` と `uv run --project pdf-shrink python -` 内のPyMuPDF: A4全4ページを描画・目視確認し、本文座標が用紙内にあることを検査。`docs/guide/validation/guide.a4.pdf` と4枚のページPNGを保存。
- `uv run --script karufile.py --help`: exit 0。既存のPDF比較オプションを確認。
- `node --check` を文書用の3スクリプトへ実行: すべてexit 0。
- `git diff --check`: exit 0。新規テキストの差分も別途検査。
- 実行機能は変更していないため、pytest・compileallと実資料圧縮Pilotは未実施。

## Outcomes / Remaining Issues

完了。ユーザーが指定した `docs/KARUFILE_GUIDE.html` を新設し、MANUALと文書索引から案内した。
本文・図はネット接続なしで読める。操作の詳細は正本マニュアルに残し、単独HTMLにはマニュアル自体を内包しないことを明記した。
既存アーキテクチャ図・compactの中断状態・実行コードは変更していない。commit・push・外部公開はしていない。

重要な未解決不具合はない。確認環境はWindows Chromeで、実プリンター・他OS・事務員の方による読解テストは未実施。
