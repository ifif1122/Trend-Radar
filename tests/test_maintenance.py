import argparse
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from trend_radar.__main__ import execute
from trend_radar.core import Client, collect, connect, now, save, sources
from trend_radar.github_sync import sync
from trend_radar.improvement import evaluate, import_feedback, proposals, register
from trend_radar.providers import metadata, parse_feed
from trend_radar.quality import metrics, snapshot, store_problems
from trend_radar.report import render
from trend_radar.storage import locked, migrate

from test_evidence import check, source


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.db = connect(':memory:')
        migrate(self.db)

    def tearDown(self):
        self.db.close()

    def metric(self, **extra):
        result = metrics(self.db, [dict(source='official-api', success=True, count=10)], 1, config={})
        result.update(extra)
        return result

    def test_retry_has_finite_attempts(self):
        c = Client()
        with patch.object(c, '_get', side_effect=URLError('transient')) as request, patch('trend_radar.core.time.sleep'):
            with self.assertRaises(URLError):
                c.get('https://github.com/a/b')
        self.assertEqual(request.call_count, 3)

    def test_long_rate_limit_not_retried(self):
        c = Client()
        error = HTTPError('https://github.com/a/b', 429, 'limited', {'Retry-After': '300'}, None)
        with patch.object(c, '_get', side_effect=error) as request:
            with self.assertRaises(HTTPError):
                c.get(error.url)
        self.assertEqual(request.call_count, 1)

    def test_304_uses_sanitized_metadata_and_resets_cooldown(self):
        c = Client(db=self.db)
        c.response_headers = {'ETag': 'version1'}
        with patch.object(c, 'get', return_value=(200, '', b'not-saved-post-body')):
            metadata(c, 'https://github.com/a/b', lambda body: [dict(title='metadata only')])
        cache = self.db.execute('SELECT payload FROM endpoint_cache').fetchone()[0]
        self.assertNotIn('not-saved-post-body', cache)
        err = HTTPError('https://github.com/a/b', 304, 'unchanged', {}, None)
        with patch.object(c, 'get', side_effect=err):
            rows = metadata(c, err.url, lambda body: self.fail('parser called for 304'))
        self.assertEqual(rows[0]['title'], 'metadata only')
        self.assertTrue(c.collection_events[-1]['cached'])

    def test_corrupt_cache_regenerates_without_deleting_sources(self):
        save(self.db, source(), check())
        self.db.execute('INSERT INTO endpoint_cache VALUES (?,?,?,?)', ('https://github.com/a/b', 'old', None, 'broken-json'))
        c = Client(db=self.db)
        with patch.object(c, 'get', return_value=(200, '', b'fresh')):
            metadata(c, 'https://github.com/a/b', lambda b: [])
        self.assertEqual(len(sources(self.db)), 1)
        self.assertEqual(self.db.execute('SELECT payload FROM endpoint_cache').fetchone()[0], '[]')

    def test_source_failure_does_not_stop_other_sources(self):
        c = Client(db=self.db)
        item = dict(title='Real issue metadata', html_url=source()['url'], created_at=source()['published_at'])
        with patch.object(c, 'get', side_effect=[URLError('outage'), (200, '', json.dumps([item]).encode())]):
            data, errors = collect(c, dict(repositories=['a/b', 'c/d'], issues_per_repository=1, releases_per_repository=0))
        self.assertEqual(len(data), 1)
        self.assertEqual(len(errors), 1)
        self.assertEqual([e['success'] for e in c.collection_events], [False, True])

    def test_rss_extracts_no_body_and_blocks_xml_entities(self):
        rss = b'<rss><channel><item><title>A title</title><link>https://github.com/a/b/issues/1</link><pubDate>Thu, 15 Oct 2026 00:00:00 GMT</pubDate><description>Do not save full text</description></item></channel></rss>'
        data = parse_feed(rss)
        self.assertNotIn('Do not save full text', json.dumps(data))
        with self.assertRaises(ValueError):
            parse_feed(b'<!DOCTYPE foo [<!ENTITY x "y">]><rss/>')

    def test_problem_dedup_recurrence_and_partial_failure(self):
        problem = dict(key='fetch:x', code='fetch', summary='failure', severity='high', cause='unknown', suggestion='retry')
        store_problems(self.db, [problem])
        store_problems(self.db, [problem])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM problems').fetchone()[0], 1)
        store_problems(self.db, [], complete=False)
        self.assertEqual(self.db.execute('SELECT active FROM problems').fetchone()[0], 1)
        store_problems(self.db, [])
        store_problems(self.db, [problem])
        self.assertIn('recurrence', self.db.execute('SELECT payload FROM problem_events ORDER BY id DESC').fetchone()[0])

    def test_quality_alerts_and_proposal_bounds(self):
        m = self.metric(duplicate_rate=.8, source_bias=.9, invalid_dates=2, freshness_rate=.1, url_valid_rate=.2, insufficient_candidates=3)
        found = snapshot(self.db, m, [])
        self.assertGreaterEqual(len(found), 5)
        ps = proposals(self.db)
        self.assertLessEqual(len(ps), 5)
        self.assertTrue(all(p['score'] <= 100 and sum(p['basis'].values()) == p['score'] for p in ps))
        self.db.execute("UPDATE proposals SET status='実装済み'")
        self.assertEqual(proposals(self.db), [])

    def test_feedback_validated_deduplicated_and_reflected(self):
        save(self.db, source(), check())
        data = dict(version=1, items=[dict(at=now(), analysis_id='editor', action='情報が不正確')])
        import_feedback(self.db, data)
        import_feedback(self.db, data)
        self.assertEqual(self.metric()['negative_feedback'], 1)
        with self.assertRaises(ValueError):
            import_feedback(self.db, dict(version=1, items=[dict(at=now(), analysis_id='unknown', action='役立った')]))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0], 1)
        with tempfile.TemporaryDirectory() as temp:
            payload = render(self.db, temp, 'report')
            self.assertEqual(payload['research'][0]['feedback']['情報が不正確'], 1)
            page = (Path(temp) / 'report.html').read_text(encoding='utf-8')
            self.assertIn('export-feedback', page)
            self.assertIn('システム品質', page)

    def test_effects_defer_then_compare_and_hold_config_changes(self):
        start = datetime.fromisoformat(now()) - timedelta(days=31)
        base = self.metric(success_rate=.8)
        for day in (3, 2, 1):
            self.db.execute('INSERT INTO quality(at,payload) VALUES (?,?)', ((start-timedelta(days=day)).isoformat(), json.dumps(base)))
        register(self.db, dict(key='change1', name='Bounded retry', implemented_at=start.isoformat()))
        self.assertTrue(all(x['verdict'] == '評価保留' for x in evaluate(self.db)))
        improved = dict(base, success_rate=.98)
        for day in (1, 3, 6, 7, 15, 29, 30):
            self.db.execute('INSERT INTO quality(at,payload) VALUES (?,?)', ((start+timedelta(days=day)).isoformat(), json.dumps(improved)))
        self.assertTrue(all(x['verdict'] == '継続候補' for x in evaluate(self.db)))
        changed = dict(improved, config_signature='other')
        self.db.execute('INSERT INTO quality(at,payload) VALUES (?,?)', ((start+timedelta(days=2)).isoformat(), json.dumps(changed)))
        self.assertTrue(all(x['verdict'] == '評価保留' for x in evaluate(self.db)))

    def test_issue_sync_idempotent_and_reopens_same_issue(self):
        p = dict(key='fetch:x', summary='failure', code='fetch', severity='high', cause='network', suggestion='retry')
        store_problems(self.db, [p])
        api = Mock(repository='owner/repo')
        api.issues.return_value = []
        api.call.return_value = dict(number=3, html_url='https://github.com/owner/repo/issues/3')
        sync(self.db, api, [dict(key='rule-fetch', name='same problem proposal', evidence=['fetch:x'])])
        self.assertEqual(api.call.call_count, 1)
        body = api.call.call_args.args[2]['body']
        api.issues.return_value = [dict(number=3, html_url='https://github.com/owner/repo/issues/3', state='closed', body=body)]
        sync(self.db, api)
        self.assertEqual(api.call.call_args.args[0], 'PATCH')
        self.assertEqual(api.call.call_args.args[2]['state'], 'open')

    def test_lock_prevents_overlap(self):
        with tempfile.TemporaryDirectory() as temp:
            with locked(temp):
                with self.assertRaises(RuntimeError):
                    with locked(temp):
                        self.fail('overlap')
            self.assertFalse((Path(temp) / 'run.lock').exists())

    def test_end_to_end_and_report_failure_logged(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / 'config.json'
            config.write_text(json.dumps(dict(repositories=[], issues_per_repository=0, releases_per_repository=0, request_interval_seconds=1, max_requests=5)), encoding='utf-8')
            args = argparse.Namespace(mode='live', config=str(config), output=str(Path(temp)/'reports'), import_file=None, feedback_file=None, register_improvement=None, sync_issues=False, weekly=True)
            with patch('trend_radar.__main__.collect_feeds', return_value=([source(), source()], [])), patch.object(Client, 'verify', return_value=check()):
                self.assertEqual(execute(args, self.db), 0)
            self.assertEqual(json.loads((Path(args.output)/'run.json').read_text(encoding='utf-8'))['accepted'], 1)
            self.assertEqual(self.db.execute('SELECT COUNT(*) FROM weekly_reports').fetchone()[0], 1)
            self.assertEqual(self.db.execute('SELECT COUNT(*) FROM quality').fetchone()[0], 1)
            self.assertTrue((Path(args.output)/'weekly.html').exists())
            args.mode = 'report'
            with patch('trend_radar.__main__.render', side_effect=OSError('secret-value-not-for-logs')):
                self.assertEqual(execute(args, self.db), 1)
            self.assertNotIn('secret-value', (Path(args.output)/'failure.json').read_text(encoding='utf-8'))
            self.assertEqual(len(sources(self.db)), 1)


if __name__ == '__main__':
    unittest.main()
