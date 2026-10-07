# KaruFile `web-public` 実装指示書

作成日: 2026-10-07  
対象: `tsutomu-n/KaruFile`  
確認した GitHub main: `bc88f56a6aadeaa11b0cd6687c45e113ce539547`（2026-10-05）  
目的: 担当者PCで、選択した写真・図版から、seimou.comへ入稿する掲載用マスターを作る。既存CLIを維持し、画像専用コマンドと簡易GUIを完成させる。

## 0. Codexへの作業依頼・権限境界

この文書は実装指示である。対象リポジトリの現在の実物を確認し、関連するテスト、画像専用CLI、簡易GUI、利用手順まで実装する。計画の提示だけで止めない。以下の新規パス・コマンド・インターフェースは、現在存在すると主張するものではなく、今回の実装目標である。

- 作業開始時に `git status --short`、`git diff --stat`、関係ファイル、依存・lockfile、`AGENTS.md`、`.agent/execplans/README.md` を読む。上記SHAへ強制的に戻さず、ローカルの新しい実装や他の作業を保全して適用する。
- 実装・ローカル検証・関連文書の更新まで行う。commit、push、PR作成、本番公開、外部サービス設定変更、実写真の外部送信は行わない。
- 原本、他の作業、利用者が作った既存成果物を削除・上書きしてよいという依頼ではない。自分が作った未完成の一時ファイルの後始末は行う。
- 既存のGUI対象外という方針は、今回の「画像用ローカルGUI」に限り改訂する。PDF・Excel・動画のGUI化や製品全体の再設計まで許可したとは扱わない。
- 不明点はまず実物から解消する。下記で決めた仕様を再質問しない。環境上実行できない確認は未実行として報告し、可能な実装・自動テストは進める。
- 小規模企業向けである。ジョブサーバー、認証基盤、キュー、クラウド変換サービス、抽象的なプラグイン基盤、包括的な写真管理台帳は追加しない。

## 1. 今回固定する役割と出力形式

### 1.1 作業フロー

`NASの原本・編集素材 → 担当者PCのKaruFile → 掲載用マスター → 担当者がPayloadへ一括入稿 → Astro/Sharp → 公開サイト`

NAS/Google Driveへのバックアップ、Payload/R2連携、記事作成、サイト公開、プレビューサイトはこのリポジトリで実装しない。担当者はPC・CAD・画像編集・ブログ更新に慣れており、選別・ぼかし・構図調整は既存の画像編集ソフトで行う。

### 1.2 「マスター」と「閲覧者に配信する画像」を分ける

| 段階 | 写真 | 透過画像・図版 | 担当 |
|---|---|---|---|
| NASの原本 | 元の形式のまま保全 | 元の形式のまま保全 | 社内保管 |
| 掲載用マスター | JPEG、高品質、幅最大1400px | PNG、透過保持、幅最大1400px | 今回のKaruFile |
| サイト内の最終配信 | AVIF優先、WebPを最終フォールバック | AVIF/WebP。細線・文字ではWebP losslessを候補にする | 別案件のAstro/Sharp |

最新方針は、サイト内の写真についてJPEG/PNGの互換フォールバックを作らないこと。これを「KaruFileのマスターもAVIFへ変更する」と読み替えない。前段のマスター仕様は維持し、公開用JPEG/PNG派生画像を不要にする。

KaruFileへAVIFエンコーダを追加しない。既存の通常モードのWebP出力は削除・変更しない。非可逆WebPを中間素材として作り、そこからAVIFへ順次変換する経路は作らない。JPEGマスター自体は非可逆であり、「無劣化」と説明してはならない。

JPEG/PNGマスターや内部manifestをそのまま公開用 `dist/` にコピーしないことは、後段のサイト担当へ渡す条件である。OGP・SNSの画像取得はブラウザー表示とは別の互換性問題であり、このKaruFile実装で対応範囲を決めたり、JPEG配信用資産を先回りして作ったりしない。

## 2. 確認済みの現状と、今回触る境界

### 2.1 確認済みの実装

