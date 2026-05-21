# BoExio プロダクトイメージ

作成日: 2026-05-18

参照元: `/Users/mondenyasuhiro/Downloads/boconcept_scraping_architecture_and_operations_plan_ja.md`

本資料の建付け: 要件定義書を作成する前段で、目的・価値・スコープ・設計方針・運用方針をそろえるための構想ドキュメントとする。

## 1. 解釈の結論

今後作るべきものは、単なるスクレイピングスクリプトではなく、BoConceptの商品情報と価格変更を継続的に監視し、営業が見積作成で迷わない状態を作るための「商品マスタ・価格差分管理基盤」である。

中心価値は、商品一覧を作ることそのものではない。最も価値が高いのは、価格改定・新商品・販売終了候補・取得失敗を毎週検知し、営業と管理側がすぐ確認できるレポートとして出すこと。

つまり、プロダクトの核は次の流れにある。

```text
BoConcept公開商品ページ
↓
商品構成ごとの情報取得
↓
商品マスタCSV化
↓
前回データとの差分検知
↓
営業向けExcelレポート生成
↓
履歴として保存
↓
見積運用へ接続
```

## 2. プロダクト定義

### プロダクト名

BoExio

### 一言でいうと

BoConceptの商品価格と構成情報を自動取得し、価格変更を検知して営業見積に使える商品マスタと差分レポートを生成する業務支援ツール。

### 誰のためのものか

- 営業担当: 最新価格を確認し、見積ミスを減らしたい
- 営業管理者: 価格改定や販売終了候補を把握したい
- 運用担当者: 商品マスタの更新作業を手作業から外したい
- 将来の見積システム: 正規化された商品・価格データを利用したい

## 3. 解決したい問題

現在の問題は、商品情報の確認と見積作成が人の目視と転記に依存していること。

主な痛点:

- 商品ページ上の価格変更を見落とす
- Excelや見積書への転記ミスが起きる
- 商品構成ごとの価格差が追いきれない
- いつ価格が変わったのか履歴が残らない
- 管理側が全体の変更状況を把握しづらい
- 見積作成前に最新価格かどうかを確認する負荷が高い

BoExioは、この問題を「商品マスタの自動生成」と「価格差分の自動検知」で解く。

## 4. 作るべき体験

### 営業担当の理想状態

毎週生成されるExcelレポートを開けば、価格変更・新商品・削除候補がわかる。見積作成時には、最新の商品マスタを参照できる。

営業にとって大事なのは、スクレイピングが動いたかどうかではなく、次の判断がすぐできること。

- どの商品が値上がりしたか
- どの商品が値下がりしたか
- 新しく追加された商品は何か
- 消えた商品は何か
- 見積に影響する変更はどれか
- データ取得に失敗した商品はどれか

### 管理者の理想状態

価格改定の履歴を日付ごとに確認でき、過去の見積や価格監査に使える。毎週の成果物がGitHub Releasesに残り、いつでも取り出せる。

### 開発・運用者の理想状態

対象URLを追加すれば、定期実行で商品マスタと差分レポートが生成される。取得失敗はログとエラー一覧に残り、修正すべき箇所が見える。

## 5. MVPで作るべきもの

MVPは「全自動の完成品」ではなく、価格差分検知までの最短ルートを作る。

対象ドメインは`https://www.boconcept.com`とし、実取得対象は`https://www.boconcept.com/ja-jp/shop/`配下に限定する（サイト全体クロールは行わない）。

初期対象カテゴリはチェアとし、対象カテゴリURLは次とする。

```text
https://www.boconcept.com/ja-jp/shop/%E3%83%81%E3%82%A7%E3%82%A2/
```

### MVPの範囲

- 対象URLリストを手動で持つ
- 第一段階ではチェアカテゴリページ1件を取得対象にする
- 1商品から主要情報を取得できる
- 商品構成ごとに1行のデータへ正規化できる
- 第一段階では取得できた内容を生データCSVとして出力できる
- 前回CSVと今回CSVを比較できる
- 価格変更、新規追加、削除候補を出力できる
- 後続段階で営業が確認できるExcelレポートを生成できる

