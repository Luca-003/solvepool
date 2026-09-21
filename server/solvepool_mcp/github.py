'''Minimal GitHub REST client on urllib. Token optional: public repos read without it.

The HTTP layer is a single injectable ``transport`` callable so tests run offline
with canned responses. Every error becomes a ``GitHubError`` carrying a hint the
model can relay to the user (missing token, private repo, rate limit).
'''

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from . import __version__

API = 'https://api.github.com'
USER_AGENT = f'solvepool/{__version__} (+https://github.com/Luca-003/solvepool)'
TIMEOUT_S = 10

Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, dict[str, str], bytes]]

TOKEN_HINT = (
    'Provide a GitHub token: set GITHUB_TOKEN (or GH_TOKEN) in the environment, '
    'or run `gh auth login` so SolvePool can read `gh auth token`.'
)


class GitHubError(Exception):
    def __init__(self, status: int, message: str, hint: str = '') -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return f'{self.message} (HTTP {self.status}). {self.hint}'.strip()


def urllib_transport(method: str, url: str, headers: dict[str, str], data: bytes | None) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read() if exc.fp else b''
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, body
    except urllib.error.URLError as exc:
        raise GitHubError(0, f'network error reaching GitHub: {exc.reason}', 'Check the connection and retry.') from exc


class GitHub:
    def __init__(self, token: str | None = None, transport: Transport | None = None) -> None:
        self.token = token
        self._send = transport or urllib_transport
        self.last_rate: dict[str, str] = {}

    @property
    def authenticated(self) -> bool:
        return bool(self.token)

    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None, body: dict | None = None) -> Any:
        url = API + path
        if params:
            url += '?' + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        headers = {
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': USER_AGENT,
        }
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        data = None
        if body is not None:
            data = json.dumps(body, sort_keys=True).encode('utf-8')
            headers['Content-Type'] = 'application/json'

        status, resp_headers, raw = self._send(method, url, headers, data)
        self.last_rate = {k: v for k, v in resp_headers.items() if k.startswith('x-ratelimit-')}

        if status >= 400:
            raise self._error(status, resp_headers, raw, path)
        if not raw:
            return None
        try:
            return json.loads(raw.decode('utf-8'))
        except ValueError as exc:
            raise GitHubError(status, 'GitHub returned a non-JSON body', 'Retry; if it persists the API may be degraded.') from exc

    def _error(self, status: int, headers: dict[str, str], raw: bytes, path: str) -> GitHubError:
        message = ''
        try:
            message = json.loads(raw.decode('utf-8')).get('message', '')
        except (ValueError, AttributeError):
            message = raw[:200].decode('utf-8', 'replace')
        remaining = headers.get('x-ratelimit-remaining')
        if status in (403, 429) and remaining == '0':
            reset = headers.get('x-ratelimit-reset', '')
            hint = 'GitHub rate limit reached. ' + (
                'Wait for the reset or ' + TOKEN_HINT + ' (5000 requests/hour instead of 60).' if not self.token
                else f'Wait until the reset (epoch {reset}).'
            )
            return GitHubError(status, message or 'rate limited', hint)
        if status == 401:
            return GitHubError(status, message or 'unauthorized', 'The token is invalid or expired. ' + TOKEN_HINT)
        if status == 403:
            return GitHubError(status, message or 'forbidden', 'The token lacks permission for this repository (scope `repo` needed for private ones).')
        if status == 404:
            hint = f'Repository or issue not found: {path}. '
            hint += 'If it is private, ' + TOKEN_HINT if not self.token else 'Check the owner/repo spelling and that your token can see it.'
            return GitHubError(status, message or 'not found', hint)
        if status == 422:
            return GitHubError(status, message or 'validation failed', 'GitHub rejected the request body.')
        return GitHubError(status, message or 'request failed', '')

    # ----- issues ---------------------------------------------------------

    def list_room_issues(self, repo: str, label: str, *, limit: int = 300) -> list[dict]:
        items: list[dict] = []
        page = 1
        while len(items) < limit:
            batch = self.request(
                'GET',
                f'/repos/{repo}/issues',
                params={'labels': label, 'state': 'open', 'per_page': 100, 'page': page, 'sort': 'updated'},
            ) or []
            items.extend(issue for issue in batch if 'pull_request' not in issue)
            if len(batch) < 100:
                break
            page += 1
        return items[:limit]

    def search_rooms(self, query: str, repos: tuple[str, ...], label: str, *, limit: int = 10) -> list[dict]:
        text = ' '.join(query.split())[:180]
        qualifiers = ' '.join(f'repo:{r}' for r in repos)
        q = f'{text} {qualifiers} label:{label} is:issue is:open'.strip()
        data = self.request(
            'GET',
            '/search/issues',
            params={'q': q, 'per_page': min(limit, 30), 'advanced_search': 'true'},
        ) or {}
        return [item for item in data.get('items', []) if 'pull_request' not in item][:limit]

    def get_issue(self, repo: str, number: int) -> dict:
        return self.request('GET', f'/repos/{repo}/issues/{number}')

    def list_comments(self, repo: str, number: int, *, limit: int = 20) -> list[dict]:
        comments = self.request('GET', f'/repos/{repo}/issues/{number}/comments', params={'per_page': min(limit, 100)}) or []
        return comments[-limit:]

    def create_issue(self, repo: str, title: str, body: str, labels: list[str]) -> dict:
        if not self.token:
            raise GitHubError(401, 'creating an issue requires a GitHub token', TOKEN_HINT)
        return self.request('POST', f'/repos/{repo}/issues', body={'title': title, 'body': body, 'labels': labels})

    # ----- meta -----------------------------------------------------------

    def rate_limit(self) -> dict:
        data = self.request('GET', '/rate_limit') or {}
        return data.get('resources', {})

    def repo_info(self, repo: str) -> dict:
        return self.request('GET', f'/repos/{repo}')


def repo_from_issue(issue: dict) -> str:
    '''Derive ``owner/repo`` from an issue payload (search results have no repository field).'''
    repo_url = issue.get('repository_url', '')
    marker = '/repos/'
    if marker in repo_url:
        return repo_url.split(marker, 1)[1]
    html = issue.get('html_url', '')
    parts = html.split('github.com/')
    if len(parts) == 2:
        segments = parts[1].split('/')
        if len(segments) >= 2:
            return f'{segments[0]}/{segments[1]}'
    return ''
