import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from trend_radar.ai_analysis import analyze_ai, packet, run_codex, validate
from trend_radar.content import analyze_content, extract, features
from trend_radar.core import connect, save, sources
from trend_radar.providers import github_parser, metadata, parse_feed
from trend_radar.report import render
from trend_radar.storage import migrate

from test_evidence import check, source


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.db = connect(':memory:')
        migrate(self.db)

    def tearDown(self):
        self.db.close()

    def add(self, title='Model inference is slow', body='I would like a latency diagnostic tool.', **changes):
        s = source(title=title, **changes)
        s['content_features'] = extract(title, body, kind=s['kind'])
        save(self.db, s, check())
        return sources(self.db)

    def response(self, inputs):
        ref = inputs['sources'][0]['id']
        return dict(summary='公開報告から調査仮説を整理しました。', observations=[dict(text='処理の遅さを訴える報告があるという観測です。', source_ids=[ref])], opportunities=[dict(title='遅延の診断支援という仮説', user='モデル運用者', problem='待ち時間の要因が分かりにくい可能性', solution='処理区間の計測を支援する', validation='同じ環境で処理時間を比較し利用者に聞く', source_ids=[ref])], unknowns=['支払い意思・市場規模は未確認'])

    def test_body_features_are_saved_without_body_text(self):
        marker = 'PRIVATE_BODY_SENTENCE_NOT_FOR_STORAGE'
        body = json.dumps([dict(title='Model issue', html_url=source()['url'], body='Inference is slow. '+marker)])
        row = github_parser(body.encode())[0]
        self.assertIn('speed', row['content_features']['pains'])
        self.assertIn('performance', row['content_features']['topics'])
        self.assertNotIn(marker, json.dumps(row))
        self.assertNotIn('body', row)

    def test_negation_resolution_code_and_official_context(self):
        self.assertFalse(extract('Fixed: no crashes anymore')['pains'])
        self.assertFalse(extract('Status', '```\ncrash slow error\n```')['pains'])
        self.assertFalse(extract('Release', 'Fixed slow inference; I will pay.', kind='公式発表')['payment_expression'])
        self.assertTrue(extract('Support', 'I would pay for this feature.')['payment_expression'])
        self.assertFalse(extract('Support', 'I would not pay for this feature.')['payment_expression'])
        self.assertIn('failure', extract('起動できない', kind='口コミ')['pains'])

    def test_feed_does_not_treat_announcement_as_user_complaint(self):
        rss = b'<rss><channel><item><title>API integration announcement</title><link>https://github.com/a/b/issues/1</link><description>We need to fix slow API requests</description></item></channel></rss>'
        row = parse_feed(rss)[0]
        self.assertIn('integration', row['content_features']['topics'])
        self.assertFalse(row['content_features']['pains'])
        self.assertNotIn('We need', json.dumps(row))

    def test_old_cache_reacquires_features_without_history_deletion(self):
        c = Mock(db=self.db, response_headers={}, collection_events=[])
        self.db.execute('INSERT INTO endpoint_cache VALUES (?,?,?,?)', ('https://github.com/a/b', 'old', None, json.dumps([dict(title='old metadata')])) )
        c.get.return_value = (200, '', json.dumps([dict(title='slow inference', html_url=source()['url'], body='fails')]).encode())
        metadata(c, 'https://github.com/a/b', github_parser)
        self.assertTrue(c.get.called)
        self.assertEqual(c.conditional_headers, {})
        self.assertIn('content_features', self.db.execute('SELECT payload FROM endpoint_cache').fetchone()[0])

    def test_topic_group_dedup_and_unverified_sources_excluded(self):
        rows = self.add()
        duplicate = dict(rows[0], id='another', url='https://github.com/a/b/issues/2')
        invalid = dict(rows[0], id='invalid', group_id='new', verification=dict(status='確認不能'))
        result = analyze_content(rows+[duplicate, invalid])
        topic = next(t for t in result['topics'] if t['id'] == 'performance')
        self.assertEqual(topic['independent_groups'], 1)
        self.assertEqual(topic['complaint_groups'], 1)
        self.assertEqual(result['counts']['verified_sources'], 2)
        self.assertTrue(all(t['score'] <= 100 for t in result['topics']))

    def test_title_fallback_and_invalid_features_are_not_mislabelled(self):
        s = source(title='Slow inference', content_features=dict(version='content-v1', pains=['invented']))
        self.assertEqual(features(s)['scope'], 'title_only')
        save(self.db, source(title='Slow inference'), check())
        result = analyze_content(sources(self.db))
        self.assertEqual(result['counts']['title_only_sources'], 1)
        self.assertEqual(result['counts']['content_sources'], 0)

    def test_ai_cache_quota_and_citations(self):
        rows = self.add()
        runner = Mock(side_effect=lambda data: (self.response(data), dict(input_tokens=100, output_tokens=50)))
        first = analyze_ai(self.db, rows, runner)
        self.assertEqual(first['status'], 'completed')
        self.assertEqual(analyze_ai(self.db, rows, runner)['status'], 'cached')
        changed = [dict(rows[0], title='Changed title')]
        self.assertEqual(analyze_ai(self.db, changed, runner)['status'], 'limited')
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(len(first['report']['evidence']), 1)

    def test_bad_output_consumes_attempt_and_preserves_last_good_report(self):
        rows = self.add()
        bad = self.response(packet(rows))
        bad['observations'][0]['source_ids'] = ['invented-source']
        self.assertEqual(analyze_ai(self.db, rows, lambda _: (bad, None))['status'], 'failed')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM ai_reports').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT status FROM ai_attempts').fetchone()[0], 'failed')
        self.assertEqual(analyze_ai(self.db, rows, Mock())['status'], 'limited')

    def test_ai_generated_url_and_extra_fields_rejected(self):
        inputs = packet(self.add())
        bad = self.response(inputs)
        bad['summary'] = 'See https://example.com/generated'
        with self.assertRaises(ValueError):
            validate(bad, inputs)
        bad = self.response(inputs) | dict(command='run something')
        with self.assertRaises(ValueError):
            validate(bad, inputs)

    def test_api_key_auth_does_not_start_inference(self):
        status = Mock(returncode=0, stdout='Logged in using API key', stderr='')
        with patch('trend_radar.ai_analysis.subprocess.run', return_value=status) as execute:
            with self.assertRaises(RuntimeError):
                run_codex(packet(self.add()), executable='codex')
        self.assertEqual(execute.call_count, 1)

    def test_saved_manual_review_remains_linked_after_regeneration(self):
        self.add()
        with tempfile.TemporaryDirectory() as temp:
            render(self.db, temp, 'report')
            self.assertNotIn('href="market_analysis.html"', (Path(temp)/'analysis.html').read_text(encoding='utf-8'))
            review = Path(temp)/'market_analysis.html'
            review.write_text('saved review', encoding='utf-8')
            render(self.db, temp, 'report')
            self.assertEqual(review.read_text(encoding='utf-8'), 'saved review')
            for name in ('report.html', 'analysis.html'):
                self.assertIn('href="market_analysis.html"', (Path(temp)/name).read_text(encoding='utf-8'))

    def test_analysis_html_and_ai_escape_titles_and_output(self):
        rows = self.add(title='<img src=x onerror=alert(1)> slow API')
        response = self.response(packet(rows))
        response['summary'] = '<script>alert(1)</script>'
        analyze_ai(self.db, rows, lambda _: (response, None))
        with tempfile.TemporaryDirectory() as temp:
            payload = render(self.db, temp, 'report')
            self.assertTrue(payload['content_analysis']['topics'])
            self.assertIsNotNone(payload['ai_analysis'])
            for name in ('report.html', 'analysis.html'):
                page = (Path(temp)/name).read_text(encoding='utf-8')
                self.assertNotIn('<img src=x', page)
                self.assertNotIn('<script>alert(1)', page)
            self.assertTrue((Path(temp)/'analysis_brief.md').exists())


if __name__ == '__main__':
    unittest.main()
