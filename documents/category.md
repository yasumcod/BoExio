# カテゴリ分割実行設計

作成日: 2026-05-27

## 1. 目的

全カテゴリ、全商品、全パターンを 1 つの GitHub Actions job で逐次取得すると、GitHub-hosted runner の実行時間上限に近づく。カテゴリ単位で取得 job を分割し、重いカテゴリは商品チャンク単位まで細分化し、最後に成果物を集約することで、実行時間、障害切り分け、再実行範囲を管理しやすくする。

この資料では、Phase 3 の商品取得をカテゴリ単位に分割し、Phase 4 以降は結合済みの商品マスタに対して既存処理を継続する設計を定義する。

## 2. 背景

現在の週次実行は次の制御で動く。

- 対象カテゴリ: `config/target_categories.csv`
- カテゴリごとの商品上限: `product_limit_per_category`
- 商品ごとのパターン上限: `variant_limit_per_product`
- リクエスト間隔: `request_interval`
- 商品一覧データ: `phase3_products_current.csv`

現在の標準実行は、カテゴリごとに 3 商品、商品ごとに 1 パターンを取得するため短時間で完了する。一方、全商品、全パターンを対象にすると、リクエスト数は大きく増える。

概算式:

```text
総リクエスト数 = カテゴリページ数 + 商品ページ数 + 全商品の全パターンページ数
```

現行の逐次実行では `request_interval=5` 秒が各リクエストに効くため、全取得時は 1 job の実行時間上限に到達する可能性がある。

## 3. 方針

カテゴリ単位で商品 URL を発見し、商品 URL を 5 件単位のチャンクへ分割する。取得は商品チャンク単位の matrix job で実行し、最後にチャンク成果物を 1 つの Phase 3 出力へ集約する。

処理構成:

1. `discover-categories`
2. `discover-products`
3. `scrape-product-chunk`
4. `merge-report`

`scrape-product-chunk` は GitHub Actions matrix でチャンクごとに実行する。`merge-report` は全チャンクの成果物をダウンロードし、Phase 3 の CSV を結合してから Phase 4、Phase 5、Phase 6 を実行する。

## 4. ワークフロー構成

### 4.1 discover-categories

目的:

- `config/target_categories.csv` から `enabled=true` のカテゴリを読み込む。
- matrix 用 JSON を生成する。

出力例:

```json
{
  "include": [
    {
      "category_name": "チェア",
      "category_url": "https://www.boconcept.com/ja-jp/shop/チェア/",
      "category_slug": "chair"
    }
  ]
}
```

設計メモ:

- `category_slug` は artifact 名と run_id に使う。
- 日本語カテゴリ名をそのまま artifact 名に使わない。
- `enabled=false` のカテゴリは matrix に含めない。
- 実装は `boexio/phase3_master.py` の `category_slug()` で固定する。
- 既存カテゴリは明示 mapping を使う: `チェア=chair`、`ソファ=sofa`、`テーブル=table`、`ベッド=bed`、`収納=storage`、`ランプ=lamp`、`ラグ=rug`、`アクセサリー=accessories`、`アウトドア家具=outdoor-furniture`。
- mapping にないカテゴリは、URL 末尾を ASCII 化できる場合はそれを slug 化し、ASCII 化できない場合は `category-<sha1先頭10桁>` にする。このため日本語カテゴリ名そのものは artifact 名に出ない。

### 4.2 discover-products

目的:

- カテゴリごとの商品 URL を先に発見する。
- 発見した商品 URL をチャンクに分ける。
- チャンク matrix 用 JSON を生成する。

出力例:

```json
{
  "include": [
    {
      "category_name": "チェア",
      "category_url": "https://www.boconcept.com/ja-jp/shop/チェア/",
      "category_slug": "chair",
      "chunk_index": 1,
      "chunk_slug": "chair-001",
      "product_urls": [
        "https://www.boconcept.com/ja-jp/p/catskills/4060001-9:0708s-14:3320/"
      ]
    }
  ]
}
```

チャンク分割ルール:

- 初期値は 1 チャンク 5 商品。
- 商品数が少ないカテゴリは 1 チャンクでよい。
- 1 商品の構成候補が 100 パターン以上あるカテゴリは、チャンクサイズを 1 から 3 商品へ落とす。
- `product_limit_per_category=0` の場合は、そのカテゴリで発見した全商品をチャンク化する。
- `variant_limit_per_product=0` は各商品の pending variant candidate を全件取得する意味にする。
- `chunk_slug` は `<category_slug>-NNN` とする。例: `chair-001`。

### 4.3 scrape-product-chunk

