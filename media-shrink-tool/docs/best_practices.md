# Media Shrink Tool — ベストプラクティス調査（2026年8月）

## 1. 言語選定：なぜ Python か

今回のような「画像・動画・PDF のバッチ変換＋重複削除」を**一発で**行うツールには **Python** が最適です。

| 観点 | Python | Go | C# |
|---|---|---|---|
| 画像処理ライブラリ | Pillow / pillow-heif / imagehash など充実 | 外部コマンド頼みが基本 | 外部ライブラリの組み合わせが必要 |
| 動画圧縮 | `imageio-ffmpeg` で ffmpeg を自動導入・呼び出し | ffmpeg 呼び出しのみ | ffmpeg 呼び出しのみ |
| PDF 圧縮 | pikepdf / PyMuPDF / Ghostscript 呼び出し | ラッパーが少ない | 有償/外部コンポーネントが多い |
| CLI 生産性 | 高い | 高い | 中程度 |
| Windows 対応 | 良好 | 良好 | ネイティブに強い |

**結論**: 今回はバッチ処理なので Python。後から Windows GUI を被せたい場合は Python でコアを作り、C# / WinUI で画面だけ作る構成が現実的です。

## 2. プロジェクト構成の推奨

```text
media-shrink-tool/
├── pyproject.toml
├── README.md
├── uv.lock
└── src/
    └── media_shrink/
        ├── __init__.py
        ├── cli.py           # Typer or argparse
        ├── config.py        # TOML/JSON 設定読み込み
        ├── image.py         # 画像変換
        ├── video.py         # 動画変換
        ├── pdf.py           # PDF 圧縮
        ├── dedup.py         # 重複削除
        └── utils.py         # ログ・パス操作・安全削除
```

- **uv** で依存管理＋実行環境を一元化する（Astral の `uv` は 2026 年現在、Python パッケージングのデファクトになりつつある）。
- CLI フレームワークは小規模なら標準 `argparse` で十分。コマンドが増えるなら `typer`。

## 3. 画像処理のベストプラクティス

### コアスタック
- **Pillow 12.2+**: 開く・EXIF 取得・リサイズ・保存
- **pillow-heif 1.3+**: HEIC/HEIF 対応（`register_heif_opener(thumbnails=False)`）
- **imagehash 4.3+**: 知覚ハッシュ（pHash）による類似画像検出（オプション）

### 必ずやること
1. **EXIF Orientation を物理的に適用する**
   ```python
   from PIL import ImageOps
   img = ImageOps.exif_transpose(img)
   ```
   その後 `orientation` タグは 1 に正規化される。リサイズ前にやらないと縦横が狂う。
2. **リサイズフィルタは `Image.LANCZOS`（= `Resampling.LANCZOS`）**
   ダウンスケール時に最もシャープでアーティファクトが少ない。
3. **透明画像を白背景に合成してから JPEG 保存**
   ```python
   if img.mode in ("RGBA", "P", "LA"):
       bg = Image.new("RGB", img.size, (255, 255, 255))
       bg.paste(img, mask=...)
       img = bg
   ```
4. **EXIF / ICC プロファイルを保持する**
   ```python
   kwargs = {"quality": 85, "optimize": True}
   if exif := img.info.get("exif"):
       kwargs["exif"] = exif
   if icc := img.info.get("icc_profile"):
       kwargs["icc_profile"] = icc
   img.save(out, "JPEG", **kwargs)
   ```

### 出力フォーマットの選択指針
| 用途 | 推奨形式 | 理由 |
|---|---|---|
| 最大互換性 | JPEG | どの環境でも開ける |
| 同画質で最小 | HEIC | iPhone/Apple エコシステムで優位 |
| Web 配信 | WebP | ブラウザ対応が進んでいる |
| 次世代・最小 | AVIF | 圧縮率は最高だがエンコード遅い |

## 4. 動画圧縮のベストプラクティス

### ffmpeg の入手方法
- Windows ユーザーには **`imageio-ffmpeg`** が便利。`pip install imageio-ffmpeg` すると初回実行時に ffmpeg/ffprobe バイナリを自動ダウンロードしてくれる。
- 本格的に使うならシステムに ffmpeg を入れ、`shutil.which()` で PATH を確認する。

### コーデック選び
| コーデック | CRF 目安 | 使いどころ |
|---|---|---|
| H.264 (libx264) | 23 | どの端末でも再生できる安全牌 |
| H.265 (libx265) | 28 | H.264 の約 40–50% サイズ縮小。新しめの端末向け |
| AV1 (SVT-AV1) | 30–35 | 最小サイズを目指す。エンコードが遅い |