| 現在のファイル | 実物で確認した内容・注意点 |
|---|---|
| `media-shrink-tool/src/media_shrink/config.py` | `ImagePreset`は`standard/compact`。`ImageRecipe`は長辺/短辺とJPEG 4:2:0を前提に検証する。`ImageConfig`には`output_format`と`strip_exif`がある。幅1400の公開マスターを無理に既存presetへ押し込まない |
| `media-shrink-tool/src/media_shrink/cli.py` | 既存サブコマンドは`resize`。`--format jpeg/png/webp`と`--strip-exif`あり。既存コマンド・stdout・終了コードを維持する |
| `media-shrink-tool/src/media_shrink/image.py` | `process_image`、`process_all`、入力/出力fingerprint、出力計画、検証、再利用、manifestがある。`_save_image`は内部markerを書き、`_verify_candidate`はmarkerを要求する。`_optional_metadata`はXMP等を保持するため、新しい公開用途にそのまま使えない |
| `media-shrink-tool/src/media_shrink/utils.py` | 入出力の同一/親子関係、危険なリンク、補助出力の検査、`staged_path`等がある。既存の安全処理を再利用する |
| `media-shrink-tool/tests/test_image_contract.py` / `test_output_formats.py` | 既存契約、JPEG/PNG/WebP、EXIF除去、再利用、失敗時の保全等の回帰確認対象 |
| `media-shrink-tool/pyproject.toml` / `uv.lock` | 画像パッケージはPython 3.11以上、Pillow・pillow-heifに依存。GUIを必須依存へ混ぜない |
| `karufile.py` / `orchestrator/shrink_all.py` | 全体CLIはPDF等も統括する。今回の画像専用実行経路では呼び出さない |

GitHub確認だけではローカルの未push版やWindows/NAS上の実行結果は分からない。既に同等機能が追加されていれば再実装せず整合させる。

### 2.2 推奨する最小配置

- 変更: `media-shrink-tool/src/media_shrink/cli.py` — 新規コマンドの解析・呼び出し。
- 新規: `media-shrink-tool/src/media_shrink/web_public.py` — 用途別設定、変換、検証、実行結果/manifest、バッチ処理。長くなる場合だけ変換処理とmanifest処理を二つへ分割する。
- 新規: `media-shrink-tool/src/media_shrink/gui.py` — 日本語のローカルNiceGUI。画像処理は持たない。
- 変更必要時のみ: `image.py` / `utils.py` — 共通のfingerprint・path・atomic write等の再利用に必要な最小調整。既存画像処理全体をコピーしない。既存テストが依存する境界も保つ。
- 変更: `pyproject.toml` / `uv.lock` — `gui` optional extraを追加し、実際に動作確認したNiceGUIをlockする。
- 新規: `media-shrink-tool/tests/test_web_public.py`、`test_web_public_cli.py`、`test_web_public_gui.py`。
- 新規: `media-shrink-tool/run-web-public.cmd` — 担当者用のWindows起動入口。SEが準備した環境を使う。
- 関連文書: `MANUAL.md`、`docs/REFERENCE.md`、画像コンポーネントの`README.md`、必要な`AGENTS.md`の範囲説明。READMEは入口の短い追記に留める。

新規設定は例えば`WebPublicConfig`という小さな不変データで表す。`ImageConfig.preset`に見せかけの値を入れたり、`max_short`に巨大な数値を入れて制限を事実上無効化したりしない。公開向けは「色・metadata・再利用・出力の契約が異なる用途」であり、圧縮強度の追加ではない。

## 3. CLIの実装目標

リポジトリ直下から以下が動くこと。以下は新規コマンドの目標で、現行CLIの使用例ではない。

```powershell
# 写真: 入力フォルダーから掲載用JPEGマスターを作る
uv run --project media-shrink-tool python -m media_shrink web-public -i "D:\工事\案件A\写真" -o "D:\工事\案件A\写真_HP掲載用" --kind photo

# 透過・図版: PNGマスターを作る
uv run --project media-shrink-tool python -m media_shrink web-public -i "D:\広報\図版" -o "D:\広報\図版_HP掲載用" --kind graphic

# 選択対象は入力フォルダーからの相対ファイル名で限定できる
uv run --project media-shrink-tool python -m media_shrink web-public -i "D:\工事\案件A\写真" --kind photo --file "施工前\01.jpg" --file "施工後\02.heic"

# 変換前確認
uv run --project media-shrink-tool python -m media_shrink web-public -i "D:\工事\案件A\写真" --kind photo --dry-run

# GUI: optional extraを導入した環境でのみ必要
uv run --project media-shrink-tool --extra gui python -m media_shrink gui
```

引数:

