# BoExio Phase 1 Task Checklist

作成日: 2026-05-21
更新日: 2026-05-22

参照:

- `documents/requirements_definition_ja.md`
- `documents/product_vision_ja.md`
- `documents/phase0_design_ja.md`
- `documents/phase1_poc_findings_ja.md`
- `documents/phase2_variant_findings_ja.md`
- `documents/phase3_master_findings_ja.md`
- `documents/phase4_diff_findings_ja.md`
- `documents/phase5_report_findings_ja.md`

## 目的

Phase 1 までの実行内容をチェックリスト化し、設計・実装・調査・成果物作成の漏れを防ぐ。

Phase 1 の到達点は、BoConcept の代表商品 1 件について商品ページ構造を調査し、1 商品分の CSV を出力できる状態にすること。

## Phase 0 評価

総評:

- Phase 0 は、Phase 1 の 1 商品 PoC を作るための最小設計としては完了している。
- 入力 URL、出力ディレクトリ、CSV v0、run metadata、エラーコード、取得方式の判定基準が文書化されており、Phase 1 実装に必要な判断材料はそろっている。
- Phase 1 PoC の成果物により、Phase 0 の設計が実行可能であることも確認できている。

良かった点:

- Phase 1 のスコープと非スコープを明確に分けたため、差分検知、Excel レポート、GitHub Actions などを PoC に混ぜずに済んでいる。
- CSV v0 は Product、Variant、PriceSnapshot の後続設計に接続できる列を先に持っており、Phase 2 以降で構成単位の正規化へ進みやすい。
- 失敗 URL も CSV に残す方針、run metadata、ログ、raw 保存先が決まっており、運用時の追跡性を意識できている。
- 取得方式の優先順位を内部 JSON/API、構造化データ、レンダリング DOM、URL パターン推測の順にしたことで、Playwright 依存を最小化する判断軸ができている。

残っている課題:

- 要件では手動投入 URL を `/ja-jp/shop/` 配下に限定しているが、実商品ページは `/ja-jp/p/` 配下である。カテゴリから発見した商品ページだけ許可する現方針を、要件定義にも反映する必要がある。
- 利用規約、正式 User-Agent、連絡先、問い合わせ対応窓口が未確定であり、運用開始前のコンプライアンス確認が残っている。
- Phase 1 では代表 1 商品のみの確認であり、複数構成の全候補、構成変更時価格、関連 API の安定性は未確認である。
- `display_price` に「から」価格が入るケースがあるため、構成単位価格としては `canonical_price` / `list_price` を優先する必要がある。
- Python 実行環境の `_ssl` 問題とネットワーク許可の前提が残っており、定期実行環境では再現しない形に整える必要がある。

Phase 0 判定:

- [x] Phase 1 PoC に進める設計として妥当。
- [x] 1 商品取得の実装に必要な入出力仕様は定義済み。
- [x] Phase 2 へ進む前の論点は明確化済み。
- [ ] 運用開始に必要なコンプライアンス事項は未完了。
- [x] 複数構成取得と価格正規化の設計は Phase 2 で追加検証済み。

## 今後のタスク遂行プラン

目的:

- 最短で「商品構成ごとの商品マスタ CSV」から「価格差分レポート」まで到達する。
- 実装順序は、取得精度、比較キー、差分検知、営業向けレポート、定期運用の順に進める。
- 各 Phase は成果物と完了条件を先に固定し、完了条件を満たしたら次 Phase に進む。

優先順位:

1. Phase 1 仕上げ: 既存 PoC を運用前提に耐える形へ整える。
2. Phase 2: 1 商品の複数構成を取得し、構成単位の 1 行化を成立させる。
3. Phase 3: チェアカテゴリから複数商品を処理し、商品マスタ CSV を生成する。
4. Phase 4: 前回 CSV と今回 CSV の差分検知を実装する。
5. Phase 5: 営業・管理者が見る Excel レポートを生成する。
6. Phase 6: GitHub Actions と Releases で週次運用へ載せる。
7. Phase 7: 見積運用へ接続できる標準データとして整える。

### Phase 1 仕上げ: PoC を次 Phase の土台にする

狙い:

- 既存の 1 商品 PoC を、Phase 2 以降の実装で使い回せる仕様に固定する。
- URL スコープ、コンプライアンス、実行環境の未確定事項を先に潰す。

タスク:

