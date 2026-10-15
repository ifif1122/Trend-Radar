import hashlib
import ipaddress
import json
import re
import socket
import sqlite3
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

KINDS = ('ニュース', 'SNS', '掲示板', '口コミ', 'GitHub Issues', '公式発表')
CATEGORIES = ('社会的な注目', '実際の不満', '有料需要の証拠', '既存サービスの問題', '公式統計')


def now():
    return datetime.now(timezone(timedelta(hours=9))).isoformat()


def canonical(url):
    p = urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443):
        raise ValueError('公開HTTPS URLが必要です')
    host = p.hostname.lower()
    if host in ('localhost', 'example.com', 'example.org', 'example.net') or host.endswith(('.invalid', '.test', '.localhost')):
        raise ValueError('実在する公開元ページが必要です')
    if not p.path.rstrip('/') or re.search(r'/(search|search\.php)(/|$)', p.path, re.I):
        raise ValueError('検索結果・ホームではなく元ページを指定してください')
    query = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith('utm_') and k.lower() not in ('fbclid', 'gclid')]
    if any(k.lower() in ('token', 'api_key', 'access_token', 'secret', 'password', 'authorization') for k, _ in query):
        raise ValueError('秘密情報を含むURLは保存できません')
    return urlunsplit(('https', host, p.path.rstrip('/'), urlencode(sorted(query)), ''))


