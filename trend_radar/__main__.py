import argparse
import json
import time
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path

from .core import Client, collect, connect, now, record_check, save, sources
from .github_sync import from_environment, sync
from .improvement import evaluate, import_feedback, proposals, register
from .providers import collect_feeds
from .quality import metrics, recent, snapshot, store_problems
from .report import render
from .storage import atomic_text, backup, locked, migrate, write_json


def read_json(path):
    path = Path(path)
    if path.stat().st_size > 2_000_000:
        raise ValueError('入力ファイル上限2MB')
    return json.loads(path.read_text(encoding='utf-8'))


def collect_run(db, args, config):
    client = Client(config['request_interval_seconds'], config['max_requests'], db)
    incoming, errors = collect(client, config)
    feeds, feed_errors = collect_feeds(client, config)
    incoming.extend(feeds)
    errors.extend(feed_errors)
    if args.import_file:
        imported = read_json(args.import_file)
        if not isinstance(imported, list) or len(imported) > 100:
            raise ValueError('入力は100件以下のメタデータ配列')
        for item in imported:
            if item.get('rights_confirmed') is not True or not item.get('origin'):
                raise ValueError('利用条件確認 rights_confirmed と origin が必要')
            item.update(fetched_at=now(), content_verified=False)
        incoming.extend(imported)
    accepted, rejected, invalid = set(), 0, 0
    seen = set()
    for source in incoming:
        try:
            check = client.verify(source['url'])
            sid = save(db, source, check)
            if sid:
                if check['status'] == '確認済み':
                    accepted.add(sid)
                seen.add(sid)
            if check['status'] != '確認済み':
                rejected += 1
                errors.append('元ページ検証不採用: ' + check['status'])
        except (KeyError, ValueError, TypeError):
            invalid += 1
            rejected += 1
            errors.append('メタデータ・日付・URL形式不正：対象レコードのみ除外')
    old = sorted((s for s in sources(db) if s['id'] not in seen), key=lambda s: s['verification']['checked_at'])
    for s in old:
        if client.count >= client.max_requests:
            break
        with db:
            record_check(db, s['id'], client.verify(s['url']))
    return client, len(accepted), rejected, invalid, errors


