"""Download public research state, derive content features and analyze via local Plus."""
import argparse
from contextlib import closing
import json
import os
import sqlite3
import subprocess
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--prepare-only', action='store_true', help='入力・HTMLだけ作成しCodexは呼ばない')
    p.add_argument('--use-prepared', action='store_true', help='1時間以内に準備した入力を使用')
    args = p.parse_args()
    root = args.project.resolve()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from trend_radar.__main__ import collect_run
    from trend_radar.ai_analysis import analyze_ai, latest
    from trend_radar.core import connect, now, sources
    from trend_radar.report import render
    from trend_radar.storage import locked, migrate, write_json
    state = root/'state/local-ai'
    state.mkdir(parents=True, exist_ok=True)
    with locked(state):
        git = ['git', '-c', 'safe.directory='+root.as_posix()]
        env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never')
        hidden = dict(creationflags=subprocess.CREATE_NO_WINDOW) if os.name == 'nt' else {}
        ledger = connect(state/'ledger.sqlite')
        migrate(ledger)
        db = None
        try:
            origin = subprocess.check_output(git+['remote', 'get-url', 'origin'], cwd=root, env=env, text=True, timeout=20, **hidden).strip()
            if origin != 'https://github.com/ifif1122/Trend-Radar.git':
                raise ValueError('収集データの取得先が想定と異なります')
            if not args.use_prepared:
                subprocess.run(git+['fetch', 'origin', 'trend-radar-state'], cwd=root, env=env, check=True, capture_output=True, timeout=60, **hidden)
                size = int(subprocess.check_output(git+['cat-file', '-s', 'FETCH_HEAD:live.sqlite'], cwd=root, env=env, text=True, **hidden))
                if size > 100_000_000:
                    raise ValueError('状態DBの取得上限100MB')
                temp = state/'input.sqlite.tmp'
                with temp.open('wb') as file:
                    subprocess.run(git+['show', 'FETCH_HEAD:live.sqlite'], cwd=root, env=env, check=True, stdout=file, timeout=30, **hidden)
                with closing(sqlite3.connect(temp)) as checked:
                    if checked.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise ValueError('取得した状態DBの整合性エラー')
                temp.replace(state/'input.sqlite')
            elif not (state/'input.sqlite').exists() or time.time()-(state/'input.sqlite').stat().st_mtime > 3600:
                raise ValueError('準備済み入力が存在しないか1時間超経過')
            db = connect(state/'input.sqlite')
            migrate(db)
            config = json.loads((root/'config.json').read_text(encoding='utf-8'))
            if args.use_prepared:
                client, accepted, rejected, invalid, errors = SimpleNamespace(count=0), 0, 0, 0, []
            else:
                client, accepted, rejected, invalid, errors = collect_run(db, SimpleNamespace(import_file=None), config)
            outcome = dict(status='prepared', reason='Codex未実行') if args.prepare_only else analyze_ai(ledger, sources(db))
            report = outcome.get('report') or latest(ledger)
            if report:
                with db:
                    db.execute('INSERT INTO ai_reports(at,input_hash,payload) VALUES (?,?,?)', (report['at'], report['input_hash'], json.dumps(report, ensure_ascii=False)))
            render(db, root/'reports', 'local-analysis', errors)
            summary = dict(at=now(), ai_status=outcome['status'], reason=outcome.get('reason'), accepted=accepted, rejected=rejected, invalid=invalid, requests=client.count, input_sources=len(sources(db)))
            write_json(root/'reports/ai_status.json', summary)
            if report:
                write_json(root/'reports/ai_analysis.json', report)
            print(json.dumps(summary, ensure_ascii=False))
            return 1 if outcome['status'] == 'failed' else 0
        except Exception as exc:
            summary = dict(at=now(), ai_status='failed', error=type(exc).__name__, locations=[dict(file=Path(frame.filename).name, function=frame.name, line=frame.lineno) for frame in traceback.extract_tb(exc.__traceback__)], note='再試行・有料APIへの切替は行いません')
            write_json(root/'reports/ai_status.json', summary)
            print(json.dumps(summary, ensure_ascii=False))
            return 1
        finally:
            if db:
                db.close()
            ledger.close()


if __name__ == '__main__':
    raise SystemExit(main())