- `web-public`は画像専用サブコマンド。全体CLIの`--preset`に追加しない。`karufile.py --preset web-public`を新設しない。
- `-i/--input`: 必須の入力フォルダー。通常は写真を選別済みの小さな案件フォルダー。
- `-o/--output`: 省略時は入力フォルダーの兄弟`<入力名>_HP掲載用`。同一・親・子への出力は既存の安全方針どおり拒否。
- `--kind`: `photo`または`graphic`、既定`photo`。
- `--file`: 繰り返し可能な入力ルート相対の完全ファイル名。globではない。省略時は対象画像を再帰列挙。指定時はそのファイルだけ処理し、絶対パス・`..`・ルート外・存在しない指定は引数/選択エラーとする。GUIのチェック欄と同じ選択ロジックを使用。
- `-j/--workers`: 既定2、許容1〜4。通常GUIには出さない。既存`resize`のworkers既定値は変えない。
- `--dry-run`: 新しい`web-public`では、デコード・計画・選択/色/寸法の確認のみ。出力フォルダー、画像、manifest、レポートを作成・変更しない。既存モードのdry-run動作はそのまま。
- `--preset`、`--format`、`--strip-exif`、任意品質の指定は新コマンドでは受け付けない。固定用途の条件と矛盾する指定を黙って無視しない。
- 終了コード: 0=選択画像すべて成功（警告あり可）、1=変換/保存/manifest等の失敗、2=引数や選択の不正。対象画像ゼロは2とし「成功0枚」で終えない。成功・警告・失敗の枚数は重複関係を正しく表示する。
- PDF・Excel・動画は探索候補に含めず、処理・コピー・依存初期化をしない。対象外ファイルは画像の失敗件数に含めない。

## 4. 画像の固定仕様

### 4.1 写真と図版

| 設定 | `photo` | `graphic` |
|---|---|---|
| 出力 | JPEG / `.jpg` | PNG / `.png` |
| 上限 | 向きを正した後の横幅1400px | 同左 |
| 縦横比 | 維持 | 維持 |
| 拡大・crop | 禁止 | 禁止 |
| JPEG設定 | quality=90、subsampling=0（4:4:4）、optimize=True、progressive=True | 不使用 |
| PNG設定 | 不使用 | RGB/RGBA、可逆、compress_level=6。減色・量子化なし |
| 色 | 8bit sRGBへ正規化 | 8bit sRGBへ正規化。alphaは別に保持 |
| 実際に透明な画素がある入力 | エラーにして「透過画像・図版を選択」と案内。白背景へ自動合成しない | 透過を維持 |
| Metadata | 入力由来の情報を継承しない。新規の標準sRGB情報のみ許可 | 同左 |
| 内部marker | 埋め込まない | 埋め込まない |

q90・4:4:4は二次生成元の画質を優先した初期仕様で、最小バイト数を狙う設定ではない。品質は公開サイト側で生成したAVIF/WebPも含めて一度確認する。原本よりファイルが大きくなっても、公開用途の契約を満たす候補は採用し、容量増加を結果に表示する。非公開metadata付き原本へ戻す処理は禁止。

### 4.2 サイズ計算

Orientation適用後の幅を`w`、高さを`h`として、`scale = min(1, 1400 / w)`。幅は`min(w, 1400)`、高さは`max(1, floor(h * scale + 0.5))`。整数演算を用いても同じ結果にする。

| 向き補正後の入力 | 期待する出力 |
|---|---|
| 4000×3000 | 1400×1050 |
| 3000×4000 | 1400×1867 |
| 1200×800 | 1200×800 |
| 800×2400 | 800×2400 |
| 8000×1000 | 1400×175 |

「横幅1400」を「長辺1400」へ置き換えない。リサイズは既存のPillow LANCZOS等を利用し、自作の補間処理は作らない。極端な縦長画像で後段エンコーダの寸法制限に抵触する場合は、黙って別サイズへ変えず、対応外と報告する。

### 4.3 入力の扱い

既存の画像拡張子を基本に、JPEG・PNG・静止WebP・静止HEIC/HEIF・BMP・単一ページTIFF・単一フレームGIFを対象とする。拡張子だけで判断せず、デコーダが認識した実形式を確認する。今回はAVIF入力、新しいコーデック、RAW、PDFの画像化まで増やさない。

新コマンドでは複数フレーム/ページを黙って先頭1枚へ落とさず、対応外とする。HEICの補助画像・depth情報と独立した複数フレームを混同しない。ロック済みpillow-heifの実際の情報を確認して判定する。