- [x] 要件定義の URL スコープを更新し、手動投入は `/ja-jp/shop/`、カテゴリから発見した商品詳細は `/ja-jp/p/` を許可する方針を明記する。
- [x] `documents/compliance_checklist.md` に利用規約確認、正式 User-Agent、連絡先、問い合わせ対応窓口を追記する。
- [x] URL 投入時と実行時の robots.txt チェック方針を、実装仕様として固定する。
- [x] `run_metadata.json` の `output_files` に `run_metadata.json` 自体と raw capture を含めるかどうかを決める。
- [x] `run_id` と日付付き成果物ファイル名の対応ルールを決める。
- [x] `canonical_price` に「から」価格を入れる場合の扱いを明記する。
- [x] 表示価格と定価が両方ある場合、MVP の差分対象を `display_price`、`list_price`、`canonical_price` のどれにするか決める。
- [x] ローカル `_ssl` フォールバックが本番運用の前提にならないよう、実行環境方針を決める。
- [ ] 最初の URL リスト管理者、URL 追加・更新の承認者を決める。

完了条件:

- [x] Phase 2 実装時に URL 許可範囲で迷わない。
- [x] 運用開始前に必要なコンプライアンス項目が一覧化されている。
- [x] 価格列、metadata、成果物ファイル名の暫定ルールが決まっている。

実施メモ:

- URL スコープは、手動投入 `/ja-jp/shop/`、カテゴリから発見した `/ja-jp/p/` のみ許可で固定した。
- `display_price` は画面表示価格の証跡として保持し、「から」価格の場合は `list_price` を `canonical_price` として採用する。
- Phase 2 以降の暫定差分対象は `canonical_price` とし、なければ `list_price` を使う。価格ソース、税区分、通貨が一致しない場合は Phase 4 で比較不可にする。
- Phase 1 の成果物は `data/runs/<run_id>/` に保存する。Phase 3 で `products_current.csv` と日付付き CSV を追加する。
- `run_metadata.json` は `output_files` に含めるが、自己参照 checksum を避けるため `output_file_checksums` からは外す。
- Phase 1 PoC 検証 run: `data/runs/phase1-finish-check-success/`。
- 検証コマンド: `python3 -m py_compile boexio/phase1_poc.py scripts/phase1_poc.py`、`python3 scripts/phase1_poc.py --run-id phase1-finish-check-success`。

### Phase 2: 構成バリエーション取得

狙い:

- 1 商品を商品単位ではなく構成単位の複数行として出力する。
- 比較キーの第 1 候補を実データで検証する。

タスク:

- [x] Catskills の HTML 内 Next.js データから、張地、脚、サイズなどの候補一覧を抽出できるか確認する。
- [x] 候補一覧から全構成分の `variant_id` 候補を生成し、取得済み構成で `sku` / 商品番号を確認する。
- [x] 構成変更時の価格を API または HTML データだけで取得できるか確認する。
- [x] HTML/API だけで価格が取れない場合、Playwright で UI 操作する最小範囲を決める。
- [x] 1 商品の複数構成を `products_poc.csv` または次期 CSV に複数行で出力する。
- [x] 比較キー優先順位を実装する。第 1 候補 `variant_id`、第 2 候補 `sku`、第 3 候補 `item_number + selected_size + selected_upholstery + selected_leg`。
- [x] 属性連結キー用に trim、小文字化、NFKC、空白圧縮、記号統一の正規化処理を実装する。
- [x] 表記ゆれ辞書の初期内容を決める。例: `fabric` / `ファブリック`、`oak` / `オーク`。
- [x] 比較キー生成失敗を `missing_required_attribute`、`conflicting_identifiers`、`normalization_failed`、`empty_key_after_normalization` に分類する。
- [x] 価格、通貨、税区分、価格ソースを差分検知に使える形へ正規化する。
- [x] PDF URL の取得可否と robots 除外対象の扱いを再確認する。
- [x] 構成取得失敗時にもログと失敗行を残す。

完了条件:

- [x] 1 商品について複数構成を CSV 化できる。
- [x] 比較キー候補とフォールバック順序が実データで検証されている。
- [x] 取得失敗、キー生成失敗、価格比較不可を errors に送る準備ができている。

実施メモ:

- Phase 2 実装ファイル: `boexio/phase2_variants.py`、`scripts/phase2_variants.py`。
- Catskills の HTML 内 `configuration.options` から、脚 2 件、張地 76 件、合計 152 候補を抽出できた。
- `variant_candidates.csv` に 152 件の候補 URL と構成属性を出力する。
- `products_poc.csv` には、`--variant-limit` で指定した件数だけ variant URL を取得して複数行出力する。
- 検証 run: `data/runs/phase2-final-check-v021/`。`--variant-limit 1` で最終 CSV 形式を確認した。
- 先頭候補では `variant_id`、`sku`、`item_number`、張地、脚、`list_price`、`display_price`、通貨、税区分、画像 URL を取得できた。
- 先頭候補と 2 種類目の脚では Playwright は不要。HTML 取得だけで構成ごとの情報を取得できた。
- `variant_key`、`variant_key_from`、`variant_key_error_type`、`variant_key_error_detail` を `products_poc.csv` に追加した。
- 比較キーは `variant_id`、`sku`、正規化済み属性連結キーの順で生成する。
- 属性正規化は trim、小文字化、NFKC、空白圧縮、記号統一、初期表記ゆれ辞書を適用する。
- 初期表記ゆれ辞書は `ファブリック -> fabric`、`レザー/革 -> leather`、`オーク -> oak`、`無垢材 -> solid wood`、`自然 -> natural`、`暗色 -> dark`。
- `list_price_value`、`display_price_value`、`canonical_price_value`、`price_compare_value`、`price_compare_from`、`price_normalization_error` を追加した。
- `display_price` は「から」価格の証跡として保持し、`canonical_price` / `list_price` を差分比較候補にする。
- `phase2_errors.csv` を追加し、`url`、`phase`、`error_code`、`message`、`first_seen_at`、`last_seen_at` 形式で取得失敗、キー生成失敗、価格正規化失敗を出力する準備をした。
- 2 種類目の脚は `--variant-offset 76 --variant-limit 2` で取得確認済み。`variant_id`、`sku`、価格、比較キーを取得できた。
- 検証 run: `data/runs/phase2-final-check-v021/`、`data/runs/phase2-second-leg-check/`。
- 152 候補すべての URL 有効性と SKU 確認は、リクエスト制御を入れた Phase 3 で扱う。
- 未確認: 他商品での attributeId 差異。

Phase 3 への導線:

- Phase 3 では、Phase 2 の `extract_candidates()` と enriched CSV 形式を再利用する。
- まずカテゴリから複数商品 URL を収集し、各商品で `variant_candidates.csv` 相当の候補抽出を行う。
- 全候補取得はリクエスト数が増えるため、Phase 3 の最初に取得間隔、リトライ、run 失敗判定、403/captcha 停止を実装する。
- `products_current.csv` は Phase 2 の拡張列を含める。最低限 `variant_key`、`price_compare_value`、`price_compare_from`、`phase2_errors.csv` 相当の errors を Phase 4 入力にする。

### Phase 3: 商品マスタ生成

狙い:

- チェアカテゴリから複数商品を処理し、`products_current.csv` と日付付きスナップショットを生成する。
- CSV カラムを固定し、以降の差分検知の入力を安定させる。

タスク:

- [x] チェアカテゴリのページネーションまたは追加読み込みの仕組みを調査する。
- [x] カテゴリ内の商品 URL を重複なく収集する。
- [x] URL リストから複数商品 URL を順次処理する。
- [x] Phase 2 の候補抽出を複数商品へ適用し、商品ごとの構成候補数を metadata に保存する。
- [x] Phase 2 で保留した 152 候補すべての URL 有効性と SKU 確認を、取得制御付きで実行する。
- [x] 成功行と失敗行を同一 CSV に出力する。
- [x] `products_current.csv` を生成する。
- [x] `products_YYYY-MM-DD.csv` または `products_YYYY-MM-DD_<run_id>.csv` を保存する。
- [x] CSV カラムを Phase 4 以降の入力として固定する。
- [x] `schema_version`、`parser_version`、`commit_sha`、`run_id`、チェックサムを metadata に保存する。
- [x] 取得間隔、タイムアウト、同時接続数 1、平均 0.2 req/sec の制御を実装する。
- [x] URL 単位の再試行を実装する。`HTTP_429`、`HTTP_5xx`、`TIMEOUT_*`、`RATE_LIMITED` は再試行対象にする。
- [x] `HTTP_404` と `SCHEMA_MISMATCH` は非再試行として扱う。
- [x] 失敗率、`SCHEMA_MISMATCH` 件数、生成済み成果物保存を含む run 全体の失敗判定を実装する。
- [x] 403 比率や captcha 検知時の即時停止ルールを設計する。

完了条件:

- [x] URL リストから複数商品を取得できる。
- [x] `products_current.csv` と日付付き CSV を保存できる。
- [x] `run_status=success` / `partial_success` / `failed` を判定できる。

実施メモ:

