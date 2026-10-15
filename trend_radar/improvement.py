import hashlib
import json
from datetime import datetime, timedelta

from .core import now
from .quality import recent

ACTIONS = ('役立った', '役立たなかった', 'もっと詳しく調査してほしい', '興味がない', '情報が不正確')
WEIGHTS = dict(value=30, severity=25, ease=20, cost=15, evidence=10)


def import_feedback(db, data):
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('items'), list) or len(data['items']) > 1000:
        raise ValueError('フィードバック形式または上限が不正')
    known = {json.loads(r[0])['analysis_id'] for r in db.execute('SELECT payload FROM sources')}
    batch = []
    for f in data['items']:
        if not isinstance(f, dict) or f.get('action') not in ACTIONS or f.get('analysis_id') not in known:
            raise ValueError('不明な評価・分析ID')
        d = datetime.fromisoformat(f['at'].replace('Z', '+00:00'))
        if not d.tzinfo or d > datetime.fromisoformat(now()) + timedelta(days=1):
            raise ValueError('フィードバック日時が不正')
        safe = {k: f[k] for k in ('at', 'action', 'analysis_id')}
        fid = hashlib.sha256(json.dumps(safe, sort_keys=True).encode()).hexdigest()
        batch.append((fid, safe['at'], json.dumps(safe, ensure_ascii=False)))
    with db:
        db.executemany('INSERT OR IGNORE INTO feedback VALUES (?,?,?)', batch)
    return len(batch)


def proposals(db):
    active = [json.loads(r['payload']) for r in db.execute('SELECT payload FROM problems WHERE active=1')]
    drafts = []
    templates = {
        'bias': ('独立した日本語情報源の拡充', '利用許諾の確認済みRSSを小規模追加', '3–6時間', '異なる発行元3以上', 24, 18, 14),
        'fetch': ('障害元の形式・接続の修復', 'ログと提供元仕様を確認してパーサーを修正', '2–4時間', '収集成功率95%以上', 25, 23, 16),
        'dates': ('日付パーサーの互換性改善', '形式サンプルを短いテストデータに変換し修正', '1–3時間', '不正日付0件', 22, 20, 18),
        'links': ('URL検証予算と元ページ確認の改善', '予算不足と削除を分離して検証対象を巡回', '3–5時間', 'URL有効率90%以上', 25, 22, 14),
        'evidence': ('根拠不足候補の独立資料調査', '候補ごとに追加の公開一次資料を調査', '3–6時間', '根拠充足率80%以上', 24, 18, 12),
        'feedback': ('不正確判定のレビューと分類改善', '取り込んだ候補別評価を確認し分類規則を検証', '2–5時間', '正解付き評価集合で分類精度を測定', 28, 20, 14),
    }
    for p in active:
        if p['code'] not in templates:
            continue
        name, method, hours, metric, value, severity, ease = templates[p['code']]
        drafts.append(dict(key='rule-' + p['code'], name=name, problem=p['summary'], reason=p['cause'], use_case='次回以降の定期調査', expected='根拠の網羅性・正確性を改善する可能性', method=method, difficulty='中', effort=hours, operating_cost='0円を前提。無料枠内の小規模実行', risk='提供元変更・データ量変動により効果が変わる', metric=metric, basis=dict(value=value, severity=severity, ease=ease, cost=15, evidence=8), evidence=['quality.json', 'events.jsonl', p['key']], inference='ルールベース・効果未確定'))
    # Gaps are proposals, never claims that an unavailable source was collected.
    kinds = {json.loads(r[0])['kind'] for r in db.execute('SELECT payload FROM sources')}
    if not kinds.intersection({'SNS', '口コミ', '掲示板'}):
        drafts.append(dict(key='consumer-evidence', name='利用者の公開不満・レビューの許諾確認', problem='生活者の直接意見が未収集', reason='保存済み情報源の種類を集計した結果', use_case='日本の消費者課題と支払い意思の探索', expected='開発者向け情報への偏りを減らす可能性', method='許諾済み無料APIの調査、または確認済み手動入力を増やす', difficulty='中', effort='4–8時間', operating_cost='無料取得条件が確認できる範囲のみ', risk='無料APIがない場合は自動化できない', metric='検証済み独立利用者投稿数・分類の人手正解率', basis=dict(value=28, severity=20, ease=10, cost=15, evidence=9), evidence=['report.json'], inference='ルールベース・効果未確定'))
    with db:
        for p in drafts:
            p['score'] = sum(p['basis'].values())
            p['score_reasons'] = dict(value='調査目的への近さで配点', severity='検出した品質問題の影響で配点', ease='既存機能との差分工数で配点', cost='有料サービスを使わない前提', evidence='保存済み実行ログの有無で配点')
            p['weights'] = WEIGHTS
            db.execute('INSERT INTO proposals(key,payload,status) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload', (p['key'], json.dumps(p, ensure_ascii=False), '提案'))
    all_rows = [dict(**json.loads(r['payload']), status=r['status'], github_url=r['github_url']) for r in db.execute('SELECT * FROM proposals')]
    for p in all_rows:
        if not p['github_url']:
            for key in p.get('evidence', []):
                issue = db.execute('SELECT github_url FROM problems WHERE key=?', (key,)).fetchone()
                if issue and issue[0]:
                    p['github_url'] = issue[0]
                    break
    active_keys = {p['key'] for p in drafts}
    return sorted((p for p in all_rows if p['key'] in active_keys and p['status'] != '実装済み'), key=lambda p: (-p['score'], p['key']))[:5]


