# KaruFile 利用者マニュアル

この文書は、KaruFileを初めて使う人のための正本です。上から順に進めると、準備、
dry-run、本実行、結果確認まで完了できます。

KaruFileは、フォルダー内のPDFと対応形式の画像、compact presetでは対応動画も再帰的に探し、
別のフォルダーへ軽量化するWindows向けCLIです。CLIは、PowerShellへコマンドを入力して使う
形式です。入力原本は変更・削除しません。

基本操作は「実行前に確認すること」から「終了コードとエラー確認」までを順に読んでください。
数値、status、再利用条件、個別CLIは [技術リファレンス](docs/REFERENCE.md)、処理全体の関係は
[実行時アーキテクチャ](docs/architecture/karufile-runtime.compact.html)から確認できます。

## 実行前に確認すること

次の4点を確認してから実行してください。

1. 入力とは別の出力フォルダーを使います。入力と出力に、同じフォルダーや互いに
   親子となるフォルダーは指定できません。
2. `--dry-run`でも、PDF状態DB、判定レポート、画像エラーCSV、画像dry-run manifestは
   更新される場合があります。
   compact動画はdry-runレポートを更新し、空の状態領域を初期作成する場合がありますが、
   通常実行の成功記録は読み書きしません。
   完成したPDF・画像・動画は作りません。
3. 画像のメタデータを削除する機能ではありません。GPSを含む情報が出力に残る場合があります。
4. 処理中の入力ファイルはロックしません。別の処理から同時に入力を更新しないでください。

PDF、対応形式の画像、compactで探索する対応動画以外のファイルは、出力フォルダーへ
コピーしません。standardでは動画を探索・コピーせず、従来のPDF・画像動作を維持します。

### プリセットを選ぶ

| 項目 | `standard`（既定値） | `compact` |
|---|---|---|
| 画像 | 長辺1280px・短辺960px以内、quality 72 | 長辺1024px・短辺768px以内、quality 60 |
| PDF配置画像 | 300 DPI目標、JPEG候補quality 92 | 同じ300 DPI目標、quality 80。既存JPEGの同寸法再圧縮も候補化 |
| 動画 | 探索・コピーしない | 対応する構成だけAV1へ変換し、複雑・未対応の構成は原本コピー |

まず使うプリセットを選び、同じプリセットでdry-runと本実行を行ってください。
compactの方が必ず小さくなるとは限りません。PDFと動画は候補の検証・削減条件により
原本を採用することがあります。両プリセットの結果を比較するときは別の出力先を使います。

### 写真PDFの閲覧用コピーを作る

写真の細部の劣化を許容できるPDFだけ、`--pdf-photo-pattern`で明示的に選べます。
一致するPDFには`photo` profileを適用し、対象JPEGの200 DPI目標・quality 80の縮小候補を作ります。
指定しないPDFは選択した`standard`または`compact`のままです。単独画像・動画の設定は変わりません。

```powershell
uv run --script karufile.py -i "D:\作業\資料" -o "D:\作業\閲覧用\資料_軽量化" --pdf-photo-pattern "2.現地写真*.pdf" --pdf-photo-pattern "5.採取写真*.pdf" --dry-run
uv run --script karufile.py -i "D:\作業\資料" -o "D:\作業\閲覧用\資料_軽量化" --pdf-photo-pattern "2.現地写真*.pdf" --pdf-photo-pattern "5.採取写真*.pdf"
```

