# 実装手順 — 既存コードに対する最小差分

この手順は `KaruFile main@79df924a` 時点の読取結果に基づく。Codexは**実行時の作業ツリーが正本**であり、コード構造が異なるなら差分を調べて適応する。

## ファイル別責務（確認済み）

| 現存ファイル | 既存の責務 | 今回の基本方針 |
|---|---|---|
| `media-shrink-tool/src/media_shrink/image.py` | 通常resize、fingerprint、再利用、原子的公開 | 通常resize処理不変。共用source identityのみ抽出し旧名を残す |
| `media-shrink-tool/src/media_shrink/utils.py` | path検査、link/junction、staged_path | **そのまま使う**。独自フォークしない |
| `media-shrink-tool/src/media_shrink/web_public.py` | 画像1件のsRGB/寸法/metadata処理、結果検証 | Pilotで再現した不具合だけ修正。source identityだけ新moduleから取り込む |
| `media-shrink-tool/src/media_shrink/web_public_batch.py` | 対象選択、new run、再利用、manifest | 振舞い固定。source identityだけ新moduleから取り込む |
| `media-shrink-tool/src/media_shrink/gui.py` | NiceGUI・選択・プレビュー・ConversionController | 拡張用メニューやplugin層は作らない。実利用上の問題のみ修正 |
| `media-shrink-tool/src/media_shrink/cli.py` | `resize`, `web-public`, `gui` | APIと終了コード固定 |
| `media-shrink-tool/tests/test_*.py` | 現行契約の自動検証 | 不具合再現/共通化回帰を追加 |
| `docs/validation/2026-10-07-web-public/README.md` | 過去の検証記録 | 歴史として維持。**今回は新しい日付の記録に分離** |

### 新規ファイル（共通化を実施する場合）

- `media-shrink-tool/src/media_shrink/file_identity.py` — sourceのSHA256/stat署名/不変性確認。画像のメタデータや変換に依存させない。
- `media-shrink-tool/tests/test_file_identity.py` — path/source fingerprintの単体・回帰テスト。
- `docs/validation/2026-10-08-web-public-pilot/README.md`（例。実施日を用いる）— Pilotと再確認の事実。

## CP0. Baseline（コード変更前）

1. 関連ファイルと`AGENTS.md`を読む。現在のGit状態・lockのバージョンを記録。
2. 下記を実行し**新鮮な結果**を控える。実行不可は理由を記す。

```powershell
uv run --project media-shrink-tool --extra dev --extra gui python -m pytest -q media-shrink-tool/tests
uv run --project media-shrink-tool python -m media_shrink web-public --help
uv run --project media-shrink-tool python -m media_shrink resize --help
uv lock --check --project media-shrink-tool
```

3. 必要なら指定済みの合成fixtureで `web-public` を1回行い、`run-id`、manifest、source/output SHA、非公開画像の形式を控える。旧正常出力を上書きしない。
4. 実素材Pilot前の結果を `baseline` と明記する。

## CP1. 実画像Pilotと最小修正

- `03_REAL_PHOTO_NAS_PILOT.md`の試験素材・視覚チェックを使う。
- `web-public --kind photo/graphic` の**既存CLIをそのまま使う**。前処理に`resize`を通さない（二重JPEG圧縮防止）。
- 原本はハッシュと容量を処理前後に照合。変換済み画像は`verify_public()`や外部の情報確認ツールで判定する。
- 実写真の品質で問題が出たら「元編集」「1400px縮小」「master JPEG保存」のどの段階か切り分ける。別のencoderを先に導入しない。
- 現行レシピに合わない高bit depth/HDR画像は自動でsRGB推定に変更せず、編集ソフトからsRGBで安全に書き出す手順を優先。
- 目視で許容できない劣化が定常的に出て、レシピ変更を提案する場合は、旧レシピとの差・画質/容量・新recipe version・再利用互換性を一式で示す。ユーザー承認前に既定値を変えない。

## CP2. NAS実環境試験

- 既存原本フォルダーではなく専用試験フォルダーを使用する（後述）。
- UNCおよびドライブ文字からの実行を両方確認。UIのパス貼付けとフォルダーダイアログも対象。
- NAS切断を誘発する試験は、業務に影響のない専用テスト共有に限る。無許可なら`SKIPPED_UNSAFE_DISCONNECT`。
- 期待: 既存原本不変、既存正常run不変、partial failure/manifest errorが成功と混同されない、再接続後の再実行で復旧する。

## CP3. source fingerprintだけ共通化

**原則**: 先に全テストと必要な現地検証を完了してbaselineを作る。共通化は局所的に最後に行う。

### 変更箇所

現在 `image.py` にある `SourceChangedError`, `SourceFingerprint`, `_sha256_file`, `_stat_signature`, `_capture_source_fingerprint`, `_assert_source_unchanged` が候補。`web_public.py`と`web_public_batch.py`がこれらを**画像変換moduleからprivate import**している。これをなくす。

新モジュール `file_identity.py` に以下の公開APIを持たせる（型注釈はPython 3.11互換）。