### CRF チューニング（内容別）
- トーク・固定カメラ：x264 CRF 22–24
- スポーツ・高動体：x264 CRF 19–21
- アニメ 2D：x264 CRF 20–22
- スクリーン録画：x264 CRF 18–20 + `-tune stillimage`
- モバイルのみ：x264 CRF 26–28

### 安全な基本コマンド
```bash
ffmpeg -i input.mov -c:v libx264 -crf 23 -preset medium \
       -vf "scale=-2:1080" -c:a aac -b:a 128k -movflags +faststart output.mp4
```

### 配信向け（帯域安定）
```bash
ffmpeg -i input.mov -c:v libx264 -crf 22 -maxrate 5M -bufsize 10M \
       -c:a aac -b:a 128k output.mp4
```

## 5. PDF 圧縮のベストプラクティス

### ライブラリ選定（2026 年ベンチマークより）
| ライブラリ | 圧縮方式 | 向く PDF | 注意点 |
|---|---|---|---|
| **pikepdf / qpdf** | コンテナ再パック（可逆） | テキスト・契約書・レポート | 画像は触らないのでスキャン PDF はあまり縮まない |
| **Ghostscript** | 再ラスタライズ（非可逆） | スキャン・写真多数のパンフレット | 電子署名が破損、画質劣化あり |
| **PyMuPDF (fitz)** | 中間的 | 画像 PDF の再エンコードも可能 | AGPL/商用ライセンスに注意 |

### 推奨戦略
1. **デフォルトは pikepdf（可逆）**
   ```python
   import pikepdf
   with pikepdf.open("input.pdf") as pdf:
       pdf.save("output.pdf", object_stream_mode=pikepdf.ObjectStreamMode.generate,
                compress_streams=True, linearize=True)
   ```
2. **スキャン PDF で「サイズ優先」モードを別途提供**
   - Ghostscript `/ebook`（150 dpi）または `/screen`（72 dpi）を選択可能にする。
   - サイズ上限を指定できるループ（目標サイズに近づくまで preset を下げる）も便利。
3. **電子署名付き PDF は pikepdf のみ**
   Ghostscript は署名を破壊する。

## 6. 重複ファイル検出のベストプラクティス

### 完全一致検出
1. サイズでグループ化
2. 同サイズ同士でハッシュ比較
   - 高速なら `xxhash`（`xxhash.xxh64`）
   - 標準ライブラリなら `hashlib.md5` や `hashlib.blake2b`
3. 辞書順で最初のファイルを残し、残りを削除 or ごみ箱へ

### 画像の類似重複検出（オプション）
```python
from PIL import Image, ImageOps
import imagehash

with Image.open(path) as img:
    img = ImageOps.exif_transpose(img)
    img.thumbnail((512, 512))
    h = imagehash.phash(img)
```
- pHash 差が 0 なら同一、5 以下ならほぼ同一、10 以上は別画像という目安。
- 類似削除は誤削除リスクがあるため、デフォルト OFF、確認付き実行が無難。

## 7. 安全設計（壊さないための鉄則）

| 項目 | 推奨 |
|---|---|
| **DRY-RUN** | 必ず実装。本番実行前に「何がどう変わるか」を表示する。 |
| **出力検証後に元ファイル削除** | 変換後ファイルが存在し、サイズ > 0、かつ簡易オープンできることを確認してから削除。 |
| **ログを残す** | 削除・変換したファイル、サイズ、エラーをテキスト/JSON で記録。 |
| **ごみ箱移送** | 可能なら `send2trash` を使い、即削除ではなくゴミ箱へ。 |
| **並列度の制御** | `ThreadPoolExecutor(max_workers=4)` 程度。動画エンコードは CPU を食うので同時実行数を抑える。 |
| **設定ファイル** | 画質・CRF・最大解像度を TOML/JSON で外だしし、再実行を楽にする。 |

## 8. パッケージング・配布

- **開発時**: `uv run` で依存を自動解決
- **技術者向け配布**: `git clone` + `uv sync`
- **一般ユーザー向け配布**: PyInstaller で単一 EXE 化（ffmpeg は別添い or 同梱）

## 9. まとめ：採用すべき技術スタック

- **言語**: Python 3.11+
- **依存管理・実行**: uv
- **画像**: Pillow + pillow-heif + ImageOps.exif_transpose + LANCZOS
- **動画**: imageio-ffmpeg + ffmpeg CRF モード
- **PDF**: pikepdf（可逆デフォルト）+ Ghostscript（非可逆オプション）
- **重複**: サイズ＋ハッシュ（xxhash）＋ オプションで imagehash
- **CLI**: argparse or typer
- **安全**: dry-run、出力検証、ログ、send2trash

この構成で、今回のような「1,000 枚超の画像＋動画＋PDF＋重複削除」を**一発で再実行できる**ツールが作れます。
