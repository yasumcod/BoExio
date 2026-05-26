# BoExio Phase 1 PoC 調査メモ

作成日: 2026-05-21
更新日: 2026-05-22

## 1. 調査対象

入力対象カテゴリ:

```text
https://www.boconcept.com/ja-jp/shop/%E3%83%81%E3%82%A7%E3%82%A2/
```

代表商品候補:

```text
https://www.boconcept.com/ja-jp/p/catskills/4060001-9%3A0708s-14%3A3320/
```

代表商品候補を Catskills にした理由:

- チェアカテゴリ上位に表示されている。
- 張地と脚の構成要素がページ上に表示される。
- 構成候補数が多く、Phase 2 の複数構成取得に接続しやすい。
- 商品番号、価格、寸法、素材、画像、PDF など Phase 1 の確認対象が多い。

補助候補:

```text
https://www.boconcept.com/ja-jp/p/hamilton/402d194-9%3A0075-11%3A0137/
```

Hamilton は構成が比較的単純で、CSV v0 の最初のパース確認に使いやすい。

## 2. 現時点で確認できたカテゴリページ情報

チェアカテゴリページでは、次の情報が確認できた。

- カテゴリ名: チェア
- 表示件数: 81 アイテム
- 初期表示: 24 / 81 製品
- 商品カードに商品名、素材、価格帯、画像リンクが表示される。
- 商品詳細リンクは `/ja-jp/p/...` 配下に遷移する。

## 3. 現時点で確認できた Catskills 商品ページ情報

PoC 実行で、次の項目が確認できた。

最新成功 run:

```text
data/runs/20260521T143134Z/
```

生成ファイル:

```text
data/runs/20260521T143134Z/products_poc.csv
data/runs/20260521T143134Z/scrape_log.txt
data/runs/20260521T143134Z/run_metadata.json
data/runs/20260521T143134Z/raw/category.html
data/runs/20260521T143134Z/raw/product.html
```

| 項目 | 確認状況 | メモ |
| --- | --- | --- |
| 商品名 | 取得可能 | `Catskills armchair` |
| シリーズ | 取得可能 | `Catskills` |
| 価格 | 取得可能 | `希望小売価格 ¥ 359,900`, `¥ 257,900から` |
| 脚 | 取得可能 | `自然無垢材オーク` |
| 張地 | 取得可能 | `ベージュ Lucca ファブリック 3320` |
| 商品番号 | 取得可能 | `406500013320730` |
| 寸法 | 取得可能 | 幅 `85 cm`、奥行 `83 cm`、高さ `45/95 cm`、重さ `39 kg` |
| 素材 | 取得可能 | 背面、フレーム、座面、サスペンションなど |
| 画像 URL | 取得可能 | `og:image` から取得 |
| PDF URL | Phase 1 では空欄 | 製品データシート相当リンクは `/print/` 配下で robots 除外対象のため出力しない |
| variant_id | 取得可能 | `variantUrlKey = 4060001-9:0708s-14:3320` |
| sku | 取得可能 | `variantKey = 406500013320730` |
| 内部 JSON/API | 一部確認 | Next.js HTML 内データに `selectedOptions`、`configuration.options`、`variantUrlKey`、`variantKey` が含まれる |

## 4. URL スコープ論点

要件定義では、対象 URL を `https://www.boconcept.com/ja-jp/shop/` 配下に限定している。

一方で、商品詳細ページは実際には次のように `/ja-jp/p/...` 配下である。

```text
https://www.boconcept.com/ja-jp/p/catskills/4060001-9%3A0708s-14%3A3320/
```

このため、Phase 1 実装では次の方針を推奨する。

- 手動投入 URL は `/ja-jp/shop/` 配下のカテゴリ URL に限定する。
- カテゴリページから発見した商品詳細 URL に限り、`/ja-jp/p/...` の取得を許可する。
- robots.txt の `*/p/*/print/` は引き続き除外する。
- 直接 `/ja-jp/p/...` を手動投入できるかどうかは、運用ルールとして別途決める。

## 5. 次に行う実装

- `config/target_urls.txt` 読み込みは完了。
- URL 検証で初期カテゴリ URL を許可する処理は完了。
- カテゴリページから代表商品 URL を抽出する処理は完了。
- 代表商品ページを取得し、HTML 内 Next.js データと DOM テキストから CSV v0 を出力する処理は完了。
- 1 商品分の `products_poc.csv`、`scrape_log.txt`、`run_metadata.json` の出力は完了。

## 5.1 実装済み PoC

実行コマンド:

```text
python3 scripts/phase1_poc.py
```

実装ファイル:

```text
boexio/phase1_poc.py
scripts/phase1_poc.py
config/target_urls.txt
```

補足:

- ローカル Python の `_ssl` が壊れているため、HTTPS 取得は `urllib` 失敗時に `curl` へフォールバックする。
- 通常のサンドボックスでは DNS 解決が制限されるため、実取得にはネットワーク許可が必要。
- 本番・定期実行環境では Python の HTTPS が利用できる環境を前提にし、`curl` フォールバックはローカル PoC 用の保険として扱う。
- User-Agent は `BoExioPriceMonitor/<parser_version> (+contact: <BOEXIO_CONTACT_EMAIL>)` 形式とし、運用開始前に正式連絡先を設定する。

## 5.2 Phase 1 仕上げで確定した仕様

URL スコープ:

- 手動投入 URL は `/ja-jp/shop/` 配下のカテゴリ URL に限定する。
- カテゴリページから発見した商品詳細 URL に限り、`/ja-jp/p/` 配下の取得を許可する。
- 手動投入された `/ja-jp/p/` URL は Phase 1 では対象外とする。
- robots.txt の `*/p/*/print/` は引き続き除外する。

価格列:

- `display_price` は Phase 1 の証跡として、画面表示価格をそのまま記録する。
- `canonical_price` は差分判定向けの価格を入れる。
- `display_price` が「から」価格で `list_price` が取れる場合、Phase 2 以降は `list_price` を `canonical_price` に入れる。
- Phase 2 以降の暫定差分対象は `canonical_price` とし、価格ソース、税区分、通貨が一致しない場合は Phase 4 で比較不可として扱う。

metadata:

- `output_files` には `products_poc.csv`、`scrape_log.txt`、`run_metadata.json`、raw capture を含める。
- `output_file_checksums` には CSV、ログ、raw capture の SHA-256 を保存する。
- `run_metadata.json` 自体は自己参照 checksum が安定しないため、checksum 対象から外す。

## 6. Phase 2 方針判断のための未確認事項

- 構成 ID または SKU が複数構成分すべて HTML 内に存在するか。
- 構成変更時の価格が API で取得できるか。
- 張地、脚、サイズの候補一覧が HTML だけで取得できるか。
- Playwright で UI 操作しないと構成価格を取得できないか。
- PDF URL が HTML から安定して取得できるか。

## 7. Phase 2 方針

Phase 2 は、まず HTML 内の Next.js データを主取得元として進める。理由は、Phase 1 の商品ページ HTML に次が含まれていたため。

- `selectedOptions`
- `configuration.options`
- `variantUrlKey`
- `variantKey`
- 構成候補の表示名

ただし、構成を切り替えた際の価格が HTML 内に全件含まれるかは未確認である。そのため Phase 2 の最初の調査は、Playwright 実装ではなく、HTML 内データと関連 API の探索を優先する。
