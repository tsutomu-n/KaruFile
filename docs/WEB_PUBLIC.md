# Web掲載用マスターの用途と処理の流れ

`web-public`は、選別・編集済みの写真や図版から、ホームページ入稿用のJPEG/PNGマスターを作る機能です。
画像専用CLIと日本語のローカルGUIが同じ変換処理を使います。入力原本を残し、今回の完成画像を別フォルダーへ保存します。

この文書は機能の位置付けと仕組みを説明します。
準備・操作・入稿前の確認事項は[利用者マニュアル](../MANUAL.md#web掲載用マスターを作る)、
数値・引数・保存契約は[技術リファレンス](REFERENCE.md#web-public掲載用マスター)が正本です。

## 通常圧縮との使い分け

| 比較点 | 通常の画像圧縮 | Web掲載用マスター |
|---|---|---|
| 主な用途 | 資料の保存・共有に向けた軽量化 | ホームページへの入稿素材の作成 |
| 入口 | root CLIまたは画像CLIの`resize` | 画像CLIの`web-public`、または日本語GUI |
| 寸法 | standardは長辺1280・短辺960、compactは長辺1024・短辺768 | 向き補正後の横幅最大1400px |
| 出力 | JPEG・PNG・WebPを選択 | 写真はJPEG品質90・4:4:4、図版は透過対応PNG |
| 色・metadata | 通常画像の保持方針、EXIF除去は任意指定 | 8bit sRGBへ変換し、入力由来のmetadataを継承しない |
| 出力名・配置 | 入力の相対ディレクトリを保持 | 中立名を新しい実行フォルダーへflatに配置 |
| 再利用の記録 | 通常画像のCSV manifestとmarker | 独立した社内用JSON manifest |
| dry-run | 完成画像を作らず、レポートは作成・更新する | 出力フォルダー・画像・manifest・レポートの書込みなし |

`web-public`はroot CLIのpresetには追加していません。PDF・Excel・動画のprocessorは呼び出しません。
写真は二次生成元としての品質を優先し、原本より容量が増えても条件を満たす画像を採用して警告します。

## GUIとCLIから完成画像まで

1. **対象を選ぶ。** GUIは入力フォルダーの一覧からチェックした画像を渡します。
   CLIは繰り返し指定できる`--file`で完全な入力相対名を選び、省略時は画像を再帰列挙します。
2. **入力を確かめる。** パス、実際の画像形式、容量・画素数、フレーム数、色情報を検査し、原本のSHA-256等を取得します。
3. **画素を整える。** 向きを一度だけ補正し、有効ICCがあればLittleCMSでsRGBへ変換します。
   透過を分離して保持し、拡大・切り抜きなしで横幅を最大1400pxへ縮小します。
4. **完成候補を検証する。** 新しい画素コンテナからJPEG/PNGを保存し、再読込みで形式・寸法・色・metadata等を確認します。
   原本と設定、前回出力が一致する場合は、検証済みの前回画像を再エンコードせず新しい実行へコピーします。
5. **画像と記録を確定する。** 原本の途中変更と保存先を再確認して画像を確定し、最後に全成功結果を照合してmanifestを原子的に更新します。
   GUIとCLIは構造化結果から成功・警告・失敗を表示します。

幅800×高さ2400の縦画像は800×2400のままです。「横幅1400」を長辺の上限として扱いません。
詳細な丸め規則・限度・対応形式は[固定recipeと入力](REFERENCE.md#固定recipeと入力)を参照してください。

## 今回の成果物と再実行

既定出力は入力の兄弟フォルダー`<入力名>_HP掲載用`です。

```text
写真_HP掲載用/
  manifest.web-public.json
  runs/
    <ランダムなrun-id>/
      files/
        img-<run-id>-0001.jpg
        img-<run-id>-0002.jpg
```

実行ごとに新しい`files`を作るため、前回画像と今回の選択画像を分けて取り出せます。
原本との対応関係はmanifestに保存します。manifestは入力名・ローカルパスを含む内部記録です。
入稿するものと保管するものの区別は[マニュアルの出力と注意事項](../MANUAL.md#出力と注意事項)を確認してください。

再利用は原本・前回出力のSHA-256、recipe、エンジン版、出力検証を根拠にします。
今回のrecipe v2ではBMPとExifの色検査を補強しており、v1の記録からは原本を再変換します。
過去のrunを上書き・自動削除する処理はありません。

1枚が失敗しても独立した画像は処理を続けます。失敗画像の原本を完成フォルダーへ代わりにコピーすることはありません。
manifestの確定失敗は実行失敗となり、前回のmanifestを保持します。
GUIでは通常の完了表示や「今回の出力フォルダーを開く」に進めません。

## ローカルGUIの動作

GUIは準備済みのWindows PCで`127.0.0.1:8080`に起動し、Python側で入力フォルダーを読みます。
NiceGUIは任意の`gui` extraとして導入します。通常の画像CLIにGUI依存を強制しません。
`run-web-public.cmd`は準備済み`.venv`のPythonを使い、起動時に依存を取得・更新しません。

変換はバックグラウンドで実行し、画面には処理済み枚数を表示します。
プレビューデコードは全タブ共通で同時1件とし、変換との重複も防ぎます。
再実行時や実行全体のエラー時には、前回の件数・容量・出力案内を消去します。
ブラウザーを閉じてもPythonプロセスが続いていれば開始済みの変換は継続します。

失敗の内部診断は起動端末へ出力し、処理段階と例外種別を記録します。
詳細は[追加の色情報検査と内部診断](REFERENCE.md#追加の色情報検査と内部診断)を参照してください。

## 実装の責務

| ファイル | 担当 |
|---|---|
| [cli.py](../media-shrink-tool/src/media_shrink/cli.py) | 引数、CLIの結果表示、終了コード |
| [gui.py](../media-shrink-tool/src/media_shrink/gui.py) | 日本語画面、実行状態、進捗・プレビュー・排他制御 |
| [web_public_batch.py](../media-shrink-tool/src/media_shrink/web_public_batch.py) | 選択、新run、再利用、manifestの検証・確定 |
| [web_public.py](../media-shrink-tool/src/media_shrink/web_public.py) | 固定recipe、色・向き・寸法の処理、候補検証、1画像の確定 |
| [file_identity.py](../media-shrink-tool/src/media_shrink/file_identity.py) | 通常resizeとweb-publicで共有するSHA・stat・処理中の原本変更検知 |

パス検査と一時保存には既存helperを使い、原本の変更検知だけを`file_identity.py`へ移しました。
このmoduleは画像変換やGUIに依存せず、旧`image.py`の名前・例外型と既存テストの呼出し互換を保ちます。
将来の別用途でも同じ原本検証を使える構成ですが、未使用のプラグインや汎用recipe/publish層は追加していません。
通常の`resize`を一度通してから公開用へ再圧縮する経路はありません。
全体の関係は[実行時アーキテクチャ](architecture/karufile-runtime.compact.html)でも確認できます。

## 検証済みの範囲と後段の作業

2026年10月8日の新規全回帰では、画像215件を含む全体1454件が成功し、既存4件はskipでした。
再利用時の読取りだけでatimeが変化し、前回画像を再エンコードしてしまう問題を合成画像で再現し、
SHAとstat署名の比較へ局所修正しました。recipe v2とmanifest schema1は維持しています。
source fingerprintの共通化前後で、同じ合成画像10枚の画素・寸法・色・metadata・manifestの意味が一致しました。
原本SHA、前回run、再利用バイト、dry-run、CLI終了コード、通常resizeも照合しました。
[今回の検証記録](validation/2026-10-08-web-public-pilot/README.md)に、実行コマンドと各検証の限界を記載しています。

Windows上のGUI操作、部分失敗、画面再読込み、プレビュー開閉の目視は
[2026-10-07の画面証拠](validation/2026-10-07-web-public/README.md)です。
今回GUIの自動テストは再実行しましたが、ブラウザー操作・OSフォルダー選択・Explorerの新規実機確認は行っていません。

実写真の画質・端末由来HEIC・実NASのUNC/割当ドライブ/切断・後段AVIF/WebPの最終表示は未検証です。
KaruFileが生成するのはJPEG/PNGマスターで、サイト側のAVIF/WebP生成・配信・公開操作は今回の機能に含みません。
実写真・NASが未提供のため`BLOCKED_REAL_PHOTOS` / `BLOCKED_REAL_NAS`、サイト側は`PENDING_DOWNSTREAM`です。
同じマスターからAVIF優先・WebP最終fallbackを検証する[下流引継ぎ資料](validation/2026-10-08-web-public-pilot/DOWNSTREAM_HANDOFF.md)を用意しました。
素材の編集と入稿前確認は[マニュアル](../MANUAL.md#web掲載用マスターを作る)に従って行います。