### MVPでまだやらないこと

- フル機能のWeb管理画面
- 見積書の完全自動作成
- 大量商品を前提にしたクラウドAPI化
- 社内顧客データとの連携
- 複雑な承認ワークフロー

## 6. 重要な設計方針

### 1商品ではなく1構成を1レコードにする

BoConceptの商品は、サイズ・張地・脚などの選択で価格やSKUが変わる。したがって、商品単位ではなく構成単位で扱う必要がある。

```text
商品名: Lucerne
構成A: サイズ1 + 張地1 + 脚1
構成B: サイズ1 + 張地2 + 脚1
構成C: サイズ2 + 張地1 + 脚2
```

この各構成を1行として管理する。

### API・内部JSON探索を優先する

UIクリックだけに依存すると、実行時間が長く、画面変更にも弱い。まずは商品ページのネットワーク通信や埋め込みJSONを調べ、商品構成データを直接取得できるか確認する。

取得戦略の優先順位:

```text
1. 内部JSON/API
2. HTML内の構造化データ
3. PlaywrightによるUI操作
4. URLパターン推測
```

### レポートを主成果物にする

CSVの商品マスタは基盤データ。実務で最初に価値が出るのは、営業・管理者が見るExcelレポート。

最低限必要なシート:

- summary
- price_changes
- added
- removed
- current_master
- errors

## 7. データモデルのイメージ

### Product

商品そのものを表す。

主な項目:

- brand
- series
- product_name
- base_item_number
- source_url
- product_description
- image_url
- pdf_url

### Variant

商品構成を表す。差分比較の主役。

主な項目:

- item_number
- selected_size
- selected_upholstery
- selected_leg
- width_cm
- depth_cm
- height_cm
- weight_kg
- material

### PriceSnapshot

ある取得日時における価格状態。

主な項目:

- variant_key
- list_price
- display_price
- canonical_price
- price_from
- currency
- tax_type
- source_checked_at
- scrape_status
- scrape_error_code
- scrape_error_message

補足ルール:

- MVPでは、取得できた表示価格をそのまま記録することを優先する。
- `canonical_price` は差分判定用の任意カラムとし、税区分変換や複雑な価格整形は後続フェーズで扱う。
- 価格ソースが複数取れた場合は、どの値を採用したかを `price_from` に記録する。
- 取得エラーもCSV内に行として残し、`scrape_status=failed` と `scrape_error_code` / `scrape_error_message` で判別できるようにする。

### ChangeEvent

前回取得との差分。

主な項目:

- change_type
- variant_key
- previous_price
- current_price
- price_delta
- detected_at
- severity

### ScrapeRun

1回の実行状態。

主な項目:

- run_id
- started_at
- finished_at
- status
- target_count
- success_count
- failure_count
- output_files

## 8. 比較キー

参照元メモの通り、比較キーは次を基本にする。

```text
item_number
+ selected_size
+ selected_upholstery
+ selected_leg
```

ただし、実装時にはBoConcept側のSKUや構成IDが取得できるなら、それを優先する。人間が読める構成名は変わる可能性があるため、機械的に安定したIDが見つかれば比較精度が上がる。

### 比較キー候補の優先順位

比較キーは単一方式に固定せず、取得可否に応じたフォールバックを持つ。

```text
第1候補: variant_id（BoConcept内部の構成ID）
第2候補: sku（構成単位SKU）
第3候補: 正規化済み属性連結キー
  = item_number + selected_size + selected_upholstery + selected_leg
```

優先順位は「安定性」と「サイト表示変更への耐性」で決める。表示名称ベースの比較は最後の手段とし、内部で一意なIDを最優先する。

### 属性正規化ルール

連結キーを使う場合は、以下の正規化を必須にする。

