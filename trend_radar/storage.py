import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def migrate(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS quality(id INTEGER PRIMARY KEY, at TEXT NOT NULL, payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS problems(key TEXT PRIMARY KEY, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, occurrences INTEGER NOT NULL, active INTEGER NOT NULL, payload TEXT NOT NULL, github_url TEXT);
    CREATE TABLE IF NOT EXISTS problem_events(id INTEGER PRIMARY KEY, key TEXT NOT NULL, at TEXT NOT NULL, payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS proposals(key TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT '提案');
    CREATE TABLE IF NOT EXISTS improvements(key TEXT PRIMARY KEY, at TEXT NOT NULL, payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS evaluations(key TEXT NOT NULL, horizon INTEGER NOT NULL, at TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(key,horizon));
    CREATE TABLE IF NOT EXISTS feedback(id TEXT PRIMARY KEY, at TEXT NOT NULL, payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS endpoint_cache(url TEXT PRIMARY KEY, etag TEXT, modified TEXT, payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS endpoint_state(url TEXT PRIMARY KEY, failures INTEGER NOT NULL, retry_at TEXT);
    CREATE TABLE IF NOT EXISTS report_snapshots(id INTEGER PRIMARY KEY, at TEXT NOT NULL, payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS weekly_reports(week TEXT PRIMARY KEY, at TEXT NOT NULL, payload TEXT NOT NULL);
    ''')
    columns = {r[1] for r in db.execute('PRAGMA table_info(problems)')}
    if 'synced_at' not in columns:
        db.execute('ALTER TABLE problems ADD COLUMN synced_at TEXT')
    if 'github_url' not in {r[1] for r in db.execute('PRAGMA table_info(proposals)')}:
        db.execute('ALTER TABLE proposals ADD COLUMN github_url TEXT')


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(text, encoding='utf-8')
    temp.replace(path)


def write_json(path, data):
    atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))


@contextmanager
def locked(state):
    path = Path(state) / 'run.lock'
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        # Never steal a lock merely because a previous run is slow.
        raise RuntimeError('別の処理が実行中、または中断後のロックが残っています') from None
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)


def backup(db, path):
    target = Path(path)
    if not target.exists():
        with sqlite3.connect(target) as copy:
            db.backup(copy)
