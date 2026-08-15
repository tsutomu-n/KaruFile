# KaruFile orchestrator 設計

## 責務

Repo ルートの `karufile.py` から委譲され、PDF と画像の processor を subprocess で順次実行する。PDF・画像の変換、状態管理、候補検証は複製しない。

```text
karufile.py
  └─ orchestrator/shrink_all.py
       ├─ pdf-shrink        PDF の唯一の処理経路
       └─ media-shrink-tool 画像 resize のみ
```

## 実行順序

1. input/output を resolve し、存在・同一・親子関係を検査する。
2. 対象 PDF・画像の件数と原本保持を表示する。
3. PDF がある場合だけ `pdf-shrink` を実行する。
4. `media-shrink-tool resize` を実行し、0件のときも画像エラー CSV を現在実行の内容へ更新する。
5. processor の CSV と標準出力から取得できる値だけを集計する。
6. 原本変更なし、削除0件、エラー数、画像エラー CSV の場所を表示する。
7. どちらかの processor が失敗した場合は終了コード `1` を返す。

## 境界

- PDF と画像は同じ出力フォルダーへ相対構造を維持して保存する。
- PDF の状態・詳細レポートは `pdf-shrink` が所有する。
- 画像の再利用判定とエラー CSV は `media-shrink-tool` が所有する。
- orchestrator は共通 DB、worker pool、structured IPC を追加しない。
- 動画、dedup、元ファイル削除は呼び出さない。

## 制約

- 実行環境に `uv` と各 project の lock 済み依存が必要。
- stdout の画像サマリーを取得できない場合だけ、出力の `.jpg` と `.jpeg` から概算する。
- dry-run は完成 PDF・画像を作らないが、processor の状態・レポート更新を禁止しない。