通常のWindows PCでの保護上限は、初期値を1画像64 MiB、デコード前の寸法で80,000,000画素とする。超過はその画像のみエラー。Pillowの安全制限をグローバルに解除しない。全画像を同時に読み込まず、最大workers枚で処理する。これはサイズの目安を保証する性能SLAではなく、暴走防止の上限である。

## 5. 色・透過・metadataの処理順

1. 入力のpathとfingerprint（size/stat/SHA-256）を確認する。
2. デコード前に実形式、寸法、フレーム、入力の色情報/bit depthを確認する。
3. 入力をデコードし、Orientationを一度だけ適用する。pillow-heifが適用済みの向きを、`original_orientation`等から再適用しない。
4. 色とalphaを分ける。妥当な入力ICCがあればPillow `ImageCms`（LittleCMS）でsRGBへ変換。`ImageCms.createProfile('sRGB')`由来のプロファイルを使用し、入力ICCを出力へそのままコピーしない。初期rendering intentは`PERCEPTUAL`で固定する。
5. 有効ICCがない8bit RGB/RGBA/L/LA/Pで、明示的な別色空間/HDRの指定がない場合はsRGBと仮定して扱い、`SRGB_ASSUMED`を記録する。P/LA等は透明度を保持して適切なRGB/RGBAへ展開する。
6. 壊れたICC、ICCなしCMYK、矛盾する色情報、PQ/HLG等の明示的HDR、未検証の高bit depth/NCLX変換は「sRGBのJPEG/PNGとして編集ソフトから書き出してください」とそのファイルを拒否する。ICC除去だけでsRGB変換済みとしない。8bitへのビット削減だけをHDRのtone mappingと見なさない。今回は汎用HDR変換機構を作らない。
7. `graphic`はalphaを維持し、透明な縁に白/黒の縁取りを作らないようPillowのRGBAリサイズを使う。`photo`は実際に透明画素がある場合だけ拒否し、全画素不透明のRGBAはRGBへ変換可能。
8. 4章の幅で一度だけ縮小する。
9. 出力用の新しいRGB/RGBA画像を画素から構成するなどして、入力の`info`、`getexif()`、テキスト、XMP、コメントを暗黙に継承しない。
10. 同じ出力ディレクトリの一時ファイルへ、固定設定と新規sRGB情報だけを指定して保存する。
11. 再オープンし、実形式・寸法・デコード・色情報・alpha・metadata方針を検証する。
12. 原本が処理途中で変わっていないこと、出力先が安全であることを既存の仕組みで再確認し、検証済み一時ファイルだけを`os.replace()`相当で確定する。

### 5.1 Metadataの完成条件

- EXIF/GPS/撮影日時/MakerNote、IPTC、XMP、入力コメント、PNG text、入力ファイル名/絶対パス、KaruFile markerを完成画像へ持ち出さない。
- 新規の標準sRGB ICC（または相当する標準sRGB宣言）と、画像形式に必要な構造情報だけを許可する。
- JPEGのJFIF構造や単位なし既定density、PNGの画像構造まで「metadataゼロ」という名目で破壊しない。「入力の撮影DPI等を継承しない」が条件。
- PillowのEXIF/info/text/applist等、形式に適した方法で確認する。少なくともEXIF、COM、XMP、IPTC、PNG textの混入を試験する。画素の圧縮バイト列を単純に文字列検索しただけでmetadata検証済みにしない。
- 保存候補から禁止情報が見つかった場合は採用しない。既存の`_save_image`や`_verify_candidate`をそのまま通してmarkerを付け、後から削る二段階エンコードはしない。
- sRGBはタグ名だけで正しさを証明できない。色変換の対照テストと、指定プロファイルへの出力の両方を確認する。
- 写り込んだ住所・看板・顔・車両番号の除去は、このmetadata処理では行えない。GUIとマニュアルに短く明記し、編集担当者が確認する。

## 6. 出力・manifest・再実行

### 6.1 出力フォルダー

原本の案件名やファイル名がCMS・URLへ流れないよう、`web-public`の完成ファイル名は中立な名前へ変更する。元名との対応はローカルmanifestにだけ保存する。

