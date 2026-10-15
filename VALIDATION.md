# 実装・検証結果

2026-10-15 JST。作業ブランチ：feature/trend-radar-maintenance。

| 検証 | 結果 |
|---|---|
| Trend Radar pytest | 21件通過（既存根拠テスト8件＋保守テスト13件） |
| Ruff | trend_radar / tests / tools の検査通過 |
| 既存株分析 | 回帰テスト9件通過。コード・ワークフロー変更なし |
| HTML操作スクリプト | 18ソース群、検索・絞り込み・候補別・関連度順の検証通過 |
| 外部リンク属性 | 元URLへのリンク36個すべて target=_blank / rel=noopener noreferrer |
| フィードバック | localStorage保存・JSON出力・破損データを上書きしない動作が通過 |
| DB | PRAGMA integrity_check=ok。旧履歴は維持 |
| 実収集 | GitHub Issues 10件、GitHub公式リリース4件、デジタル庁公式RSS4件（独立URL） |
| URL | 全18件で元URLのHTTP 200・HTML・転送なしを確認 |
| 差分取得 | 再実行で5取得先中3取得先が304キャッシュ再利用 |
| 重複 | 入力19項目を18URLとして保存。同じRSSの同URL重複を除去 |
| 最新の観測品質 | 取得成功率1.0、URL有効率1.0、鮮度1.0、根拠充足率1.0。小規模・限定範囲の値 |

保守テストは有限再試行、長いレート制限の停止、304、破損キャッシュ再生成、取得元の障害分離、XML実体参照拒否、問題の重複・再発、品質警告・100点採点、フィードバック検証・重複除去、7/30日保留と比較、Issue新規・再開、排他、収集から週間HTMLまでの統合、HTML失敗時の診断・履歴保持を含む。

元投稿内容の真偽・不具合再現は未検証。有料需要の根拠0件、ニュース・SNS・掲示板・口コミの専用APIは未接続。開発者向けGitHubが約78%を占める偏りを検出し、独立した日本語情報源の拡充と生活者意見の許諾調査を提案している。

操作可能なブラウザーが存在せず、実画面のレイアウト・実クリック・新タブ表示は未確認。JavaScriptの実行テストとHTTPでの元ページ取得確認を代わりに行った。PC/スマートフォン向けCSSは実装済みだが実機確認と区別する。

今回導入した改善はDBに登録済み。導入前の品質時系列がなく、7/30日評価は評価保留。テスト内の比較用数値は人工データであり、運用の改善効果として表示していない。指標定義の変更はmetric_versionでも区別する。

Actionsは08:00/20:00 JST、日曜週間集計、手動実行、read-only収集・Issue同期・状態保存の権限分離を設定。GitHub上の[回帰CI](https://github.com/ifif1122/stock-analyzer/actions/runs/38674300841)は成功。[Draft PR #1](https://github.com/ifif1122/stock-analyzer/pull/1)を作成済み。mainへのマージと定期有効化は未実施で、収集・状態永続化のActionsジョブはまだ実行していない。

Issueの実API同期では、[情報源の偏り #2](https://github.com/ifif1122/stock-analyzer/issues/2)と[生活者意見の収集条件調査 #3](https://github.com/ifif1122/stock-analyzer/issues/3)を登録。同じ状態で再同期しても同じ2つのURLに対応し、Issue増殖がないことを確認した。解決済みIssueの再開はモック試験のみであり、実在Issueをテスト目的で閉じてはいない。

追加費用の契約・課金API利用なし。Actions無料枠やストレージの残量は未取得であり、他ジョブと共用するため0円での長期稼働は保証しない。Codex残枠も未取得・推測なし。日々のコードにCodex/LLM呼出しはない。

成果物：reports/report.html、reports/weekly.html、report.json、quality.json、proposals.json、evaluations.json、run-live.json、events.jsonl、state/live.sqlite。レポート・DBはGit管理対象外。運用方法はREADME.md。