def execute(args, db):
    started = time.monotonic()
    errors, accepted, rejected, invalid = [], 0, 0, 0
    client = None
    try:
        config = read_json(args.config)
        if args.feedback_file:
            import_feedback(db, read_json(args.feedback_file))
        if args.register_improvement:
            register(db, read_json(args.register_improvement))
        if args.mode == 'live':
            for file in sorted(Path('changes').glob('*.json')):
                change = read_json(file)
                change['source_authored_at'] = change.get('implemented_at')
                change['implemented_at'] = now()  # First observation of this reviewed code in this environment.
                register(db, change)
            client, accepted, rejected, invalid, errors = collect_run(db, args, config)
            m = metrics(db, client.collection_events, time.monotonic()-started, rejected, invalid, config)
            if client.collection_events and not any(e['success'] for e in client.collection_events):
                m['failed_runs'] += 1
            snapshot(db, m, client.collection_events)
        elif args.import_file:
            raise ValueError('根拠取り込みはliveでURL検証が必要')
        choices = proposals(db)
        evaluation = evaluate(db)
        if args.sync_issues:
            sync(db, from_environment(), choices if args.weekly else ())
        payload = render(db, args.output, args.mode, errors)
        rows = payload['sources']
        summary = dict(at=now(), mode=args.mode, accepted=accepted, rejected=rejected, saved=len(rows), verified=sum(s['verification']['status'] == '確認済み' for s in rows), by_kind=dict(Counter(s['kind'] for s in rows)), by_category=dict(Counter(c for s in rows for c in s['categories'])), errors=errors, duration_seconds=round(time.monotonic()-started, 3), events=client.collection_events if client else [], proposals=len(choices))
        summary['failed'] = bool(args.mode == 'live' and (not summary['verified'] or (client.collection_events and not any(e['success'] for e in client.collection_events))))
        if args.mode == 'live':
            with db:
                db.execute('INSERT INTO report_snapshots(at,payload) VALUES (?,?)', (summary['at'], json.dumps(dict(ranking=payload['ranking'], summary=summary), ensure_ascii=False)))
        with db:
            db.execute('INSERT INTO runs(at,payload) VALUES (?,?)', (summary['at'], json.dumps(summary, ensure_ascii=False)))
        write_json(Path(args.output) / 'run.json', summary)
        write_json(Path(args.output) / f'run-{args.mode}.json', summary)
        write_json(Path(args.output) / 'quality.json', recent(db))
        write_json(Path(args.output) / 'proposals.json', choices)
        write_json(Path(args.output) / 'evaluations.json', evaluation)
        if client:
            atomic_text(Path(args.output) / 'events.jsonl', '\n'.join(json.dumps(e, ensure_ascii=False) for e in client.collection_events + client.network_events))
        if args.weekly:
            week = datetime.fromisoformat(now()).strftime('%G-W%V')
            weekly = dict(week=week, generated_at=now(), quality=[m for m in recent(db, 100) if datetime.fromisoformat(m['at']).strftime('%G-W%V') == week], proposals=choices[:5], evaluation=evaluation, note='ルールベース。因果効果・購入需要の確定ではありません。')
            write_json(Path(args.output) / f'weekly-{week}.json', weekly)
            with db:
                db.execute('INSERT OR REPLACE INTO weekly_reports VALUES (?,?,?)', (week, now(), json.dumps(weekly, ensure_ascii=False)))
            from .dashboard import weekly_html
            atomic_text(Path(args.output) / 'weekly.html', weekly_html(weekly))
        print(json.dumps(summary, ensure_ascii=False))
        return 2 if summary['failed'] else 0
    except Exception as exc:
        failure = dict(at=now(), error=type(exc).__name__, frames=[dict(file=Path(f.filename).name, function=f.name, line=f.lineno) for f in traceback.extract_tb(exc.__traceback__)])
        write_json(Path(args.output) / 'failure.json', failure)
        with db:
            db.execute('INSERT INTO runs(at,payload) VALUES (?,?)', (failure['at'], json.dumps(dict(**failure, failed=True), ensure_ascii=False)))
        store_problems(db, [dict(key='pipeline:system', code='pipeline', severity='critical', summary='収集・検証・HTML生成の失敗', cause=type(exc).__name__, suggestion='failure.jsonの位置とテストを確認', scope='system', reproduction='同一設定でCLIを再実行', log='failure.json', priority=1)], complete=False)
        print(json.dumps(failure, ensure_ascii=False))
        return 1


def main():
    p = argparse.ArgumentParser(description='Trend Radar — no-AI scheduled research and maintenance')
    p.add_argument('--mode', choices=('live', 'sample', 'report'), default='report')
    p.add_argument('--config', default='config.json')
    p.add_argument('--state', default='state')
    p.add_argument('--output', default='reports')
    p.add_argument('--import-file')
    p.add_argument('--feedback-file')
    p.add_argument('--register-improvement')
    p.add_argument('--weekly', action='store_true')
    p.add_argument('--sync-issues', action='store_true', help='環境のGITHUB_TOKENでIssueを明示同期')
    args = p.parse_args()
    state = Path(args.state)
    state.mkdir(parents=True, exist_ok=True)
    with locked(state):
        db = connect(state / ('sample.sqlite' if args.mode == 'sample' else 'live.sqlite'))
        try:
            backup(db, state / ('sample-before-maintenance.sqlite' if args.mode == 'sample' else 'live-before-maintenance.sqlite'))
            migrate(db)
            result = execute(args, db)
        finally:
            db.close()
    raise SystemExit(result)


if __name__ == '__main__':
    main()