```text
写真/                                  # 入力、変更禁止
写真_HP掲載用/                         # -o: 出力ルート
  manifest.web-public.json              # 最新実行の結果。社内専用、入稿しない
  runs/
    <run-id>/
      files/                           # この実行で検証できた画像だけ
        img-<run-id>-0001.jpg
        img-<run-id>-0002.jpg
```

- `run-id`はランダムな識別子。案件名、撮影日、ユーザー名、パスを組み込まない。同じ名前があれば新たに生成し、既存runを上書きしない。
- この小さな実行別フォルダーは、前回の失敗画像/古い画像を今回の入稿候補へ混ぜないために使う。ジョブDBは作らない。
- 完成画像はflatに置く。順序は選択一覧の安定した順。入力の元フォルダー名を出力パスへ公開情報として引き継がない。
- GUIの「出力を開く」は、今回の`runs/<run-id>/files`を開く。出力ルートや古い実行を開かない。
- 原本と既存の実行別フォルダーは自動削除しない。自動履歴整理機構も初期実装に含めない。

### 6.2 manifestの最小構造

既存の通常画像CSVやroot側パーサーを変更せず、新用途は独立した小さなUTF-8 JSONにする。`schema_version=1`。これは公開CMSの台帳ではなく、ローカル変換と再利用の記録である。

トップレベル:

- `schema_version`, `run_id`, `input_root`, `output_root`, `recipe`, `recipe_hash`, `engine_versions`, `results`。

各結果:

- `source_path`: 入力ルート相対。
- `source_sha256`, `source_size`, `source_mtime_ns`。
- `source_width`, `source_height`, `oriented_width`, `oriented_height`。
- `output_path`: 出力ルート相対。`ERROR`ではnull。予定パスと実在する完成出力を混同しない。
- `output_sha256`, `output_size`, `output_width`, `output_height`, `output_format`。
- `action`: `CONVERTED` / `SKIPPED_COMPLETE` / `ERROR`。警告はactionへ混ぜない。
- `warnings`: 機械判定可能な短いコードの配列。
- `error`: 成功時null、失敗時は`code`と短い日本語`message`。

変換完了時、manifest参照対象の原本/出力の同一性と内容を検証し、一時JSON→原子的置換で更新する。manifest書込み失敗は終了コード1とし、前回のmanifestを保持する。成功とエラーが混在していても、検証済み成功分と失敗を区別した今回のmanifestを保存できる。禁止情報を検出した候補は完成ファイル群へ出さない。

### 6.3 再利用

- 再利用根拠は前回manifestの成功行。画像内markerやファイル名だけを信頼しない。
- `source_path`、source SHA-256、固定recipe/hash、エンジンの互換性、前回output SHA-256、今回の出力ポリシー検査が一致した時だけ再利用する。
- 再利用する場合は検証済み前回画像のバイト列を新しい実行のfilesへ安全にコピーし、`SKIPPED_COMPLETE`とする。再エンコードしない。hardlinkは使わない。
- manifestがない/古いschema/破損/対応外の場合は、再利用せず原本から作り直す。manifestに書かれたパスを無条件に読み込まず、指定output配下・通常ファイル・リンクでないことを検査する。
- 原本のmtimeだけが同じ、サイズだけが同じ、画像に旧KaruFile markerがある、といった理由で再利用しない。
- `recipe_hash`にはkind、幅制限、丸め規則、形式、JPEG/PNG設定、色・alpha・metadata方針、web-publicのrecipe versionを含める。Pillow/pillow-heif/LittleCMS等の処理結果に影響する版は記録し、版が変わった場合は再生成できるようにする。既存モードのhash定義は変えない。
- run-idや実行時刻をrecipe hashへ入れない。sRGBプロファイル生成時の作成時刻が毎回変わるために、同じ設定の再利用が常に外れる設計にしない。
- 新modeは原本への再アクセスとmanifestが基本。metadata除去済み画像単体を渡されて、以前の処理済みマスターと必ず識別できるとは約束しない。

## 7. 既存コードの再利用方法

新規関数名は以下を目安とし、ローカルの既存追加と衝突する場合は同等の小さな境界を使う。

```text
WebPublicConfig(kind, workers=2)
  固定recipeを解決する。出力形式やmetadataを自由入力で上書きしない。

process_web_public_image(source, destination, config, *, input_root, output_root)
  1ファイルを変換・検証し、構造化した結果を返す。CLI/GUIに依存しない。

run_web_public(input_dir, output_dir, config, *, selected_files=None,
               dry_run=False, on_result=None)
  選択検査、出力計画、再利用、独立ファイル処理、結果集計、manifestを担当する。
  on_resultは1枚終了時に構造化結果を通知。UI更新の実行はGUI側。
```

