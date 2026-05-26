# BoExio 作業サマリー

作成日: 2026-05-23

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

## 明日どこから始めるか

次は Phase 6: GitHub Actions 定期実行。

Phase 6 の決定事項:

- 定期実行は毎週日曜 15:00 JST とする。
  - GitHub Actions の cron は UTC 指定のため `0 6 * * 0` を使う。
- 成果物は GitHub Actions artifact にも保存し、最終的には GitHub Releases にも保存する。
- artifact は一時確認用として 30 日保持を推奨する。
- GitHub Releases は監査・過去参照用として長期保存する。
- Release tag は `weekly-YYYY-MM-DD`、Release name は `BoExio Weekly Report YYYY-MM-DD` を基本形にする。
- `run_status=failed` の場合も、生成済み成果物、metadata、errors、ログを保存する。
- GitHub Releases 作成に必要な workflow permissions は `contents: write` とする。
- 通知機能は実装するが、通知先は未設定でも動くようにする。通知先 secret は後で設定する。
- `BOEXIO_CONTACT_EMAIL` は secret / env で渡せる形にするが、正式な連絡先は後で設定する。

最初にやること:

1. `workflow_dispatch` で Phase 3、Phase 4、Phase 5 を順に実行する workflow を作る。
2. 週次 `cron` を `0 6 * * 0` に設定する。
3. 成果物 CSV、Excel、metadata、ログ、errors を artifact と GitHub Releases に保存する。
4. `BOEXIO_CONTACT_EMAIL` と通知先 secret を未設定でも動く任意 env として扱う。
5. `run_status=failed` でも成果物保存まで到達するように workflow を組む。

Phase 3 で再利用するもの:

- `boexio.phase1_poc.read_target_urls`
- `boexio.phase1_poc.parse_product`
- `boexio.phase2_variants.extract_candidates`
- `boexio.phase2_variants.enrich_rows`
- `boexio.phase2_variants.error_rows`
- `boexio.phase3_master.collect_product_urls`
- `boexio.phase3_master.fetch_with_control`
- `boexio.phase3_master.determine_run_status`
- `boexio.phase4_diff.diff_rows`
- `boexio.phase4_diff.PRICE_CHANGE_COLUMNS`
- `boexio.phase4_diff.ADDED_COLUMNS`
- `boexio.phase4_diff.REMOVED_COLUMNS`
- `boexio.phase5_report.build_worksheets`
- `boexio.phase5_report.validate_errors_csv`
- `boexio.xlsx_writer.write_xlsx`

Phase 3 の成果物イメージ:

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

## 残っている判断事項

- 最初の URL リスト管理者。
- URL 追加・更新の承認者。
- 正式な連絡先メールアドレス。
- 問い合わせ対応窓口。
- 他商品で attributeId が変わるか。
- 他カテゴリへ広げる場合、固定列ではなく構成属性 key/value 形式にするか。
- チェアカテゴリの 23 件が UI 上の全件か、追加読み込み API でさらに増えるか。
- Phase 4 の `removed_items` を次回 run の状態入力としてどう保存・引き継ぐか。
- Excel レポートの確認責任者と確認期限。
- GitHub Actions の通知先 secret 名と通知先実体。
- 正式な連絡先メールアドレス。
- GitHub Releases の長期保存期間を将来削除する場合の運用方針。
