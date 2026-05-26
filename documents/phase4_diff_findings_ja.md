# BoExio Phase 4 差分検知 調査・実装メモ

作成日: 2026-05-23

参照:

- `documents/task.md`
- `documents/summary.md`
- `documents/phase3_master_findings_ja.md`

## 1. 実装ファイル

```text
boexio/phase4_diff.py
scripts/phase4_diff.py
```

Phase 4 では、Phase 3 の `products_current.csv` 同士を比較し、価格変更、新規追加、削除候補、比較不可を分離する。

## 2. 入力

CLI:

```text
python3 scripts/phase4_diff.py \
  --previous-csv <previous products_current.csv> \
  --current-csv <current products_current.csv> \
  --run-id <run_id>
```

metadata:

- `--previous-metadata` / `--current-metadata` を省略した場合、各 CSV と同じディレクトリの `run_metadata.json` を読む。
- 両 metadata に `schema_version` があり、不一致なら差分処理を停止する。
- metadata がない場合は CSV カラム検証で代替する。

## 3. 出力

```text
data/runs/<run_id>/
  price_changes_YYYY-MM-DD_<run_id>.csv
  new_items_YYYY-MM-DD_<run_id>.csv
  removed_items_YYYY-MM-DD_<run_id>.csv
  errors.csv
  diff_summary.json
  run_metadata.json
```

`run_metadata.json` には、入力 CSV、入力 metadata、schema version、summary、成果物 checksum を保存する。

## 4. 比較キー

比較キーは Phase 3 で生成済みの `variant_key` を使う。

前処理:

- `scrape_status != success` は diff error に送る。
- `variant_key` 欠損は diff error に送る。
- `variant_key` 重複は diff error に送る。

## 5. 価格比較

比較対象:

- `price_compare_value`

比較前に一致必須:

- `currency`
- `tax_type`
- `price_compare_from`

不一致または欠損時は価格変更として扱わず、`errors.csv` に出力する。

主な error code:

- `missing_comparable_price`
- `price_parse_error`
- `currency_mismatch`
- `tax_type_mismatch`
- `price_source_mismatch`
- `duplicate_variant_key`
- `missing_variant_key`
- `schema_version_mismatch`
- `schema_mismatch`

## 6. 状態遷移

追加:

- current にあり previous にない `variant_key` は `new`。

削除候補:

- previous にあり current にない `variant_key` は `missing_candidate`。
- `missing_streak` を 1 増やす。
- 4 回目以降は `discontinued`。
- `discontinued_at` と `missing_streak_at_discontinue` を記録する。

復活:

- previous に `current_state=discontinued` として残っていた `variant_key` が current に戻った場合は `revived`。
- `revived_at` と `revived_price` を記録する。

現時点の制約:

- Phase 3 の `products_current.csv` には状態管理列がないため、継続的な `missing_streak` 管理は Phase 4 出力の `removed_items` を次回以降の状態入力として取り込む運用設計が必要。

## 7. 検証 run

### サンプル差分検証

run:

```text
data/runs/phase4-fixture-check/
```

検証内容:

- 価格変更 1 件。
- 新規追加 1 件。
- 削除候補 1 件。
- 通貨不一致 1 件。

結果:

- `price_change_count`: 1
- `added_count`: 1
- `removed_count`: 1
- `currency_mismatch_count`: 1
- `comparison_error_count`: 1

### 差分なし検証

run:

```text
data/runs/phase4-same-csv-check/
```

入力:

- previous: `data/runs/phase3-catskills-all-variants/products_current.csv`
- current: `data/runs/phase3-catskills-all-variants/products_current.csv`

結果:

- `previous_row_count`: 152
- `current_row_count`: 152
- `price_change_count`: 0
- `added_count`: 0
- `removed_count`: 0
- `comparison_error_count`: 0
- `run_status`: `success`

### スキーマ不一致検証

run:

```text
data/runs/phase4-schema-mismatch-check/
```

結果:

- `errors.csv` に `schema_version_mismatch` を出力。
- `run_status`: `failed`
- exit code: 1

### 実データ追加検知

run:

```text
data/runs/phase4-smoke-to-full-check/
```

入力:

- previous: `data/runs/phase3-smoke-check-success/products_current.csv`
- current: `data/runs/phase3-catskills-all-variants/products_current.csv`

結果:

- `previous_row_count`: 1
- `current_row_count`: 152
- `added_count`: 151
- `price_change_count`: 0
- `removed_count`: 0
- `comparison_error_count`: 0

## 8. 判断

- Phase 4 の CSV 差分検知は、Phase 5 の Excel レポート入力として使える形になった。
- 比較不可データは価格変更から分離できる。
- schema version 不一致時は停止し、errors で原因を追える。
- `removed_items` は週次状態管理の土台になるが、継続運用では前回状態ファイルの読み込み設計を Phase 5/6 前に固める必要がある。

## 9. 単体テスト

追加ファイル:

```text
tests/test_phase4_diff.py
```

検証コマンド:

```text
python3 -m unittest tests/test_phase4_diff.py
```

テスト対象:

- 価格変更判定。
- added / removed 判定。
- `missing_candidate` から `discontinued` への状態遷移。
- `discontinued` から `revived` への状態遷移。
- 通貨不一致を価格変更に混ぜないこと。
- `schema_version` 不一致判定。
