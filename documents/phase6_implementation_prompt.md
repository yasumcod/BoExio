# Phase 6 Implementation Prompt

BoExio の Phase 6: GitHub Actions 定期実行を実装してください。

## 前提

- 実装前に `documents/summary.md` と `documents/task.md` を確認してください。
- Phase 1 から Phase 5 は実装済みです。
- Phase 6 では、GitHub Actions で Phase 3、Phase 4、Phase 5 を順に実行し、成果物を保存できる状態にします。
- Playwright は現時点では不要です。
- ネットワーク取得を伴う本番相当 run は慎重に扱い、まず workflow 構文、既存テスト、ローカルで再現できる範囲の検証を優先してください。

## 実装すること

1. GitHub Actions workflow を追加してください。
   - `workflow_dispatch` で手動実行できるようにする。
   - 毎週日曜 15:00 JST に定期実行する。
   - GitHub Actions の cron は UTC 指定なので `0 6 * * 0` を使う。

2. Phase 3、Phase 4、Phase 5 を順に実行してください。
   - Phase 3 で商品マスタ CSV を生成する。
   - Phase 4 で前回 CSV と今回 CSV の差分を生成する。
   - Phase 5 で Excel レポートを生成する。
   - 既存 script の引数を確認し、現在の実装に合う形で呼び出す。
   - 前回 CSV の扱いが未実装または不明な場合は、GitHub Releases から前回成果物を取得する方針を検討し、最小実装で破綻しない形にする。

3. 成果物を保存してください。
   - GitHub Actions artifact として保存する。
   - artifact の `retention-days` は 30 日にする。
   - GitHub Releases の assets としても保存する。
   - Release tag は `weekly-YYYY-MM-DD` を基本形にする。
   - Release name は `BoExio Weekly Report YYYY-MM-DD` を基本形にする。
   - `run_status=failed` の場合も、生成済み成果物、errors、metadata、ログを保存する。
   - 失敗時も保存 step が動くように `if: always()` を使う。

4. workflow permissions を設定してください。
   - Release 作成に必要な `contents: write` を設定する。
   - 不要に広い権限は付けない。

5. secrets / env を任意設定として扱ってください。
   - `BOEXIO_CONTACT_EMAIL` は `secrets.BOEXIO_CONTACT_EMAIL` から渡せるようにする。
   - 通知先は後で設定するため、通知先 secret が空でも workflow が失敗しないようにする。
   - 通知先 secret 名は分かりやすい名前にする。例: `BOEXIO_NOTIFY_WEBHOOK_URL`。
   - 通知機能は実装するが、未設定なら skip する。

6. 検証してください。
   - workflow YAML の構文を確認する。
   - 既存 Python ファイルを `py_compile` する。
   - 既存テストを実行する。
   - 可能であれば Phase 6 に必要な小さな script / helper の単体テストを追加する。
   - ネットワーク取得を伴う実行は通常テストから分離する。

## 注意点

- `documents/task.md` の Phase 6 チェックリストに沿って進めてください。
- 実装中に未決事項が見つかった場合は、推測で業務判断を固定せず、文書に TODO として残してください。
- `run_status=failed` でも成果物が残ることを重視してください。
- 既存の Phase 3 / Phase 4 / Phase 5 の入出力仕様に合わせてください。
- 関係ないリファクタリングは避けてください。

## 完了条件

- cron と手動実行の両方で起動できる workflow がある。
- 毎週日曜 15:00 JST 相当の cron が設定されている。
- 成果物が GitHub Actions artifact と GitHub Releases の両方に保存される設計になっている。
- 失敗時にもログ、metadata、errors、生成済み成果物を追える。
- 通知先と連絡先メールが未設定でも workflow が失敗しない。
