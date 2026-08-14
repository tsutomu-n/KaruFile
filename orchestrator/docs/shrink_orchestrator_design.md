# shrink_orchestrator 設計書

## 1. 目的

`pdf-shrink`（PDF 軽量化）と `media-shrink-tool`（画像リサイズ）を 1 回のコマンドで連続実行し、混在したメディアフォルダー（PDF + 画像）をまとめて軽量化する。

## 2. 配置

- 設計書: `orchestrator/docs/shrink_orchestrator_design.md`
- 実装: `orchestrator/shrink_all.py`（サードパーティ依存を持たない単一ファイル、PEP 723）
- 呼び出し対象（リポジトリ直下、環境変数 `PDF_SHRINK_ROOT` / `MEDIA_SHRINK_ROOT` で上書き可）:
  - `<repo>/pdf-shrink`
  - `<repo>/media-shrink-tool`

## 3. CLI インターフェース

```
uv run --script orchestrator/shrink_all.py \
  -i "C:\Users\tn\Downloads\安全会議資料および議事録\安全会議資料および議事録" \
  [-o "C:\Users\tn\Downloads\安全会議資料および議事録\安全会議資料および議事録_軽量化"] \
  [--pdf-workers 2] \
  [--image-workers 4] \
  [-n] \
  [-v]
```

| オプション | 説明 |
|---|---|
| `-i`, `--input` | 入力ディレクトリ（必須） |
| `-o`, `--output` | 出力ディレクトリ（未指定時は `<input>_軽量化`） |
| `--pdf-workers` | `pdf-shrink` の並列数（デフォルト 2） |
| `--image-workers` | `media-shrink-tool` の並列数（デフォルト 4） |
| `-n`, `--dry-run` | 書き込みせず計画のみ確認 |
| `-v`, `--verbose` | 詳細ログ |

## 4. 処理フロー

1. **入力検証**
   - 入力ディレクトリの存在確認
   - 対象ファイルの粗略カウント（PDF / 画像）

2. **PDF 軽量化**
   - `pdf-shrink` をサブプロセスで実行
   - コマンド: `uv run --project <pdf-shrink> python -m pdf_shrink run --input <input> --output <output> --workers <n>`
   - 結果は `<output_parent>/report.csv` に保存される

3. **画像リサイズ**
   - `media-shrink-tool resize` をサブプロセスで実行
   - コマンド: `uv run --project <media-shrink-tool> python -m media_shrink resize -i <input> -o <output> -j <n>`
   - 出力は `<output>` 内に元のディレクトリ構造を維持して配置される

4. **結果集計**
   - PDF: `report.csv` をパース
   - 画像: 入力画像の合計サイズと出力 `.jpg` の合計サイズを比較
   - 両方を足した総合サマリーを表示

5. **終了コード**
   - `pdf-shrink` と `media-shrink-tool` 両方が正常終了したら `0`
   - いずれかが失敗したら `1`

## 5. 出力戦略

- PDF と画像の両方を **同じ出力ディレクトリ** にミラー配置する。
- これにより、軽量化済みファイルが 1 箇所にまとまり、運用が簡潔になる。
- `pdf-shrink` のデフォルト出力先 (`<input>_軽量化`) に合わせる。

## 6. エラー処理

- 各ステップを `subprocess.run(..., check=False)` で実行。
- PDF 失敗でも画像処理に進み、逆も同様。
- 最後に両方の成否を表示。
- ツール内部で発生したエラーは、ツール自体がログ/レポートに記録する。

## 7. 状態管理・再実行

- PDF: `pdf-shrink` 内の SQLite 状態 DB (`<output_parent>/.pdf-shrink/state.sqlite3`) により、変更のないファイルは自動スキップされる。
- 画像: `media-shrink-tool` は現時点で状態 DB を持たないため、再実行時はすべて再処理する。これを回避するには将来 `shrink-orchestrator` 側で簡易な JSON 状態ファイルを追加することを検討する。

## 8. レポート

- コンソールに統合サマリーを表示。
- PDF 詳細は `pdf-shrink` が生成する `report.csv` を参照。
- 画像詳細は標準出力のサマリーを参考にする。

## 9. 拡張性

- 動画や重複削除を追加する場合は、`media-shrink-tool` の `video` / `dedup` サブコマンドを同様に呼び出す段を追加する。
- 設定ファイルを導入する場合は、TOML/JSON を読み込み、各ツールの設定を注入する。

## 10. 制約事項

- ツールは uv 経由で呼び出すため、実行環境に `uv` と両プロジェクトの `.venv` が必要。
- 画像処理は全て `.jpg` へ変換される。元の `.png` などが透過を必要とする場合は別途対応が必要。
- `media-shrink-tool` が HEIC/HEIF を処理できるかは `pillow-heif` の有無に依存する。
