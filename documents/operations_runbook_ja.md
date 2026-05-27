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