- 画像処理をNiceGUIイベントハンドラーに書かない。
- hash、path guard、`staged_path`、原本の変更検知、`_replace_staged`相当の確定境界は既存コードを優先する。内部関数を同じパッケージから利用するための最小調整はよい。
- 既存の`process_image`に`ImageConfig`を渡し、一度standard JPEGを作ってから公開用へ再変換する実装は禁止。原本から今回のrecipeへ直接進む。
- `web-public`固有のmetadata/manifest契約を、既存の`strip_exif`の別義にしない。既存モードへ公開用の挙動を波及させない。
- GUIはstdoutを解析せず、上記結果またはmanifestから件数・警告・失敗理由を表示する。

## 8. GUIと担当者向け起動

### 8.1 必要な画面だけ作る

日本語の1画面で、次の順に操作できるようにする。

1. 入力フォルダーを選ぶ。NASのUNCや割当ドライブを入力欄へ貼り付けてもよい。
2. 対象画像の一覧を表示。チェック欄で処理対象を選ぶ。全選択/全解除がある。
3. 用途は「Web掲載写真」「透過画像・図版」の二択。初期値は写真。quality、codec、ICC、metadata、workersは見せない。
4. 出力ルートを表示し、必要な場合だけ変更可能。
5. 「変換する」。処理中は二重実行を防ぎ、処理済み枚数/対象枚数を表示する。
6. 完了後は、成功枚数、うち警告枚数、失敗枚数、容量の前後、ファイルごとの結果を表示。
7. 今回の検証済み出力を表示する。部分失敗は赤字だけに頼らず「一部失敗。成功した画像のみ入っています」と示す。
8. 「今回の出力フォルダーを開く」。失敗画像はそのフォルダーに含めない。manifest確定に失敗した場合は通常の完了扱いをしない。

小さな縮小プレビューと画像を拡大して確認する操作までを上限とする。左右比較スライダー、自動選別、顔検出、crop、明るさ補正、施工前中後の分類、記事編集、ファイルのクラウド送信は作らない。

### 8.2 ローカル実行

- NiceGUIは `host='127.0.0.1'`、`show=True`、`reload=False` で起動。LAN公開や`on_air`は使わない。
- 起動中はそのWindowsユーザーの権限でNASを読む。管理者実行、NAS資格情報の入力・保存、共有権限変更は要求しない。
- ブラウザーのupload部品から元のNASパスを取得できる前提を置かない。Python側で実フォルダーを読む。フォルダー選択は標準OS機能かNiceGUI公式local-file-picker例に沿った小さなダイアログを使い、UNC貼り付けを併用する。
- CPUを使う変換でUIのイベントループを塞がない。実行はバックグラウンドのローカルスレッド等へ分離し、結果通知を安全にUIへ戻す。新しいサーバー/キューは不要。
- ブラウザータブを閉じても原本は変わらず、Pythonプロセスが続いていれば開始した実行は完了できる。プロセス終了・NAS切断時は未検証の候補を成功として扱わない。再起動後は再実行可能。
- ブラウザーへの画像提供は今回選択した画像/今回の結果に限定し、NAS全体を静的ディレクトリとして公開しない。外部Originからファイル操作が起動できるAPIを追加しない。

### 8.3 配布

- `gui` extraにNiceGUIを追加。既存CLIの利用者にGUI依存を強制しない。
- SEが`uv sync --project media-shrink-tool --extra gui --extra dev`等で検証済み環境を準備する。
- 担当者は`media-shrink-tool/run-web-public.cmd`をダブルクリックして使える。起動スクリプトは自身の位置から作業ディレクトリを解決し、空白/日本語のパスに対応する。検証済み`.venv`のPython等を呼び、起動のたびに依存を自動更新・取得しない。
- 未セットアップ/ポート競合/uvやPythonの未検出は、日本語の簡潔なエラーとSE向け準備手順を出す。`0.0.0.0`へ切り替えたり、Windowsの実行ポリシーを広く緩めたりして回避しない。
- NAS上の入力/出力を実Windowsで検証する。利用可能でなければ未実行と記録し、Linux上のPathテストで代替済みとはしない。

## 9. 実装順と受入テスト

