import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from trend_radar.core import Client, canonical, collect, connect, ranking, save, sources
from trend_radar.report import render


def source(**changes):
    s = dict(title='User reports editor accessibility issue', url='https://github.com/microsoft/vscode/issues/123', media='GitHub', published_at='2026-10-01T00:00:00Z', fetched_at='2026-10-15T00:00:00+00:00', summary='A short paraphrase, not the original post.', kind='GitHub Issues', categories=['実際の不満'], analysis_id='editor', analysis_title='Editor assistance', reason='User report, unverified', reliability='自己申告', content_verified=False)
    s.update(changes)
    return s


def check(status='確認済み'):
    return dict(status=status, checked_at='2026-10-15T00:00:00+00:00', http=200 if status == '確認済み' else 404, final_url=None)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.db = connect(':memory:')

    def tearDown(self):
        self.db.close()

    def test_canonical_and_invalid_urls(self):
        self.assertEqual(canonical(source()['url']+'/?utm_source=a#reply'), source()['url'])
        for url in ('javascript:alert(1)', 'https://example.com/story', 'https://github.com/search?q=test', 'https://github.com', 'http://github.com/a', 'https://user:pass@github.com/a', 'https://github.com/a/b?access_token=do-not-store'):
            with self.assertRaises(ValueError):
                canonical(url)

    def test_unverified_source_never_accepted(self):
        self.assertIsNone(save(self.db, source(), check('確認不能')))
        self.assertEqual(sources(self.db), [])

    def test_history_retained_but_broken_link_excluded(self):
        save(self.db, source(), check())
        save(self.db, source(summary='Updated paraphrase'), check('削除済み・リンク切れ'))
        rows = sources(self.db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['versions'], 2)
        self.assertEqual(ranking(rows)[0]['score'], 0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM checks').fetchone()[0], 2)

    def test_same_url_and_similar_articles_count_once(self):
        save(self.db, source(), check())
        save(self.db, source(url=source()['url']+'?utm_campaign=x'), check())
        self.assertEqual(len(sources(self.db)), 1)
        self.assertEqual(sources(self.db)[0]['versions'], 1)
        save(self.db, source(url='https://github.com/another/editor/issues/234', title=source()['title']+'!'), check())
        self.assertEqual(len(sources(self.db)), 2)
        self.assertEqual(ranking(sources(self.db))[0]['score'], 1)

    def test_html_escapes_untrusted_fields_and_links(self):
        save(self.db, source(title='<script>alert(1)</script>', summary='<img src=x onerror=alert(1)>', analysis_title='<svg onload=alert(1)>', media='" onmouseover="alert(1)'), check())
        with tempfile.TemporaryDirectory() as temp:
            render(self.db, temp, 'live')
            page = (Path(temp) / 'report.html').read_text(encoding='utf-8')
            self.assertNotIn('<script>alert(1)', page)
            self.assertNotIn('<img src=x', page)
            self.assertIn('&lt;script&gt;', page)
            self.assertIn('target="_blank" rel="noopener noreferrer"', page)
            self.assertNotIn('_PLACEHOLDER', page)
            self.assertEqual(len(json.loads((Path(temp) / 'report.json').read_text(encoding='utf-8'))['sources']), 1)

    def test_empty_sample_has_no_fake_links(self):
        with tempfile.TemporaryDirectory() as temp:
            data = render(self.db, temp, 'sample')
            self.assertEqual(data['sources'], [])
            self.assertNotIn('example.com', (Path(temp) / 'report.html').read_text(encoding='utf-8'))

    def test_verify_rejects_redirect_and_login(self):
        c = Client()
        with patch.object(c, 'get', return_value=(200, 'https://github.com/login', b'<html><title>Sign in</title>')):
            self.assertNotEqual(c.verify(source()['url'])['status'], '確認済み')
        with patch.object(c, 'get', return_value=(200, source()['url'], b'<html><title>Access denied</title>')):
            self.assertNotEqual(c.verify(source()['url'])['status'], '確認済み')

    def test_collector_ignores_pull_requests_and_does_not_infer_payment(self):
        items = [dict(pull_request={}, title='PR'), dict(title='Bug title', html_url=source()['url'], created_at='2026-10-01T00:00:00Z', labels=[dict(name='bug')])]
        # Real API pull_request value is a nonempty object.
        items[0]['pull_request'] = {'url': 'https://api.github.com/repos/a/b/pulls/1'}
        c = Client()
        with patch.object(c, 'get', return_value=(200, '', json.dumps(items).encode())):
            data, errors = collect(c, dict(repositories=['a/b'], issues_per_repository=2, releases_per_repository=0))
        self.assertFalse(errors)
        self.assertEqual(len(data), 1)
        self.assertIn('実際の不満', data[0]['categories'])
        self.assertNotIn('有料需要の証拠', data[0]['categories'])


if __name__ == '__main__':
    unittest.main()