目的:

- 1 job で 1 チャンクだけを取得する。
- チャンク内の商品について、商品ページとパターンページを取得する。
- 取得結果をチャンク単位の artifact として保存する。

実行イメージ:

```bash
python3 scripts/phase3_master.py \
  --run-id "weekly-YYYY-MM-DD-${GITHUB_RUN_ID}-${chunk_slug}" \
  --category-url "$category_url" \
  --product-urls-file "$product_urls_file" \
  --variant-limit-per-product "$variant_limit_per_product" \
  --request-interval "$request_interval" \
  --retries "$retries"
```

必要な実装変更:

- `phase3_master.py` に `--category-name` または `--category-url` フィルタを追加する。
- `phase3_master.py` に `--product-urls-file` を追加し、発見済み商品 URL の一部だけを処理できるようにする。
- 指定されたカテゴリだけを `target_categories` として処理できるようにする。
- 出力ディレクトリはチャンクごとに分ける。

出力 artifact:

- `products_current.csv`
- `products_YYYY-MM-DD_<run_id>.csv`
- `variant_candidates.csv`
- `discovered_product_urls.csv`
- `errors.csv`
- `scrape_log.txt`
- `run_metadata.json`
- `raw/`

artifact 名:

```text
boexio-weekly-chunk-<run_date>-<chunk_slug>
```

### 4.4 merge-report

目的:

- 全チャンク artifact を取得する。
- チャンク別の Phase 3 CSV を結合する。
- 結合済み CSV を使って Phase 4、Phase 5、Phase 6 を既存通り実行する。

入力:

- 各チャンクの `products_current.csv`
- 各チャンクの `variant_candidates.csv`
- 各チャンクの `discovered_product_urls.csv`
- 各チャンクの `errors.csv`
- 各チャンクの `run_metadata.json`

出力:

- `phase3_products_current.csv`
- `phase3_products_snapshot.csv`
- `phase3_variant_candidates.csv`
- `phase3_discovered_product_urls.csv`
- `phase3_errors.csv`
- `phase3_run_metadata.json`
- `phase5_weekly_report.xlsx`
- `phase6_metadata.json`
- Release assets

結合ルール:

- CSV ヘッダーは既存スキーマ順を維持する。
- `products_current.csv` は `variant_key` を主キー候補として扱う。
- 同一 `variant_key` が複数カテゴリに出た場合は、最初の行を採用し、重複は `phase3_errors.csv` に記録する。
- `source_url` が同じ重複も同様に記録する。
- `errors.csv` は全カテゴリ分を単純結合する。
- `run_metadata.json` はチャンク別 metadata を配列で保持し、集約 metadata にカテゴリ別件数とチャンク別件数を残す。

## 5. 並列数とアクセス制御

matrix 並列数は初期値を `max-parallel: 2` にする。

`2` は同時に実行する取得 job の最大数を意味する。チャンク job が 20 個作られても、同時に動くのは最大 2 個だけに制限する。

理由:

- 各 job 内で `request_interval=5` 秒を守っても、並列数を増やすとサイト全体への実効アクセス頻度が上がる。
- 403、captcha、challenge のリスクを抑える。
- カテゴリごとの負荷差を確認しながら段階的に増やせる。

初期設定:

```yaml
strategy:
  fail-fast: false
  max-parallel: 2
```

運用ルール:

- 403、captcha、challenge が出た場合は即時に並列数を増やさない。
- 安定 run が 2 回続いた場合のみ `max-parallel: 3` を検討する。
- `request_interval` はチャンク job ごとではなく、サイト全体の実効頻度を意識して決める。
- `max-parallel: 2`、`request_interval=5` 秒の場合、サイト全体では約 2.5 秒に 1 リクエスト相当になる。

## 6. 失敗時の扱い

チャンク分割では、1 カテゴリまたは 1 チャンクの失敗で全成果物を完全に失うことは避ける。

扱い:

- `scrape-product-chunk` はチャンク内の取得失敗を `errors.csv` と `run_metadata.json` に残す。
- GitHub Actions job 自体の失敗はチャンク artifact が欠ける原因になるため、`merge-report` で欠落チャンクを検出する。
- 欠落カテゴリがある場合、`overall_run_status` は `partial_success` または `failed` にする。
- 必須カテゴリの欠落、商品数 0 のカテゴリ、または期待されたチャンク artifact 欠落は `overall_run_status=failed` とする。
- チャンク artifact が存在し、当該チャンクの `run_status=failed` または `partial_success` の場合は、集約成果物を残したうえで `overall_run_status=partial_success` とする。
- 重複 `variant_key` / `source_url` は最初の行を採用し、重複行は `errors.csv` に残す。重複が出た run は `partial_success` とする。
- Release は作成し、欠落カテゴリと失敗理由を `phase6_metadata.json` と Release 本文に残す。

