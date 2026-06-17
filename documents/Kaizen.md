# Kaizen: 商品 discovery 再設計方針

作成日: 2026-06-17

## 1. 背景

BoConcept のカテゴリ初期 URL だけでは、カテゴリ内の商品を網羅できないことが判明した。

例: チェアカテゴリ

- 初期 URL: `https://www.boconcept.com/ja-jp/shop/チェア/`
- 初期表示: `24 / 80製品を表示中`
- `?q=page--2`: `48 / 80製品を表示中`
- `?q=page--3`: `72 / 80製品を表示中`
- `?q=page--4`: `80 / 80製品を表示中`

この挙動から、`?q=page--N` は単一ページではなく、N ページ分までの累積表示と見なせる。

一方で、BoConcept の `robots.txt` には次の除外がある。

```text
Disallow: */shop/*?q=*
```

そのため、現行の延長で `?q=page--N` を直接巡回して商品 URL を増やす設計は採用しない。

## 2. 問題

現在の Phase 3 discovery は、カテゴリ URL を 1 回取得し、その HTML 内の `/ja-jp/p/` 商品リンクを集める構造である。

この方式では、初期表示分の商品しか取得できないカテゴリがある。

影響:

- full run が実際には full ではない。
- `category_completeness.discovery_complete=true` の意味が崩れる。
- カテゴリ別の商品欠落を検知できない。
- `?q=page--N` を追加すれば技術的には補えるが、現行の robots / compliance 方針と衝突する。

## 3. 推奨方針

`?q=page--N` を商品 URL discovery の正式経路にしない。

代わりに、次の sitemap-driven discovery に切り替える。

1. `https://www.boconcept.com/sitemap.xml` を取得する。
2. `https://www.boconcept.com/ja-jp/sitemap/products/` を取得する。
3. sitemap 内の `/ja-jp/p/...` 商品 URL を商品候補の母集団にする。
4. 各商品ページを取得し、商品ページ内の構造化データまたは Next.js payload からカテゴリ判定用 metadata を抽出する。
5. `productMasterKey` または `superMasterKey` で商品マスター単位に dedupe する。
6. 通常カテゴリ URL から取得した公開総数と、分類後の商品マスター件数を照合する。

抽出候補 metadata:

- `productMasterKey`
- `superMasterKey`
- `biProductGroup`
- `biProductType`
- `itemCategory`
- `itemCategory2`
- `isOutlet`

実確認では、商品ページに `biProductGroup` / `itemCategory` が含まれる例がある。

例: Reno 商品ページ

- `biProductGroup`: `Chairs`
- `itemCategory`: `Chairs`
- `itemCategory2`: `Living chairs`

## 4. Completeness の再定義

商品 discovery complete と variant complete を分ける。

商品 discovery complete:

- 通常カテゴリ URL から公開総数を取得できる。
- sitemap 由来の商品 URL を商品ページ metadata で分類できる。
- 分類後の商品マスター件数がカテゴリ公開総数と一致する。

variant complete:

- 各商品で抽出した variant candidate 数を記録する。
- 取得 attempt 数と candidate 数を照合する。
- 失敗 URL、HTTP error、schema mismatch、captcha / challenge 疑いを metadata に残す。

full run は、上記 2 種類の complete を別々に判定する。

## 5. 調査結果

2026-06-17 時点の確認結果。

### product sitemap

`https://www.boconcept.com/ja-jp/sitemap/products/` には、日本語の商品 URL が 1350 件含まれていた。

### チェア

通常カテゴリ URL:

`https://www.boconcept.com/ja-jp/shop/チェア/`

確認結果:

- 公開総数: 80 アイテム
- 初期表示: 24 / 80
- `?q=page--4` 相当で 80 / 80

補足:

- `?q=page--N` は robots.txt の `Disallow: */shop/*?q=*` に該当するため、正式 discovery 経路にはしない。
- 検算では、`?q=page--4` の 80 商品 URL のうち 79 件が product sitemap の URL と完全一致した。
- 1 件は sitemap 側に同シリーズ別 URL があり、商品マスター単位の dedupe / 照合が必要。

### ソファ

通常カテゴリ URL:

`https://www.boconcept.com/ja-jp/shop/ソファ/`

確認結果:

- 公開総数: 183 アイテム
- 初期表示: 24 / 183

sitemap-driven discovery では、ソファカテゴリの期待商品マスター数を 183 件として扱う。

実装時は product sitemap 由来の商品ページから `biProductGroup=Sofas` または同等の `itemCategory` を抽出し、商品マスター単位に dedupe した件数が 183 件に一致するかを gate にする。

### テーブル

通常カテゴリ URL:

`https://www.boconcept.com/ja-jp/shop/テーブル/`

確認結果:

- 公開総数: 39 アイテム
- 初期表示: 24 / 39

sitemap-driven discovery では、テーブルカテゴリの期待商品マスター数を 39 件として扱う。

実装時は product sitemap 由来の商品ページから `biProductGroup=Tables` または同等の `itemCategory` を抽出し、商品マスター単位に dedupe した件数が 39 件に一致するかを gate にする。

## 6. 実装ステップ

### Step 1: sitemap reader を追加する

新規処理:

- sitemap index から `ja-jp/sitemap/products/` を発見する。
- product sitemap から `/ja-jp/p/` URL を抽出する。
- URL は既存の `validate_discovered_product_url()` で検証する。

