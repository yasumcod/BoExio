# BoExio 運用メモ

作成日: 2026-05-26

## 1. 対象

このメモは Phase 6 の週次 GitHub Actions 運用を対象にする。

- workflow: `.github/workflows/boexio-weekly.yml`
- 定期実行: 毎週日曜 15:00 JST
- cron: `0 6 * * 0`
- 成果物: GitHub Actions artifact と GitHub Releases

## 2. 通常運用

週次実行後、運用担当者は GitHub Release `weekly-YYYY-MM-DD` を確認する。

確認項目:

- Release 本文の `run_status`
- `phase6_metadata.json` の `overall_run_status`
- `phase3_errors.csv`、`phase4_errors.csv`、`phase6_errors.csv`
- `phase5_weekly_report.xlsx`
- `workflow_phase3.log`、`workflow_phase4.log`、`workflow_phase5.log`

`overall_run_status=success` の場合、Excel レポートを価格改定確認者へ共有する。

`overall_run_status=partial_success` または `failed` の場合、次の順で原因を確認する。

1. `phase6_errors.csv`
2. 各 phase の `run_metadata.json`
3. workflow log
4. GitHub Actions の job summary と failed step

カテゴリ分割実行を導入した後は、次も確認する。

- 欠落カテゴリまたは欠落チャンクがないか。
- `merge-report` job が全チャンク artifact を取得できているか。
- チャンク別 `run_metadata.json` の失敗率、schema mismatch 件数、403、captcha、challenge の有無。
- `max-parallel` が 2 のまま運用されているか。

全商品・全パターン取得を行った場合は、追加で次を確認する。

- `phase3_run_metadata.json` の `category_completeness` で、カテゴリ別に `discovery_complete`、`fetch_attempt_complete`、`comparison_complete` を確認する。
- `product_variant_completeness` で、商品別に `variant_candidate_count`、`variant_fetch_attempt_count`、`variant_success_count`、`variant_failure_count`、`variant_skipped_count` を確認する。
- full run では `variant_candidate_count = variant_fetch_attempt_count + variant_skipped_count`、`variant_fetch_attempt_count = variant_success_count + variant_failure_count` が崩れていないか確認する。
- チェア、ソファなど張地が多いカテゴリで、後半の商品または後半 variant が欠落していないか。
- 欠落がある場合、workflow / job timeout、retry 増加、chunk artifact 欠落、候補生成漏れのどれに近いか。
- 全カテゴリ一括実行で欠落した場合は、まず既存 workflow のカテゴリ指定 `workflow_dispatch` で再実行する。専用カテゴリ workflow は、既存 input で運用できない理由が明確になるまで追加しない。

## 3. 停止後の再開手順

自動停止、captcha/challenge 検知、403 増加、schema mismatch、GitHub Actions 障害のいずれかで停止した場合は、即時に連続再実行しない。

再開手順:

1. 直近 Release の `phase6_metadata.json` と errors CSV を保存確認する。
2. `phase3_scrape_log.txt` で停止理由を確認する。
3. robots.txt と利用規約に変更がないか確認する。
4. schema mismatch の場合は、raw HTML と parser 差分を確認し、修正後に通常テストを通す。
5. 403、captcha、challenge の場合は、同日中の再実行を避け、翌営業日以降に 1 商品・1 variant の手動実行で確認する。
6. 手動実行は `workflow_dispatch` で `product_limit_per_category=1`、`variant_limit_per_product=1`、`request_interval=5` 以上から再開する。全体上限をさらに絞る場合だけ `product_limit` に正の値を指定する。
7. smoke run が成功した場合のみ、通常の上限値で再実行する。

カテゴリ分割実行後の再開手順:

1. 欠落または失敗した `category_slug` / `chunk_slug` を確認する。
2. 失敗カテゴリまたは失敗チャンクだけを `workflow_dispatch` で再実行する。`category_slug` と `chunk_slug` を指定できる。`chunk_slug` だけで再実行する場合も、可能な限り対応する `category_slug` を併せて指定する。
3. 再実行結果を集約 job で結合し、Release 更新は集約 job のみで行う。
4. 403、captcha、challenge が出た場合は `max-parallel` を増やさず、必要なら 1 へ下げる。
5. `variant_limit_per_product=0` は全パターン取得を意味するため、再開確認ではまず `1` を指定する。

全パターン取得でカテゴリ途中の欠落が疑われる場合:

1. 欠落カテゴリの `run_metadata.json` で `category_completeness` と `product_variant_completeness` を確認し、`discovery_complete`、`fetch_attempt_complete`、`comparison_complete` のどこで false になったか切り分ける。
2. workflow / job timeout が疑わしい場合は、該当カテゴリだけを再実行し、必要に応じて `chunk_size=1` まで下げる。
3. カテゴリ単独 full run は、まず次の input で実行する。

