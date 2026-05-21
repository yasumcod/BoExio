# BoExio コンプライアンス確認メモ

作成日: 2026-05-21

## 1. 確認対象

- 対象サイト: `https://www.boconcept.com`
- 初期対象 URL: `https://www.boconcept.com/ja-jp/shop/%E3%83%81%E3%82%A7%E3%82%A2/`
- 確認日: 2026-05-21

## 2. robots.txt 確認

確認 URL:

```text
https://www.boconcept.com/robots.txt
```

確認できた主な Disallow:

```text
*/search/?*
*/shop/*_*
*/shop/*?q=*
*/on/demandware*
*/p/*/print/
*/store-lead/*
*/undefined/*
*/v/*
```

初期対象のチェアカテゴリ URL は、上記の初期除外パターンには該当しない。

## 3. Phase 1 の注意点

チェアカテゴリページ上の商品リンクは、実ページでは `/ja-jp/p/...` 配下に遷移する。

現行要件では対象 URL を `/ja-jp/shop/` 配下に限定しているため、Phase 1 で商品詳細ページを直接取得する場合は次のどちらかを決める必要がある。

- URL リストの投入対象は `/ja-jp/shop/` に限定し、カテゴリページから発見した `/ja-jp/p/...` 商品ページのみ取得を許可する。
- Phase 1 の商品ページ PoC に限り、代表商品 URL として `/ja-jp/p/...` を明示的に許可する。

この扱いは Phase 1 実装前に確定する。

## 4. 未確認事項

- 利用規約のスクレイピング関連記述。
- 正式な User-Agent 表記。
- 連絡先メールアドレス。
- サイト側から問い合わせがあった場合の対応窓口。
