# 実写真・NAS Pilot実施要領（安全優先、会社規模相応）

## 目的と合格条件

既存 `web-public` が現場で使う実素材を「担当者が迷わずPayloadへ入稿できるJPEG/PNGマスター」にできるか確認する。高速化競争や実データの網羅分析は今回しない。

**合格条件:** 選択した許可済み写真の原本不変、出力形式と横幅上限、表示上の色/向き/細部、不要メタデータを除去、GUI上の警告と失敗理由、NASでの保存と再実行が確認できること。下流AVIF/WebPは別責務（`05`参照）。

## 写真収集・権限

- 写真は**ユーザー/会社が試験使用を許可した10〜15枚**に絞る。試験結果の証拠としてGitHubに写真を上げない。試験者個人の写真も許諾なしで流用しない。
- データの見た目に住所・看板・人の顔・車両番号・撮影場所が映る場合、公開可否は別途人が確認。EXIFを削除しても画素内の情報は消えない。
- 許可された作業用コピーを入力に使い、原本正本のリネーム/削除/上書きは禁止。
- 機密を含む実際のUNCパス、ユーザー名、hashと写真の対応一覧を外部共有しない。GitHubへ上げるのは集計と判定だけ。
- **安全な作業用コピー**上であっても、書き込み/停止を伴う異常試験は対象共有の管理者承認が必要。権限不明ならスキップ。

## 10〜15枚の選定目安（合計に重複可）

| 素材 | 目安 | 確認事項 |
|---|---:|---|
| 法面・金網・細かい繊維や岩のディテール | 3 | 1400px後の網・ワイヤ・細部が破綻していないか |
| 重機・構造物・作業遠景 | 2 | 輪郭、細部、色、文字の視認性 |
| 草木・空・グラデーション・暗部 | 2 | 葉、空の段差、暗部のつぶれ、色ずれ |
| 縦写真/EXIF Orientation付きJPEG | 1〜2 | 横幅基準1400、向きの重複回転なし |
| 実端末由来 HEIC/HEIF（許可されれば） | 1〜2 | HEICデコード、ICC/NCLX判定、必要なら編集ソフトからsRGB変換 |
| CAD出力図・透過PNG・ロゴ等 | 1〜2 | `graphic`, alpha維持、線や文字が読めるか |
| 既に1400px以下の写真 | 1 | 拡大されないこと、追加劣化の見た目 |

HEIC等が手配できない場合に合成データを使ってもよいが、それを「端末由来実写真PASS」とは呼ばない。

## 事前に記録するもの

`templates/PILOT_CASES.csv`の各行へcase_id, 種類, source_format, before_dimensions, expected_behavior、匿名化した試験場所（local/UNC/drive）を書く。**実ファイル名・住所・工事名はテンプレートへ記録せず、別のローカル保管物にする。**

処理前に、許可済み作業用コピーのSHA-256とバイト数をローカル保存。処理後に原本が不変であることを確認する。ログ全文が機密パスを含む場合は公開に使わない。

## 実行（PowerShell例・実際のパスは置換する）

```powershell
# 会社で許可された専用の一時・非公開フォルダーに準備（以下は例）
$InputFolder  = 'D:\WebPilot\input'
$OutputFolder = 'D:\WebPilot\output'

# 事前確認（dry-runは書き込みなし）
uv run --project media-shrink-tool python -m media_shrink web-public `
  -i $InputFolder -o $OutputFolder --kind photo --dry-run

# 写真だけを実行。図版は入力/出力を別に分け --kind graphic を使う
uv run --project media-shrink-tool python -m media_shrink web-public `
  -i $InputFolder -o $OutputFolder --kind photo
```

用途混在時はGUIで選択し、写真/図版を別々のrunにする。`resize`を先に通さない。出力rootは入力rootと同一/親子にしない。手元で実物を目視する場合は `runs/<run-id>/files/` 内の完成画像だけを使い、`manifest.web-public.json` は入稿しない。

