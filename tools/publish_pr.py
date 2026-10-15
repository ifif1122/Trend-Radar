"""Publish a prepared draft PR using existing GitHub git credentials, never print tokens."""
import json
import os
import subprocess
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main():
    root = Path(__file__).resolve().parents[1]
    git = ['git', '-c', 'safe.directory=' + root.as_posix()]
    remote = subprocess.check_output(git + ['remote', 'get-url', 'origin'], cwd=root, text=True).strip()
    prefix = 'https://github.com/'
    if not remote.startswith(prefix):
        raise SystemExit('GitHub HTTPS remote is required')
    repo = remote.removeprefix(prefix).removesuffix('.git')
    branch = subprocess.check_output(git + ['branch', '--show-current'], cwd=root, text=True).strip()
    if not branch.startswith('feature/trend-radar-'):
        raise SystemExit('A Trend Radar work branch is required')
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never')
    token = env.get('GH_TOKEN') or env.get('GITHUB_TOKEN')
    if not token:
        result = subprocess.run(git + ['credential', 'fill'], input='protocol=https\nhost=github.com\n\n', cwd=root, text=True, capture_output=True, env=env, timeout=30)
        values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        token = values.get('password')
    if not token:
        raise SystemExit('Existing GitHub authentication is unavailable; PR_BODY.md is ready.')
    body = Path(__file__).resolve().parents[1].joinpath('PR_BODY.md').read_text(encoding='utf-8')
    payload = dict(title='Trend Radar: bounded maintenance, quality history and improvement evaluation', head=branch, base='main', body=body, draft=True)
    req = Request(f'https://api.github.com/repos/{repo}/pulls', data=json.dumps(payload).encode(), headers={'Authorization': 'Bearer '+token, 'User-Agent': 'TrendRadar-development', 'Accept': 'application/vnd.github+json'}, method='POST')
    try:
        with urlopen(req, timeout=30) as response:
            data = json.load(response)
            print(data['html_url'])
    except HTTPError as exc:
        raise SystemExit(f'PR creation failed: HTTP {exc.code}; credentials were not logged.') from None


if __name__ == '__main__':
    main()
