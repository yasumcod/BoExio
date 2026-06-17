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

全商品・全パターン取得では、チェア、ソファなど張地が多いカテゴリほど 1 商品あたりの variant 候補数が大きくなり、単一 workflow / 単一 job の逐次実行では完了前にタイムアウトまたは実行時間上限へ到達する可能性が高い。このため、今後は「全カテゴリを 1 つの workflow で一括取得する」ことを前提にせず、カテゴリごとに確実に完走できる workflow または workflow input を用意する方針とする。

カテゴリ別 workflow 方針:

- チェア、ソファのように張地・脚などの構成候補が多いカテゴリは、専用 workflow または専用 `workflow_dispatch` input で単独実行できるようにする。
- 軽いカテゴリは共通 workflow の category matrix で扱ってよいが、重いカテゴリとは同じ完了時間前提にしない。
- 1 回の実行で全カテゴリを網羅できなかった場合も、カテゴリ別成果物と集約 metadata から欠落カテゴリを特定し、該当カテゴリだけを再実行できるようにする。
- 完了判定は「workflow が成功したか」ではなく、「期待カテゴリ、期待商品 URL、期待 variant 候補がすべて成果物に現れているか」で行う。
- 全パターン取得の正式運用前に、カテゴリごとの商品数、variant 候補数、実行時間、失敗率を計測し、カテゴリ別の chunk_size と実行単位を決める。

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

全パターン欠落の主な仮説:

- GitHub Actions job または workflow 全体の実行時間上限に到達した。
- 張地が多い商品で variant URL 数が増え、`request_interval` を守った結果、想定より実行時間が伸びた。
- 一部カテゴリまたはチャンクの artifact が生成されず、集約時に欠落として扱われた。
- 取得途中の timeout / retry が積み重なり、後続商品または後続 variant まで到達しなかった。

この仮説はまだ原因確定ではないため、次回以降の全取得では `run_metadata.json` にカテゴリ別・チャンク別の期待件数と実取得件数を残し、timeout、retry、artifact 欠落、候補生成漏れを切り分ける。

### 6.1 completeness gate

全商品・全パターン取得では、完了判定を単一 boolean にしない。Phase 3 の `run_metadata.json` には、カテゴリ別の `category_completeness` と商品別の `product_variant_completeness` を出力し、次の 3 段階を分けて確認する。

- `discovery_complete`: `discovered_product_urls.csv` で発見した unique 商品 URL が、現在の discovery ロジック上すべて chunk matrix へ割り当てられた状態。カテゴリページに公式 total count がない場合、これは BoConcept サイト全体の絶対保証ではなく、現行 discovery ロジック上の完了を意味する。
- `fetch_attempt_complete`: 発見・割り当て済み商品と、商品ごとに生成した variant candidate がすべて fetch 対象として試行された状態。missing chunk、failed chunk、candidate 数と attempt 数の不一致、途中停止で false になる。
- `comparison_complete`: 差分比較に使える成功行が、期待 variant candidate 分そろった状態。fetch attempt が完了していても一部 variant が取得失敗または比較不可なら false になる。

商品別 completeness では、次の式を満たすかを記録する。

```text
variant_candidate_count = variant_fetch_attempt_count + variant_skipped_count
variant_fetch_attempt_count = variant_success_count + variant_failure_count
```

`variant_limit_per_product=0` の full variant mode では `variant_skipped_count` は原則 0 とする。`variant_limit_per_product > 0` または `product_limit_per_category > 0` の制限実行では、limit 適用を metadata に明示し、full run と同じ strict 判定は適用しない。

`product_limit_per_category=0`、`product_limit=0`、`variant_limit_per_product=0`、かつ `chunk_slug` filter なしの full run では、aggregate completeness を `overall_run_status` に反映する。

- 全カテゴリで `discovery_complete=true`、`fetch_attempt_complete=true`、`comparison_complete=true`: `success`
- fetch attempt は完了したが、一部 variant が取得失敗または比較不可: `partial_success`
- missing chunk、missing category、failed chunk、fetch attempt 未完了、candidate 数と attempt 数の不一致: `failed`