出力候補:

- `sitemap_product_urls.csv`
- `sitemap_discovery_metadata.json`

### Step 2: 商品ページ metadata extractor を追加する

各商品ページからカテゴリ判定用 metadata を抽出する。

抽出できなかった商品は除外せず、`category_classification_status=unknown` として metadata / errors に残す。

出力候補:

- `classified_product_urls.csv`
- `product_master_key`
- `super_master_key`
- `bi_product_group`
- `bi_product_type`
- `item_category`
- `item_category2`
- `classification_status`
- `classification_error`

### Step 3: カテゴリ公開総数 reader を追加する

通常カテゴリ URL だけを取得し、`80アイテム`、`183アイテム`、`39アイテム` のような公開総数を抽出する。

`?q=page--N` は取得しない。

出力候補:

- `category_expected_counts.csv`
- `category_name`
- `category_url`
- `category_slug`
- `expected_product_count`
- `initial_visible_count`

### Step 4: discovery completeness gate を更新する

カテゴリごとに次を比較する。

- `expected_product_count`
- `classified_unique_product_master_count`
- `unknown_classification_count`
- `duplicate_variant_url_count`

判定:

- 件数一致かつ unknown なし: `discovery_complete=true`
- 件数不一致または unknown あり: `discovery_complete=false`

### Step 5: 既存 Phase 3 へ接続する

`classified_product_urls.csv` から対象カテゴリの商品代表 URL を選び、既存の variant candidate 抽出へ渡す。

代表 URL 選定ルール:

- 同一 `productMasterKey` / `superMasterKey` は 1 商品として扱う。
- `isDefault=true` の variant URL を優先する。
- default が複数または不明な場合は、sitemap 順または canonical URL を採用し、理由を metadata に残す。

## 7. 未解決事項

- Relewise 商品検索 API を正式利用してよいか。
- product sitemap とカテゴリ公開総数が一致しない場合、どちらを正とするか。
- `productMasterKey` と `superMasterKey` のどちらを商品マスター主キーにするか。
- outlet 商品を対象に含めるか。
- sitemap にあるがカテゴリ分類できない商品をどう扱うか。

## 8. 当面の推奨

まずチェア、ソファ、テーブルの 3 カテゴリで sitemap-driven discovery の PoC を行う。

受け入れ条件:

- チェア: 80 件に一致する。
- ソファ: 183 件に一致する。
- テーブル: 39 件に一致する。
- `?q=page--N` を取得しない。
- 不一致がある場合は、商品 URL、product master key、抽出 metadata、分類不能理由を CSV に残す。

## 9. 実装状況

2026-06-17 時点で Phase 3 に sitemap-driven discovery を実装した。

実装ファイル:

- `boexio/phase3_discovery.py`
- `boexio/phase3_master.py`
- `boexio/phase3_matrix.py`
- `boexio/phase3_merge.py`
- `.github/workflows/boexio-weekly.yml`

固定した仕様:

- 既存互換のため、ローカル CLI の既定 `--discovery-mode` は `category-html` のままにする。
- workflow の `discover-products` では `--discovery-mode sitemap` を明示する。
- `--product-urls-file` / `--product-plan-file` 指定時は、従来どおり discovery をスキップする。
- sitemap mode は `https://www.boconcept.com/sitemap.xml` から `https://www.boconcept.com/ja-jp/sitemap/products/` を発見し、`/ja-jp/p/` 商品 URL だけを候補にする。
- `*/shop/*?q=*` と `*/p/*/print/` は discovery fetch 対象にしない。
- 商品分類は `biProductGroup` / `itemCategory` の `Chairs`、`Sofas`、`Tables` をそれぞれ `chair`、`sofa`、`table` に対応させる。
- 商品マスター dedupe は `productMasterKey`、`superMasterKey`、canonical URL、sitemap URL の順でキーを決める。
- 代表 URL は `isDefault=true` の variant URL、canonical URL、sitemap 順の順で選ぶ。
- `discovery_complete` はカテゴリ公開総数と分類済み unique 商品マスター件数の一致、かつ unknown classification なしを意味する。
- `fetch_attempt_complete` / `comparison_complete` は既存どおり variant 取得段階の判定として分ける。
- 次段階の本番検証用に workflow `run_profile=chair-full` を追加し、チェアだけ全商品・全パターンを取得する設定を固定する。
- チェア検証後は同じ workflow の `run_profile=all-full` で全 enabled カテゴリへ移行できる。

追加 artifact:

- `sitemap_product_urls.csv`
- `category_expected_counts.csv`
- `classified_product_urls.csv`
- `phase3_discovery_metadata.json`

追加 metadata:

- `discovery_mode`
- `sitemap_product_url_count`
- `category_expected_counts`
- `category_completeness.*.expected_product_count`
- `category_completeness.*.classified_unique_product_master_count`
- `category_completeness.*.unknown_classification_count`
- `category_completeness.*.duplicate_product_url_count`
- `category_completeness.*.deduped_product_count`

追加した error code:

- `sitemap_parse_failed`
- `product_classification_failed`
- `product_classification_unknown`
- `product_master_key_missing`
- `incomplete_product_discovery`
- `discovery_count_mismatch`
- `robots_disallowed_discovery_url`
