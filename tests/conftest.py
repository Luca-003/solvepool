'''Shared fixtures: an offline GitHub transport and a temporary data directory.'''

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'server'))

from solvepool_mcp import rooms  # noqa: E402
from solvepool_mcp.config import Settings  # noqa: E402
from solvepool_mcp.github import GitHub  # noqa: E402

REPO = 'acme/rooms'


def room_issue(number: int, title: str, problem: str, solution: str, tags: list[str] | None = None, *, body: str | None = None) -> dict:
    if body is None:
        body = rooms.render(rooms.RoomBody(problem=problem, solution=solution, variables=['x — thing · a, b'], verification='run it', example_prompts=['do the thing']))
    labels = [{'name': 'room'}] + [{'name': t} for t in (tags or [])]
    return {
        'number': number,
        'title': title,
        'body': body,
        'labels': labels,
        'html_url': f'https://github.com/{REPO}/issues/{number}',
        'repository_url': f'https://api.github.com/repos/{REPO}',
        'updated_at': '2026-09-20T10:00:00Z',
        'user': {'login': 'alice'},
    }


ISSUES = [
    room_issue(1, 'Deploy a FastAPI app on Apify standby with readiness probe', 'Apify standby actor returns 502 until probe answers', 'Handle the x-apify-container-server-readiness-probe header in GET / and return 200 quickly. Start the HTTP server before heavy imports. Set memory to 512MB.', ['apify', 'fastapi']),
    room_issue(2, 'Compute Italian VAT on a freelance invoice with reverse charge', 'Freelancer invoicing an EU company', 'Apply reverse charge: no VAT line, add the mention art. 7-ter DPR 633/72, report in Intrastat quarterly. Keep {{aliquota}} for domestic clients.', ['fattura', 'iva']),
    room_issue(3, 'Choose a home NAS for photo backup under 500 euro', 'Two-bay NAS, RAID1, low noise', 'Pick a two-bay unit with 2.5GbE, use RAID1 with two NAS-grade disks, enable snapshots, back up offsite monthly.', ['nas', 'backup']),
]


class FakeTransport:
    '''Routes (method, path) to canned responses and records every call.'''

    def __init__(self, *, token_required_paths: set[str] | None = None) -> None:
        self.calls: list[tuple[str, str, dict[str, str], bytes | None]] = []
        self.routes: dict[tuple[str, str], object] = {}
        self.token_required_paths = token_required_paths or set()
        self.rate_headers = {'x-ratelimit-limit': '60', 'x-ratelimit-remaining': '59'}

    def add(self, method: str, path: str, body: object, status: int = 200) -> None:
        self.routes[(method, path)] = (status, body)

    def __call__(self, method: str, url: str, headers: dict[str, str], data: bytes | None):
        parts = urlsplit(url)
        path = parts.path
        self.calls.append((method, url, headers, data))
        if path in self.token_required_paths and 'Authorization' not in headers:
            return 404, self.rate_headers, json.dumps({'message': 'Not Found'}).encode()
        route = self.routes.get((method, path))
        if route is None:
            return 404, self.rate_headers, json.dumps({'message': f'no route {method} {path}'}).encode()
        status, body = route
        if callable(body):
            body = body(parse_qs(parts.query), json.loads(data) if data else None)
        return status, self.rate_headers, json.dumps(body).encode()


@pytest.fixture
def transport() -> FakeTransport:
    t = FakeTransport()
    t.add('GET', f'/repos/{REPO}/issues', lambda q, _: ISSUES)
    t.add('GET', f'/repos/{REPO}', {'private': False, 'open_issues_count': 3, 'full_name': REPO})
    t.add('GET', '/rate_limit', {'resources': {'core': {'limit': 60, 'remaining': 58}, 'search': {'limit': 10, 'remaining': 9}}})
    for issue in ISSUES:
        t.add('GET', f'/repos/{REPO}/issues/{issue["number"]}', issue)
        t.add('GET', f'/repos/{REPO}/issues/{issue["number"]}/comments', [
            {'user': {'login': 'bob'}, 'created_at': '2026-09-21T09:00:00Z', 'body': 'Worked for me with {{aliquota}}=22.'}
        ])

    def search(q, _):
        text = q.get('q', [''])[0].lower()
        hits = [i for i in ISSUES if any(w in i['title'].lower() for w in text.split() if len(w) > 3 and ':' not in w)]
        return {'total_count': len(hits), 'items': hits}

    t.add('GET', '/search/issues', search)

    def create(_, body):
        return {**room_issue(99, body['title'], '', '', body=body['body']), 'labels': [{'name': l} for l in body['labels']]}

    t.add('POST', f'/repos/{REPO}/issues', create, status=201)
    return t


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(repos=(REPO,), data_dir=tmp_path / 'data', token=None, index_ttl_s=600)


@pytest.fixture
def github(transport: FakeTransport) -> GitHub:
    return GitHub(token=None, transport=transport)


@pytest.fixture
def github_auth(transport: FakeTransport) -> GitHub:
    return GitHub(token='ghp_' + 'x' * 36, transport=transport)
