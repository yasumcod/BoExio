# BoExio Phase 2 構成バリエーション調査メモ

作成日: 2026-05-23
更新日: 2026-05-23

## 1. 目的

Phase 2 は、Phase 1 で確認した代表商品 Catskills について、商品単位ではなく構成単位で複数行の CSV を出力できるか確認する段階とする。

主な確認対象:

- HTML 内 Next.js データから構成候補一覧を抽出できるか。
- 構成候補から variant URL を組み立てられるか。
- variant URL を取得し、構成ごとの `variant_id`、`sku`、価格、張地、脚を取得できるか。
- Playwright の UI 操作なしで Phase 2 PoC が成立するか。

## 2. 実装

実行コマンド:

```text
python3 scripts/phase2_variants.py --run-id phase2-second-leg-check --variant-offset 76 --variant-limit 2
python3 scripts/phase2_variants.py --run-id phase2-final-check-v021 --variant-limit 1
```

実装ファイル:

```text
boexio/phase2_variants.py
scripts/phase2_variants.py
```

出力:

```text
data/runs/<run_id>/products_poc.csv
data/runs/<run_id>/variant_candidates.csv
data/runs/<run_id>/phase2_errors.csv
data/runs/<run_id>/scrape_log.txt
data/runs/<run_id>/run_metadata.json
data/runs/<run_id>/raw/
```

## 3. 確認結果

Catskills の商品ページ HTML 内 `configuration.options` から、次の候補を抽出できた。

| 属性 | attributeId | 候補数 |
| --- | --- | --- |
| 脚 | `vaMaterialLeg` | 2 |
| 張地 | `vaMaterialUpholstery` | 76 |

組み合わせ候補数:

```text
2 * 76 = 152
```

Phase 2 PoC では、サイト負荷を避けるため `--variant-limit 4` として、先頭 4 件のみ variant URL を取得した。

## 4. 取得できた項目

先頭 4 件の variant URL 取得で、次を確認できた。

- `variant_id`
- `sku`
- `item_number`
- `selected_upholstery`
- `selected_leg`
- `list_price`
- `display_price`
- `currency`
- `tax_type`
- `image_url`
- raw HTML
- `variant_key`
- `variant_key_from`
- `list_price_value`
- `display_price_value`
- `canonical_price_value`
- `price_compare_value`
- `price_compare_from`

例:

| variant_id | sku | 張地 | 脚 | list_price | display_price |
| --- | --- | --- | --- | --- | --- |
| `4060001-9:0708s-14:2063` | `406500012063730` | ライトグレー aquaclean加工Frisco ファブリック アクアクリーン加工 2063 | 自然無垢材オーク | `¥ 339,900` | `¥ 257,900から` |
| `4060001-9:0708s-14:2065` | `406500012065730` | ダークブルーFrisco ファブリック アクアクリーン加工2065 | 自然無垢材オーク | `¥ 339,900` | `¥ 257,900から` |
| `4060001-9:0708s-14:2110` | `406500012110730` | サンドNaniファブリック 2110 | 自然無垢材オーク | `¥ 257,900` | `¥ 257,900から` |
| `4060001-9:0708s-14:2111` | `406500012111730` | ダークグレーNaniファブリック 2111 | 自然無垢材オーク | `¥ 257,900` | `¥ 257,900から` |

## 5. 判断

- 構成候補一覧は HTML 内 Next.js データから取得できる。
- variant URL は、現在の `variantUrlKey` と `selectedOptions` を使って組み立てられる。
- 取得した variant URL の HTML から、構成ごとの `variant_id`、`sku`、張地、脚、価格を取得できる。
- 先頭 4 件の確認範囲では、Playwright による UI 操作は不要。
- `display_price` は引き続き「から」価格になるため、構成単位価格としては `list_price` の扱いを Phase 4 前に整理する必要がある。
- Phase 2 仕上げで、`display_price` が「から」価格の場合は `list_price` を `canonical_price` に入れ、差分比較候補として `price_compare_value` を出力する方針にした。
- 比較キーは `variant_id`、`sku`、正規化済み属性連結キーの順で生成する。
- 先頭 4 件と 2 種類目の脚 2 件では、`variant_id` 由来の `variant_key` を生成できた。
- `phase2_errors.csv` を追加し、取得失敗、比較キー生成失敗、価格正規化失敗を `url`、`phase`、`error_code`、`message`、`first_seen_at`、`last_seen_at` 形式で出力できるようにした。

## 6. 未確認事項

- 152 候補すべての variant URL が有効か。
- 152 候補すべてで SKU と価格が安定して取得できるか。
- 張地・脚以外の構成属性を持つ商品で同じ抽出ロジックが使えるか。
- 複数商品へ広げたとき、attributeId が商品種別ごとに変わるか。

Phase 3 追記:

- 複数商品検証で attributeId 差異を確認した。
- Hamilton ダイニングチェアは `vaMaterialUpholstery` ではなく `vaMaterialSeat` を持つ。
- Phase 3 では `vaMaterialSeat` を張地相当の比較軸として fallback し、CSV schema を維持する。

## 7. 次の実装方針

- Phase 3 では、Phase 2 の候補抽出と `products_poc.csv` 拡張列を再利用する。
- カテゴリから複数商品 URL を収集し、商品ごとに構成候補を抽出する。
- 全 152 件取得は、アクセス制御、リトライ、run 失敗判定、403/captcha 停止の実装後に扱う。
- Phase 3 の `products_current.csv` には、`variant_key`、`price_compare_value`、`price_compare_from`、キー生成エラー列、価格正規化エラー列を含める。

## 8. Phase 3 への導線

Phase 2 から Phase 3 へ持ち越す再利用部品:

- カテゴリ URL から代表商品 URL を発見する処理。
- 商品 HTML から `configuration.options` を抽出する処理。
- `variantUrlKey` と `selectedOptions` から variant URL を組み立てる処理。
- `parse_product()` による商品・構成・価格・画像の抽出処理。
- `variant_key` 生成と価格数値化処理。
- `phase2_errors.csv` の errors 形式。

Phase 3 の先頭で実装すべきこと:

- カテゴリ内の複数商品 URL を重複なく収集する。
- 商品ごとに variant 候補を生成する。
- 取得対象数が増えるため、リクエスト間隔、リトライ、打ち切り、run 全体失敗判定を先に入れる。
- Phase 2 の `--variant-limit` / `--variant-offset` は検証用として残し、Phase 3 では設定ファイルまたは CLI で商品数・構成数の上限を制御する。
