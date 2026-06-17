# BoExio 作業サマリー

作成日: 2026-05-23
更新日: 2026-05-27

## 今日実装したところ

### Phase 1 仕上げ

- `task.md` を `documents/task.md` に移動した。
- Phase 1 PoC の URL スコープを固定した。
  - 手動投入 URL は `/ja-jp/shop/` 配下のみ。
  - カテゴリから発見した `/ja-jp/p/` 商品詳細 URL のみ取得許可。
- `documents/compliance_checklist.md` に robots.txt、利用規約、User-Agent、連絡先未確定事項を整理した。
- `boexio/phase1_poc.py` を更新した。
  - User-Agent を `BOEXIO_CONTACT_EMAIL` で差し替え可能にした。
  - Python SSL 証明書エラー時も `curl` フォールバックするようにした。
  - `run_metadata.json` の `output_files` に raw capture と metadata 自身を含めるようにした。
  - metadata 自身の checksum は自己参照になるため `output_file_checksums` から除外した。
  - `display_price` が「から」価格で `list_price` が取れる場合、`list_price` を `canonical_price` に入れる方針へ寄せた。

検証 run:

```text
data/runs/phase1-finish-check-success/
```

検証コマンド:

```text
python3 -m py_compile boexio/phase1_poc.py scripts/phase1_poc.py
python3 scripts/phase1_poc.py --run-id phase1-finish-check-success
```

### Phase 2 構成バリエーション取得

追加ファイル:

```text
boexio/phase2_variants.py
scripts/phase2_variants.py
documents/phase2_variant_findings_ja.md
```

実装内容:

- Catskills 商品ページ HTML 内の Next.js データ `configuration.options` から構成候補を抽出した。
- 脚 2 件、張地 76 件、合計 152 件の候補を生成できることを確認した。
- `variantUrlKey` と `selectedOptions` から variant URL を組み立てる処理を実装した。
- `variant_candidates.csv` に全 152 候補を出力するようにした。
- `--variant-limit` / `--variant-offset` で取得する variant 件数と開始位置を制御できるようにした。
- `products_poc.csv` に複数構成行を出力できるようにした。
- 2 種類目の脚も少数取得で確認した。

Phase 2 で追加した CSV 列:

```text
variant_key
variant_key_from
variant_key_error_type
variant_key_error_detail
list_price_value
display_price_value
canonical_price_value
price_compare_value
price_compare_from
price_normalization_error
```

比較キー:

- 第 1 候補: `variant_id`
- 第 2 候補: `sku`
- 第 3 候補: `item_number + selected_size + selected_upholstery + selected_leg`

属性正規化:

- trim
- 小文字化
- NFKC
- 空白圧縮
- 記号統一
- 初期表記ゆれ辞書
  - `ファブリック -> fabric`
  - `レザー` / `革 -> leather`
  - `オーク -> oak`
  - `無垢材 -> solid wood`
  - `自然 -> natural`
  - `暗色 -> dark`

価格正規化:

- `list_price_value`
- `display_price_value`
- `canonical_price_value`
- `price_compare_value`
- `price_compare_from`

現時点の方針:

- `display_price` は「から」価格の証跡として保持する。
- 差分比較候補は `canonical_price` 優先、なければ `list_price`。
- `price_compare_value` は数値文字列で持つ。

errors:

- `phase2_errors.csv` を追加した。
- 列は `url`, `phase`, `error_code`, `message`, `first_seen_at`, `last_seen_at`。
- 取得失敗、比較キー生成失敗、価格正規化失敗を Phase 4 / 5 の errors に接続できる形にした。

検証 run:

```text
data/runs/phase2-final-check-v021/
data/runs/phase2-second-leg-check/
```

検証コマンド:

```text
python3 -m py_compile boexio/phase1_poc.py boexio/phase2_variants.py scripts/phase1_poc.py scripts/phase2_variants.py
python3 scripts/phase2_variants.py --run-id phase2-final-check-v021 --variant-limit 1
python3 scripts/phase2_variants.py --run-id phase2-second-leg-check --variant-offset 76 --variant-limit 2
```

## 現在の到達点

