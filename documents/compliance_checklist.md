# BoExio コンプライアンス確認メモ

作成日: 2026-05-21
更新日: 2026-05-22

## 1. 確認対象

- 対象サイト: `https://www.boconcept.com`
- 初期対象 URL: `https://www.boconcept.com/ja-jp/shop/%E3%83%81%E3%82%A7%E3%82%A2/`
- 確認日: 2026-05-21
- 再確認日: 2026-05-22

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

2026-05-22 時点でも、上記 Disallow と `Sitemap: https://www.boconcept.com/sitemap.xml` を確認した。

## 3. 利用規約確認

確認 URL:

```text
https://www.boconcept.com/ja-jp/カスタマーサービス/法的情報/利用規約/
https://www.boconcept.com/ja-jp/カスタマーサービス/法的情報/
```

確認結果:

- 日本語の利用規約は、BoConcept Japan のウェブサイト経由の商品売買取引に適用される規約として掲載されている。
- 2026-05-22 の確認範囲では、スクレイピング、クローリング、bot、API 利用を明示的に禁止する記述は確認できなかった。
- ただし、これは法的判断ではない。運用開始前に、運用責任者または法務確認者が再確認する。
- 個人情報、ログイン情報、Cookie、顧客情報、社内価格表は扱わない。

## 4. User-Agent と連絡先

Phase 1 の暫定 User-Agent:

```text
BoExioPriceMonitor/<parser_version> (+contact: <BOEXIO_CONTACT_EMAIL>)
```

実装上の扱い:

- 環境変数 `BOEXIO_CONTACT_EMAIL` が設定されている場合は、そのメールアドレスを User-Agent に含める。
- 未設定の場合は暫定値 `boexio-ops@example.com` を使う。
- 運用開始前に、受信可能な正式連絡先へ差し替える。

未確定:

- 正式な連絡先メールアドレス。
- サイト側から問い合わせがあった場合の社内対応窓口。
- 問い合わせ受領時のエスカレーション手順。

## 5. Phase 1 の URL スコープ

チェアカテゴリページ上の商品リンクは、実ページでは `/ja-jp/p/...` 配下に遷移する。

Phase 1 では次の方針で固定する。

- URL リストの投入対象は `/ja-jp/shop/` に限定する。
- 許可済みカテゴリページから発見した `/ja-jp/p/...` 商品ページのみ取得を許可する。
- 手動投入された `/ja-jp/p/...` 商品ページは Phase 1 では除外する。
- robots.txt の `*/p/*/print/` に該当する製品データシート相当 URL は取得しない。

## 6. 実行時チェック

- URL 投入時に scheme、host、path、robots.txt 除外パターンを確認する。
- カテゴリページから発見した商品詳細 URL も、取得前に scheme、host、path、robots.txt 除外パターンを確認する。
- 不許可 URL は `URL_NOT_ALLOWED` または `ROBOTS_DISALLOWED` として失敗行またはログに残す。
- 公開ページのみを対象にし、ログイン、Cookie、顧客情報、社内価格表は扱わない。

## 7. 運用開始前の未確定事項

- 正式な User-Agent 表記。
- 正式な連絡先メールアドレス。
- サイト側から問い合わせがあった場合の対応窓口。
- robots.txt と利用規約の確認頻度。
- 確認者と承認者。