```text
category_slug=sofa
chunk_size=1
product_limit_per_category=0
variant_limit_per_product=0
request_interval=5
retries=2
```

4. 再実行でも同じ商品・同じ variant で止まる場合は、実行時間ではなく schema mismatch、URL 生成、サイト側応答の問題として切り分ける。

カテゴリ分割実行の status 判断:

- full run で全カテゴリの `discovery_complete`、`fetch_attempt_complete`、`comparison_complete` が true: `overall_run_status=success`
- full run で fetch attempt は完了したが、一部 variant が取得失敗または比較不可: `overall_run_status=partial_success`
- full run で必須カテゴリ欠落、商品数 0 のカテゴリ、期待チャンク artifact 欠落、failed chunk、fetch attempt 未完了、candidate 数と attempt 数の不一致: `overall_run_status=failed`
- `product_limit_per_category > 0` または `variant_limit_per_product > 0` の制限実行では、full run と同じ strict completeness gate は適用しない。metadata の limit 適用有無を確認する。
- 重複 `variant_key` / `source_url` は最初の行を採用し、重複を `errors.csv` に記録する。この場合は `partial_success` として確認対象にする。

再開判断の記録先:

- GitHub Release の説明または運用記録
- 必要に応じて GitHub Issue

## 4. 監視通知

通知機能は `BOEXIO_NOTIFY_WEBHOOK_URL` が設定されている場合だけ送信する。

初期運用の通知先:

- GitHub Actions の失敗通知
- GitHub Release の `run_status`
- 任意 webhook secret: `BOEXIO_NOTIFY_WEBHOOK_URL`

正式な通知先が未設定の場合でも workflow は失敗させない。

通知先の決定事項:

- 初期は GitHub Actions の失敗通知を監視通知として扱う。
- `BOEXIO_NOTIFY_WEBHOOK_URL` は Slack、Teams、または社内 webhook のいずれかに接続する。
- 正式な webhook 実体は運用開始前に決める。

## 5. robots.txt と利用規約の確認頻度

確認頻度:

- 通常時: 月 1 回
- 障害・403・captcha/challenge 発生時: 再開前
- 対象カテゴリ追加前: 追加前
- 実装が取得範囲を広げる前: リリース前

確認記録:

- `documents/compliance_checklist.md` に確認日、確認者、差分有無を追記する。

差分があった場合:

- 対象 URL が Disallow に該当する場合は取得を停止する。
- 利用規約に自動取得禁止が明記された場合は取得を停止し、運用責任者に確認する。

## 5.1 並列数変更の判断

`scrape-product-chunk` の初期設定は `max-parallel: 2` とする。

増やす場合の判断基準:

- 403、captcha、challenge が発生していない。
- `max-parallel: 2` の安定 run が 2 回以上続いている。
- `request_interval` と並列数を掛け合わせたサイト全体の実効アクセス頻度が許容できる。
- 重いカテゴリや 100 パターン以上の商品が多い場合は、並列数を増やすより先に `chunk_size` を下げる。
- 全パターン取得で欠落が出た場合は、並列数増加で解決しようとせず、カテゴリ単独実行と chunk_size 縮小を先に行う。専用カテゴリ workflow は、既存 input で運用できない理由が明確になった場合だけ検討する。

## 6. 障害時の復旧目標

初期運用の復旧目標:

- GitHub Actions / Release 作成失敗: 1 営業日以内に再実行または原因記録
- schema mismatch: 2 営業日以内に原因切り分け
- 403 / captcha / challenge: 取得を停止し、再開可否を運用責任者が判断
- Excel レポート生成失敗: 1 営業日以内に CSV 成果物から代替確認

価格確認業務に影響する場合は、直近成功 Release の `phase5_weekly_report.xlsx` と今回生成済み CSV を使って手動確認する。

## 7. 運用記録と成果物の保存期間

保存期間:

- GitHub Actions artifact: 30 日
- GitHub Releases: 3 年
- 運用判断の記録: 3 年

削除運用:

- 3 年を超えた Release asset は、監査要件を確認したうえで削除対象にできる。
- 削除前に `phase6_metadata.json` と `phase5_weekly_report.xlsx` の保存要否を確認する。

## 8. 未確定事項

- 正式な `BOEXIO_CONTACT_EMAIL`
- サイト側問い合わせの一次対応窓口
- webhook 通知先の実体
- 価格改定レポートの最終確認責任者
