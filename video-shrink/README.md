# video-shrink

KaruFile の独立した動画処理コンポーネントです。入力を変更せず、同じ相対パスを別の
出力ツリーへ公開します。FFmpeg/ffprobe は同梱・自動取得せず、`PATH` または明示パスの
外部実行ファイルを使います。

```powershell
uv run --project video-shrink python -m video_shrink run `
  --input "D:\input" `
  --output "D:\input_軽量化" `
  --preset compact `
  --workers 1
```

音声除去＋圧縮は上記に `--remove-audio`、厳格な入力形式判定は `--safe` を追加します。
統合CLIではそれぞれ `--video-remove-audio`、`--video-safe` です。どちらも既定OFFです。

## CLI

```text
run --input PATH --output PATH
    --preset {standard,compact}
    --workers N
    [--dry-run]
    [--safe]
    [--remove-audio]
    [--ffmpeg-path PATH]
    [--ffprobe-path PATH]
    [-v|--verbose]
```

- `standard`: 動画を再圧縮せず、通常実行では原本を原子的にコピーします。
- `compact`: 適格な動画だけを AV1 へ変換します。
- `--workers` の既定値は1です。複数指定時はファイル単位で並列処理します。
- dry-run は完成動画を作らず、通常実行の成功recordも読取り・上書きしません。初回は
  state workspace/空DBを作成する場合がありますが、処理結果はdry-runレポートだけへ記録します。

## compact の初期契約

対象拡張子は `.mp4`, `.m4v`, `.mkv`, `.webm` です。次を満たす入力だけを変換します。

- 非attached映像が1本
- 8-bit SDRのYUV 4:2:0。通常はfield_order/SAR情報の欠落とVFRを許容
- 音声は0本または1本、1～2 channel
- 字幕、data、attachment、chapterを含まない
- 回転は0/90/180/270度のみ

`--safe` で従来の厳格なprogressive/SAR 1:1/CFR明示判定を有効にします（既定OFF）。
`--remove-audio` は全音声を除去して圧縮します（既定OFF）。この場合、音声数とchannel数の
入力制限は適用しません。両オプションは併用可能でcompact専用、standardでは引数エラーです。
HDR、既知interlace、非正方SAR、字幕・複数映像等への対応は追加していません。
通常時も原本保護、保存先検査、出力構造・全decode・VMAF・削減条件は維持します。
VFRは公称fpsと平均fpsの大きい方を上限30fpsでCFR化し、フレームの複製・間引きがあります。
欠落SARは1:1として扱います。

映像は拡大せず1280x720以内、30fpsを超える場合だけ30fpsへ下げ、`libsvtav1`で
符号化します。表示方向の幅1280px・高さ720pxが上限で、縦1080x1920は404x720になります。
音声を残す場合、MP4/M4Vの音声はAAC、MKV/WebMはOpusです。複雑または未対応の入力は
音声除去なしなら原本をコピーし、音声除去指定時はERRORとします。

初期recipeはCRF 38→35→32、SVT-AV1 `preset=8` / `tune=0`です。音声はmono 64 kbps、
stereo 96 kbpsとし、AACは入力以下かつ最大48 kHz、Opusは48 kHzへします。VMAF
`vmaf_v0.6.1`を5 frameごとに評価し、mean 85以上かつ5 percentile 70以上、さらに入力より
1 MiB以上かつ10%以上小さい候補だけを採用します。containerと取得可能な各streamのdurationは
0.25秒以内で一致させます。これらは代表実データでのPilot調整前の初期値です。

候補はffprobe検査、全stream decode、duration・stream構成検査、VMAF、削減基準を
すべて通過した場合だけ`os.replace()`で公開します。VMAFは映像のみを評価し、fps低下や
音声品質を保証しません。

## 状態とレポート

```text
<output>.video-state\state.sqlite3
<output>.video-state\temp\
<output>.video-report.csv
<output>.video-report.dry-run.csv
```

レポートは現在の入力集合を1ファイル1行で原子的に更新します。`ERROR`が1件でもあれば
終了コード1です。FFmpeg/ffprobeの不足、encoder/filter不足、変換失敗を成功扱いしません。
音声除去なしで出力が未作成の失敗では原本の回復コピーを試みますが、その場合も`ERROR`のままです。
`--remove-audio` 時は未対応・品質不合格・削減不足も`ERROR`とし、有音コピーは作りません。
失敗時は既存出力を維持します。既存の有音ファイルが残っても無音化の成功ではありません。

statusは次の意味です。

- `ADOPTED`: 検証済みの圧縮候補を公開
- `UNCHANGED`: 品質または削減基準を満たさず原本をコピー
- `SKIPPED_STANDARD`: standardとして原本をコピー
- `SKIPPED_COMPLEX`: 複雑なstream構成などを検出し原本をコピー
- `SKIPPED_UNSUPPORTED`: 対応外の映像条件またはcontainerを検出し原本をコピー
- `SKIPPED_COMPLETE`: source/config/tool versionと出力hashが一致した完了済み結果を再利用
- `DRY_RUN`: 判定のみで完成動画を未作成
- `ERROR`: 処理失敗。既存出力は置換しない

CSVには少なくとも`source_path, source_size, output_size, saved_bytes, status,
error_message, preset`を含みます。状態の再利用判定にはsource/output SHA-256、設定hash、
FFmpeg/ffprobeのversionを使います。CSVは`safe`と`remove_audio`をtrue/falseで記録し、
両設定をprocessing hashに含めます。旧DBは保持し、旧hashの結果は再利用しません。
`SKIPPED_COMPLETE` の再利用時はfull decodeとVMAFを再実行しません。state/reportは利用者の
ローカル管理下にある信頼済みcacheとして扱います。手動編集または破損が疑われる場合は、
`<output>.video-state` を別名へ退避してから再実行してください。

## FFmpegの配布とライセンス

このprojectはFFmpeg/ffprobeのbinaryをdownload・同梱・再配布しません。利用するbuildの
license条件は、そのbuildで有効なcodec/libraryとconfigure optionに依存します。配布する
場合は[`ffmpeg -version`と公式Legalページ](https://ffmpeg.org/legal.html)を基に別途確認して
ください。本componentは実行時に利用したFFmpeg versionを状態DBとCSVへ記録します。

## 初版で残る判定上の制約

safe時のCFRはffprobeが報告する`r_frame_rate == avg_frame_rate`を保守的な入口条件にしています。
これは全frame timestampの均一性を数学的に証明するものではありません。既知のHDR/Dolby
Vision metadataは拒否しますが、metadataが欠けた入力のSDR性までは証明しません。またVMAFは
映像の平均値と5 percentileだけを検査します。音声channel数と予定sample rateは構造検査しますが、
bitrateはmono 64 kbps・stereo 96 kbpsへ設定し、音声の知覚品質は測定しません。
FFmpegのstdout/stderrは固定長tailだけをmemory保持しますが、VMAF JSONの
64 MiB上限は生成完了後の検査です。異常なlibvmafがvalidation timeoutまで一時領域を消費する
余地は残ります。

## 開発時の検証

```powershell
uv sync --project video-shrink --group dev
uv run --project video-shrink python -m pytest -q video-shrink/tests
uv run --project video-shrink python -m compileall -q video-shrink/src video-shrink/tests
uv run --project video-shrink python -m video_shrink --help
```
