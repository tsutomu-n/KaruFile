# shrinker

PDF・画像・動画などのメディアファイルを軽量化するツール群です。3つの独立した
`uv` プロジェクトから構成されます。

```text
shrinker/
├── pdf-shrink/        PDF一括軽量化CLI（PyMuPDF + qpdf + SQLite状態管理）
├── media-shrink-tool/ 画像・動画・PDFの一括圧縮＋重複削除CLI
├── orchestrator/      pdf-shrink と media-shrink-tool を1回のコマンドで実行する統合CLI
└── .devin/            Devin CLI のローカル設定
```

各プロジェクトの詳細は、それぞれの `README.md` を参照してください。

- [pdf-shrink/README.md](pdf-shrink/README.md)
- [media-shrink-tool/README.md](media-shrink-tool/README.md)
- [orchestrator/README.md](orchestrator/README.md)

## 統合実行（PDF + 画像をまとめて軽量化）

```powershell
uv run --script orchestrator/shrink_all.py -i "C:\...\入力フォルダー"
```