- trim: 前後空白を除去する
- 大小文字: 英字は小文字化して比較する（case-insensitive）
- 全角半角: 英数字・記号・スペースをNFKCで正規化する
- 記号: 比較に不要な区切り記号（例: `-`, `_`, `/`, `・`）は統一ルールで除去または単一記号に寄せる
- 空白: 連続空白を1つに圧縮し、比較前に不要空白を除去する
- 表記ゆれ辞書: 代表的な同義表現を辞書で正規化する（例: `fabric` ↔ `ファブリック`、`oak` ↔ `オーク`）

この正規化処理は、差分検知前の共通前処理として固定し、実行ごとに結果がぶれないようにする。

### キー生成失敗時の扱い

比較キーが生成できないレコードは、通常の差分比較に混ぜない。

- エラー分類: `missing_required_attribute` / `conflicting_identifiers` / `normalization_failed` / `empty_key_after_normalization` などで分類
- diff対象外: キー不成立レコードは `added` / `removed` / `price_changes` の判定対象から除外
- errorsシート出力: `run_id`, `source_url`, `raw_attributes`, `error_type`, `error_detail` を `errors` シートへ出力

これにより、比較結果の誤検知を防ぎつつ、運用者が修正対象を追えるようにする。

### 既存キーから新キーへの移行互換方針

比較キー方式を変更する場合は、履歴整合性を守るための移行方針を先に決める。

- 互換期間: 一定期間は旧キー・新キーを併記し、両方でマッチングを試みる
- 監査可能性: レポート上で「旧キー一致」「新キー一致」「不一致」を判別できる列を持つ
- 過去スナップショット再計算:
  - 原則: 価格履歴の連続性が重要なため、可能なら過去スナップショットを新キーで再計算する
  - 例外: 再計算コストが高い場合は、切替日（例: 2026-05-19）を境にキー体系を分け、比較ロジック側でブリッジする

どちらを採る場合でも、切替日と採用方針を運用ドキュメントに明記し、差分の見え方が変わる期間を事前共有する。

## 8.1 価格差分判定ルール

差分検知の実装をぶらさないため、MVPでは価格比較を次の最小ルールで行う。

- 比較対象: 取得できた価格文字列または数値を、過度に整形せず同一ソース同士で比較する。
- 価格ソース: `list_price` / `display_price` / ページ表示価格など、採用した取得元を `price_from` に必ず残す。
- 比較不可: 価格が欠損、価格ソースが前回と今回で一致しない、または数値化できない場合は `errors` に記録し、価格変更としては扱わない。
- 税込/税抜: MVPでは自動換算しない。取得できた表示の税区分を `tax_type` に記録し、差分比較は同じ税区分同士に限定する。
- 通貨: 原則として同一通貨間のみ差分比較する。異通貨は自動換算せず、`currency_mismatch` 警告として `errors` と `summary` に件数を出す。
- 正準価格: `canonical_price` を使った税区分正規化・丸め・価格ソース優先順位の厳密化は、取得実態を確認した後の後続フェーズで設計する。

## 9. 画面ではなく成果物で始める

初期段階ではWebアプリを作らない。まずは次の成果物が安定して生成される状態を目指す。

```text
products_current.csv
products_YYYY-MM-DD.csv
price_changes_YYYY-MM-DD.csv
new_items_YYYY-MM-DD.csv
removed_items_YYYY-MM-DD.csv
weekly_report_YYYY-MM-DD.xlsx
scrape_log_YYYY-MM-DD.txt
```

この成果物が業務で使えることを確認してから、必要なら管理画面や見積書連携へ進む。

## 10. レポートの見せ方

### summary

1回の取得結果を俯瞰する。

第一段階では生データCSVを優先し、以下のシート構成や列定義は固定しない。Excelレポート化する段階で、実際に取得できた項目に合わせて整える。

- 取得日
- 対象商品数
- 取得成功数
- 取得失敗数
- 総構成数
- 価格変更数
- 値上げ数
- 値下げ数
- 新規追加数
- 削除候補数

### price_changes

営業が最も見るシート。

- 商品名
- 商品番号
- サイズ
- 張地
- 脚
- 前回価格
- 今回価格
- 差額
- 変化率
- 商品URL
- 取得日時

