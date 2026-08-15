# KaruFile orchestrator

`pdf-shrink` と画像専用の `media-shrink-tool` を順番に実行し、結果を KaruFile の開始・終了表示へまとめる薄い統合 CLI です。処理ロジックや共通 DB は持ちません。

利用者は Repo ルートの `karufile.py` を通常入口として使います。

```powershell
uv run --script karufile.py -i "D:\資料" [-o "D:\資料_軽量化"] [-n] [-v]
```

| オプション | 説明 |
|---|---|
| `-i`, `--input` | 入力ディレクトリ（必須） |
| `-o`, `--output` | 出力ディレクトリ（省略時は `<input>_軽量化`） |
| `--pdf-workers` | `pdf-shrink` の並列数（既定 2） |
| `--image-workers` | 画像 processor の並列数（既定 4） |
| `-n`, `--dry-run` | 完成出力を作らず判定を確認 |
| `-v`, `--verbose` | 詳細ログ |

resolve 後の input/output が同一または親子関係なら、processor 起動前に終了コード `1` で拒否します。PDF を先、画像を後に処理し、片方が失敗しても可能な範囲で他方を実行します。どちらかの終了コードが非0なら KaruFile は `1` を返します。

呼び出し先は既定で Repo 直下の `pdf-shrink/` と `media-shrink-tool/` です。開発・検証時だけ環境変数 `PDF_SHRINK_ROOT` / `MEDIA_SHRINK_ROOT` で差し替えられます。

画像エラーの詳細は `<出力フォルダー>.image-errors.csv`、PDF の詳細は `pdf-shrink` の CSV を参照してください。入力原本は変更・削除しません。

## 開発と検証

```powershell
Push-Location orchestrator
uv run --with pytest python -m pytest -q
Pop-Location
uv run --script karufile.py --help
```
