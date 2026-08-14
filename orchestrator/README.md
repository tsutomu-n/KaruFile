# shrink-orchestrator

`pdf-shrink` と `media-shrink-tool` を1回のコマンドで連続実行し、PDF・画像が
混在するフォルダーをまとめて軽量化するオーケストレータです。各ツールを
`uv run --project` 経由でサブプロセス実行し、結果を統合サマリーとして表示します。

サードパーティ依存を持たない単一ファイルスクリプト（[PEP 723](https://peps.python.org/pep-0723/)
インラインメタデータ付き）です。専用の `.venv` や `uv.lock` は不要です。

設計の詳細は [`docs/shrink_orchestrator_design.md`](docs/shrink_orchestrator_design.md)
を参照してください。

## 必要環境

- リポジトリ直下に `pdf-shrink/` と `media-shrink-tool/` が存在すること
- 各プロジェクトで `uv sync` 済みであること
- `uv` がPATH上にあること

## 実行

```powershell
uv run --script orchestrator/shrink_all.py -i "C:\...\入力フォルダー" [-o "C:\...\出力先"] [-n] [-v]
```

主なオプションは次のとおりです。

| オプション | 説明 |
|---|---|
| `-i`, `--input` | 入力ディレクトリ（必須） |
| `-o`, `--output` | 出力ディレクトリ（未指定時は `<input>_軽量化`） |
| `--pdf-workers` | `pdf-shrink` の並列数（デフォルト 2） |
| `--image-workers` | `media-shrink-tool` の並列数（デフォルト 4） |
| `-n`, `--dry-run` | 書き込みせず計画のみ確認 |
| `-v`, `--verbose` | 詳細ログ |

呼び出し先プロジェクトのパスは環境変数 `PDF_SHRINK_ROOT` / `MEDIA_SHRINK_ROOT`
で上書きできます（未指定時はリポジトリ直下の `pdf-shrink` / `media-shrink-tool`）。

## 開発と検証

```powershell
cd orchestrator
uv run --with pytest pytest -q
```