各段階で、意味のある失敗テスト→最小実装→そのテストの通過を確認する。テスト追加自体を目的にしない。

### 第1段階: 変換コアと公開用の契約

変更/追加: `web_public.py`、必要最小限の共通helper、新規`test_web_public.py`。

必須テスト:

| テスト名の例 | 必須の確認 |
|---|---|
| `test_width_cap_after_orientation` | 4.2の寸法表、Orientation 2〜8の向き/反転、拡大なし。縦写真を長辺1400へ縮めない |
| `test_photo_and_graphic_outputs` | 実JPEG/PNG、写真quality/subsamplingの設定、PNGのalpha、全不透明RGBAは写真可、透明写真は拒否 |
| `test_public_metadata_allowlist` | EXIF GPS、XMP、IPTC/comment、PNG textを持つ入力から新規sRGB以外を持ち出さない。`karufile:image-`が出力metadataに存在しない |
| `test_srgb_conversion_and_rejection` | 有効ICCからの変換、ICCなしsRGB仮定の記録、破損ICC/未知CMYK/明示HDRでエラー。色タグを書いただけの実装を通さない |
| `test_bad_candidate_not_published` | エンコーダ失敗、禁止metadataが混入した保存候補、破損入力で確定しない。原本不変 |
| `test_independent_files_continue` | 1枚失敗しても別の正常画像が完成。混合結果は終了1に対応 |
| `test_limits_and_non_images` | 画素/容量上限、複数フレームの扱い、PDF/Excel/動画が呼ばれない |

合成画像は向き・alpha・metadata検査向け。圧縮画質は一色の合成画像だけで判定しない。Pillow/LittleCMS/pillow-heifの版依存の内容は実行環境で確認する。

### 第2段階: バッチ・manifest・CLI

変更/追加: `cli.py`、新用途のmanifest処理、`test_web_public_cli.py`。

必須テスト:

- 実際のCLIサブプロセスで写真/図版を変換できる。`--file`指定外は出力しない。
- dry-run前後で原本、既存出力、manifest、ディレクトリが変化しない。
- 同一・親子の入出力、危険なlink、ルート外の選択/manifest参照を拒否。
- 同名ファイルが異なる入力サブフォルダーにあっても衝突せず、完成名に元案件名が出ない。
- 同一sourceとrecipeで再実行すると、エンコーダを呼ばず、前回のバイト列と一致する完成画像を新runへ用意できる。
- sourceを同サイズ/同mtimeで変更、outputを改変、recipe/engineを変更した場合は誤再利用しない。
- 旧marker付き画像を入力しても、markerだけで変換を省略しない。
- 前回manifestがない/破損していても原本から再生成できる。
- manifest確定失敗、入力途中変更、NAS相当のI/Oエラーを成功扱いしない。前回の正常データを破壊しない。
- 今回の出力フォルダーへ前回の画像や失敗した原本が混入しない。
- 終了0/1/2と件数表示が一致する。

### 第3段階: GUI・Windows起動

変更/追加: `gui.py`、gui extra/lock、`run-web-public.cmd`、`test_web_public_gui.py`。

- GUIで選んだ用途・チェック対象がコアへ一致して渡る。
- 2枚以上の正常画像と1枚の不正画像で、件数・進捗・部分失敗・今回出力の案内を確認。
- 変換中の二重クリックで二重実行しない。大きな画像の処理中もUIが応答する。
- 127.0.0.1へのbind、通常CLIではNiceGUIをimportしないこと、起動用cmdのパス引用を確認。
- Windowsの日本語/空白パス、UNC入力・UNC出力・割当ドライブ、NAS切断を実機で確認できる範囲で実施。

### 第4段階: 回帰・実写真・文書

リポジトリ直下で実行するコマンド例。新しいCLI/GUIを実装した後の検証コマンドである。

```powershell
uv run --project media-shrink-tool --extra dev --extra gui python -m pytest -q media-shrink-tool/tests
uv run --project media-shrink-tool python -m compileall -q media-shrink-tool/src media-shrink-tool/tests
uv run --project media-shrink-tool python -m media_shrink resize --help
uv run --project media-shrink-tool python -m media_shrink web-public --help
uv run --script karufile.py --help
git diff --check
```