### added

新しく検知された商品または構成。

### removed

前回存在したが今回見つからなかった商品または構成。すぐ販売終了と断定せず、削除候補として扱う。

状態遷移を明確化するため、removed 判定は次のステータスを持つ。

- active: 今回実行で検知できた通常状態
- missing_candidate: 今回未検知。販売終了候補として監視中
- discontinued: 連続未検知が閾値に達し、販売終了確定
- revived: discontinued 後に再検知され、復活として記録された状態

週次実行を前提に、`連続4回未検知` を discontinued 化の閾値とする。

```text
active
  └─(1回未検知)→ missing_candidate
missing_candidate
  ├─(再検知)→ active
  └─(連続4回未検知到達)→ discontinued
discontinued
  └─(再検知)→ revived
revived
  └─(次回も検知)→ active
```

revived 条件は「discontinued 判定済みの比較キーが再検知されたこと」。このとき次を必須で記録する。

- 復活検知日（revived_at）
- 直前の discontinued 判定日（discontinued_at）
- 連続未検知回数（missing_streak_at_discontinue）
- 復活後初回価格（revived_price）

集計項目は summary / removed の双方で次を出力する。

- 新規候補数（missing_candidate に新規遷移した件数）
- 確定終了数（discontinued に新規遷移した件数）
- 復活数（discontinued から revived に遷移した件数）

### errors

取得失敗や解析失敗を一覧化する。運用上はこのシートが重要。失敗が見えない自動化は信用されない。

MVPでは別レポートだけに分離せず、生データCSVにも取得失敗行を残す。成功行は `scrape_status=success`、失敗行は `scrape_status=failed` とし、取得できなかった項目は空欄にする。これにより、CSV単体でも対象URLごとの成功・失敗を確認できる。

## 11. フェーズ計画

### Phase 1: 1商品PoC

目的:

- 商品ページのHTML構造を確認する
- 価格、商品名、商品番号、寸法などが取れるか確認する
- 内部JSON/APIの有無を調べる

完了条件:

- 1商品のCSVを出力できる
- 取得項目と未取得項目が整理されている
- JSON/API方式で進めるか、Playwright中心にするか判断できる

### Phase 2: 構成バリエーション取得

目的:

- サイズ・張地・脚の組み合わせを取得する
- 価格やSKUが構成ごとに変わることを確認する

完了条件:

- 1商品について複数構成をCSV化できる
- 比較キーの候補が決まっている
- 取得失敗時のログが残る

### Phase 3: 商品マスタ生成

目的:

- 複数商品URLを処理する
- products_current.csvを生成する

完了条件:

- URLリストから複数商品を取得できる
- CSVカラムが固定されている
- 日付付きCSVを保存できる

### Phase 4: 差分検知

目的:

- 前回CSVと今回CSVを比較する
- 価格変更、新規追加、削除候補を判定する

完了条件:

- price_changes CSVを生成できる
- added / removed CSVを生成できる
- 比較ロジックのテストがある

### Phase 5: Excelレポート生成

目的:

- 営業が確認しやすいExcelにまとめる

完了条件:

- weekly_report.xlsxが生成される
- summary、price_changes、added、removed、current_master、errorsが含まれる
- 金額や差額が見やすく整形されている

### Phase 6: GitHub Actions定期実行

目的:

- 毎週自動実行する
- 成果物をReleasesに保存する

- URL単位の再試行制御とrun全体の失敗判定を標準化する
- サイト負荷とブロックリスクを抑えた実行制御を標準化する

完了条件:

- cronで実行できる
- 手動実行もできる
- 失敗時にログを確認できる
- Private Repositoryで運用できる
- 再試行・打ち切り・run失敗判定が設定ファイルで管理できる
- CSV、Excel、run metadata、ログをGitHub Releasesのassetsとして保存できる

運用仕様（再試行・打ち切り・全体失敗判定）:

