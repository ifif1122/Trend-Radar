"""Conservative temporal observations. No LLM or purchase-intent inference."""
import json
from datetime import datetime, timedelta

from .core import now, ranking


def analyze(rows, db):
    at = datetime.fromisoformat(now())
    output = []
    feedback = [json.loads(r[0]) for r in db.execute('SELECT payload FROM feedback')]
    for candidate in ranking(rows):
        evidence = [s for s in rows if s['analysis_id'] == candidate['id'] and s['verification']['status'] == '確認済み']
        current = {s['group_id'] for s in evidence if datetime.fromisoformat(s['first_seen']) >= at - timedelta(days=7)}
        previous = {s['group_id'] for s in evidence if at-timedelta(days=14) <= datetime.fromisoformat(s['first_seen']) < at-timedelta(days=7)}
        categories = {c for s in evidence for c in s['categories']}
        role = []
        if '実際の不満' in categories:
            role.extend(['消費者・利用者の不満（自己申告）', '未充足需要の調査候補'])
        if '既存サービスの問題' in categories:
            role.append('競合の課題を調査する候補')
        if '有料需要の証拠' in categories:
            role.append('支払い意思の根拠あり（確認範囲限定）')
        if not role:
            role.append('公開活動・社会課題の観測')
        output.append(dict(**candidate, roles=role, evidence_ids=[s['id'] for s in evidence], new_7d=len(current), previous_7d=len(previous), delta=len(current)-len(previous), rising=len(previous) >= 2 and len(current) >= 2 * len(previous), trend_note='初回収集や取得対象追加の影響を含む。社会全体の急上昇を意味しません。', software_opportunity='小規模なソフトウェア解決策の調査候補。実現性と競合不足は未確認。' if len(evidence) >= 2 and '実際の不満' in categories else '根拠不足または実現性未確認', feedback=dict((a, sum(f['analysis_id'] == candidate['id'] and f['action'] == a for f in feedback)) for a in ('役立った', '役立たなかった', 'もっと詳しく調査してほしい', '興味がない', '情報が不正確'))))
    return output
