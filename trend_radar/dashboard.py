import html
import json
from pathlib import Path

from .improvement import ACTIONS, evaluate, proposals
from .quality import recent
from .research import analyze
from .storage import migrate
from .content import analyze_content
from .content_report import fragment as content_fragment
from .ai_analysis import latest, packet
from .ai_report import fragment as ai_fragment
import hashlib


def data(db, rows):
    migrate(db)
    ai = latest(db)
    digest = hashlib.sha256(json.dumps(packet(rows), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return dict(quality=recent(db), proposals=proposals(db), evaluations=evaluate(db), research=analyze(rows, db), content_analysis=analyze_content(rows, db), ai_analysis=ai, ai_input_state='current' if ai and ai['input_hash'] == digest else 'stale', problems=[dict(r) | dict(payload=json.loads(r['payload'])) for r in db.execute('SELECT * FROM problems ORDER BY active DESC,last_seen DESC')], feedback_count=db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0], previous_reports=[dict(r) for r in db.execute('SELECT * FROM report_snapshots ORDER BY id DESC LIMIT 20')])


def escaped(value):
    return html.escape(str(value), quote=True)


def pretty(value):
    return '<pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + escaped(json.dumps(value, ensure_ascii=False, indent=2)) + '</pre>'


def fragment(d):
    e = escaped
    research = []
    for a in d['research']:
        buttons = ''.join(f'<button class="feedback-button" data-analysis="{e(a["id"])}" data-action="{e(action)}">{e(action)}</button>' for action in ACTIONS)
        research.append(f'<article><h3>{e(a["title"])}</h3><p>{e(" / ".join(a["roles"]))}</p><p>収集増減：直近7日 {a["new_7d"]}群 / 前7日 {a["previous_7d"]}群 / 差 {a["delta"]:+}群。急増条件：{"該当" if a["rising"] else "非該当・比較データ不足の場合を含む"}</p><p>{e(a["trend_note"])} {e(a["software_opportunity"])}</p><p>取り込み済み評価：{e(a["feedback"])}</p><a href="#candidate-{e(a["id"])}">候補・根拠へ</a><div>{buttons}</div></article>')
    labels = dict(success_rate='情報収集成功率', freshness_rate='7日以内の情報率', duplicate_rate='類似ソース群による重複率', url_valid_rate='元URL有効率', evidence_coverage='独立根拠2群以上の充足率', insufficient_candidates='根拠不足候補数', duration_seconds='収集・検証時間（秒）', invalid_dates='不正・不明日付数', classification_accuracy='分類正解率', actions_duration_seconds='Actions全体時間（秒）')
    q = d['quality'][0] if d['quality'] else None
    values = ''.join(f'<dt>{e(label)}</dt><dd>{e(q.get(key)) if q and q.get(key) is not None else "未測定・データなし"}</dd>' for key, label in labels.items())
    history_rows = ''.join('<tr>' + ''.join(f'<td>{e(x.get(k)) if x.get(k) is not None else "未測定"}</td>' for k in ('at', 'success_rate', 'freshness_rate', 'duplicate_rate', 'url_valid_rate', 'duration_seconds')) + '</tr>' for x in d['quality'][:30])
    history_table = '<div style="overflow:auto"><table><caption>品質推移（最新30測定）</caption><tr><th>測定日時</th><th>成功率</th><th>鮮度</th><th>重複率</th><th>URL有効率</th><th>秒</th></tr>' + history_rows + '</table></div>'
    problems = ''.join(f'<article><h3>{e(p["payload"]["summary"])} — {e(p["payload"]["severity"])}</h3><p>{"発生中" if p["active"] else "検出解消"} / 発生 {p["occurrences"]}回 / 初回 {e(p["first_seen"])} / 最新 {e(p["last_seen"])}</p><p>{e(p["payload"]["suggestion"])}</p>{f"<a href=\"{e(p['github_url'])}\" target=\"_blank\" rel=\"noopener noreferrer\">関連Issue</a>" if p['github_url'] else "Issueは未同期"}</article>' for p in d['problems'])
    proposal_cards = []
    for i, p in enumerate(d['proposals']):
        detail = {k: p[k] for k in ('problem', 'reason', 'use_case', 'expected', 'method', 'difficulty', 'effort', 'operating_cost', 'risk', 'metric', 'evidence', 'score_reasons')}
        if p.get('github_url'):
            detail['関連GitHub Issue'] = p['github_url']
        issue_link = f'<a href="{e(p["github_url"])}" target="_blank" rel="noopener noreferrer">関連Issueを開く</a>' if p.get('github_url') else ''
        proposal_cards.append(f'<article><h3>優先{i+1}：{e(p["name"])}</h3><p>{p["score"]}/100 · {e(p["status"])} · {e(p["inference"])}</p><p>配点 {e(p["basis"])} / 上限 {e(p["weights"])}</p>{issue_link}{pretty(detail)}</article>')
    evaluations = ''.join(f'<article><h3>{e(x["name"])}：{x["horizon"]}日評価 — {e(x["verdict"])}</h3><p>評価予定 {e(x["due"])} / {e(x["reason"])}</p>{pretty(x)}</article>' for x in d['evaluations'])
    return ai_fragment(d['ai_analysis'], d['ai_input_state']) + content_fragment(d['content_analysis']) + f'''<section id="research"><h2>トレンド・社会需要の観測</h2><p>最新の公開情報から作る調査仮説です。社会課題・未充足需要・ビジネス機会の確定には追加調査が必要です。AI分析の実行状況は別枠に表示します。</p>{''.join(research) or '<p>観測データなし</p>'}</section>
<section id="quality"><h2>システム品質</h2><p>比率は0〜1。内容の真偽や分類精度をURL有効率と混同しません。最新測定：{e(q['at']) if q else '未実施'}</p><dl>{values}</dl><p>入力同一URL重複率：{e(q.get('input_duplicate_rate')) if q else '未測定'} / 失敗実行累計：{e(q.get('failed_runs')) if q else '未測定'}</p><h3>情報源ごとのエラー</h3>{pretty(q.get('source_errors', {}) if q else {})}{history_table}<details><summary>品質履歴の詳細</summary>{pretty(d['quality'])}</details><h3>検出した問題</h3>{problems or '<p>検出なし（未検査の場合を含む）</p>'}</section>
<section id="proposals"><h2>新機能・改善提案（最大5件）</h2><p>固定ルールによる推奨順位。点数は期待効果の保証ではありません。既に実装済みの提案は除外します。高度なAI提案は明示承認・月額上限を設定するまで無効です。</p>{''.join(proposal_cards) or '<p>追加提案なし</p>'}</section>
<section id="effects"><h2>改善効果・履歴</h2>{evaluations or '<p>登録済み改善なし。実装前基準値は次の改善の比較に利用します。</p>'}<details><summary>過去レポートとの比較用スナップショット</summary>{pretty(d['previous_reports'])}</details></section>
<section id="feedback"><h2>利用者フィードバック</h2><p>候補ごとのボタンでこのブラウザー内に保存します。サーバーへ送信しません。JSONをエクスポートし、CLIの --feedback-file で取り込むと次回の候補表示・品質検査・改善提案に反映します。興味がない評価でも根拠を削除しません。</p><button id="export-feedback">フィードバックJSONを保存</button><p id="feedback-status" role="status">取り込み済み {d['feedback_count']}件。ブラウザー内の評価は未送信です。</p></section>'''


def feedback_script():
    return '<script>' + Path(__file__).with_name('feedback.js').read_text(encoding='utf-8') + '</script>'


def weekly_html(payload):
    return '<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Trend Radar 週間レポート</title><body style="font:16px/1.7 system-ui;max-width:1000px;margin:auto;padding:20px"><h1>Trend Radar 週間レポート</h1><a href="report.html">ダッシュボードへ</a>' + pretty(payload) + '</body></html>'
