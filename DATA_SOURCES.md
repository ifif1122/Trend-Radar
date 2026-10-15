# 取得元と制約

| 取得元 | 接続・内容 | 制約 |
|---|---|---|
| GitHub公式REST | microsoft/vscode、ollama/ollamaの公開Issues・リリース | 少数取得、PR除外、ETag/Last-Modified、403/429停止、本文は保存しない |
| デジタル庁公式RSS | 日本の行政デジタル化の新着題名・元URL・公開日時 | 5配信項目/回、独自の短い概要、元URL検証、転載記事本文は保存しない |
| ニュース・SNS・掲示板・口コミ・公式統計 | 利用許諾確認済みメタデータの手動取込に対応 | 専用自動APIは未接続。有料APIや汎用スクレイピングを代用しない |

デジタル庁の[RSS案内](https://www.digital.go.jp/rss)が案内する配信を使用し、[サイトポリシー](https://www.digital.go.jp/site-policy)・[コピーライトポリシー](https://www.digital.go.jp/copyright-policy)を確認。出典メディア名と直接URLを必ず併記し、概要にはTrend Radarによる分類・要約と表示する。外部の第三者著作物・商標の権利は別途尊重する。RSS掲載は内容の事実確認や有料需要の証明ではない。

[GitHub API best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)に従い、直列通信・条件付き取得・有限待機を使用。レート制限値を回避する認証切り替えはしない。

収集済みの元URLはすべて最初の保存時にHTML応答を検証する。検索結果URL・架空URL・未確認情報は採用しない。200応答でもソフト404・真偽の完全な判別はできず、確認範囲と日時を表示する。重複群化は文字列類似であり意味的重複の完全検出ではない。
