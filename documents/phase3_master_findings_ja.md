# BoExio Phase 3 商品マスタ生成 調査・実装メモ

作成日: 2026-05-23

参照:

- `documents/task.md`
- `documents/summary.md`
- `documents/phase2_variant_findings_ja.md`

## 1. 実装ファイル

```text
boexio/phase3_master.py
scripts/phase3_master.py
```

Phase 3 では、Phase 1/2 の取得・解析部品を再利用し、カテゴリ URL から商品 URL を発見して、商品ごとの構成候補を `products_current.csv` と日付付き snapshot に出力する。

## 2. 出力成果物

```text
data/runs/<run_id>/
  products_current.csv
  products_YYYY-MM-DD_<run_id>.csv
  variant_candidates.csv
  discovered_product_urls.csv
  errors.csv
  scrape_log.txt
  run_metadata.json
  raw/
```

CSV は Phase 2 の拡張列を継承する。

主な追加 metadata:

- `product_candidate_counts`
- `product_attribute_summaries`
- `category_pagination_summaries`
- `scrape_error_code_counts`
- `failure_rate`
- `schema_mismatch_count`
- `run_status_reasons`

## 3. 取得制御

実装済み:

- 同時接続数 1。
- `--request-interval` で URL 間隔を制御する。既定は 5 秒。
- `--timeout` で fetch timeout を制御する。
- `--retries` で URL 単位の再試行回数を制御する。
- 再試行対象は `HTTP_429`、`HTTP_5xx`、`TIMEOUT_CONNECT`、`TIMEOUT_READ`、`RATE_LIMITED`。
- `HTTP_404` と `SCHEMA_MISMATCH` は非再試行。
- `HTTP_403` または captcha/challenge 検知時は即時停止。

## 4. run 全体の失敗判定

要件定義に合わせて次の基準を実装した。

- `failure_rate = failure_count / target_count`
- `failure_rate > 0.30` なら `run_status=failed`
- `target_count >= 20` かつ `failure_count >= 5` なら `run_status=failed`
- `SCHEMA_MISMATCH` が 3 件以上なら `run_status=failed`
- 停止理由がある場合は `run_status=failed`
- `run_status=failed` の場合も生成済み成果物と `errors.csv` を保存する

判定理由は `run_metadata.json` の `run_status_reasons` に保存する。

## 5. カテゴリ URL 収集

検証 run:

```text
data/runs/phase3-catskills-all-variants/
```

結果:

- チェアカテゴリから `/ja-jp/p/` 商品 URL を 23 件発見した。
- `discovered_product_urls.csv` に重複なしで保存した。
- HTML 内の `pageParams` は `[1]`。
- `rel="next"` は確認できなかった。
- HTML には `Load more` 文字列があるが、商品一覧の実ボタンではなく翻訳辞書内の汎用文言だった。

現時点の判断:

- サーバー返却 HTML からは 23 件が初期取得範囲。
- 追加読み込み API が存在する可能性は残るため、全カテゴリ網羅前にはブラウザまたはネットワーク API trace で確認する。
- Phase 3 の PoC としては、静的 HTML 内の商品 URL 収集で商品マスタ生成まで進められる。

## 6. Catskills 152 構成全件検証

実行コマンド:

```text
python3 scripts/phase3_master.py --run-id phase3-catskills-all-variants --product-limit 1 --variant-limit-per-product 152 --request-interval 5 --retries 2
```

結果:

- `variant_candidates.csv`: 152 候補。
- `products_current.csv`: 152 行。
- `scrape_status=success`: 152 行。
- `errors.csv`: エラーなし。
- SKU 欠損: 0。
- `variant_key` 欠損: 0。
- `price_compare_value` 欠損: 0。
- `variant_key_from`: 全件 `variant_id`。
- unique SKU: 152。
- unique `variant_id`: 152。
- `run_status`: `success`。
- `failure_rate`: 0.0。
- `schema_mismatch_count`: 0。

判断:

- Catskills の 152 構成 URL は全件有効。
- 全件で SKU、variant_id、比較価格が取得できた。
- 5 秒間隔、単一接続で 403/captcha 停止は発生しなかった。

## 7. 複数商品 attributeId 検証

検証 run:

```text
data/runs/phase3-multi-product-attribute-check-v2/
```

実行コマンド:

```text
python3 scripts/phase3_master.py --run-id phase3-multi-product-attribute-check-v2 --product-limit 6 --variant-limit-per-product 1 --request-interval 5 --retries 2
```

結果:

| 商品 | 候補数 | attributeId |
| --- | ---: | --- |
| Catskills armchair | 152 | `vaMaterialLeg` 2 件、`vaMaterialUpholstery` 76 件 |
| Nawabari アームチェア | 74 | `vaMaterialLeg` 1 件、`vaMaterialUpholstery` 74 件 |
| Nawabari アームチェア | 148 | `vaMaterialLeg` 2 件、`vaMaterialUpholstery` 74 件 |
| Catskills フットスツール | 152 | `vaMaterialLeg` 2 件、`vaMaterialUpholstery` 76 件 |
| Hamilton ダイニングチェア | 6 | `vaMaterialLeg` 2 件、`vaMaterialSeat` 3 件 |
| Squilla アームチェア、回転式 | 104 | `vaMaterialLeg` 1 件、`vaMaterialUpholstery` 104 件 |

対応:

- `vaMaterialUpholstery` がない商品向けに `vaMaterialSeat` fallback を追加した。
- Hamilton は fallback 前は 1 候補扱いだったが、対応後は 6 候補へ展開できた。
- `parse_product()` でも `selected_upholstery` に `vaMaterialSeat` の選択名を入れるようにした。

判断:

- 複数商品では attributeId 差異が実際に存在する。
- Phase 3 時点では、`vaMaterialSeat` を張地相当の比較軸として扱うことで CSV schema を維持する。
- 将来、椅子以外の商品カテゴリへ広げる場合は、構成属性を固定列ではなく key/value 形式で持つ設計を再検討する。

## 8. 残論点

- チェアカテゴリの 23 件が UI 上の全件か、追加読み込み API でさらに取得できるかは、全カテゴリ運用前にブラウザまたは API trace で確認する。
- Phase 3 PoC では 6 商品の候補抽出まで確認した。23 商品すべての全構成取得は、リクエスト数が大きくなるため運用上限決定後に実施する。
- 正式運用前に `BOEXIO_CONTACT_EMAIL` の正式値を決める。