- Phase 3 実装ファイル: `boexio/phase3_master.py`、`scripts/phase3_master.py`。
- カテゴリ HTML から `/ja-jp/p/` 商品 URL を重複なしで収集し、`discovered_product_urls.csv` に出力する。
- カテゴリ入力は `config/target_categories.csv` を既定にし、`category_name`、`category_url`、`enabled` を持つ。
- 有効カテゴリはすべて巡回し、既定では `--product-limit-per-category 3` でカテゴリごとに 3 商品ずつ取得する。`--product-limit 0` は全体上限なし、正の値は緊急停止用の全体上限として使う。
- `products_current.csv` と日付付き snapshot には `category_name` / `category_url` を追加する。
- `discovered_product_urls.csv` にはカテゴリ名、カテゴリ URL、商品 URL、重複状態を出力する。
- 最小検証ではチェアカテゴリから 23 商品 URL を発見した。
- 商品ごとに Phase 2 の `extract_candidates()` を適用し、候補数を `run_metadata.json` の `product_candidate_counts` に保存する。
- Catskills 1 商品では 152 構成候補を `variant_candidates.csv` に出力できた。
- 実取得件数は `--product-limit-per-category`、`--product-limit`、`--variant-limit-per-product` で制御する。
- `products_current.csv` と `products_YYYY-MM-DD_<run_id>.csv` を同一内容で保存する。
- 取得制御は同時接続数 1、`--request-interval` 既定 5 秒、`--timeout`、`--retries` で実装した。
- 再試行対象は `HTTP_429`、`HTTP_5xx`、`TIMEOUT_CONNECT`、`TIMEOUT_READ`、`RATE_LIMITED`。
- `HTTP_403` と captcha/challenge 検知時は即時停止する。
- `scrape_status=failed` の行は fetch error のみ errors に出し、normalize error を重複出力しないよう `phase2_variants.error_rows()` を修正した。
- 検証 run: `data/runs/phase3-smoke-check-success/`。
- 検証コマンド: `python3 -m py_compile boexio/phase1_poc.py boexio/phase2_variants.py boexio/phase3_master.py scripts/phase1_poc.py scripts/phase2_variants.py scripts/phase3_master.py`、`python3 scripts/phase3_master.py --run-id phase3-smoke-check-success --product-limit 1 --variant-limit-per-product 1 --request-interval 0 --retries 0`。
- 失敗率、`SCHEMA_MISMATCH` 件数、停止理由を含む run 全体の失敗判定を `boexio/phase3_master.py` に実装した。
- `run_metadata.json` に `scrape_error_code_counts`、`failure_rate`、`schema_mismatch_count`、`run_status_reasons` を保存する。
- `run_metadata.json` に `target_categories`、`product_limit_per_category`、カテゴリ別の発見件数、選択件数を保存する。
- Phase 3 検証資料: `documents/phase3_master_findings_ja.md`。
- Catskills 152 構成全件検証 run: `data/runs/phase3-catskills-all-variants/`。
- 152 構成は全件 `scrape_status=success`、SKU 欠損 0、`variant_key` 欠損 0、`price_compare_value` 欠損 0、errors 0。
- 複数商品 attributeId 検証 run: `data/runs/phase3-multi-product-attribute-check-v2/`。
- 6 商品で候補抽出を確認し、`vaMaterialUpholstery` がない Hamilton では `vaMaterialSeat` を使う差異を確認した。
- `vaMaterialSeat` fallback を実装し、Hamilton は 6 候補へ展開できるようになった。
- カテゴリ HTML では商品 URL 23 件を確認した。`pageParams` は `[1]`、`rel="next"` はなし。`Load more` は翻訳辞書内の汎用文言で、商品一覧追加読み込みボタンとは断定しない。

### Phase 4: 差分検知

狙い:

- 前回 CSV と今回 CSV を比較し、価格変更、新規追加、削除候補、比較不可を分離する。
- 誤検知を避けるため、比較不可データは errors に出す。

タスク:

- [x] 前回 CSV と今回 CSV の読み込み処理を実装する。
- [x] `schema_version` 不一致時の挙動を決める。停止するか、互換変換後に比較するかを明記する。
- [x] 比較キー生成ロジックを差分検知前の共通前処理にする。
- [x] `price_changes_YYYY-MM-DD.csv` を生成する。
- [x] `new_items_YYYY-MM-DD.csv` または `added` CSV を生成する。
- [x] `removed_items_YYYY-MM-DD.csv` または `removed` CSV を生成する。
- [x] 価格欠損、価格ソース不一致、税区分不一致、通貨不一致、数値化不可を価格変更として扱わず errors に出す。
- [x] `currency_mismatch` を errors と summary 件数に反映する。
- [x] `missing_candidate`、`discontinued`、`revived` の状態遷移を実装する。
- [x] 連続 4 回未検知で `discontinued` とする。
- [x] `revived_at`、`discontinued_at`、`missing_streak_at_discontinue`、`revived_price` を記録する。
- [x] 比較キー方式変更時の旧キー・新キー併記と切替日記録の方針を決める。

完了条件:

- [x] price_changes、added、removed、errors を生成できる。
- [x] 比較不可データが差分判定に混ざらない。
- [x] 状態遷移が週次運用前提で追跡できる。

実施メモ:

- Phase 4 実装ファイル: `boexio/phase4_diff.py`、`scripts/phase4_diff.py`。
- 入力 CSV は `--previous-csv` と `--current-csv` で指定する。
- metadata は明示指定がなければ CSV と同じディレクトリの `run_metadata.json` を読む。
- `schema_version` 不一致時は差分処理を停止し、`errors.csv` に `schema_version_mismatch` を出して `run_status=failed` とする。
- 比較キーは Phase 3 生成済みの `variant_key` を使う。欠損・重複は diff error に出す。
- 価格比較は `price_compare_value` を使う。ただし `currency`、`tax_type`、`price_compare_from` が一致しない場合は価格変更に混ぜず errors に出す。
- 削除候補は `missing_candidate` とし、`missing_streak` が 4 回以上で `discontinued` とする。
- `previous` に `current_state=discontinued` の行があり、今回復活した場合は `revived` として `new_items` に出す。
- 比較キー方式変更は schema / parser の互換性問題として扱い、現時点では旧キー・新キー併記ではなく `schema_version` 不一致で停止する方針にした。
- Phase 4 検証資料: `documents/phase4_diff_findings_ja.md`。
- 検証 run: `data/runs/phase4-fixture-check/`、`data/runs/phase4-same-csv-check/`、`data/runs/phase4-schema-mismatch-check/`、`data/runs/phase4-smoke-to-full-check/`。
- `phase4-fixture-check` では価格変更 1 件、新規 1 件、削除候補 1 件、通貨不一致 1 件を検出した。
- `phase4-same-csv-check` では 152 行同士の比較で差分 0、errors 0 を確認した。
- `phase4-schema-mismatch-check` では schema 不一致で `run_status=failed`、exit code 1 を確認した。
- `phase4-smoke-to-full-check` では 1 行から 152 行への比較で新規 151 件を検出した。
- Phase 4 の単体テスト: `tests/test_phase4_diff.py`。
- 検証コマンド: `python3 -m unittest tests/test_phase4_diff.py`。

### Phase 5: Excel レポート生成

狙い:

- 営業担当と管理者が、価格変更、新商品、削除候補、取得失敗を 1 ファイルで確認できるようにする。
- CSV は基盤データ、Excel は業務確認用成果物として扱う。

タスク:

- [x] `weekly_report_YYYY-MM-DD.xlsx` を生成する。
- [x] `summary` シートを作る。取得日、対象商品数、成功数、失敗数、総構成数、価格変更数、値上げ数、値下げ数、新規追加数、削除候補数を含める。
- [x] `summary` に新規候補数、確定終了数、復活数、通貨不一致件数、比較不可件数を含める。
- [x] `price_changes` シートを作る。商品名、商品番号、サイズ、張地、脚、前回価格、今回価格、差額、変化率、商品 URL、取得日時を含める。
- [x] `added` シートを作る。
- [x] `removed` シートを作る。`variant_key`、現在状態、連続未検知回数、初回未検知日、discontinued 判定日、revived 検知日、復活後初回価格を含める。
- [x] `current_master` シートを作る。
- [x] `errors` シートを作る。必須列は `url`、`phase`、`error_code`、`message`、`first_seen_at`、`last_seen_at`。
- [x] `phase` は `fetch`、`render`、`parse`、`normalize`、`diff`、`report` のいずれかに統一する。
- [x] errors シートの必須列欠損時はレポート生成を失敗扱いにする。
- [x] 金額、差額、変化率を営業が確認しやすい形式に整形する。
- [ ] 価格改定レポートの確認責任者と確認期限を決める。

完了条件:

- [x] 営業確認に必要な 6 シートを含む Excel が生成される。
- [x] 取得失敗や解析失敗が errors シートで追える。
- [x] 価格変更の見落としを減らす確認導線になっている。

実施メモ:

- Phase 5 実装ファイル: `boexio/xlsx_writer.py`、`boexio/phase5_report.py`、`scripts/phase5_report.py`。
- 外部依存を増やさず、Python 標準ライブラリで XLSX を生成する。
- 入力は Phase 4 の run ディレクトリと Phase 3 の `products_current.csv`。
- 出力は `weekly_report_YYYY-MM-DD_<run_id>.xlsx` と `run_metadata.json`。
- 生成シートは `summary`、`price_changes`、`added`、`removed`、`current_master`、`errors` の 6 シート。
- 明細シートは autofilter と freeze top row を付ける。
- `errors.csv` の必須列が欠損している場合はレポート生成を失敗させる。
- Phase 5 検証資料: `documents/phase5_report_findings_ja.md`。
- 検証 run: `data/runs/phase5-smoke-report/`。
- 生成ファイル: `data/runs/phase5-smoke-report/weekly_report_2026-05-23_phase5-smoke-report.xlsx`。
- `phase5-smoke-report` では `summary` 19 行、`added` 151 明細行、`current_master` 152 明細行、`errors` ヘッダーのみを確認した。
- Phase 5 の単体テスト: `tests/test_phase5_report.py`。
- 検証コマンド: `python3 -m unittest tests/test_phase4_diff.py tests/test_phase5_report.py`。

