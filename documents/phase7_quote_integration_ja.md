# Phase 7 見積運用連携メモ

作成日: 2026-05-26

## 1. 目的

Phase 7 では、週次で生成される商品マスタと価格差分レポートを、見積作成前の標準参照データとして使える状態にする。

初期段階では見積書自動生成や管理画面は作らない。まず営業が迷わず参照でき、将来の自動化入力にも転用できる標準ファイルとカラム定義を固定する。

## 2. 営業確認に必要なカラム

営業が見積前に確認する標準カラムは次の通り。

| 区分 | カラム | 用途 |
| --- | --- | --- |
| 識別 | `variant_key` | 構成単位の安定比較キー |
| 識別 | `variant_key_from` | キー生成元の確認 |
| 識別 | `sku` | SKU が取得できる場合の外部参照 |
| 識別 | `item_number` | 商品番号の確認 |
| 商品 | `brand` | ブランド確認 |
| 商品 | `series` | シリーズ確認 |
| 商品 | `product_name` | 商品名 |
| 構成 | `selected_size` | サイズ |
| 構成 | `selected_upholstery` | 張地または座部 |
| 構成 | `selected_leg` | 脚 |
| 価格 | `price_compare_value` | 見積前の基準価格 |
| 価格 | `price_compare_from` | 価格ソース |
| 価格 | `currency` | 通貨 |
| 価格 | `tax_type` | 税区分 |
| 価格 | `list_price` | 画面・元データ上の定価 |
| 価格 | `display_price` | 画面表示価格 |
| 価格 | `canonical_price` | 正規化前の比較候補価格 |
| 状態 | `scrape_status` | 取得成功・失敗 |
| 状態 | `current_state` | `active`、`missing_candidate`、`discontinued`、`revived` |
| 状態 | `missing_streak` | 連続未検知回数 |
| 参照 | `source_url` | 元商品ページ |
| 参照 | `image_url` | 画像確認 |
| 参照 | `raw_data_ref` | raw HTML 追跡 |
| 監査 | `source_checked_at` | 取得日時 |
| 監査 | `run_id` | run 追跡 |
| 監査 | `parser_version` | parser 追跡 |
| 監査 | `schema_version` | schema 追跡 |

既存 `products_current.csv` にない状態列は、Phase 4 の `removed_items` と `new_items` で管理する。営業向け標準ファイルでは、商品マスタと差分ファイルを組み合わせて状態を確認する。

## 3. 営業が参照する標準ファイル

初期運用で営業が参照する標準ファイルは GitHub Release asset の次の 3 種類とする。

1. `phase5_weekly_report.xlsx`
2. `phase3_products_current.csv`
3. `phase6_metadata.json`

用途:

- `phase5_weekly_report.xlsx`: 営業・管理者が通常確認する主ファイル。
- `phase3_products_current.csv`: 見積前の構成単位マスタ。Excel で確認できない詳細や機械処理に使う。
- `phase6_metadata.json`: 監査、取得日時、run 状態、過去成果物追跡に使う。

Excel の確認優先順:

1. `summary`
2. `price_changes`
3. `added`
4. `removed`
5. `errors`
6. `current_master`

実装メモ:

- Phase 7 標準カラム順は `boexio/quote_columns.py` の `QUOTE_MASTER_COLUMNS` に定義する。
- Phase 5 の `current_master` シートは `QUOTE_MASTER_COLUMNS` の順に出力する。
- Phase 3 の `products_current.csv` には `category_name` / `category_url` を追加し、Phase 5 の `current_master` でも同じ列を営業確認用に出力する。
- 既存 `products_current.csv` にない `current_state`、`missing_streak` は空欄で出力する。
- `parser_version`、`schema_version` は Phase 3 の `run_metadata.json` が同じディレクトリにある場合は Phase 5 Excel 側へ補完し、metadata がない場合も空欄で壊れないようにする。
- 標準マスタ CSV は初期実装では追加しない。標準参照ファイルを上記 3 種類に固定し、まず `phase5_weekly_report.xlsx` の `current_master` を営業向け標準順に整える。

