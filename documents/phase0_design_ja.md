# BoExio Phase 0 設計メモ

作成日: 2026-05-21
更新日: 2026-05-22

参照:

- `documents/requirements_definition_ja.md`
- `documents/product_vision_ja.md`

## 1. 目的

Phase 0 は、Phase 1 の 1 商品 PoC を作る前に、後続フェーズで作り直しになりにくい最小設計を決める段階とする。

Phase 1 では、BoConcept の代表商品 1 件について商品ページ構造を確認し、取得できた内容を CSV として出力する。差分検知、Excel レポート、GitHub Actions、販売終了状態管理は Phase 1 の実装対象外とする。

## 2. Phase 1 スコープ

対象にすること:

- 手動 URL リストからカテゴリ URL を 1 件読み込む。
- 手動投入 URL が `https://www.boconcept.com/ja-jp/shop/` 配下であることを確認する。
- 許可済みカテゴリページから発見した商品詳細 URL に限り、`https://www.boconcept.com/ja-jp/p/` 配下の取得を許可する。
- HTML、構造化データ、内部 JSON/API の取得可能性を調査する。
- 必要に応じて Playwright によるレンダリング取得の必要性を判断する。
- 商品名、商品番号、価格、寸法、素材、画像 URL、PDF URL、SKU、構成 ID、構成属性の取得可否を確認する。
- 取得できた項目を 1 商品分の CSV として出力する。
- 取得失敗時も `scrape_status=failed` の行を CSV に残す。
- Phase 2 の取得方式方針を決める。

対象外にすること:

- 複数商品 URL の一括処理。
- 複数構成の完全な組み合わせ展開。
- 前回 CSV との価格差分検知。
- Excel レポート生成。
- GitHub Actions 定期実行。
- GitHub Releases への成果物保存。
- `missing_candidate`、`discontinued`、`revived` の状態管理。

## 3. 入力 URL リスト v0

Phase 1 では、手動管理のテキストファイルを入力とする。

想定パス:

```text
config/target_urls.txt
```

形式:

```text
# 1 行 1 URL
# 空行と # 始まりのコメント行は無視する
https://www.boconcept.com/ja-jp/shop/...
```

検証ルール:

- URL の scheme は `https` のみ許可する。
- host は `www.boconcept.com` のみ許可する。
- 手動投入 URL の path は `/ja-jp/shop/` 配下のみ許可する。
- `/ja-jp/p/` 配下の商品詳細 URL は、許可済みカテゴリページから発見した場合のみ取得を許可する。
- robots.txt の Disallow 対象は投入時と実行時の両方でスキップする。
- 不許可 URL は処理対象から除外し、ログまたは errors に理由を残す。

## 4. 出力ディレクトリ v0

Phase 1 の出力は run 単位で保存する。

```text
data/
  runs/
    <run_id>/
      products_poc.csv
      scrape_log.txt
      run_metadata.json
      raw/
        <optional raw capture files>
```

`run_id` は次の形式を基本とする。

```text
YYYYMMDDTHHMMSSZ
```

JST 実行時も、run_id は UTC ベースで固定する。人間向け表示や `source_checked_at` は ISO 8601 でタイムゾーンを含める。

## 5. CSV v0 カラム定義

Phase 1 では、Product、Variant、PriceSnapshot の後続設計につながる広めの列を用意する。取得できない項目は空欄にする。

必須列:

```text
run_id
source_url
source_checked_at
scrape_status
scrape_error_code
scrape_error_message
brand
series
product_name
base_item_number
variant_id
sku
item_number
selected_size
selected_upholstery
selected_leg
width_cm
depth_cm
height_cm
weight_kg
material
list_price
display_price
canonical_price
price_from
currency
tax_type
image_url
pdf_url
raw_data_ref
```

Phase 1 の扱い:

- `scrape_status` は `success` または `failed` とする。
- `display_price` は Phase 1 の証跡として、画面表示価格をそのまま記録する。
- `canonical_price` は差分判定用の価格を入れる。`display_price` が「から」価格で `list_price` が取れる場合は、`list_price` を `canonical_price` に入れる。
- `price_from` は価格を取得した場所を記録する。例: `structured_data`, `embedded_json`, `dom_text`, `api_response`。
- `variant_id`、`sku`、構成属性は、取得可否の確認が主目的であり、比較キー確定には使わない。
- `raw_data_ref` は保存した raw ファイルがある場合に相対パスを入れる。

## 6. run metadata v0

Phase 1 の `run_metadata.json` には、最低限次を保存する。

```json
{
  "schema_version": "0.1.0",
  "parser_version": "0.1.0",
  "commit_sha": "",
  "run_id": "",
  "started_at": "",
  "finished_at": "",
  "target_urls": [],
  "output_files": [],
  "output_file_checksums": {},
  "run_status": "",
  "success_count": 0,
  "failure_count": 0,
  "notes": []
}
```

Phase 1 では `run_status` は `success`、`partial_success`、`failed` のいずれかとする。

Phase 1 仕上げ後の扱い:

- `output_files` には `products_poc.csv`、`scrape_log.txt`、`run_metadata.json`、raw capture を含める。
- `output_file_checksums` には CSV、ログ、raw capture の SHA-256 を保存する。
- `run_metadata.json` 自体は自己参照 checksum が安定しないため、checksum 対象から外す。

## 7. エラーコード v0

Phase 1 では、要件定義のエラーコード体系から次を利用する。

| エラーコード | 用途 |
| --- | --- |
| `HTTP_<status>` | HTTP ステータス起因 |
| `TIMEOUT_CONNECT` | 接続タイムアウト |
| `TIMEOUT_READ` | 応答タイムアウト |
| `TIMEOUT_RENDER` | 描画待ちタイムアウト |
| `SELECTOR_MISS` | 期待 DOM が取得不可 |
| `SCHEMA_MISMATCH` | JSON/HTML 構造が想定外 |
| `PARSE_ERROR` | 値変換失敗 |
| `RATE_LIMITED` | レート制限検知 |
| `URL_NOT_ALLOWED` | 対象外 URL |
| `ROBOTS_DISALLOWED` | robots.txt による除外 |
| `UNKNOWN` | 分類不能 |

エラー行には、運用者が修正対象を特定できるように `source_url`、`scrape_error_code`、`scrape_error_message` を必ず残す。

## 8. 取得方式の判定基準

Phase 1 の調査順序:

1. 内部 JSON/API。
2. HTML 内の構造化データ。
3. Playwright によるレンダリング後 DOM。
4. URL パターン推測。

採用判断:

- SKU、構成 ID、価格、構成属性が内部 JSON/API で安定して取れる場合は JSON/API 中心で進める。
- JSON/API で商品基本情報のみ取れ、構成変更後価格が DOM 依存の場合は Playwright 併用とする。
- DOM セレクタだけに依存する場合は、Phase 2 前に壊れやすい箇所を調査メモへ明記する。

## 9. コンプライアンス記録

robots.txt と利用規約の確認結果は、運用開始前に次のファイルへ記録する。

```text
documents/compliance_checklist.md
```

Phase 1 では、実取得の前に少なくとも robots.txt の対象パス確認を行う。

## 10. Phase 1 完了時の判断事項

Phase 1 の最後に、次を `documents/phase1_poc_findings_ja.md` にまとめる。

- 実際に確認した代表商品 URL。
- 採用候補の取得方式。
- 取得できた項目。
- 取得できなかった項目。
- `variant_id` / `sku` / 構成属性の取得可否。
- Phase 2 で複数構成取得へ進む際の課題。
- JSON/API 中心で進めるか、Playwright 中心で進めるかの判断。
