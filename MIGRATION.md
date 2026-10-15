# リポジトリの独立化

2026-10-15、ユーザー指定の https://github.com/ifif1122/Trend-Radar.git に独立配置。
ローカル作業フォルダは C:/Users/Owner/Trend-Radar。

株分析コードとそのGit履歴は取り込まず、Trend Radarのコード・専用Actionsのみを配置した。取得済み18URLとSQLite履歴・レポートはローカルに引き継ぎ、旧リポジトリのIssue/PRは履歴として保持する。旧リポジトリ自体は変更しない。

旧PR・Issue・CIへのリンクは移行前の検証履歴であり、現在の連携先ではない。実行時のIssue同期先はGITHUB_REPOSITORY、PR作成先はこのフォルダのoriginから解決する。新しいIssue参照は新リポジトリで同期する。旧参照はDBのrepository_migrationsに保全した。

新リポジトリは空であることを確認して初期登録する。既存mainの変更・マージではない。以後の一般的なコード変更は作業ブランチとPRを使う。定期実行の有効化は別途リポジトリ変数で管理する。