- URL単位の再試行
  - `max_retries_per_url = 3`（初回失敗後に最大3回再試行、合計4試行）
  - backoffは指数方式 + ジッター（例: `base=5s`, `10s`, `20s` + ランダム0-3s）
  - `HTTP_404` と `SCHEMA_MISMATCH` は非再試行（恒久失敗として即打ち切り）
  - `HTTP_429`, `HTTP_5xx`, `TIMEOUT_*`, `RATE_LIMITED` は再試行対象
- URL単位の打ち切り条件
  - 同一URLで再試行上限到達
  - 単一URLの累積処理時間が `max_url_runtime_sec`（例: 180秒）を超過
  - `SELECTOR_MISS` または `PARSE_ERROR` が連続2回発生（DOM変更疑いとして打ち切り）
- 実行全体（run）失敗判定
  - `failure_rate = failure_count / target_count`
  - `failure_rate > 0.30` のとき `run_status=failed`
  - または `target_count >= 20` かつ `failure_count >= 5` でも `run_status=failed`
  - 上記未満でも `SCHEMA_MISMATCH` が全体で3件以上なら `run_status=failed`（実装破綻シグナル）
  - `run_status=failed` の場合も生成済み成果物と `errors` シートは必ず保存する
  - レート制限（requests/sec上限・同時接続数・クロール時間帯）が設定ファイルで管理される
  - ブロック兆候（403増加、captcha検知）を監視し、しきい値超過でジョブを自動停止できる
  - 実行ログに停止理由（403率、captcha検知件数、停止時刻）を記録できる

### Phase 7: 見積運用連携

目的:

- 商品マスタを見積書作成に接続する

完了条件:

- 見積に必要なカラムがそろっている
- 営業が参照する標準ファイルが定義されている
- 将来的な見積書自動生成の入力として使える

## 12. 技術構成のイメージ

初期:

```text
Python
requests
BeautifulSoup
pandas
openpyxl
Playwright
```

運用:

```text
GitHub Actions
GitHub Releases
Private Repository
```

将来:

```text
Cloud Run / AWS
管理画面
API
見積書連携
```

## 13. ディレクトリ構成案

```text
repo/
├─ documents/
│  └─ product_vision_ja.md
├─ config/
│  └─ target_urls.csv
├─ src/
│  └─ boexio/
│     ├─ scraper/
│     ├─ parser/
│     ├─ diff/
│     └─ report/
├─ data/
│  ├─ current/
│  └─ snapshots/
├─ output/
│  └─ reports/
├─ tests/
├─ requirements.txt
└─ .github/
   └─ workflows/
      └─ weekly_scrape.yml
```

## 14. 品質基準

### 正確性

価格、SKU、構成名、取得日時が正確であること。曖昧なデータは空欄やエラーとして扱い、勝手に補完しすぎない。

### 再現性

同じ入力URLと同じ取得日時のデータから、同じCSVとレポートが生成されること。監査時の再実行に備え、最小情報セット（入力URL一覧、取得日時、schema_version、parser_version、commit_sha、run_id、実行ログ、出力ファイルチェックサム）を必ず保存する。

### メタデータ管理

CSV/Excel成果物とは別ファイルで run metadata を保存し、最低でも `schema_version`、`parser_version`、`commit_sha`、`run_id` を持たせる。

差分比較時は `schema_version` の一致を必須条件とし、不一致時は「差分処理を停止」または「互換変換を実施してから比較」のどちらかを明示ルールで選択する。互換変換を選ぶ場合は変換ロジックのバージョンも記録する。

ファイル命名は `products_YYYY-MM-DD.csv` を維持しつつ、必ず `run_id` と紐付ける（例: 同日複数実行時はメタデータで1対1対応、または `products_YYYY-MM-DD_<run_id>.csv` を許容）。どの命名方式でも、比較対象の特定に `run_id` を使う運用ルールを固定する。

### 追跡性

各行にsource_urlとsource_checked_atを持たせ、後から元ページを確認できること。加えて、成果物ファイルと run metadata を run_id で相互参照できること。

### 失敗の見える化

取得失敗、パース失敗、価格未取得をレポートとログに出すこと。

運用仕様（最低限）:

- エラーコード体系を統一する。
  - `HTTP_<status>`: HTTPステータス起因（例: `HTTP_404`, `HTTP_429`, `HTTP_500`）
  - `TIMEOUT_CONNECT` / `TIMEOUT_READ` / `TIMEOUT_RENDER`: 接続・応答・描画待ちのタイムアウト
  - `SELECTOR_MISS`: 期待したDOMセレクタ要素が取得不可
  - `SCHEMA_MISMATCH`: JSON/HTMLの構造が想定スキーマと不一致
  - `PARSE_ERROR`: 価格・SKU・寸法などの値変換失敗
  - `RATE_LIMITED`: サイト側レート制限を検知
  - `UNKNOWN`: 上記に分類できない例外（messageに生ログ要約を残す）
- `errors` シートの必須列を固定し、欠損時はレポート生成を失敗扱いにする。
  - 必須列: `url`, `phase`, `error_code`, `message`, `first_seen_at`, `last_seen_at`
  - `phase` は `fetch` / `render` / `parse` / `normalize` / `diff` / `report` のいずれか
  - `first_seen_at` は当該run内での初回発生時刻、`last_seen_at` は最終発生時刻

### 運用安全性

公開ページのみを対象とし、ログイン情報、Cookie、顧客情報、社内価格表を扱わない前提で始める。

対象範囲ポリシーとして、`https://www.boconcept.com/ja-jp/shop/`配下のみを許可し、それ以外のパスはURL投入時点で除外する。

運用開始前チェックとして、以下を必須化する。

- robots.txtの取得・確認（アクセス禁止パス、クロール間隔指示の有無）
- 利用規約の確認（自動取得禁止条項、再配布制限、商用利用制限）
- 確認結果を`documents/compliance_checklist.md`等に記録し、更新日と確認者を残す

現時点の`https://www.boconcept.com/robots.txt`を前提に、初期運用ルールを次で固定する。

- 許可対象: `https://www.boconcept.com/ja-jp/shop/`配下
- 除外対象（robots.txt Disallow準拠）:
  - `*/search/?*`
  - `*/shop/*_*`
  - `*/shop/*?q=*`
  - `*/on/demandware*`
  - `*/p/*/print/`
  - `*/store-lead/*`
  - `*/undefined/*`
  - `*/v/*`
- URL投入時とクロール実行時の2段階で、上記除外パターンに一致するURLを必ずスキップする
- サイトマップは`https://www.boconcept.com/sitemap.xml`を参照可能だが、抽出対象は`/ja-jp/shop/`配下URLのみとする

アクセス制御ポリシー（初期値）は次を標準とする。

- requests/sec上限: 平均0.2 req/sec（5秒に1リクエスト相当）
- 同時接続数: 1（単一ワーカーで直列処理）
- クロール時間帯: 02:00-05:00 JST（通常業務時間帯を避ける）
- リトライ時は指数バックオフ＋ジッターを適用し、短時間の再試行集中を避ける

ブロック兆候の自動停止条件を次で定義する。

- 直近20リクエスト中の403比率が20%以上になった場合は即時停止
- captcha検知（captcha文字列、challenge画面、bot判定レスポンス）が1件でも発生した場合は即時停止
- 自動停止時は成果物生成を中断し、運用担当に通知する（Actions失敗＋ログ出力）

User-Agentと連絡先ポリシーは次を基本とする。

- User-Agentは固定で明示し、プロジェクト名・用途・連絡先を含める
- 例: `BoExioPriceMonitor/1.0 (+contact: boexio-ops@example.com)`
- 連絡先は運用チームの受信可能なメールアドレスを設定し、退職・異動時に更新する
- サイト側要請がある場合は、要請内容を優先してUser-Agent表記・連絡先を調整する

## 15. 要件定義書作成までの確認事項

本資料を構想ドキュメントとして確定したうえで、要件定義書に落とす前に次を確認する。

### 15.1 業務要件

