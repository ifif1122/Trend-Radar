import hashlib
import json
import os
import time
from collections import Counter
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from .core import now, ranking, sources


def recent(db, limit=100):
    return [dict(at=r['at'], **json.loads(r['payload'])) for r in db.execute('SELECT at,payload FROM quality ORDER BY id DESC LIMIT ?', (limit,))]


def metrics(db, events, elapsed, rejected=0, invalid_dates=0, config=None):
    rows = sources(db)
    verified = [s for s in rows if s['verification']['status'] == '確認済み']
    cutoff = datetime.fromisoformat(now()) - timedelta(days=7)
    dates, bad = [], invalid_dates
    for s in rows:
        try:
            d = datetime.fromisoformat((s.get('published_at') or '').replace('Z', '+00:00'))
            if d.tzinfo is None or d > datetime.fromisoformat(now()) + timedelta(days=1):
                raise ValueError('invalid date')
            dates.append(d)
        except (ValueError, TypeError):
            bad += 1
    safe_div = lambda a, b: round(a / b, 4) if b else None
    ranks = ranking(rows)
    media = Counter(s['media'] for s in rows)
    domains = Counter(urlsplit(s['url']).hostname for s in rows)
    groups = len({s['group_id'] for s in rows})
    feedback = [json.loads(r[0]) for r in db.execute('SELECT payload FROM feedback')]
    config = config or {}
    result = dict(collected=sum(e.get('count', 0) for e in events if e['success']), source_count=len(rows), success_rate=safe_div(sum(e['success'] for e in events), len(events)), url_valid_rate=safe_div(len(verified), len(rows)), freshness_rate=safe_div(sum(d >= cutoff for d in dates), len(rows)), duplicate_rate=safe_div(len(rows) - groups, len(rows)), evidence_coverage=safe_div(sum(a['score'] >= 2 for a in ranks), len(ranks)), insufficient_candidates=sum(a['score'] < 2 for a in ranks), invalid_dates=bad, rejected=rejected, duration_seconds=round(elapsed, 3), source_errors=dict(Counter(e['source'] for e in events if not e['success'])), source_bias=safe_div(max(media.values(), default=0), len(rows)), classification_accuracy=None, actions_duration_seconds=None, feedback_count=len(feedback), negative_feedback=sum(f['action'] in ('役立たなかった', '情報が不正確') for f in feedback), config_signature=hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16])
    result['collected'] = sum(e.get('selected_count', e.get('count', 0)) for e in events if e['success'])
    total = result['collected']
    duplicates = sum(e.get('selected_count', e.get('count', 0)) - e.get('selected_unique_count', e.get('selected_count', e.get('count', 0))) for e in events if e['success'])
    result['input_duplicate_rate'] = safe_div(duplicates, total)
    result['metric_version'] = 2
    result['source_bias'] = safe_div(max(domains.values(), default=0), len(rows))
    result['failed_runs'] = sum(bool(json.loads(r[0]).get('failed')) for r in db.execute('SELECT payload FROM runs'))
    action_start = os.environ.get('TREND_ACTIONS_STARTED_AT', '')
    if action_start.isdigit() and 0 <= time.time() - int(action_start) < 3600:
        result['actions_duration_seconds'] = round(time.time() - int(action_start), 3)
    return result