- Phase 1 仕上げは、社内決定が必要な URL 管理者・承認者以外は完了。
- Phase 2 は、Catskills 1 商品について候補抽出、複数構成取得、比較キー生成、価格数値化、errors 出力準備まで完了。
- Phase 3 は、カテゴリから複数商品 URL を収集し、商品ごとの構成候補抽出、取得制御、`products_current.csv` と日付付き snapshot 出力、run 全体の失敗判定まで実装済み。
- Phase 3 は `config/target_categories.csv` の有効カテゴリをすべて巡回し、既定でカテゴリごとに 3 商品ずつ取得する段階へ移行した。全体上限は `--product-limit`、カテゴリ別上限は `--product-limit-per-category` で制御する。
- `products_current.csv`、日付付き snapshot、Phase 5 の `current_master` には `category_name` / `category_url` を出力する。
- 検証 run `data/runs/phase3-smoke-check-success/` では、チェアカテゴリから 23 商品 URL、Catskills 1 商品から 152 構成候補を抽出し、1 構成を `products_current.csv` に出力できた。
- 検証 run `data/runs/phase3-catskills-all-variants/` では、Catskills 152 構成を 5 秒間隔・単一接続で全件取得し、152 行すべて成功した。SKU、variant_key、price_compare_value の欠損は 0。
- 検証 run `data/runs/phase3-multi-product-attribute-check-v2/` では、6 商品の候補抽出を確認した。Hamilton は `vaMaterialUpholstery` ではなく `vaMaterialSeat` を使うため、fallback を実装して 6 候補へ展開できるようにした。
- Playwright は現時点では不要。HTML 内 Next.js データと variant URL 取得で進められる。
- カテゴリ HTML では商品 URL 23 件を確認した。`pageParams` は `[1]`、`rel="next"` はなし。HTML 内の `Load more` は翻訳辞書内の汎用文言で、商品一覧追加読み込みボタンとは断定しない。
- Phase 3 検証資料は `documents/phase3_master_findings_ja.md` に整理した。
- Phase 4 は、前回 CSV と今回 CSV の差分検知、価格変更 / 新規 / 削除候補 / 比較不可 errors の分離、schema version 不一致停止、削除候補の状態遷移まで実装済み。
- 検証 run `data/runs/phase4-fixture-check/` では、価格変更 1 件、新規 1 件、削除候補 1 件、通貨不一致 1 件を期待どおり検出した。
- 検証 run `data/runs/phase4-same-csv-check/` では、Catskills 152 行同士の比較で差分 0、errors 0 を確認した。
- 検証 run `data/runs/phase4-smoke-to-full-check/` では、1 行から 152 行への比較で新規 151 件を検出した。
- `tests/test_phase4_diff.py` を追加し、価格変更、added / removed、`discontinued`、`revived`、通貨不一致、schema 不一致を単体テストで確認した。
- Phase 4 検証資料は `documents/phase4_diff_findings_ja.md` に整理した。
- Phase 5 は、Phase 4 の差分 CSV と Phase 3 の商品マスタから 6 シートの Excel レポートを生成できる状態まで実装済み。
- 検証 run `data/runs/phase5-smoke-report/` では、`weekly_report_2026-05-23_phase5-smoke-report.xlsx` を生成した。
- Excel には `summary`、`price_changes`、`added`、`removed`、`current_master`、`errors` の 6 シートが含まれる。
- `tests/test_phase5_report.py` を追加し、summary 集計、必須 6 シート、errors 必須列欠損時の失敗を単体テストで確認した。
- Phase 5 検証資料は `documents/phase5_report_findings_ja.md` に整理した。
- Phase 7 実装として `boexio/quote_columns.py` を追加し、営業向け標準カラム順をコード上に固定した。
- Phase 5 の `current_master` シートは、識別、商品、構成、価格、状態、参照、監査の順に出力するよう更新した。
- `current_state`、`missing_streak` など既存 CSV にない状態列は空欄で出力する。
- `parser_version`、`schema_version` は Phase 3 の `run_metadata.json` から Phase 5 Excel 側へ補完し、metadata がない場合も空欄で壊れないようにした。
- `source_url` は標準確認導線として残し、空の場合は `source_url_review_required=yes` で見積確定前の手動確認対象にする。
- Phase 7 標準カラムに `category_name` / `category_url` を追加し、営業確認時にカテゴリ別で商品を見られるようにした。

### Phase 6 定期実行