## 視覚検証（事務員とSEが各代表画像を確認）

1. 原本と掲載用マスターを**同倍率の表示サイズ**で並べる。まず現実の画面サイズで比較し、次に100%表示で金網・細線・文字・葉・岩・暗部を確認。
2. 横写真・縦写真それぞれで向きと構図を確認。`width <= 1400`は確認するが、縦方向の高さに1400px上限を誤適用しない。
3. 色が不自然な場合、元デバイスICCと変換後sRGBを比較。ICCに矛盾があれば自動修正せず安全なsRGB書き出しを試す。
4. `graphic`の透過輪郭、半透明、細いCAD線やラベルを確認。
5. 入稿前に、写り込み・顔・ナンバー・工事場所・社外非公開情報が画像**そのもの**に含まれないか確認。
6. 生成JPEG/PNGのファイルサイズが増えても、二次生成マスター目的のため機械的に不合格としない。

## 自動で確認する契約

- `web-public`の成功行: `width <= 1400`、元より拡大なし、`photo` JPEG q90/4:4:4/新sRGB、`graphic` PNG/alpha維持、原寸縦横比/crop禁止。
- `verify_public()`等でEXIF/GPS/XMP/元comment/内部markerの不在を検査。PNG textとJPEGの禁止segmentまで確認。
- `manifest.web-public.json`の成功行のsource/output SHAと実ファイルを照合。警告は件数・内容を記録。
- 同入力の再実行では`SKIPPED_COMPLETE`等の再利用を確認し、**新runの files に今回の出力だけあること**を確認。
- 不正画像を混ぜた時は正常画像だけ成功、失敗はERRORであり、原本コピーを完了画像として混入させない。

## NAS（ユーザーから実パス・許可が提供された場合のみ）

検証パス例（**実shareではない**）:

```text
\\<NAS-host>\<test-share>\web-public-pilot\input\
\\<NAS-host>\<test-share>\web-public-pilot\output\
```

| ケース | 手順 | 合格条件 |
|---|---|---|
| NAS-01 UNC読込→ローカル出力 | UNCの専用test inputから読む | 読込成功、原本のSHA不変 |
| NAS-02 ローカル読込→UNC出力 | 安全なローカルcopyからtest shareへ保存 | manifest検証・files検証成功 |
| NAS-03 UNC読込→UNC出力 | 同一shareでも入出力非親子の専用領域 | path guard・原子的確定・再実行成功 |
| NAS-04 Windows割当ドライブ | ユーザーが既に設定済みのドライブ文字（提供時のみ） | UNCの場合と同じ結果で認証情報露出なし |
| NAS-05 失敗と復旧 | ローカルのmock I/O失敗→許可時だけテスト共有を使った安全な書込不可等 | エラーを成功扱いしない、旧manifest保持、再実行で復旧 |
| NAS-06 権限がない/切断済 | 読込/書込不可を試す | ファイル破壊せず失敗理由が分かる |

**禁止:** 本番NASの電源/ネットワーク切断、運用中SMBセッションの強制遮断、共有設定変更、全社の割当ドライブ操作、既存フォルダーの削除。これはPilotに不要。

## Pilot完了判定

- `PASS`: 実写真とNASの必須項目を両方実施し、既知の問題がなく、正式な最終表示への引継ぎが完了。
- `PASS_WITH_LIMITATIONS`: 一部の入力形式のみ人手sRGB書出しが必要等、担当者が回避できる制約が明確。
- `BLOCKED_REAL_PHOTOS` / `BLOCKED_REAL_NAS`: 実データ・実アクセス未提供。**コードテストPASSとは分ける**。
- `FAIL`: 再現した出力破壊、誤公開、危険なmetadata残存などが未修正。

データの実ファイル一覧・hash一覧は社内/試験端末内に限定して保存。Gitに入れるPilot報告には匿名化したcase_id、使用モード、件数、制約、数値概要を記す。