### Phase 6: GitHub Actions 定期実行

狙い:

- 週次自動実行し、成果物を GitHub Releases に保存する。
- 失敗時にもログ、metadata、errors を残す。

決定事項:

- 定期実行は毎週日曜 15:00 JST とする。
- GitHub Actions の cron は UTC 指定のため `0 6 * * 0` とする。
- 成果物は GitHub Actions artifact と GitHub Releases の両方に保存する。
- artifact は一時確認用として 30 日保持する。
- GitHub Releases は監査・過去参照用として長期保存する。
- Release tag は `weekly-YYYY-MM-DD`、Release name は `BoExio Weekly Report YYYY-MM-DD` を基本形にする。
- `run_status=failed` の場合も、生成済み成果物、errors、metadata、ログを保存する。
- Release 作成に必要な workflow permissions は `contents: write` とする。
- `BOEXIO_CONTACT_EMAIL` は secret / env で渡せる形にするが、正式な値は後で設定する。
- 通知機能は実装するが、通知先は未設定でも動くようにする。

タスク:

- [x] GitHub Actions の `workflow_dispatch` を追加する。
- [x] GitHub Actions の週次 `cron` を `0 6 * * 0` で追加する。
- [x] 実行基準時刻とタイムゾーンを決める。毎週日曜 15:00 JST。
- [x] Private Repository で Release 作成に必要な権限を確認する。`contents: write` を使う。
- [x] secrets / env の扱いを決める。`BOEXIO_CONTACT_EMAIL` と通知先は任意設定にする。
- [x] Phase 3、Phase 4、Phase 5 を順に実行する workflow を作る。
- [x] 失敗しても成果物保存 step が実行されるように `if: always()` を使う。
- [x] CSV、Excel、run metadata、ログ、errors を GitHub Actions artifact として 30 日保存する。
- [x] CSV、Excel、run metadata、ログを GitHub Releases の assets として保存する。
- [x] `run_status=failed` の場合も生成済み成果物と errors を保存する。
- [x] Release tag を `weekly-YYYY-MM-DD` 形式にする。
- [x] Release name を `BoExio Weekly Report YYYY-MM-DD` 形式にする。
- [x] failed run の Release 本文または名前で失敗が分かるようにする。
- [x] 通知先 secret が設定されている場合だけ通知を送る処理を入れる。
- [x] 停止後の再開手順を運用メモにまとめる。
- [x] 監視通知先を決める。初期は GitHub Actions 失敗通知、任意 webhook は `BOEXIO_NOTIFY_WEBHOOK_URL`。
- [x] robots.txt と利用規約の確認頻度を決める。通常時は月 1 回、停止・対象追加・取得範囲拡大時は都度確認。
- [x] 障害時の復旧目標と運用記録の保存期間を決める。

完了条件:

- [x] cron と手動実行の両方で起動できる。
- [x] 毎週日曜 15:00 JST 相当の cron が設定されている。
- [x] 成果物が GitHub Releases から取得できる設計になっている。
- [x] 成果物が GitHub Actions artifact からも 30 日間取得できる設計になっている。
- [x] 失敗時に運用担当者がログと errors から原因を追える設計になっている。
- [x] 通知先と連絡先メールが未設定でも workflow が失敗しない。

実施メモ:

- Phase 6 workflow: `.github/workflows/boexio-weekly.yml`。
- 手動実行は `workflow_dispatch`、定期実行は毎週日曜 15:00 JST 相当の `0 6 * * 0`。
- 手動実行では `product_limit_per_category` を指定できる。既定は 3 件で、`product_limit=0` は全体上限なしを意味する。
- workflow permissions は `contents: write` のみ設定した。
- Phase 3、Phase 4、Phase 5 を順に実行し、各 phase の終了コードと `run_metadata.json` の `run_status` を Phase 6 metadata に集約する。
- 前回 CSV は最新の過去 GitHub Release asset `phase3_products_current.csv` から取得する。初回など前回 CSV がない場合は Phase 2 schema の空 CSV を生成し、今回行を new item として扱う。
- `artifacts/` に CSV、Excel、metadata、errors、workflow logs、tar.gz bundle、Release body を集約し、GitHub Actions artifact と GitHub Release assets の両方に保存する。
- artifact retention は 30 日。
- Release tag は `weekly-YYYY-MM-DD`、Release name は `BoExio Weekly Report YYYY-MM-DD`。
- `BOEXIO_CONTACT_EMAIL` は任意 secret として env に渡す。未設定時は既存既定値で動く。
- 通知 secret は `BOEXIO_NOTIFY_WEBHOOK_URL`。未設定時は skip し、設定済みでも通知 step は `continue-on-error` とする。
- TODO: 正式な webhook 通知先と正式な `BOEXIO_CONTACT_EMAIL` を決める。
- Phase 6 運用メモ: `documents/operations_runbook_ja.md`。
- 初期監視通知は GitHub Actions 失敗通知を使い、任意 webhook は `BOEXIO_NOTIFY_WEBHOOK_URL` に接続する。
- robots.txt と利用規約は通常時に月 1 回、停止・対象追加・取得範囲拡大時に都度確認する。
- 初期保存期間は GitHub Actions artifact 30 日、GitHub Releases 3 年、運用判断記録 3 年。