- Phase 6 は実装済み。
- workflow は `.github/workflows/boexio-weekly.yml`。
- `workflow_dispatch` と毎週日曜 15:00 JST 相当の cron `0 6 * * 0` で起動できる。
- `workflow_dispatch` は `product_limit_per_category` でカテゴリごとの取得商品数を指定できる。既定は 3 件、`product_limit=0` は全体上限なし。
- Phase 3、Phase 4、Phase 5 を順に実行し、成果物を `artifacts/` に集約する。
- GitHub Actions artifact は 30 日保持、GitHub Releases は初期 3 年保存とする。
- `BOEXIO_CONTACT_EMAIL` と `BOEXIO_NOTIFY_WEBHOOK_URL` は任意 secret として扱い、未設定でも workflow は失敗しない。
- `tests/test_phase6_workflow.py` を追加し、Release 名、前回 CSV 初期化、成果物 staging、UTF-8 BOM 出力を確認した。

### 運用メモと品質ゲート

- Phase 6 運用メモ `documents/operations_runbook_ja.md` を追加した。
- 停止後の再開手順、初期監視通知、robots.txt / 利用規約の確認頻度、障害時復旧目標、保存期間を定義した。
- `documents/compliance_checklist.md` に robots.txt と利用規約の定期確認頻度を追記した。
- `tests/test_phase2_variants.py` を追加し、比較キー生成、属性正規化、Phase 2 CSV fixture、HTML fixture からの parser 回帰を確認した。
- fixture は `tests/fixtures/phase2_products_fixture.csv` と `tests/fixtures/phase2_product_fixture.html`。
- 通常テストはネットワーク取得を伴わずに実行できる。

### Phase 7 見積運用連携

- Phase 7 設計資料 `documents/phase7_quote_integration_ja.md` を追加した。
- 営業確認に必要な標準カラムを棚卸しした。
- 営業が参照する標準ファイルは `phase5_weekly_report.xlsx`、`phase3_products_current.csv`、`phase6_metadata.json` とした。
- 見積前の元ページ確認導線は `source_url` とする。
- 価格履歴監査は GitHub Releases を正本とし、初期保存期間は 3 年とする。
- 複数カテゴリへ広げる判断基準と、全商品カテゴリへ広げる前の受け入れ条件を定義した。
- 全商品、全パターン取得に向けたカテゴリ分割実行設計を `documents/category.md` に追加した。
- 設計方針は、カテゴリ一覧から商品 URL を発見し、重いカテゴリは商品チャンク単位へ分割し、GitHub Actions matrix を `max-parallel: 2` で実行して最後に `phase3_products_current.csv` へ集約する。
- カテゴリ/チャンク分割実行を実装した。
  - `scripts/phase3_matrix.py` で enabled カテゴリ matrix と商品チャンク matrix を生成する。
  - `category_slug` は既存カテゴリ mapping 優先、未知カテゴリは ASCII 化または `category-<sha1先頭10桁>` にする。
  - チャンク初期値は 5 商品、`chunk_slug` は `<category_slug>-NNN`。
  - `scripts/phase3_master.py` は `--product-urls-file` 指定時にカテゴリ discovery をスキップし、その URL だけを処理する。
  - `variant_limit_per_product=0` は全 pending variant candidate の取得として扱う。
  - `scripts/phase3_merge.py` でチャンク CSV と metadata を集約し、従来互換の `products_current.csv` を生成する。
  - 重複 `variant_key` / `source_url` は最初の行を採用し、重複は `errors.csv` に残す。
  - 必須カテゴリ欠落または期待チャンク欠落は `failed`、生成済みチャンク内の失敗は `partial_success` とする。
- 全商品・全パターン取得向けの completeness gate を追加した。
  - `run_metadata.json` にカテゴリ別 `category_completeness` と商品別 `product_variant_completeness` を出力する。
  - `discovery_complete`、`fetch_attempt_complete`、`comparison_complete` を分け、単一 boolean の「全件取得」判定にしない。
  - full run は `product_limit=0`、`product_limit_per_category=0`、`variant_limit_per_product=0`、`chunk_slug` filter なしとして扱い、candidate 数と attempt 数の不一致や missing chunk を `failed` にする。
  - fetch attempt が完了しているが一部 variant が取得失敗または比較不可の場合は `partial_success` にする。
  - 制限実行では strict full run 判定を適用せず、limit 適用を metadata に残す。
  - Release 本文には missing category、missing chunk、failed chunk に加え、`comparison_complete=false` のカテゴリを表示する。
  - 専用カテゴリ workflow は追加せず、既存 workflow の `category_slug` と `chunk_size=1` でチェア、ソファなど重いカテゴリを単独検証する方針にした。
- `.github/workflows/boexio-weekly.yml` は `discover-categories`、`discover-products`、`scrape-product-chunk`、`merge-report` の 4 job 構成になった。
  - `scrape-product-chunk` は `strategy.fail-fast: false`、`max-parallel: 2`。
  - Release 作成、編集、asset upload は `merge-report` のみで実行する。
  - 再実行 input として `chunk_size`、`category_slug`、`chunk_slug` を追加した。