def public_url(url):
    canonical(url)
    for item in socket.getaddrinfo(urlsplit(url).hostname, 443, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(item[4][0]).is_global:
            raise ValueError('非公開ネットワークへのアクセスは禁止です')


class Redirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Client:
    def __init__(self, interval=1.1, max_requests=60, db=None):
        self.interval, self.max_requests = max(1.0, interval), min(100, max_requests)
        self.count, self.last, self.blocked = 0, 0, False
        self.opener = build_opener(Redirects())
        self.db = db
        self.blocked_hosts = {}
        self.collection_events = []
        self.network_events = []
        self.conditional_headers = {}
        self.response_headers = {}

    def get(self, url):
        for attempt in range(3):
            try:
                return self._get(url)
            except HTTPError as exc:
                if exc.code == 429:
                    delay = exc.headers.get('Retry-After', '60')
                    delay = int(delay) if delay.isdigit() else 60
                    if attempt < 1 and delay <= 30:
                        time.sleep(max(1, delay))
                        self.blocked_hosts.pop(urlsplit(url).hostname, None)
                        continue
                if exc.code not in (500, 502, 503, 504) or attempt == 2:
                    raise
            except (URLError, TimeoutError, ConnectionError):
                if attempt == 2:
                    raise
            time.sleep(2 ** attempt)

    def _get(self, url):
        host = urlsplit(url).hostname
        if host in self.blocked_hosts or self.count >= self.max_requests:
            raise RuntimeError('通信上限・API制限により停止')
        public_url(url)
        time.sleep(max(0, self.interval - (time.monotonic() - self.last)))
        self.count += 1
        self.last = time.monotonic()
        try:
            headers = {'User-Agent': 'TrendRadar/0.2 (+public metadata only)', 'Accept': 'application/vnd.github+json' if host == 'api.github.com' else 'text/html, application/rss+xml, application/atom+xml'}
            headers.update(self.conditional_headers)
            with self.opener.open(Request(url, headers=headers), timeout=10) as r:
                self.response_headers = dict(r.headers)
                body = r.read(2_000_001)
                if len(body) > 2_000_000:
                    raise ValueError('応答サイズ上限')
                self.network_events.append(dict(host=host, status=r.status))
                return r.status, r.geturl(), body
        except HTTPError as e:
            self.network_events.append(dict(host=host, status=e.code))
            if e.code in (403, 429):
                self.blocked_hosts[host] = e.code
            raise

    def verify(self, url):
        checked = now()
        try:
            code, final, body = self.get(canonical(url))
            final = canonical(final)
            if final != canonical(url):
                return dict(status='転送先要確認', checked_at=checked, http=code, final_url=final)
            page = body.decode('utf-8', errors='replace').lower()
            if any(x in page for x in ('<title>sign in', '<title>access denied', '<title>just a moment', 'this content is no longer available')):
                return dict(status='非公開・確認不能', checked_at=checked, http=code, final_url=final)
            return dict(status='確認済み' if code == 200 and '<html' in page else '確認不能', checked_at=checked, http=code, final_url=final)
        except HTTPError as e:
            status = {404: '削除済み・リンク切れ', 410: '削除済み', 401: '非公開', 403: '非公開・アクセス制限', 429: 'API制限'}.get(e.code, '取得失敗')
            return dict(status=status, checked_at=checked, http=e.code, final_url=None)
        except (URLError, OSError, ValueError, RuntimeError):
            return dict(status='確認不能', checked_at=checked, http=None, final_url=None)


def connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript('''
    CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, url TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, group_id TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS versions(id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, at TEXT NOT NULL, payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS checks(id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, at TEXT NOT NULL, payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, at TEXT NOT NULL, payload TEXT NOT NULL);
    ''')
    return db


def normalized(title):
    return re.sub(r'[^\w]', '', unicodedata.normalize('NFKC', title).casefold())


def save(db, source, check):
    source = dict(source)
    source['url'] = canonical(source['url'])
    source.setdefault('published_at', None)
    required = ('title', 'media', 'fetched_at', 'summary', 'analysis_id', 'analysis_title', 'reason', 'reliability')
    if not all(isinstance(source.get(k), str) and 0 < len(source[k]) <= 1000 for k in required) or source.get('kind') not in KINDS or not isinstance(source.get('categories'), list) or not source['categories'] or any(c not in CATEGORIES for c in source['categories']):
        raise ValueError('出典メタデータが不足しています')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', source['analysis_id']):
        raise ValueError('分析IDは英数字・ハイフン・アンダースコアで指定してください')
    if len(source['summary']) > 400 or len(source['title']) > 500:
        raise ValueError('全文保存は禁止。短い要約を使用してください')
    if source.get('published_at'):
        published = datetime.fromisoformat(source['published_at'].replace('Z', '+00:00'))
        if not published.tzinfo or published > datetime.fromisoformat(now()) + timedelta(days=1):
            raise ValueError('投稿日時が不正')
    datetime.fromisoformat(source['fetched_at'])
    sid = hashlib.sha256(source['url'].encode()).hexdigest()[:20]
    old = db.execute('SELECT * FROM sources WHERE id=?', (sid,)).fetchone()
    if check['status'] != '確認済み' and not old:
        return None
    group = old['group_id'] if old else sid
    # Collapse syndication only on a strong title match; preserve every original URL.
    if not old:
        for row in db.execute('SELECT payload,group_id FROM sources ORDER BY first_seen,id'):
            other = json.loads(row['payload'])
            a, b = normalized(source['title']), normalized(other['title'])
            if source['kind'] == other['kind'] and min(len(a), len(b)) >= 15 and SequenceMatcher(None, a, b).ratio() >= .93:
                group = row['group_id']
                break
    payload = json.dumps(source, ensure_ascii=False, sort_keys=True)
    at = source['fetched_at']
    with db:
        if not old or json.loads(old['payload']) | {'fetched_at': at} != source:
            db.execute('INSERT INTO versions(source_id,at,payload) VALUES (?,?,?)', (sid, at, payload))
        db.execute('INSERT INTO sources VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,last_seen=excluded.last_seen', (sid, source['url'], payload, old['first_seen'] if old else at, at, group))
        record_check(db, sid, check)
    return sid


def record_check(db, sid, check):
    db.execute('INSERT INTO checks(source_id,at,payload) VALUES (?,?,?)', (sid, check['checked_at'], json.dumps(check, ensure_ascii=False)))


def sources(db):
    result = []
    for row in db.execute('SELECT * FROM sources ORDER BY first_seen DESC,id'):
        item = json.loads(row['payload'])
        check = db.execute('SELECT payload FROM checks WHERE source_id=? ORDER BY id DESC LIMIT 1', (row['id'],)).fetchone()
        item.update(id=row['id'], group_id=row['group_id'], first_seen=row['first_seen'], last_seen=row['last_seen'], verification=json.loads(check[0]), versions=db.execute('SELECT COUNT(*) FROM versions WHERE source_id=?', (row['id'],)).fetchone()[0])
        result.append(item)
    return result


def ranking(rows):
    analyses = {}
    for s in rows:
        a = analyses.setdefault(s['analysis_id'], dict(id=s['analysis_id'], title=s['analysis_title'], groups=set(), categories=set()))
        if s['verification']['status'] == '確認済み':
            a['groups'].add(s['group_id'])
            a['categories'].update(s['categories'])
    return [dict(id=a['id'], title=a['title'], score=len(a['groups']), categories=sorted(a['categories'])) for a in sorted(analyses.values(), key=lambda x: (-len(x['groups']), x['id']))]


def collect(client, config):
    from .providers import github_parser, metadata

    result, errors = [], []
    for repo in config['repositories']:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
            raise ValueError('不正なリポジトリ名')
        for endpoint, limit in (('issues', config['issues_per_repository']), ('releases', config['releases_per_repository'])):
            limit = min(10, max(0, int(limit)))
            if not limit:
                continue
            try:
                url = f'https://api.github.com/repos/{repo}/{endpoint}?per_page={min(30, limit * 3)}'
                items = metadata(client, url, github_parser)
                if not isinstance(items, list):
                    raise ValueError('API応答形式')
                items = [i for i in items if not i.get('pull_request')][:limit]
                client.collection_events[-1]['selected_count'] = len(items)
                client.collection_events[-1]['selected_unique_count'] = len({item['html_url'] for item in items})
                for item in items:
                    issue = endpoint == 'issues'
                    labels = {x['name'].lower() for x in item.get('labels', [])}
                    problem = issue and any(x in labels for x in ('bug', 'bug verified', 'confirmed', 'regression'))
                    categories = ['実際の不満', '既存サービスの問題'] if problem else ['社会的な注目']
                    title = item.get('title') if issue else item.get('name') or item['tag_name']
                    result.append(dict(url=item['html_url'], title=title[:500], media=f'GitHub / {repo}', published_at=item.get('created_at') if issue else item.get('published_at'), fetched_at=now(), kind='GitHub Issues' if issue else '公式発表', categories=categories,
                        summary=('利用者による課題報告。内容の再現・事実確認は未実施。' if problem else '公開Issueとして話題を観測。需要や不具合の存在は未確定。') if issue else '開発元によるリリース告知。利用者数や購入意思を示すものではありません。',
                        analysis_id=repo.replace('/', '-'), analysis_title=f'{repo} の利用支援・運用改善需要（仮説）', reason='bug等のラベルに基づく仮分類。人手レビューが必要。' if problem else '公開活動の観測。社会全体での注目度を示す統計ではありません。', reliability='利用者の自己申告・未検証' if issue else '開発元の一次発表', content_verified=False, classification='自動・暫定', origin='GitHub公式REST API', content_features=item.get('content_features')))
            except (HTTPError, URLError, OSError, RuntimeError, ValueError, KeyError, TypeError):
                errors.append(f'{repo}/{endpoint}: 取得失敗・制限（全文・認証情報は記録しません）')
    return result, errors
