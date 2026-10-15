"""Allowlisted public API/RSS metadata. No article/post bodies in cache."""
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError

from .core import canonical, now


def metadata(client, url, parser):
    db = getattr(client, 'db', None)
    old = db.execute('SELECT * FROM endpoint_cache WHERE url=?', (url,)).fetchone() if db else None
    state = db.execute('SELECT * FROM endpoint_state WHERE url=?', (url,)).fetchone() if db else None
    if state and state['retry_at'] and state['retry_at'] > now():
        raise RuntimeError('失敗した情報源を次回実行まで一時停止')
    try:
        cached = json.loads(old['payload']) if old else None
        if cached is not None and not isinstance(cached, list):
            raise ValueError('invalid cache')
    except (ValueError, TypeError):
        cached = None
        old = None  # Only derived cache is regenerated; research history stays intact.
    client.conditional_headers = {}
    if old:
        if old['etag']:
            client.conditional_headers['If-None-Match'] = old['etag']
        if old['modified']:
            client.conditional_headers['If-Modified-Since'] = old['modified']
    try:
        try:
            code, _, body = client.get(url)
        except HTTPError as exc:
            if exc.code != 304 or cached is None:
                raise
            code, body = 304, b''
        rows = cached if code == 304 else parser(body)
        if not isinstance(rows, list):
            raise ValueError('metadata must be a list')
        if db:
            h = getattr(client, 'response_headers', {})
            with db:
                if code != 304:
                    db.execute('INSERT OR REPLACE INTO endpoint_cache VALUES (?,?,?,?)', (url, h.get('ETag'), h.get('Last-Modified'), json.dumps(rows, ensure_ascii=False)))
                db.execute('INSERT OR REPLACE INTO endpoint_state VALUES (?,0,NULL)', (url,))
        client.collection_events.append(dict(source=url, success=True, count=len(rows), cached=code == 304))
        return rows
    except (HTTPError, OSError, RuntimeError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
        if db:
            failures = state['failures'] + 1 if state else 1
            retry = (datetime.fromisoformat(now()) + timedelta(hours=min(12, 2 ** min(failures, 4)))).isoformat()
            with db:
                db.execute('INSERT OR REPLACE INTO endpoint_state VALUES (?,?,?)', (url, failures, retry))
        client.collection_events.append(dict(source=url, success=False, count=0, error=type(exc).__name__))
        raise
    finally:
        client.conditional_headers = {}


def github_parser(body):
    data = json.loads(body)
    if not isinstance(data, list):
        raise ValueError('GitHub API schema changed')
    result = []
    for item in data:
        if isinstance(item, dict) and 'pull_request' in item:
            continue
        if not isinstance(item, dict) or 'html_url' not in item:
            raise ValueError('GitHub API schema changed')
        # Keep only fields used by analysis; never body, comments, author profiles.
        result.append({k: item[k] for k in ('title', 'name', 'tag_name', 'html_url', 'created_at', 'published_at', 'updated_at', 'labels', 'pull_request') if k in item})
    return result


def parse_feed(body):
    if b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():
        raise ValueError('XML entities forbidden')
    root = ET.fromstring(body)
    local = lambda tag: tag.rsplit('}', 1)[-1]
    if local(root.tag) not in ('rss', 'RDF', 'feed'):
        raise ValueError('RSS/Atom schema changed')
    result = []
    for entry in root.iter():
        if local(entry.tag) not in ('item', 'entry'):
            continue
        fields = {local(c.tag): c for c in entry}
        title = ''.join(fields['title'].itertext()).strip() if 'title' in fields else ''
        link = fields.get('link')
        url = (link.get('href') or link.text or '').strip() if link is not None else ''
        date = next((fields[k].text for k in ('pubDate', 'published', 'updated', 'date') if k in fields), None)
        if date:
            try:
                date = datetime.fromisoformat(date.strip().replace('Z', '+00:00')).isoformat()
            except ValueError:
                date = parsedate_to_datetime(date).isoformat()
        if title and url:
            result.append(dict(title=title[:500], url=canonical(url), published_at=date))
    return result


def collect_feeds(client, config):
    result, errors = [], []
    for feed in config.get('feeds', []):
        if not feed.get('enabled', False):
            continue
        try:
            if feed.get('rights_confirmed') is not True:
                raise ValueError('RSS permission not confirmed')
            rows = metadata(client, canonical(feed['url']), parse_feed)
            selected = rows[:min(10, max(0, int(feed.get('limit', 5))))]
            client.collection_events[-1]['selected_count'] = len(selected)
            client.collection_events[-1]['selected_unique_count'] = len({item['url'] for item in selected})
            for item in selected:
                result.append(dict(**item, media=feed['name'], fetched_at=now(), kind=feed.get('kind', '公式発表'), categories=['社会的な注目'], analysis_id=re.sub('[^a-zA-Z0-9_-]', '-', feed['id']), analysis_title=feed['analysis_title'], summary='配信元の公開情報をもとにTrend Radarが分類・要約。題名から政策・社会課題の動きを観測。具体的な不満や購入意思は未確認。', reason='公式RSS掲載。内容の検証や需要の確定を意味しません。', reliability='配信元の一次告知', content_verified=False, classification='ルールベース・暫定', origin=feed['url']))
        except (HTTPError, OSError, RuntimeError, ValueError, KeyError, TypeError, ET.ParseError):
            errors.append(f'{feed.get("id", "feed")}: RSS取得・形式確認失敗')
    return result, errors