再実行方針:

- 失敗カテゴリまたは失敗チャンクだけを `workflow_dispatch` で再実行できるようにする。
- 再実行時は `category_slug` または `chunk_slug` を input で指定できる。`chunk_slug` だけで再実行する場合も、可能な限り対応する `category_slug` を併せて指定する。
- `chunk_size` input の既定値は `5`。`product_limit_per_category=0` はカテゴリ内全商品、`variant_limit_per_product=0` は全パターン取得を意味する。
- 最終的な Release 更新は `merge-report` だけが行う。

## 7. GitHub Release への反映

Release の作成、編集、asset upload は `merge-report` job のみで行う。

カテゴリ job とチャンク job では Release に直接 upload しない。

理由:

- asset 名の衝突を避ける。
- Release 本文の run_status を集約結果に合わせる。
- GitHub Release API の一時障害時の再試行を 1 箇所に集約する。

## 8. 段階導入

### Step 1: カテゴリフィルタ追加

- `phase3_master.py` にカテゴリフィルタを追加する。
- 既存の単体実行と後方互換にする。
- `config/target_categories.csv` 全件実行は従来通り動かす。

### Step 2: チャンク別 artifact 生成

- workflow に `scrape-product-chunk` matrix job を追加する。
- 初期は 1 カテゴリ 1 チャンクとして動かす。
- まず `product_limit_per_category=3`、`variant_limit_per_product=1` で検証する。

### Step 3: 商品チャンク matrix 生成

- `discover-products` job を追加する。
- カテゴリごとに発見した商品 URL を 5 商品単位のチャンクへ分ける。
- 軽いカテゴリは 1 チャンク、チェアやソファは複数チャンクに分かれることを確認する。

### Step 4: 集約スクリプト追加

- チャンク別 CSV を結合するスクリプトを追加する。
- Phase 4 以降が結合済みディレクトリを入力にできることを確認する。

### Step 5: 全商品取得

- `product_limit_per_category=0` で全商品を対象にする。
- まず `variant_limit_per_product=1` のまま実行する。
- カテゴリ別件数、失敗率、実行時間を確認する。

### Step 6: 全パターン取得

- `variant_limit_per_product=0` を全パターン取得の意味に拡張する。
- `max-parallel: 2` を維持し、全チャンク完了時間、重い商品、失敗率を確認する。

## 9. 商品チャンク分割の具体例

チェアカテゴリに 23 商品ある場合、5 商品単位では次のように分割する。

```text
chair-001: 商品 1 から 5
chair-002: 商品 6 から 10
chair-003: 商品 11 から 15
chair-004: 商品 16 から 20
chair-005: 商品 21 から 23
```

ソファカテゴリに 22 商品ある場合も同様に 5 チャンク程度へ分ける。

実行時の見え方:

```text
実行中:
  chair-001
  chair-002

待機中:
  chair-003
  chair-004
  sofa-001
  sofa-002
  table-001
```

`max-parallel: 2` のため、待機中の job が多くても同時実行は 2 つまでになる。

チャンク単位:

- 初期値は 5 商品単位。
- 重い商品がある場合は 1 商品単位まで落とす。
- チャンク単位でも Release には直接 upload しない。
- 最終成果物はカテゴリ別ではなく、結合済みの `phase3_products_current.csv` とする。

導入判断:

- 1 カテゴリ job が 2 時間を超える。
- ソファ、チェアなど一部カテゴリだけ構成候補数が極端に多い。
- 1 商品で 100 パターン以上の取得が継続的に発生する。

## 10. 実装で固定した事項

- `category_slug` は既存カテゴリ mapping 優先、未知カテゴリは ASCII slug または `category-<sha1先頭10桁>`。
- チャンク取得の公式 input は `--category-name`、`--category-url`、`--category-slug`、`--chunk-slug`、`--product-urls-file`。
- 重複 `variant_key` と重複 `source_url` は最初の行を採用し、重複は `errors.csv` に記録する。
- 必須カテゴリ欠落と期待チャンク欠落は `failed`、生成済みチャンク内の取得失敗は `partial_success`。
- `max-parallel` の初期値は 2 から変更しない。増やす場合は 403/captcha/challenge がなく、安定 run が 2 回以上続き、サイト全体の実効リクエスト頻度が許容できることを確認してから検討する。