- 第一段階の対象カテゴリはチェアとする
- 第一段階の対象URLは `https://www.boconcept.com/ja-jp/shop/%E3%83%81%E3%82%A7%E3%82%A2/` とする
- URLリストは手動管理とする
- 最初のURLリストは誰が管理し、更新承認を誰が行うか
- 第一段階の成果物は生データCSVとし、Excelレポートは後続段階で扱う
- 価格改定レポートの確認責任者と確認期限（例: 毎週何曜日まで）

### 15.2 データ要件

- 第一段階では取得できた価格表示をそのまま保存し、税込/税抜の正規化は後続段階で扱う
- 表示価格と定価が両方ある場合、どちらを差分対象にするか
- 張地・脚などの表記ゆれをどう正規化するか
- 削除候補の初期閾値（連続4回未検知）を変更する例外条件はあるか
- 比較キーにSKU/構成IDを使える場合の優先順位

### 15.2.1 状態遷移に関する確定事項（removed 運用）

- 状態は `active / missing_candidate / discontinued / revived` の4種類を採用する
- 週次実行前提で `連続4回未検知` を `discontinued` の閾値とする
- `discontinued` の比較キーが再検知された場合は `revived` を付与し、履歴（復活日・終了判定日・連続未検知回数・復活時価格）を残す
- 集計は `summary` と `removed` の双方で `新規候補数 / 確定終了数 / 復活数` を出す

### 15.3 システム要件

- 成果物はGitHub Releasesに残す
- CSV/Excel成果物とは別の run metadata を、どの保存先にどの期間残すか
- 定期実行の基準時刻とタイムゾーン（JST固定かUTC運用か）
- リトライ回数、タイムアウト、停止後の再開手順
- 監視通知先（メール/Slack等）と当番運用

### 15.4 コンプライアンス要件

- robots.txtと利用規約の確認頻度（初回のみ／定期見直し）
- 対象URLの許可条件（`/ja-jp/shop/`配下のみ）と除外条件（Disallowパターン）の最終定義
- User-Agentの正式表記と連絡先メールアドレス
- 停止条件（403率・captcha検知）の最終しきい値
- 問い合わせ受領時のエスカレーション手順

### 15.5 受け入れ要件（要件定義書への入力）

- 第一段階: チェアカテゴリページ1件を手動URLリストから取得できる
- 第二段階: 複数カテゴリで各10商品ずつ取得できる
- 最終段階: 全商品カテゴリの全商品を取得対象にできる
- 差分検知の許容誤差（誤検知率・見逃し率の目標）
- 障害時の復旧目標（RTO）と運用記録の保存期間

## 16. 次に作るべき具体物

優先順位は次の通り。

1. `config/target_urls.csv`（初期値はチェアカテゴリURL）
2. 1商品取得スクリプト
3. 取得結果のCSVスキーマ
4. 構成バリエーション取得の検証
5. 前回CSVとの差分比較スクリプト
6. Excelレポート生成
7. GitHub Actionsでの週次実行

最初の判断ポイントは、BoConceptの商品ページから内部JSON/APIを安定して取得できるかどうか。ここで設計の難易度が大きく変わる。

## 17. プロダクトの成功条件

初期成功:

- 1商品について、構成ごとの商品マスタをCSV化できる
- 手作業より正確に価格確認できる見込みがある

業務成功:

- 毎週の価格変更レポートが営業確認に使われる
- 価格改定の見落としが減る
- 見積作成前の価格確認工数が下がる

長期成功:

- 商品マスタが見積運用の標準データになる
- 過去価格の履歴を監査できる
- 新商品・販売終了候補の確認が定常業務として回る

## 18. まとめ

BoExioは「商品ページをスクレイピングするツール」ではなく、「営業見積の価格事故を減らすための商品情報運用基盤」として作るべき。

最短で価値を出すなら、Web画面や大規模クラウド化よりも先に、次の3点を固める。

1. 構成単位の商品マスタCSV
2. 前回との差分検知
3. 営業が読めるExcelレポート

この3つが安定すれば、GitHub Actionsによる週次自動化、履歴保存、見積書連携へ自然に拡張できる。
