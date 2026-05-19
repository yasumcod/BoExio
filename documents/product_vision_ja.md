# BoExio プロダクトイメージ

作成日: 2026-05-18

参照元: `/Users/mondenyasuhiro/Downloads/boconcept_scraping_architecture_and_operations_plan_ja.md`

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

## 2. 仮のプロダクト定義

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

価格改定の履歴を日付ごとに確認でき、過去の見積や価格監査に使える。毎週の成果物がGitHub ReleasesやArtifactsに残り、いつでも取り出せる。

### 開発・運用者の理想状態

対象URLを追加すれば、定期実行で商品マスタと差分レポートが生成される。取得失敗はログとエラー一覧に残り、修正すべき箇所が見える。

## 5. MVPで作るべきもの

MVPは「全自動の完成品」ではなく、価格差分検知までの最短ルートを作る。

### MVPの範囲

- 対象商品URLリストを持つ
- 1商品から主要情報を取得できる
- 商品構成ごとに1行のデータへ正規化できる
- CSVの商品マスタを出力できる
- 前回CSVと今回CSVを比較できる
- 価格変更、新規追加、削除候補を出力できる
- 営業が確認できるExcelレポートを生成できる

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
- price_from
- currency
- tax_type
- source_checked_at

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
- 成果物をArtifactsまたはReleasesに保存する

完了条件:

- cronで実行できる
- 手動実行もできる
- 失敗時にログを確認できる
- Private Repositoryで運用できる

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
GitHub Artifacts / Releases
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

同じ入力URLと同じ取得日時のデータから、同じCSVとレポートが生成されること。

### 追跡性

各行にsource_urlとsource_checked_atを持たせ、後から元ページを確認できること。

### 失敗の見える化

取得失敗、パース失敗、価格未取得をレポートとログに出すこと。

### 運用安全性

公開ページのみを対象とし、ログイン情報、Cookie、顧客情報、社内価格表を扱わない前提で始める。実運用前に対象サイトの利用規約、robots.txt、アクセス頻度を確認する。

## 15. 最初に決めるべき未確定事項

- 対象商品カテゴリはどこまでか
- 最初のURLリストは誰が管理するか
- 価格は税込・税抜どちらを正とするか
- 表示価格と定価が両方ある場合、どちらを差分対象にするか
- 張地や脚の表記ゆれをどう扱うか
- 成果物はArtifactsで十分か、Releasesに残すか
- 営業が最初に見るべきファイルはCSVかExcelか

### 状態遷移に関する確定事項（removed 運用）

- 状態は `active / missing_candidate / discontinued / revived` の4種類を採用する
- 週次実行前提で `連続4回未検知` を `discontinued` の閾値とする
- `discontinued` の比較キーが再検知された場合は `revived` を付与し、履歴（復活日・終了判定日・連続未検知回数・復活時価格）を残す
- 集計は `summary` と `removed` の双方で `新規候補数 / 確定終了数 / 復活数` を出す

## 16. 次に作るべき具体物

優先順位は次の通り。

1. `config/target_urls.csv`
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