## 4. 元ページ確認導線

見積前に元ページを確認する導線は `source_url` を標準とする。

運用ルール:

- 見積で使う価格は `price_compare_value` を基準にする。
- 価格差分やエラーがある行は、`source_url` で元ページを確認する。
- `source_url` が空または取得失敗の行は、見積確定前に手動確認対象とする。
- `pdf_url` は robots.txt の除外対象に該当する場合は取得しない。PDF ではなく商品ページ確認を標準にする。
- Phase 5 の `current_master` では `source_url` が空の行を `source_url_review_required=yes` として出力する。

## 5. 価格履歴監査

価格履歴監査は GitHub Releases を正本とする。

保存ルール:

- GitHub Releases: 3 年保存。
- GitHub Actions artifact: 30 日保存。
- 運用判断の記録: 3 年保存。

監査時に確認するファイル:

- `phase3_products_snapshot.csv`
- `phase4_price_changes.csv`
- `phase4_new_items.csv`
- `phase4_removed_items.csv`
- `phase5_weekly_report.xlsx`
- `phase6_metadata.json`

監査観点:

- いつ取得したか。
- どの parser / schema で取得したか。
- 価格変更がどの run で検出されたか。
- 比較不可や取得失敗が価格変更に混ざっていないか。

## 6. 複数カテゴリへ広げる判断基準

チェア以外を含む全カテゴリの smoke run に広げる前に、次を満たすこと。

- チェアカテゴリの週次 run が 2 回連続で `success` または許容済み `partial_success`。
- errors に継続的な `SCHEMA_MISMATCH` がない。
- 403、captcha、challenge による停止がない。
- 新カテゴリの URL が robots.txt と利用規約に反しない。
- 新カテゴリの商品 3 件以上で候補抽出ができる。
- `config/target_categories.csv` で対象カテゴリを管理し、`--product-limit-per-category 3` でカテゴリごとに 3 商品ずつ取得できる。
- `variant_key`、`price_compare_value`、`currency`、`tax_type` の欠損が業務許容範囲内。
- 構成属性がチェアと異なる場合、固定列で表現できるか key/value 拡張が必要かを判断する。
- 全商品、全パターン取得へ進む前に、カテゴリ matrix と商品チャンク分割の設計を `documents/category.md` に固定する。

## 7. 全商品カテゴリへ広げる前の受け入れ条件

全商品カテゴリへ広げる前の受け入れ条件は次の通り。

- カテゴリごとの実行上限、取得間隔、停止条件が設定できる。
- カテゴリ別の成功率、失敗率、schema mismatch 件数を metadata で追える。
- 重いカテゴリを商品チャンクに分割し、GitHub Actions の取得 job を `max-parallel: 2` で制御できる。
- チャンク別 artifact を結合し、最終的な `phase3_products_current.csv` を 1 ファイルとして出力できる。
- 営業がカテゴリ別に Excel を確認できる。
- 構成属性がカテゴリごとに異なっても、見積確認に必要な最低限の列が欠けない。
- Release asset のサイズと保存期間が運用可能な範囲に収まる。
- 価格改定確認責任者がカテゴリ追加を承認する。

## 8. 将来の管理画面・API・見積書自動生成に必要な追加データ

将来の自動化で追加検討するデータ:

- `category_name`
- `category_url`
- `option_attributes_json`
- `normalized_option_attributes_json`
- `availability_status`
- `sales_status`
- `price_valid_from`
- `price_valid_to`
- `quote_price_policy`
- `manual_override_flag`
- `manual_override_reason`
- `confirmed_by`
- `confirmed_at`
- `quote_note`

当面は CSV / Excel を正本とし、管理画面や API は Phase 7 の後続候補として扱う。

## 9. 未決事項

- 価格改定レポートの確認責任者。
- 価格改定レポートの確認期限。
- 正式な URL リスト管理者。
- URL 追加・更新の承認者。
- 見積に使う価格の社内丸め・割引・掛け率ルール。
- カテゴリ固有属性を固定列で増やすか、key/value JSON で持つか。