def detect(m, previous, events, failure=None):
    problems = []
    def add(code, severity, message, cause, action, scope='system'):
        problems.append(dict(key=f'{code}:{scope}', code=code, severity=severity, summary=message, cause=cause, suggestion=action, scope=scope, reproduction='同一設定で python -m trend_radar --mode live を実行', log='run.json / events.jsonl / quality.json', priority={'critical': 1, 'high': 2, 'medium': 3, 'low': 4}[severity]))
    for event in events:
        if not event['success']:
            add('fetch', 'high', '情報源の取得失敗・一時停止', event.get('error', '通信失敗'), '次回再取得。連続失敗は設定と提供元の形式を確認', event['source'])
    rules = [
        (m['duplicate_rate'] is not None and m['duplicate_rate'] > .4, 'duplicates', 'medium', '同一・類似ソースが40%超', '転載・再配信の増加', '元URLと類似群をレビュー'),
        (m.get('input_duplicate_rate') is not None and m['input_duplicate_rate'] > .4, 'input-duplicates', 'medium', '入力の同一URL重複が40%超', '同じ配信項目の大量重複', '配信元ごとのURL正規化と取得範囲を確認'),
        (m['source_bias'] is not None and m['source_bias'] > .7, 'bias', 'medium', '情報源の70%超が単一メディア', '取得範囲の偏り', '許諾済み日本語一次ソースを追加'),
        (m['freshness_rate'] is not None and m['freshness_rate'] < .5, 'stale', 'medium', '7日以内の情報が50%未満', '更新の停滞・歴史データの増加', '新着の収集範囲と日付を確認'),
        (m['url_valid_rate'] is not None and m['url_valid_rate'] < .9, 'links', 'high', 'URL有効率が90%未満', 'リンク切れ・アクセス制限・通信予算', '無効な根拠を除外し次回再確認'),
        (m['invalid_dates'] > 0, 'dates', 'high', '不正・不明な日付を検出', 'データ形式変更または欠損', '解析形式を確認。不明値を補完しない'),
        (m['insufficient_candidates'] > 0, 'evidence', 'medium', '独立根拠2群未満の候補あり', '根拠不足', '追加の独立ソースを収集'),
        (m['duration_seconds'] > 600, 'duration', 'medium', '処理時間が10分超', '応答遅延・取得対象の増加', '通信上限・差分取得を確認'),
        (m.get('negative_feedback', 0) > 0, 'feedback', 'medium', '不正確・役立たないという評価あり', '分類と利用目的の不一致', '対象候補と分類を人手レビュー'),
    ]
    for condition, *args in rules:
        if condition:
            add(*args)
    if previous and previous['config_signature'] == m['config_signature'] and previous.get('metric_version', 1) == m.get('metric_version', 1):
        if previous['collected'] >= 5 and m['collected'] < previous['collected'] * .5:
            add('drop', 'high', '取得件数が前回の半分未満', '障害・ニュース量の変化', '情報源ごとの取得ログを比較')
        for key in ('success_rate', 'url_valid_rate', 'freshness_rate'):
            if m[key] is not None and previous[key] is not None and m[key] < previous[key] - .2:
                add('regression', 'high', f'{key}が20ポイント超悪化', '外部要因または実装退行', '前回ログと同一設定で比較', key)
    if failure:
        add('pipeline', 'critical', '収集またはHTML生成失敗', failure, '履歴を保持して次回再実行。コード変更はPR経由')
    return problems


def store_problems(db, found, at=None, complete=True):
    at = at or now()
    keys = {p['key'] for p in found}
    with db:
        for row in db.execute('SELECT key,payload FROM problems WHERE active=1').fetchall():
            if complete and row['key'] not in keys:
                db.execute('UPDATE problems SET active=0 WHERE key=?', (row['key'],))
                db.execute('INSERT INTO problem_events(key,at,payload) VALUES (?,?,?)', (row['key'], at, json.dumps(dict(state='resolved'), ensure_ascii=False)))
        for p in found:
            previous = db.execute('SELECT active FROM problems WHERE key=?', (p['key'],)).fetchone()
            db.execute('INSERT INTO problems(key,first_seen,last_seen,occurrences,active,payload) VALUES (?,?,?,1,1,?) ON CONFLICT(key) DO UPDATE SET last_seen=excluded.last_seen,occurrences=occurrences+1,active=1,payload=excluded.payload', (p['key'], at, at, json.dumps(p, ensure_ascii=False)))
            db.execute('INSERT INTO problem_events(key,at,payload) VALUES (?,?,?)', (p['key'], at, json.dumps(dict(state='recurrence' if previous and not previous['active'] else 'observed', **p), ensure_ascii=False)))


def snapshot(db, m, events, failure=None):
    previous = recent(db, 1)
    found = detect(m, previous[0] if previous else None, events, failure)
    with db:
        db.execute('INSERT INTO quality(at,payload) VALUES (?,?)', (now(), json.dumps(m, ensure_ascii=False)))
    store_problems(db, found)
    return found