パターンは入力フォルダーからの相対パスです。大文字小文字を区別せず、`/`と`\`を同じ区切りと
みなします。`*`はサブフォルダーの区切りにも一致するため、`*.pdf`は全PDFを選びます。
絶対パス、空のパターン、`..`を含むパスは使えません。複数選ぶときはオプションを繰り返します。

写真かどうかは自動分類しません。図面、黒板の小さい文字、顕微鏡写真などの細部を保護する必要が
あるPDFを一括指定しないでください。300 DPI以下を「OCR不要」と判断する機能でもありません。
dry-runのPDFレポートで`profile`が`photo`になった対象を確認し、本実行後は文字や細部を原本と
見比べてください。画質検証はありますが、可読性やOCR精度を保証しません。

## 必要なもの

- Windows
- Python 3.13以上
- [uv](https://docs.astral.sh/uv/)

PDFを含む通常実行ではqpdfを使用します。KaruFileは `PATH` とローカルキャッシュから
qpdfを探し、見つからない場合はqpdf 12.3.2のWindows向け配布ZIPをGitHub Releasesから
取得します。初回実行時に取得が必要になる場合があります。PDFを含まない実行と
`--dry-run` ではqpdfを使用しません。

JPEG画像の解像度を変えない追加最適化は、`--pdf-lossless-jpeg`で有効にできます（既定OFF）。
[公式libjpeg-turbo 3.2.0 Windows x64配布物](https://github.com/libjpeg-turbo/libjpeg-turbo/releases/tag/3.2.0)を
手動で準備し、公式配布物のSHA-256とWindows署名を確認してください。自動取得・インストールはしません。
`jpegtran.exe`と同梱DLLの配置を維持し、明示パスまたはPATHを使います。

```powershell
uv run --script karufile.py -i "D:\作業\資料" -o "D:\作業\JPEG検証\資料_軽量化" --pdf-lossless-jpeg --pdf-jpegtran-path "C:\Tools\libjpeg-turbo\bin\jpegtran.exe"
```

パス指定だけでは有効になりません。有効時にツールが見つからない、または3.2.0でない場合はPDF処理開始前に
エラーとなります。dry-runではツールを探索・実行せず、要求設定だけをCSVへ記録します。
この指定は可逆候補を追加します。presetや写真指定による既存の非可逆候補も比較対象に残るため、
「完成出力は必ず可逆」を意味しません。可逆処理だけが必要な場合はPDF個別CLIの`--safe --lossless-jpeg`を使います。

compactで動画を処理する場合は、`ffmpeg` と `ffprobe` が `PATH` に必要です。KaruFileは
これらを自動取得・同梱しません。別の実行ファイルを使う場合は `--ffmpeg-path` と
`--ffprobe-path` で指定できます。利用するFFmpeg buildにはSVT-AV1、AAC、Opus、libvmaf、
scale/fps filter、MP4/Matroska/WebM muxerが必要です。不足は処理開始時にエラーとして検出します。

動画の`--dry-run`ではffprobeだけを使い、FFmpegのencoder/filterや実際の圧縮品質は検証しません。
compactでも対象動画がなければFFmpeg/ffprobeは使いません。

## 基本手順

### 1. PowerShellでリポジトリを開く

以降のコマンドは、`karufile.py` があるKaruFileリポジトリの直下で実行します。

### 2. 初回だけ依存関係を準備する

```powershell
uv sync --project pdf-shrink --dev
uv sync --project media-shrink-tool
```

compactで動画も処理する場合は、追加で動画コンポーネントを準備します。

```powershell
uv sync --project video-shrink
```

これらは各コンポーネントのPython環境を準備するコマンドです。FFmpeg/ffprobeは含まれません。

### 3. 入力と出力を決める

このマニュアルでは、次のフォルダーを例にします。

| 用途 | フォルダー |
|---|---|
| 入力 | `D:\作業\資料` |
| 出力 | `D:\作業\資料_軽量化` |

`-o`を省略すると、入力と同じ階層の `<入力フォルダー名>_軽量化` を使います。

### 4. dry-runで対象を確認する

```powershell
uv run --script karufile.py -i "D:\作業\資料" -o "D:\作業\資料_軽量化" --dry-run
```

`--dry-run`の短縮形は `-n` です。dry-runでは、対象の検査と処理方法の判定を行います。
完成したPDF・画像・動画は作りませんが、状態DBとレポートは更新される場合があります。
圧縮後のサイズや品質、通常実行の成功を保証する検査ではありません。

compactのPDF・画像・動画候補を確認する場合:

```powershell
uv run --script karufile.py --preset compact -i "D:\作業\資料" -o "D:\作業\資料_軽量化" --dry-run
```

### 5. 本実行する

```powershell
uv run --script karufile.py -i "D:\作業\資料" -o "D:\作業\資料_軽量化"
```

出力を既定値にする場合:

```powershell
uv run --script karufile.py -i "D:\作業\資料"
```

compactを選んだ場合は、上のstandard実行に代えて次を実行します:

```powershell
uv run --script karufile.py --preset compact -i "D:\作業\資料" -o "D:\作業\資料_軽量化"
```

通常実行では確認入力を求めません。PDF、画像、compactの場合は動画の順に処理します。
1つが失敗しても、可能な範囲で他のprocessorを処理します。

### 6. 結果を確認する

終了時の統合サマリーを確認します。

PowerShellでは、実行コマンドの直後に`$LASTEXITCODE`を入力すると終了コードを確認できます。

| 表示 | 意味 |
|---|---|
| `PDF errors` | PDFの失敗件数 |
| `Image errors` | 画像の失敗件数 |
| `Video errors` | compact動画の失敗件数 |
| `Original size` | 処理結果から集計した入力サイズ |
| `Output size` | 処理結果から集計した出力サイズ |
| `Saved` | 削減できたサイズ |
| `Reduction` | 削減率 |
| `Source files changed: NO` | 起動前と終了時のidentity・SHA-256検査で入力変更を検出しなかったこと |
| `Files deleted: 0` | 入力を削除していないこと |

正確な値を取得できなかった項目は `unknown` と表示します。dry-runでは完成出力を
作らないため、出力サイズ、削減量、削減率を計算しません。
`Source files changed: YES OR COULD NOT VERIFY` の場合は入力の変更または検証不能を表し、
他の集計値も `unknown`、終了コードは `1` になります。

PDFが`UNCHANGED`になった場合はPDFサマリーの理由別件数と、`report.csv`の`decision_reason`を
確認します。`candidate_not_smaller`は候補が小さくならなかった、`reduction_below_threshold`は
削減基準未達、`quality_rejected`は画質検証による棄却、`no_image_savings`は画像候補が採用されず
画像の書き換えがなかったことを表します。`candidate_size`は最初に試した
候補のサイズで、完成出力の`output_size`とは異なります。可逆候補への切り替えも含む全履歴は
`candidate_details`に残ります。詳細は[PDFレポートの診断列](docs/REFERENCE.md#pdfレポートの診断列)を参照してください。

## 出力とレポートの場所

入力内の相対フォルダー構造は、出力内でも維持します。前の例では、保存先は次のとおりです。

| 内容 | 保存先 |
|---|---|
| 軽量化したPDF・画像・動画 | `D:\作業\資料_軽量化\` |
| 通常実行のPDFレポート | `D:\作業\report.csv` |
| dry-runのPDFレポート | `D:\作業\report.dry-run.csv` |
| PDFの再開状態 | `D:\作業\.pdf-shrink\state.sqlite3` |
| 画像エラーCSV | `D:\作業\資料_軽量化.image-errors.csv` |
| 通常実行の画像manifest | `D:\作業\資料_軽量化.image-manifest.csv` |
| dry-runの画像manifest | `D:\作業\資料_軽量化.image-manifest.dry-run.csv` |
| 通常実行の動画レポート | `D:\作業\資料_軽量化.video-report.csv` |
| dry-runの動画レポート | `D:\作業\資料_軽量化.video-report.dry-run.csv` |
| 動画の再開状態・一時領域 | `D:\作業\資料_軽量化.video-state\` |

PDFレポートと状態DBは、入力ではなく出力フォルダーの親へ保存します。PDFがない実行では、
PDFレポートと状態DBを作成・更新しません。以前の実行で同じ場所にあるファイルは削除しません。

複数の出力フォルダーが同じ親フォルダーにある場合、PDFレポートと状態DBは同じ保存先を
使います。PDFレポートは、現在の実行で選ばれた入力を対象に更新します。
実行を並行させる場合は、出力先だけでなくPDFの状態・レポートを置く親フォルダーも分けてください。

画像処理が起動し、CSVの更新に成功した場合、画像エラーが0件でもエラーCSVをヘッダーだけへ
更新します。全画像のpath、size、SHA-256、action、preset、recipe、処理前後の寸法は、通常実行と
dry-runを分けた画像manifestへ記録します。統合CLIはこのmanifestを現在の入力・出力と照合して
集計します。安全性検査、画像処理の起動、またはレポート更新に失敗した場合は終了コード `1` と
なり、以前のレポートが残ることがあります。

動画レポートと状態領域は、統合CLIでcompactを選び、対象動画がある場合だけ使用します。
standardの実行で過去の動画出力やレポートを削除することはありません。

### 再実行と結果の比較

再実行では、各処理の再利用条件を満たす完成済み出力を再利用し、それ以外は再評価します。
同じ出力先でプリセットを変えると、既存出力が新しい結果へ置き換わる場合があります。
以前の結果を残す場合は別の出力先を指定してください。PDFレポートも別々に残す場合は、
出力先の親フォルダーも分けます。

PDFの写真選択パターンを変えた場合も再評価します。候補診断と可逆候補への切り替えを導入した
この版では設定hashが変わるため、以前のPDF状態がある場合も一度再処理します。

画像の非JPEG入力は、元のファイル名全体へ`.jpg`を追加します（例: `photo.png` → `photo.png.jpg`）。
JPEG入力は`.jpg`または`.jpeg`を維持します。出力名が衝突する場合は名前を調整するため、
最終的な出力先は画像manifestの`output_path`で確認してください。

## 終了コードとエラー確認

| コード | 意味 |
|---:|---|
| `0` | 対象となったPDF・画像・動画のエラーが0件 |
| `1` | 1件以上の処理失敗、レポート更新失敗、結果不整合、または入出力の安全性検査失敗 |
| `2` | コマンド引数が不正 |

終了コードが `1` の場合は、次を確認します。

1. ターミナルのエラー表示
2. PDFレポートの `status` と `error_message`
3. 画像エラーCSVの `error`
4. 画像manifestの `action` と `error`
5. 動画レポートの `status`、`reason`、`error_message`

集計に必要なレポートが現在の入力と一致しない場合、KaruFileは過去の出力から
推測せず、該当値を `unknown` として終了コード `1` を返します。

## 処理される内容

### 画像

JPEG、PNG、TIFF、BMP、GIF、WebP、HEIC、HEIFをJPEGとして出力します。

- standardは長辺1280px・短辺960px以内、quality 72
- compactは長辺1024px・短辺768px以内、quality 60
- 縦横比を維持し、拡大・切り抜きなし
- EXIF Orientationを画素へ適用
- 透過部分を白背景へ合成
- animationと複数ページは先頭フレームだけを使用
- 印刷DPIへ合わせる変換ではない

情報が変わった場合はターミナルへ警告を表示します。警告だけなら終了コードは `0` です。
警告は画像エラーCSVへ保存しません。

### PDF

PDFの特性に応じてPyMuPDFまたはqpdfで候補を作り、検証と削減条件を満たした候補だけを
採用します。候補を採用しない場合や、安全上圧縮しない場合は原本を出力へコピーします。

写真選択のないPDFでは、ページ上の配置transformから軸別に見た画像実効解像度が300DPIを超える場合、その軸を
300DPI目標へ縮小します。この固定目標はstandardとcompactで共通です。compactではJPEG qualityを80とし、
300DPI以下の既存JPEGも寸法を下げず再圧縮候補にします。JPEGに埋め込まれた解像度
メタデータは使いません。拡大はしません。
ベクター文字はラスター化しません。1bit画像とsoft mask付き画像は縮小しません。
xrefを持たないinline画像がいずれかの軸で300 DPIを超えるPDFは、standard/compactで安全に画像を書き換えられない
ため、通常の統合CLIでは圧縮せず原本を採用します。PDF個別CLIの`--safe`による可逆処理は
継続できます。`--safe`は`karufile.py`のオプションではありません。

明示選択した`photo`では、単純なRGB・グレースケールの8bit JPEGだけを対象にします。
非JPEG、1bit、mask付き、複雑な色空間・色変換を使う画像や、画像参照の同定が曖昧な群は維持します。同じ画像が複数箇所で
使われる場合は最も低い実効DPIを軸ごとに基準とし、200 DPIを超える軸だけを約200 DPIへ縮小します。
200 DPI以下の軸は寸法を維持し、両軸に縮小余地のない画像は再圧縮しません。拡大もしません。
候補は元PDFの画像を書き換えて作り、ベクター文字や線を維持します。HTMLへの往復変換は行いません。

暗号化、電子署名、フォーム、添付ファイル、修復済みPDFなどは圧縮しません。通常実行では
原本を出力へコピーします。
添付ファイルまたは電子署名の有無を検査できないPDFも、安全側で
`SKIPPED_COMPLEX` として原本を採用します。

非可逆候補を作る場合は元PDFから可逆候補も作り、検証と採用条件を満たす最小の候補を選びます。
同サイズなら可逆候補を優先します。採用条件を満たす候補がなければ原本を採用します。
可逆候補は16 KiB以上かつ2%以上の削減が必要です。JPEG可逆を指定した場合の同サイズ優先順は
qpdf単独、JPEG baseline、JPEG progressive、非可逆です。JPEG候補は原寸画素と完成PDFの
描画一致を検査しますが、全ビューアーでの互換性やOCR精度を保証するものではありません。
ツール、構造検査、I/Oの失敗は`ERROR`であり、
回復コピーが成功しても成功扱いにしません。300 DPI・200 DPIは候補作成の目標であり、最終出力の
強制上限ではありません。

変換条件、採用基準、再利用条件、PDF status、全オプションは
[KaruFile技術リファレンス](docs/REFERENCE.md)を参照してください。

### 動画

動画は `--preset compact` のときだけ処理します。MP4、M4V、MKV、WebMのうち、単一映像、
8-bit SDR、progressive、固定frame rate、音声なしまたはmono/stereo 1本など、安全に扱える
構成だけを変換します。

- 1280×720以内、30fps以内。小さい動画は拡大しません
- 映像はSVT-AV1
- MP4/M4Vの音声はAAC、MKV/WebMの音声はOpus
- 全decode、duration・stream構成、VMAF、削減量を検証した候補だけ採用
- HDR、VFR、interlace、字幕、複数映像・音声、chapter等は変換せず原本を出力へコピー

FFmpegまたは候補検証が失敗した場合は他ファイルを継続しますが、該当行を `ERROR` として
終了コード `1` を返します。
出力が未作成なら原本の回復コピーを試みる場合がありますが、コピーが成功しても`ERROR`のままです。
ファイルが出力先にあることだけで成功と判断せず、終了コードと動画レポートを確認してください。

## 図で全体を確認する

[KaruFile実行時アーキテクチャ](docs/architecture/karufile-runtime.compact.html)は、利用者から
`karufile.py`、PDF・画像・動画処理、出力、状態・レポートまでの関係を示す対話型HTMLです。

PowerShellからローカルのブラウザで開く場合:

```powershell
Start-Process .\docs\architecture\karufile-runtime.compact.html
```

静止画は [light](docs/architecture/karufile-runtime.compact.visual-check.1440x900.light.png) と
[dark](docs/architecture/karufile-runtime.compact.visual-check.1440x900.dark.png) を用意しています。

## 対象外と確認済みの制約

KaruFileは、HDR/VFR/interlace/字幕/複数stream等を保持した動画変換、重複削除、
知覚ハッシュ、元ファイル削除、GUIを提供しません。
PDF処理は `pdf-shrink` だけが担当します。

現在確認できている未解決事項:

- 自動取得するqpdf配布ZIPのSHA-256または署名は検証していません。
- PDF表示検証はstandardで72 DPIグレースケール、compactで72 DPI RGBと局所差を使います。
  photoではこれに変更画像の配置領域を300 DPIでタイル比較する検査を追加しますが、細かい文字の
  可読性やOCR精度を保証しません。検査量の上限を超えた非可逆候補も採用しません。
- 処理中の入力はロックしません。KaruFileは起動前と全processor終了後に全対象のidentityと
  SHA-256を照合して変更を失敗として検出しますが、別プロセスによる変更そのものは防止しません。
- 自動テストは小さな合成データが中心で、今回の実装では実データPilotを実施していません。
- 動画のCFR判定はffprobeのrate比較による入口判定です。既知のHDR metadataは拒否しますが、
  metadataが欠けた動画のSDR性までは証明しません。VMAFは映像だけを評価し、30fps化の
  滑らかさと音声品質は測定しません。
- 動画のVMAF JSONは生成後に64 MiB上限を検査するため、異常なlibvmaf実行中の一時領域消費を
  事前停止できません。
- 完了済み動画の再利用時は、保存したsource/config/tool versionと出力hashを照合しますが、
  full decodeとVMAFを再実行しません。動画stateを手動編集した疑いがある場合は
  `<output>.video-state` を別名へ退避してから再実行してください。

代表的な実データでのPilotを行わずに、スキャン判定、削減率、表示差分の既定値が実際の
文書群に適するとは確認できません。