completeness が崩れた箇所は、既存 `ERROR_COLUMNS` を維持したまま `errors.csv` にも記録する。主な error code は `incomplete_product_discovery`、`missing_chunk_artifact`、`incomplete_variant_fetch`、`variant_candidate_count_mismatch`、`comparison_incomplete` とする。

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
- チェア、ソファなど重いカテゴリは、既存 workflow の `category_slug` と `chunk_size=1` で単独実行し、全カテゴリ一括実行の成功を前提にしない。
- カテゴリ別に `category_completeness` と `product_variant_completeness` を確認し、欠落があれば `discovery_complete`、`fetch_attempt_complete`、`comparison_complete` のどこで崩れたかを切り分ける。

### Step 7: カテゴリ別 workflow の運用化

- 今回の completeness gate 実装時点では、専用カテゴリ workflow は追加しない。
- 既存 workflow の `category_slug`、`chunk_slug`、`chunk_size`、`product_limit_per_category`、`variant_limit_per_product` input でカテゴリ単独 full run と chunk 単位再実行ができるため、ロジック重複を増やさない。
- チェア、ソファなど重いカテゴリの検証は、まず `category_slug=<対象>`、`chunk_size=1`、`product_limit_per_category=0`、`variant_limit_per_product=0` で行う。
- 実測したカテゴリ別実行時間と variant 候補数をもとに、それでも既存 workflow input では運用上不十分な場合だけ、共通 workflow を呼び出す wrapper として専用 workflow を検討する。
- 専用 workflow を追加しても、最終成果物は引き続き結合済みの `phase3_products_current.csv` と Phase 5 Excel レポートに集約する。

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
- Phase 3 discovery mode は `category-html` と `sitemap` を持つ。ローカル CLI の既定は後方互換の `category-html`、workflow の既定 input は `sitemap`。
- workflow は段階実行用に `run_profile` を持つ。次段階の標準は `chair-full`、全カテゴリ移行時は `all-full`、個別調整時は `custom` を使う。
- `chair-full` は `category_slug=chair`、`product_limit_per_category=0`、`variant_limit_per_product=0`、`discovery_mode=sitemap`、`chunk_size=1`、`request_interval=5`、`retries=2` を固定する。
- `all-full` はカテゴリ filter を空にし、同じ sitemap / full variant 条件で全 enabled カテゴリへ広げる。
- sitemap mode は `https://www.boconcept.com/sitemap.xml` から `https://www.boconcept.com/ja-jp/sitemap/products/` を発見し、`/ja-jp/p/` 商品 URL を母集団にする。
- 通常カテゴリ URL は公開総数と初期表示数の取得に使う。`?q=page--N` は `Disallow: */shop/*?q=*` に該当するため正式 discovery 経路にしない。
- sitemap mode の追加成果物は `sitemap_product_urls.csv`、`category_expected_counts.csv`、`classified_product_urls.csv`、`phase3_discovery_metadata.json`。
- 商品ページ metadata の `biProductGroup` / `itemCategory` により `Chairs`、`Sofas`、`Tables` を `chair`、`sofa`、`table` へ分類する。
- 商品マスター dedupe は `productMasterKey`、`superMasterKey`、canonical URL、sitemap URL の順でキーを決める。
- 商品 discovery の `discovery_complete` は、full run でカテゴリ公開総数と分類済み unique 商品マスター件数が一致し、unknown classification が 0 の場合だけ true とする。
- 受け入れ件数はチェア 80、ソファ 183、テーブル 39。
- 重複 `variant_key` と重複 `source_url` は最初の行を採用し、重複は `errors.csv` に記録する。
- 必須カテゴリ欠落と期待チャンク欠落は `failed`、生成済みチャンク内の取得失敗は `partial_success`。
- full run では aggregate completeness gate を適用し、candidate 数と attempt 数の不一致、missing chunk、fetch attempt 未完了を `failed` にする。
- fetch attempt が完了しているが一部 variant が取得失敗または比較不可の場合は `partial_success` とする。
- Release 本文には missing category、missing chunk、failed chunk に加え、`comparison_complete=false` のカテゴリを表示する。
- `max-parallel` の初期値は 2 から変更しない。増やす場合は 403/captcha/challenge がなく、安定 run が 2 回以上続き、サイト全体の実効リクエスト頻度が許容できることを確認してから検討する。