- Phase 3 商品 discovery を sitemap-driven に対応した。
  - 新規 `boexio/phase3_discovery.py` で product sitemap 抽出、カテゴリ公開総数抽出、商品 metadata 分類、商品マスター dedupe、公開総数照合を実装した。
  - `scripts/phase3_master.py` / `scripts/phase3_matrix.py` に `--discovery-mode category-html|sitemap`、`--sitemap-url`、`--product-sitemap-url` を追加した。
  - ローカル CLI の既定は後方互換の `category-html`、workflow の既定 input は `sitemap` とした。
  - `?q=page--N` は正式 discovery 経路にしない。通常カテゴリ URL は公開総数と初期表示数の取得にだけ使う。
  - sitemap mode は `sitemap_product_urls.csv`、`category_expected_counts.csv`、`classified_product_urls.csv`、`phase3_discovery_metadata.json` を追加出力する。
  - 商品 discovery complete は `expected_product_count == classified_unique_product_master_count` かつ `unknown_classification_count == 0` の意味に再定義し、variant の `fetch_attempt_complete` / `comparison_complete` と分離した。
  - チェア 80 件、ソファ 183 件、テーブル 39 件を sitemap discovery の受け入れ件数として扱う。
- チェア単独の本番 full run 用に workflow `run_profile=chair-full` を追加した。
  - `chair-full` は `category_slug=chair`、`product_limit_per_category=0`、`variant_limit_per_product=0`、`discovery_mode=sitemap`、`chunk_size=1` を固定する。
  - チェア検証後に同じ workflow で `run_profile=all-full` を選ぶと、全 enabled カテゴリへ移行できる。
- 将来的な管理画面、API、見積書自動生成に必要な追加データを整理した。
- Phase 7 標準カラム定義を `boexio/quote_columns.py` に追加した。
- Phase 5 の `current_master` シートを Phase 7 標準カラム順に更新した。
- Phase 5 の `current_master` シートに `category_name` / `category_url` を追加した。
- 標準マスタ CSV は今回は追加せず、既存標準ファイル 3 種類のうち `phase5_weekly_report.xlsx` の `current_master` を営業向け標準順に整える方針にした。
- 追加テストで、標準列順、空欄列、`source_url`、価格監査列、run 追跡列、空 `source_url` の手動確認フラグを確認した。

## 次にどこから始めるか

次は全カテゴリ 3 商品ずつのスモーク run を実施し、カテゴリごとの属性差異と取得可否を確認する段階。その後、`documents/category.md` の設計に沿ってカテゴリ matrix、商品チャンク、集約 job の順に実装する。

優先候補:

1. `config/target_categories.csv` のカテゴリ URL が現行サイトで有効か確認し、全カテゴリ 3 商品ずつの Phase 3 smoke run を行う。
2. `documents/category.md` に沿って、カテゴリ matrix と商品チャンクの GitHub Actions 設計を実装する。
3. Fixture または smoke run を使って Phase 5 レポートを再生成し、`current_master` のカテゴリ付き表示を営業確認する。
4. カテゴリ固有属性を固定列で増やすか、`selected_attributes_json` のような key/value 形式にするかを判断する。
5. URL リスト管理者、価格改定レポート確認責任者、正式連絡先を決める。

## 残っている判断事項

- 最初の URL リスト管理者。
- URL 追加・更新の承認者。
- 正式な連絡先メールアドレス。
- 問い合わせ対応窓口。
- 他商品で attributeId が変わるか。
- カテゴリ固有属性を固定列ではなく key/value 形式にするか。
- `config/target_categories.csv` の初期カテゴリが UI 上の全カテゴリを網羅しているか。
- sitemap discovery とカテゴリ公開総数が一致しない場合の運用判断。
- outlet 商品を対象カテゴリの公開総数へ含めるか。
- Phase 4 の `removed_items` を次回 run の状態入力としてどう保存・引き継ぐか。
- Excel レポートの確認責任者と確認期限。
- GitHub Actions の通知先実体。
- 全商品、全パターン取得時の `max-parallel` を 2 から増やす判断基準。
- 正式な連絡先メールアドレス。
- 見積に使う価格の社内丸め・割引・掛け率ルール。
- カテゴリ固有属性を固定列で増やすか、key/value JSON で持つか。