```python
class SourceChangedError(OSError): ...

@dataclass(frozen=True, slots=True)
class SourceFingerprint:
    stat: os.stat_result
    sha256: str
    @property
    def stat_signature(self) -> tuple[int, int, int, int, int]: ...

def sha256_file(path: Path) -> str: ...
def stat_signature(stat: os.stat_result) -> tuple[int, int, int, int, int]: ...
def capture_source_fingerprint(source: Path) -> SourceFingerprint: ...
def assert_source_unchanged(source: Path, expected: SourceFingerprint, input_root: Path) -> None: ...
```

- 実装内容は現行 `image.py` の**既存処理を忠実に移す**。CRC以外の新しい同一性方式、fingerprintのDB化などを導入しない。
- `file_identity.py` が参照してよい社内モジュールは `utils.py` のpath validation程度。**`image.py`, `web_public.py`, `gui.py`をimportしない**。循環依存禁止。
- `image.py` では上記の旧private名・class名を `file_identity.py` からaliasまたは薄いラッパーで公開し続け、既存利用/テストを保つ。
- `web_public.py` / `web_public_batch.py` はsource identity関連を `file_identity.py` の公開APIへ切り替える。**`_replace_staged`, `_validate_replaceable_file` は現段階では今の動作を維持**し、無条件に全ファイル公開ロジックを分離しない。これらの新たな実用途ができた時に別設計とする。
- `_sha256_file` 等を monkeypatch する既存テストがある場合、その呼出しを維持できる薄い関数委譲が必要か確認する。例外クラスのidentityも変えない。
- `source fingerprint` APIを画像メタデータ等と結合しない。将来の別用途からimportできる**小さい独立モジュール**に留める。

### CP3テスト（自動テストは環境で実行）

1. `test_file_identity.py`で「正常、同サイズ/同mtimeの内容変化、hash中のファイル変更、source pathがlink/junction、例外型」を確認する。
2. 通常`resize`と `web-public` の**両方**で、処理前後のsource変更エラーを確認。dry-run, reuse, manifest失敗も実行。
3. `file_identity`のimportからPillow/NiceGUIがimportされないことを確認。`image.py`経由の旧名importが引き続き可能なことを確認。
4. 再利用`SKIPPED_COMPLETE`がsource SHA/output SHA/recipe/engine/policyを同様に検査することを確認。
5. 同じ入力で共通化前後の`output width/height`, `format`, ICC/EXIF, alpha, error codes, manifest結果を比較。**異なるプロセスで生成したICCの作成日時等が違う場合に、無条件のファイルバイト一致を要求しない**。再利用した同一バイト画像は一致必須。

### もし想定外に広い変更になった場合

既存テストやmonkeypatch契約への影響が大きければ、CP3を**保留**しPilotと受入の完了を優先。コードを巨大に変更して「将来対応」を作ることは禁止。保留内容と必要な準備を記録する。

## CP4. 全回帰

`AGENTS.md`に従い、影響範囲のtestsと全suiteをfreshで実行。

```powershell
uv run --project pdf-shrink python -m pytest -q pdf-shrink/tests
uv run --project media-shrink-tool --extra dev --extra gui python -m pytest -q media-shrink-tool/tests
uv run --project excel-shrink python -m pytest -q excel-shrink/tests
uv run --project video-shrink python -m pytest -q video-shrink/tests
Push-Location orchestrator
uv run --with pytest python -m pytest -q
Pop-Location
uv run --project pdf-shrink python -m compileall -q pdf-shrink/src pdf-shrink/tests
uv run --project media-shrink-tool python -m compileall -q media-shrink-tool/src media-shrink-tool/tests
uv run --project excel-shrink python -m compileall -q excel-shrink/src excel-shrink/tests
uv run --project video-shrink python -m compileall -q video-shrink/src video-shrink/tests
uv run --project pdf-shrink python -m compileall -q karufile.py orchestrator
uv run --project media-shrink-tool python -m media_shrink web-public --help
uv run --project media-shrink-tool python -m media_shrink resize --help
uv run --script karufile.py --help
uv lock --check --project media-shrink-tool
git diff --check
```

何を実行したか、exit code、件数、skipの理由を記録する。前回`1435 passed / 4 skipped`は比較用数値であり、変更後の実行を省略する口実にしない。

## CP5. ドキュメント更新

- `AGENTS.md`: 新`file_identity.py`の責務と旧名互換を追記。PDF/Excel/動画GUIは引き続き対象外。
- `docs/REFERENCE.md`: source SHA の位置変更が利用者契約に影響しないなら、説明は変更必要箇所だけ。
- `docs/WEB_PUBLIC.md`, `MANUAL.md`: 実Pilotで判明した注意/運用手順を追加。QAデータ自体は添付しない。
- `docs/validation/<today>-web-public-pilot/README.md`: 新実行結果、機密性を守った集計、未検証/条件付きの境界を記録。
- `docs/architecture`: 実行時の責務やimport依存境界が変わった場合だけソースJSONを更新し、リポジトリの生成手順でHTML・visual-checkを再生成。生成HTMLの手修正は禁止。
- READMEは導線だけ。正本を重複させて仕様の不整合を生まない。

## 今回の非対象

- 別の広報SNS用画像の独立encoderや新用途の自動追加
- 画質スコアを強制するAI判定機能
- GUIの巨大な設定メニュー、複数アカウント管理、クラウド同期
- 一括キャッシュ削除・過去runs自動整理・社内NASへの破壊的整理
- 既存画像の全置換とWebサイトの本番deploy
