# Trend Radar

公式リポジトリ：[ifif1122/Trend-Radar](https://github.com/ifif1122/Trend-Radar)。独立したGitリポジトリとして管理します。

## 収集内容の分析・PC側Plus分析

内容から不満・機能要望・需要仮説を整理する画面を追加。`reports/analysis.html` に根拠・試作案・検証方法、`reports/report.html#ai-analysis` に実行済みAI分析を表示する。本文はメモリ内で特徴を抽出し、全文は保存・送信しない。

ユーザー指定により、GitHub側はPythonで収集し、PC側でChatGPTログイン済みCodexを1日1回実行する。別料金のAPIへは切り替えない。Plusの利用枠を開発と共有するため、消費率の保証はしない。設定・制限・保存先・解除方法は[CONTENT_ANALYSIS.md](CONTENT_ANALYSIS.md)を参照。

```powershell
py -3.13 -B tools/daily_analysis.py --project C:\Users\Owner\Trend-Radar
```

日本株分析とは独立した新規プロジェクト。Python 3.12以上・標準ライブラリのみ。

## 自律保守・改善（2026-10-15追加）

GitHub側の収集・保守はPythonとActionsで実行し、Codex・OpenAI API・有料サービスを呼び出さない。PC側の内容分析だけは、承認されたChatGPTログイン済みCodexで1日1回実行する。品質検査、有限再試行、メタデータキャッシュ、情報源の一時停止、改善タスク、週間提案、7/30日評価まで自動化する。一般的なコード変更・mainへのマージは自動実行しない。

```powershell
py -3.13 -m pip install -r requirements-dev.txt
py -3.13 -m pytest -q
py -3.13 -m ruff check trend_radar tests tools
py -3.13 -B -m trend_radar --mode live --weekly
py -3.13 -B -m trend_radar --mode report --feedback-file feedback.json
py -3.13 -B -m trend_radar --mode report --register-improvement change.json
```

ブラウザーの評価ボタンはlocalStorageに保存し、JSONをエクスポートする。自動送信は行わない。CLI取込か、エクスポートしたJSONを `feedback/inbox/` にレビューして追加すると、次回Actionsが取り込む。評価は重複除去し、候補別集計、品質問題、改善提案へ反映する。保存した根拠やランキングの事実性を利用者の好みで改変しない。

`reports/report.html` に品質・社会需要・改善提案・効果評価を追加。`weekly.html` が週間レポート、`quality.json`・`events.jsonl`・`failure.json` が診断用。DBに品質、問題イベント、提案、改善、評価、フィードバック、過去レポートを保持する。7/30日実データが未成立の場合は評価保留。

ActionsはUTC 23:00/11:00（JST 08:00/20:00）。日曜実行時に週間集計。手動実行も可能。実行時刻はGitHub側の遅延があり保証しない。手動有効化の前に支出上限0円・使用量を確認し、リポジトリ変数 `TREND_RADAR_SCHEDULE_ENABLED=true` を設定する。Issue同期のジョブだけ `issues:write`、状態保存のジョブだけ `contents:write` を持つ。必要なトークンはActionsの `secrets.GITHUB_TOKEN` を利用し、通常収集にAPIキーは不要。

ローカルでIssue同期を実行する場合だけ、環境変数 `GITHUB_REPOSITORY` と `GITHUB_TOKEN` を設定して `--sync-issues` を付ける。秘密値をファイルやコマンド引数に保存しない。無指定時はネット上のIssueを作らず、DB内の改善タスクだけを生成する。

追加費用の契約・課金API利用は0。Actionsは無料枠を優先し、収集12分、Issue管理3分、状態保存3分の上限、Artifact 7/14日保持。既存の株分析や他リポジトリと枠を共有するため、実費0円の継続を保証できない。利用量・ストレージを確認し、無料枠不足時は頻度・対象数を減らすか手動実行にする。

今回のCodex開発作業は利用枠を消費するが、残量は取得しておらず推測しない。消費を一定以下に保証しない。[OpenAI公式の利用枠説明](https://learn.chatgpt.com/docs/pricing)もタスク等による変動を案内している。将来AI APIを追加する場合も、明示承認と月額上限の設定が必要。今回の定期処理にAI自動開発機能はない。

仕様：[ROADMAP.md](ROADMAP.md) / [MAINTENANCE.md](MAINTENANCE.md) / [QUALITY_RULES.md](QUALITY_RULES.md) / [FEATURE_PROPOSALS.md](FEATURE_PROPOSALS.md) / [EFFECT_MEASUREMENT.md](EFFECT_MEASUREMENT.md) / [DATA_SOURCES.md](DATA_SOURCES.md)。開発は[AGENTS.md](AGENTS.md)に従い、別ブランチ・CI・Draft PRを使用する。PR作成例：`gh pr create --draft --base main --body-file PR_BODY.md`。GitHub認証がある環境では `tools/publish_pr.py` でも本文を送信できる。

```powershell
cd Trend-Radar
py -3.13 -B -m unittest discover -s tests -v
py -3.13 -B -m trend_radar --mode sample --output reports-sample
py -3.13 -B -m trend_radar --mode live
py -3.13 -B -m trend_radar --mode report
```

`reports/report.html` をブラウザーで開く。サーバー不要。元ソースは新しいタブで開く。
sampleは根拠0件の空レポート（架空URLなし）。liveはGitHub公式REST APIでIssuesとリリースの公開メタデータを取得し、元ページへのGETとHTML応答・転送・ログイン画面を確認できたもののみ初回採用する。reportは通信せず保存データを再出力し、前回確認日時を表示する。

`config.json` で対象リポジトリ、上限件数を設定。ページングで大量取得しない。通信は直列・最低1秒間隔・最大100回/実行（既定40回）・10秒タイムアウト・2MB応答上限。再試行とホスト別停止の仕様はMAINTENANCE.mdを参照。非公開ネットワークやHTTPS以外への接続を拒否する。認証情報は不要。取得API応答の本文・投稿本文は永続化しない。

## 表示と履歴

- 根拠ソース一覧／トレンド別／不満／有料需要／新着の5ビュー。投稿日時の範囲、情報源種別、根拠分類、需要候補、キーワードで絞り込み。日付不明は範囲指定時に除外。新着はレポート生成日の初回取得（JST）。
- 需要候補と根拠の相互リンク。分類理由・自己申告・URL確認と内容確認の区別を表示。
- `state/live.sqlite` に全ソース、変更版、毎回のURL確認、実行履歴を無期限保持。sampleとはDBを分離。各live実行で履歴上のURLを通信予算内で巡回確認し、削除・非公開・確認不能はランキングの集計から除外する。
- `report.json` は全メタデータ版と確認履歴を含む。`run.json` は最新の収集・採用・除外件数。初回から確認できないURLは保存しないが、除外理由は実行履歴に残す。実行・取得・確認日時はJSTで保存する。新着の基準日もJST。
- URL正規化で追跡パラメーター等の重複を除去。同種の15文字以上のタイトルが93%以上一致した場合は同一群にまとめ、元URLをすべて残して1件としてランキング計上。類似度判定には誤結合・見逃しがあり、意味的な転載検出は人手レビューが必要。
- ランキングは検証済み独立ソース群の件数順。市場需要・支払い意思の推定モデルではない。公式告知は公開活動、bug等のラベル付きIssueは不満・既存問題の**仮分類**。個人の投稿内容は再現確認していない。

## ニュース・SNS・掲示板・口コミの追加

サイトごとの許諾・API条件に従った外部取得結果から、メタデータJSON配列を `--mode live --import-file evidence.json` で取り込める。汎用スクレイピングは実装しない。手動入力も毎回URLを再検証し、検索結果・架空ドメイン・リンク不明は採用しない。API・投稿の利用条件を確認した担当者が `rights_confirmed: true` を指定する。短い独自の要約を記入し、本文を貼り付けない。

必須キー：`url`, `title`, `media`, `published_at`（不明はnull）, `summary`（400文字以下）, `kind`, `categories`（配列）, `analysis_id`, `analysis_title`, `reason`, `reliability`, `origin`, `rights_confirmed`。取得日時は実行時に設定。analysis_idは同じ需要候補で共通にする。

kind：ニュース / SNS / 掲示板 / 口コミ / GitHub Issues / 公式発表。
categories：社会的な注目 / 実際の不満 / 有料需要の証拠 / 既存サービスの問題。

有料需要は、購入・有償契約・具体的な支払い意思に言及した元投稿を担当者が確認した場合のみ指定し、`reason` に根拠と限界を記す。現在の自動収集では付与しない。200応答でもソフト404や閲覧者別のアクセス制限を完全には判別できず、内容の真偽まで保証しない。SNS・口コミの自動収集コネクターとAPI契約は未設定。

## 定期実行

本リポジトリの `.github/workflows/trend-radar.yml` を追加。既存の株分析ワークフローは変更しない。手動実行と毎日23:00/11:00 UTC（08:00/20:00 JST）の設定。日曜日は週間集計も実行。定期実行は `TREND_RADAR_SCHEDULE_ENABLED=true` のリポジトリ変数で有効化。SQLite全履歴を専用 `trend-radar-state` ブランチに保存し、レポートはArtifactに保存。GitHubへのpushとActionsの実動作は別途リポジトリへの反映が必要。

## 設計上の境界

API取得 → 直接URL検証 → メタデータ妥当性確認 → SQLite保存・類似群化 → 保守的ランキング → エスケープ済みHTML。外部リンクは `target="_blank" rel="noopener noreferrer"`。本文はAPI処理中のメモリだけに存在し、保存・HTML出力しない。履歴は削除しないためDB容量は運用時に監視する。

参照：[GitHub REST API best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)、[Rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)。APIの制限・提供元の利用規約変更に合わせて収集設定を見直す。
