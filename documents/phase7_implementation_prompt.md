# Phase 7 Implementation Prompt

BoExio の Phase 7: 見積運用連携の実装を進めてください。

## 前提

- 実装前に次の文書を確認してください。
  - `documents/summary.md`
  - `documents/task.md`
  - `documents/phase7_quote_integration_ja.md`
  - `documents/operations_runbook_ja.md`
- Phase 1 から Phase 6 は実装済みです。
- Phase 7 の設計資料では、営業が参照する標準ファイルを次の 3 つと定義しています。
  - `phase5_weekly_report.xlsx`
  - `phase3_products_current.csv`
  - `phase6_metadata.json`
- まずは Web アプリ、管理画面、見積書自動生成は作らず、既存 CSV / Excel 成果物を見積運用で使いやすい形に整えます。
- ネットワーク取得を伴う本番相当 run は慎重に扱い、まず既存テストと fixture ベースの検証を優先してください。

## 実装すること

1. 営業向け標準カラム順をコード上に定義してください。
   - Phase 7 設計資料の「営業確認に必要なカラム」を基準にする。
   - 既存 CSV に存在しない状態管理列は、空欄でも壊れないように扱う。
   - カラム定義は Phase 5 の Excel 出力で再利用しやすい場所に置く。
   - 関係ない既存 CSV schema は不用意に変更しない。

2. Phase 5 の `current_master` シートを標準カラム順に寄せてください。
   - 営業が見る順番を優先する。
   - 識別、商品、構成、価格、状態、参照、監査の順に並べる。
   - 既存データにない列は空欄で出力する。
   - 既存の `summary`、`price_changes`、`added`、`removed`、`errors` シートを壊さない。

3. 必要であれば営業向け標準マスタ CSV を追加してください。
   - 出力名の候補は `quote_master_YYYY-MM-DD_<run_id>.csv`。
   - 追加する場合は Phase 5 run directory に出力する。
   - GitHub Actions / Phase 6 の artifact staging で保存対象に含める。
   - 追加しない判断をする場合は、理由を `documents/task.md` または Phase 7 の実施メモに残す。

4. `source_url` による元ページ確認導線を維持してください。
   - `current_master` または標準マスタ CSV に `source_url` を必ず含める。
   - robots 除外対象の PDF URL を標準導線にしない。
   - `source_url` が空の行は見積確定前の手動確認対象として分かるようにする。

5. 価格履歴監査に必要な情報を落とさないでください。
   - `run_id`
   - `source_checked_at`
   - `parser_version`
   - `schema_version`
   - `price_compare_value`
   - `price_compare_from`
   - `currency`
   - `tax_type`

6. テストを追加・更新してください。
   - Phase 5 の `current_master` シートが Phase 7 標準カラム順になること。
   - 存在しない任意列が空欄で出力されること。
   - `source_url`、価格監査列、run 追跡列が欠落しないこと。
   - 標準マスタ CSV を追加した場合は、その列順と UTF-8 BOM 出力を確認すること。
   - ネットワーク取得を伴うテストは追加しない。

7. 文書を更新してください。
   - `documents/task.md` に実施メモを追記する。
   - `documents/summary.md` の現在地と次の着手候補を更新する。
   - 必要であれば `documents/phase7_quote_integration_ja.md` に実装上の決定を追記する。

## 注意点

- Phase 3 の取得 schema を大きく変える変更は避けてください。
- 見積価格の社内丸め、割引、掛け率ルールは未決事項です。推測で実装しないでください。
- カテゴリ固有属性を固定列で増やすか key/value JSON で持つかは未決事項です。必要なら TODO として残してください。
- 既存 Excel レポートの 6 シート構成は維持してください。
- `run_status=failed` の場合でも、生成済み成果物が Phase 6 で保存される前提を壊さないでください。
- 関係ないリファクタリングは避けてください。

## 完了条件

- `current_master` シートが Phase 7 の標準カラム順で出力される。
- 営業が見積前に必要な識別、商品、構成、価格、状態、参照、監査の列を確認できる。
- `source_url` が元ページ確認導線として残っている。
- 価格履歴監査に必要な列が欠落していない。
- 既存テストと追加テストが通る。
- `documents/task.md` と `documents/summary.md` が更新されている。
