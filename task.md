# BoExio Phase 1 Task Checklist

作成日: 2026-05-21

参照:

- `documents/requirements_definition_ja.md`
- `documents/product_vision_ja.md`

## 目的

Phase 1 までの実行内容をチェックリスト化し、設計・実装・調査・成果物作成の漏れを防ぐ。

Phase 1 の到達点は、BoConcept の代表商品 1 件について商品ページ構造を調査し、1 商品分の CSV を出力できる状態にすること。

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
