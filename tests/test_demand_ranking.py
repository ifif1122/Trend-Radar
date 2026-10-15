import json
import tempfile
import unittest
from pathlib import Path

from trend_radar.demand_ranking import build, fragment


class DemandRankingTests(unittest.TestCase):
    def test_review_matching_excludes_unverified_and_escapes_text(self):
        rows = [dict(id='ok', url='https://github.com/a/b/issues/1', title='<script>x</script>', verification=dict(status='確認済み')), dict(id='bad', url='https://github.com/a/b/issues/2', verification=dict(status='リンク切れ'))]
        item = dict(title='<img onerror=x>', priority='保留', features=['<b>feature</b>'], buyer='buyer', value='value', price='仮説100円', proof='未確認', risks='risk', validation='有料試行', alternatives='既存手段', sources=[rows[0]['url'], rows[0]['url'], rows[1]['url']])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'market_analysis.json'
            path.write_text(json.dumps(dict(date='2026-10-15', decisions=[item])), encoding='utf-8')
            result = build(rows, None, path)
            self.assertEqual(result['candidates'][0]['source_ids'], ['ok'])
            page = fragment(result, rows)
            self.assertNotIn('<img onerror', page)
            self.assertNotIn('<script>x', page)
            self.assertIn('href="#source-ok"', page)
            self.assertIn('rel="noopener noreferrer"', page)
            path.write_text('{invalid', encoding='utf-8')
            self.assertEqual(build(rows, None, path)['candidates'], [])

    def test_ai_fallback_requires_available_verified_citations(self):
        row = dict(id='ok', url='https://github.com/a/b/issues/1', title='issue', verification=dict(status='確認済み'))
        idea = dict(title='idea', solution='feature', user='user', problem='problem', validation='test', source_ids=['missing', 'ok'])
        ai = dict(at='2026-10-15', result=dict(opportunities=[idea]))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'missing.json'
            result = build([row], ai, path)
            self.assertEqual(result['candidates'][0]['source_ids'], ['ok'])
            self.assertIn('未評価', result['candidates'][0]['priority'])
            self.assertEqual(build([], ai, path)['candidates'], [])


if __name__ == '__main__':
    unittest.main()