### Phase 7: 見積運用連携

狙い:

- 商品マスタを見積作成前の標準参照データとして使える状態にする。
- 将来的な見積書自動生成や管理画面の入力として使える形に整える。

タスク:

- [x] 見積に必要なカラムを営業確認の観点で棚卸しする。
- [x] 営業が参照する標準ファイルを定義する。
- [x] 商品 URL から元ページを確認できる導線を残す。
- [x] 価格履歴監査に必要な過去成果物の保存期間を決める。
- [x] 複数カテゴリへ広げる判断基準を作る。
- [x] 全商品カテゴリへ広げる前の受け入れ条件を決める。
- [x] 将来的な管理画面、API、見積書自動生成に必要な追加データを整理する。
- [x] 営業向け標準カラム順をコード上に定義する。
- [x] Phase 5 の `current_master` シートを Phase 7 標準カラム順に寄せる。
- [x] 既存データにない状態管理列と監査列は空欄で出力できるようにする。
- [x] `source_url` を標準確認導線として `current_master` に残す。
- [x] `source_url` が空の行を見積確定前の手動確認対象として分かるようにする。

完了条件:

- [x] 商品マスタが見積運用の標準データとして使える。
- [x] 過去価格の履歴を監査できる。
- [x] 新商品と販売終了候補の確認が定常業務として回る。
- [x] `current_master` シートが Phase 7 の標準カラム順で出力される。
- [x] `source_url`、価格監査列、run 追跡列が `current_master` から欠落しない。

実施メモ:

- Phase 7 設計資料: `documents/phase7_quote_integration_ja.md`。
- 営業が参照する標準ファイルは `phase5_weekly_report.xlsx`、`phase3_products_current.csv`、`phase6_metadata.json` とする。
- 見積前の元ページ確認導線は `source_url` とする。robots 除外対象の PDF 取得は標準導線にしない。
- 価格履歴監査は GitHub Releases を正本とし、初期保存期間は 3 年とする。
- 複数カテゴリ拡張は、チェアカテゴリの週次 run が 2 回連続で成功または許容済み `partial_success` であることを前提にする。
- 全商品カテゴリへ広げる前に、カテゴリ別 metadata、属性差異、Release asset サイズ、営業確認体制を受け入れ条件として確認する。
- Phase 7 標準カラム定義は `boexio/quote_columns.py` に追加した。
- Phase 5 の `current_master` は、識別、商品、構成、価格、状態、参照、監査の順に固定した。
- Phase 7 標準カラムに `category_name` / `category_url` を追加し、カテゴリ別の営業確認ができるようにした。
- `current_state`、`missing_streak` など、既存 `products_current.csv` にない状態列は空欄で出力する。
- `parser_version`、`schema_version` は Phase 3 の `run_metadata.json` が同じディレクトリにある場合は補完し、metadata がない場合も空欄で壊れないようにした。
- `source_url` が空の行は `source_url_review_required=yes` として、見積確定前の手動確認対象にする。
- robots 除外対象になり得る `pdf_url` は Phase 7 の標準確認導線には含めず、`source_url` を標準導線とする。
- 標準マスタ CSV は今回は追加しない。Phase 7 設計で営業参照ファイルを `phase5_weekly_report.xlsx`、`phase3_products_current.csv`、`phase6_metadata.json` の 3 種類に固定しており、まずは既存成果物の列順整備を優先するため。
- Phase 7 の追加テストは `tests/test_phase5_report.py` に入れた。`current_master` の列順、存在しない標準列の空欄出力、`source_url`、価格監査列、run 追跡列の欠落防止、空 `source_url` の手動確認フラグを確認する。
- 検証コマンド: `python3 -m unittest tests/test_phase5_report.py tests/test_phase6_workflow.py`、`python3 -m unittest discover -s tests`。

### 横断タスク: テストと品質ゲート

- [x] 比較キー生成ロジックの単体テストを追加する。
- [x] 属性正規化ロジックの単体テストを追加する。
- [x] 価格差分判定ロジックの単体テストを追加する。
- [x] added / removed / price_changes の判定テストを追加する。
- [x] `missing_candidate`、`discontinued`、`revived` の状態遷移テストを追加する。
- [x] errors シートの必須列欠損時にレポート生成が失敗扱いになることをテストする。
- [x] `schema_version` 不一致時の挙動をテストする。
- [x] 実取得なしで再現できる fixture HTML / CSV を整備する。Phase 2 の最小 HTML fixture と CSV fixture を追加済み。
- [x] ネットワーク取得を伴う検証は、通常テストと分離して手動または CI の限定ジョブにする。

