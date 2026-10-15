"""Explicitly enabled Issue synchronization; never executes Issue contents."""
import hashlib
import json
import os
import re
import time
from urllib.request import Request, urlopen

from .core import now


class GitHub:
    def __init__(self, repository, token):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) or not token:
            raise ValueError('GitHub repository/token are required')
        self.repository, self.token = repository, token
        self.calls = 0

    def call(self, method, path, payload=None):
        if not path.startswith(f'/repos/{self.repository}/') or self.calls >= 30:
            raise ValueError('GitHub scope/request budget exceeded')
        self.calls += 1
        time.sleep(1)
        req = Request('https://api.github.com' + path, data=json.dumps(payload).encode() if payload is not None else None, headers={'Authorization': 'Bearer ' + self.token, 'User-Agent': 'TrendRadar/0.2', 'Accept': 'application/vnd.github+json'}, method=method)
        # No retry for writes: an ambiguous timeout is reconciled by marker next run.
        with urlopen(req, timeout=20) as response:
            return json.load(response)

    def issues(self):
        result = []
        for page in range(1, 11):
            batch = self.call('GET', f'/repos/{self.repository}/issues?state=all&per_page=100&page={page}')
            result.extend(batch)
            if len(batch) < 100:
                return result
        raise RuntimeError('Issue検索上限。重複防止のため作成を停止')


def sync(db, api, weekly_proposals=()):
    existing = api.issues()
    tasks = []
    for row in db.execute("SELECT * FROM problems WHERE active=1 ORDER BY COALESCE(synced_at,''),key"):
        p = json.loads(row['payload'])
        tasks.append((p['key'], p['summary'], dict(**p, first_seen=row['first_seen'], last_seen=row['last_seen'], occurrences=row['occurrences'], related_previous_issue=row['github_url']), True))
    for p in weekly_proposals:
        if any(key in p.get('evidence', []) for key, _, _, _ in tasks):
            continue  # Keep a proposal linked to its existing problem rather than opening a duplicate.
        tasks.append(('proposal:' + p['key'], p['name'], {k: v for k, v in p.items() if k != 'github_url'}, False))
    synced = []
    for key, title, content, problem in tasks[:5]:
        marker = '<!-- trend-radar:' + hashlib.sha256(key.encode()).hexdigest() + ' -->'
        match = next((i for i in existing if marker in (i.get('body') or '') and not i.get('pull_request')), None)
        # Only generated diagnostics and validated values; raw exceptions/secrets excluded.
        body = marker + '\nTrend Radar 自動保守タスク。分類・原因は推定、コード変更は未実施。\n\n```json\n' + json.dumps(content, ensure_ascii=False, indent=2) + '\n```\n\n影響範囲: Trend Radar。ログ: Actionsの同実行Artifact内 quality.json / events.jsonl。'
        if match:
            payload = dict(body=body)
            if match['state'] == 'closed':
                payload['state'] = 'open'
            if match.get('body') != body or match['state'] == 'closed':
                match = api.call('PATCH', f'/repos/{api.repository}/issues/{match["number"]}', payload)
        else:
            match = api.call('POST', f'/repos/{api.repository}/issues', dict(title=('[Trend Radar] ' + title)[:200], body=body))
            existing.append(match)
        url = match['html_url']
        if not url.startswith(f'https://github.com/{api.repository}/issues/'):
            raise ValueError('Unexpected GitHub issue URL')
        if problem:
            with db:
                db.execute('UPDATE problems SET github_url=?,synced_at=? WHERE key=?', (url, now(), key))
        else:
            with db:
                db.execute('UPDATE proposals SET github_url=? WHERE key=?', (url, key.removeprefix('proposal:')))
        synced.append(url)
    return synced


def from_environment():
    return GitHub(os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_TOKEN'])