`AGENTS.md`の検証方針と変更範囲を照合する。orchestrator/common helperへ影響する変更があれば、既存`test_image_contract.py`・`test_output_formats.py`に加え、影響するorchestrator検証を実施する。既に失敗していたものは今回の回帰と区別する。関係ないPDF等を修正してPASSにしようとしない。共有境界を変えた場合に必要な回帰確認を省略しない。

実写真は、利用許可済みのローカル素材からまず10〜15枚程度でよい。金網、植生、岩肌、遠景、看板の文字、縦写真、HEIC、透過イラスト、線/文字の図版を含める。NAS外や外部APIへ送らない。入力→JPEG/PNGマスターの見た目、処理時間、容量を記録する。実素材が利用できなければ合成画像テストを完了し、画質・NASの実機確認は未実行と明記する。資料不足を理由に動作実装全体を止めない。

AstroでのAVIF/WebP最終表示確認は後段の受入項目。KaruFileリポジトリへAstro/Sharp/Nodeの実行依存を追加して再現環境を新設しない。既に使用可能な連携環境があれば、許可範囲の確認だけ行い、未実行ならサイト担当へ引き継ぐ。

## 10. 完成条件・報告

完成条件は「画像専用CLIとGUIが同じ処理を使い、原本を保全しながら、幅1400以内・公開用metadata方針・色/alphaの契約を満たす掲載用マスターを、事務員が取り出せる」こと。

次を短く報告する。

1. 変更ファイル、実装したCLI/GUI、既存仕様を保持した範囲。
2. 実際に使える起動・変換コマンド。ダミーAPIやTODOのみを完成扱いしない。
3. 実行したテストと結果。未実行のWindows/NAS/実写真/最終AVIF-WebP表示は別記。
4. 既存不具合と今回の未解決事項を分ける。GUIのデモ画面だけで完了としない。
5. commit/push/公開はしていないこと。

## 11. サイト担当へ渡す境界情報（今回の変更対象外）

- KaruFileの成果物はJPEG/PNGマスター。これを素材として、Astro/SharpでAVIFとWebPを独立生成する。
- 写真のHTMLはAVIFの`source`、WebPの`img`を基本とする。JPEG/PNGフォールバックを生成・参照しない。Astroの`Picture`を使うなら`formats={['avif']}`と`fallbackFormat="webp"`のようにWebPを最終画像へ指定する。
- 1400px上限を超える派生画像やDPR倍率の画像を自動生成せず、入力寸法を超えて拡大しない。
- 公開HTML/CSS/JS/JSON・一覧/デフォルト画像にも、元のファイル名、NASパス、manifest、未公開データを持ち出さない。
- 図版は可読性とalphaを優先する。AVIFを第一候補にすることが画質確認で不適切なら、その図版はWebP losslessで配信する。数値のqualityを異なるcodec間の同等画質として扱わない。
- 公開前プレビューの仕組み、本番とマスター保管先の認証、OGP、既存画像移行はサイト担当の作業であり、この実装へ追加しない。

## 12. 参照根拠

以下は現行実装・ライブラリ機能の根拠。`web-public`の新規仕様、quality、制限値、ディレクトリ構成は本指示で決めた実装方針であり、これらの資料が既に実装を提供しているという意味ではない。

- KaruFile基準コード: `https://github.com/tsutomu-n/KaruFile/tree/bc88f56a6aadeaa11b0cd6687c45e113ce539547/media-shrink-tool`
- KaruFile既存規約: `https://github.com/tsutomu-n/KaruFile/blob/bc88f56a6aadeaa11b0cd6687c45e113ce539547/AGENTS.md`
- Pillowの形式・出力設定: `https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html`
- Pillow ImageCms: `https://pillow.readthedocs.io/en/stable/reference/ImageCms.html`
- pillow-heif入力情報: `https://pillow-heif.readthedocs.io/en/stable/reference/HeifImagePlugin.html`
- NiceGUI起動: `https://nicegui.io/documentation/run`
- NiceGUI local file picker例: `https://github.com/zauberzeug/nicegui/tree/main/examples/local_file_picker`
- AVIF/WebPのブラウザー対応・透過: `https://developer.mozilla.org/en-US/docs/Web/Media/Guides/Formats/Image_types`
- Astro Picture/fallbackFormat: `https://v5.docs.astro.build/en/reference/modules/astro-assets/`

参照先の最新版とlock済み版のAPI差は、ローカルの依存版を優先して確認する。ネット上の最新サンプルを理由にPillow/Python/既存依存を一括更新しない。