### 横断タスク: 未確定事項の決定

- [ ] 最初の URL リストの管理者を決める。
- [ ] URL 追加・更新の承認者を決める。
- [ ] 価格改定レポートの確認責任者を決める。
- [ ] 価格改定レポートの確認期限を決める。
- [ ] 表示価格と定価が両方ある場合の差分対象を決める。
- [ ] 張地・脚などの表記ゆれ辞書の初期内容を決める。
- [ ] 削除候補の連続 4 回未検知ルールを変更する例外条件を決める。
- [ ] run metadata の保存先と保存期間を決める。
- [x] 定期実行の基準時刻とタイムゾーンを決める。毎週日曜 15:00 JST。
- [x] 停止後の再開手順を決める。
- [x] 監視通知先を決める。初期は GitHub Actions 失敗通知、任意 webhook は `BOEXIO_NOTIFY_WEBHOOK_URL`。
- [x] robots.txt と利用規約の確認頻度を決める。
- [ ] User-Agent の正式表記を決める。Phase 6 では env / secret で差し替え可能にする。
- [ ] 連絡先メールアドレスを決める。Phase 6 では `BOEXIO_CONTACT_EMAIL` を任意設定にする。
- [ ] 問い合わせ受領時のエスカレーション手順を決める。
- [ ] 差分検知の許容誤差を決める。
- [x] 障害時の復旧目標を決める。
- [x] 運用記録の保存期間を決める。

## 実行ルール

- 公開ページのみを対象にする。
- 対象 URL は `https://www.boconcept.com/ja-jp/shop/` 配下に限定する。
- 取得できない項目は推測で補完せず、空欄またはエラーとして扱う。
- 失敗 URL も `scrape_status=failed` の行として CSV に残す。
- Phase 1 では差分検知、Excel レポート、GitHub Actions、販売終了状態管理は実装対象外とする。
- 設計判断は後続 Phase で参照できるように文書へ残す。

## Phase 0: 着手前設計

- [x] Phase 0 設計メモを作成する。
- [x] Phase 1 のスコープと非スコープを明記する。
- [x] 入力 URL リストの形式を決める。
- [x] CSV v0 のカラム定義を決める。
- [x] run metadata v0 の項目を決める。
- [x] エラーコード v0 の扱いを決める。
- [x] 出力ディレクトリ構成を決める。
- [x] robots.txt / 利用規約確認の記録先を決める。

## Phase 1: 1 商品 PoC

- [x] 代表商品 URL を 1 件選定する。
- [x] 商品ページの HTML 構造を確認する。
- [x] HTML 内の構造化データを確認する。
- [x] 内部 JSON / API の有無を確認する。
- [x] Playwright が必要か判断する。
- [x] 商品名の取得可否を確認する。
- [x] 商品番号の取得可否を確認する。
- [x] 価格の取得可否を確認する。
- [x] 寸法の取得可否を確認する。
- [x] 画像 URL の取得可否を確認する。
- [x] PDF URL の取得可否を確認する。
- [x] `variant_id` の取得可否を確認する。
- [x] `sku` の取得可否を確認する。
- [x] サイズ、張地、脚など構成属性の取得可否を確認する。
- [x] 1 商品分の生データ CSV を出力する。
- [x] 取得失敗時に失敗行 CSV を出力できることを確認する。
- [x] 取得項目と未取得項目を整理する。
- [x] Phase 2 の取得方式方針を決める。

## Phase 1 成果物

- [x] `documents/phase0_design_ja.md`
- [x] `documents/phase1_poc_findings_ja.md`
- [x] 入力 URL リスト
- [x] 1 商品分の CSV サンプル
- [x] 取得ログ
- [x] run metadata サンプル

## Phase 1 完了判定

- [x] 1 商品の CSV を出力できる。
- [x] 取得できた項目と未取得項目が整理されている。
- [x] JSON/API 方式で進めるか、Playwright 中心にするか判断できる。
- [x] Phase 2 で複数構成取得へ進むための未解決事項が明確になっている。

## Phase 1 では実装しない項目

- [x] 差分検知は Phase 1 対象外として確認済み。
- [x] Excel レポート生成は Phase 1 対象外として確認済み。
- [x] GitHub Actions 定期実行は Phase 1 対象外として確認済み。
- [x] GitHub Releases への成果物保存は Phase 1 対象外として確認済み。
- [x] 連続未検知による `discontinued` 判定は Phase 1 対象外として確認済み。
- [x] 見積運用連携は Phase 1 対象外として確認済み。