def register(db, change):
    if not isinstance(change, dict) or not all(change.get(k) for k in ('key', 'name', 'implemented_at')):
        raise ValueError('改善のkey/name/implemented_atが必要')
    if len(change['key']) > 100 or len(change['name']) > 200:
        raise ValueError('改善情報が長すぎます')
    at = datetime.fromisoformat(change['implemented_at'])
    if not at.tzinfo or at > datetime.fromisoformat(now()):
        raise ValueError('実装日時は過去のタイムゾーン付き日時')
    for k in ('issue_url', 'pr_url'):
        if change.get(k):
            from .core import canonical
            change[k] = canonical(change[k])
    old = db.execute('SELECT payload FROM improvements WHERE key=?', (change['key'],)).fetchone()
    if old:
        original = json.loads(old[0])
        original.update({k: change[k] for k in ('issue_url', 'pr_url') if change.get(k)})
        with db:
            db.execute('UPDATE improvements SET payload=? WHERE key=?', (json.dumps(original, ensure_ascii=False), change['key']))
        return  # Preserve original implementation time and baseline when adding review links.
    baseline = [m for m in recent(db) if datetime.fromisoformat(m['at']) < at and datetime.fromisoformat(m['at']) >= at - timedelta(days=7)]
    record = dict(**change, baseline=baseline, implementation_status='実装済み・効果未検証')
    with db:
        db.execute('INSERT INTO improvements VALUES (?,?,?)', (change['key'], change['implemented_at'], json.dumps(record, ensure_ascii=False)))
        db.execute('UPDATE proposals SET status=? WHERE key=?', ('実装済み', change['key']))


def evaluate(db, at=None):
    at = datetime.fromisoformat(at or now())
    history = recent(db, 1000)
    output = []
    for row in db.execute('SELECT * FROM improvements'):
        c = json.loads(row['payload'])
        start = datetime.fromisoformat(row['at'])
        for horizon in (7, 30):
            due = start + timedelta(days=horizon)
            after = [m for m in history if start < datetime.fromisoformat(m['at']) <= due]
            baseline = c['baseline']
            reason, verdict, comparison = '評価期間またはサンプルが不足', '評価保留', {}
            configs = {(m['config_signature'], m.get('metric_version', 1)) for m in baseline + after}
            if at >= due and len(baseline) >= 3 and len(after) >= 3 and len(configs) == 1 and max(datetime.fromisoformat(m['at']) for m in after) >= due - timedelta(days=1):
                scores = []
                for key in ('success_rate', 'freshness_rate', 'duplicate_rate', 'url_valid_rate', 'evidence_coverage', 'duration_seconds', 'classification_accuracy', 'actions_duration_seconds', 'negative_feedback', 'failed_runs'):
                    b = [m[key] for m in baseline if m.get(key) is not None]
                    a = [m[key] for m in after if m.get(key) is not None]
                    if b and a:
                        before, current = sum(b) / len(b), sum(a) / len(a)
                        comparison[key] = dict(before=before, after=current, delta=current-before)
                        if key in ('success_rate', 'freshness_rate', 'url_valid_rate', 'evidence_coverage'):
                            scores.append(current-before)
                if scores:
                    verdict = 'ロールバック検討' if min(scores) < -.1 else '継続候補' if max(scores) > .05 else '再改善候補'
                    reason = '同一取得設定の観測比較。ニュース量・提供元変動を含み因果効果は未確定'
            elif len(configs) > 1:
                reason = '取得設定または指標定義が異なり比較できない（外部要因・情報源増減）'
            result = dict(key=c['key'], name=c['name'], horizon=horizon, due=due.isoformat(), verdict=verdict, reason=reason, comparison=comparison, baseline_samples=len(baseline), after_samples=len(after), issue_url=c.get('issue_url'), pr_url=c.get('pr_url'), classification_accuracy='正解ラベルがないため未測定', user_feedback='取り込んだ評価のみ反映')
            with db:
                db.execute('INSERT OR REPLACE INTO evaluations VALUES (?,?,?,?)', (c['key'], horizon, at.isoformat(), json.dumps(result, ensure_ascii=False)))
            output.append(result)
    return output
