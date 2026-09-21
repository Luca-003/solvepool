from __future__ import annotations

import pytest

from conftest import REPO, FakeTransport
from solvepool_mcp.github import GitHub, GitHubError, repo_from_issue


def test_no_authorization_header_without_token(github, transport):
    github.rate_limit()
    _, _, headers, _ = transport.calls[-1]
    assert 'Authorization' not in headers
    assert headers['User-Agent'].startswith('solvepool/')


def test_bearer_header_with_token(github_auth, transport):
    github_auth.rate_limit()
    assert transport.calls[-1][2]['Authorization'].startswith('Bearer ghp_')


def test_private_repo_without_token_gives_hint():
    t = FakeTransport(token_required_paths={f'/repos/{REPO}'})
    gh = GitHub(None, transport=t)
    with pytest.raises(GitHubError) as exc:
        gh.repo_info(REPO)
    assert exc.value.status == 404
    assert 'GITHUB_TOKEN' in exc.value.hint


def test_rate_limit_hint():
    t = FakeTransport()
    t.rate_headers = {'x-ratelimit-remaining': '0', 'x-ratelimit-reset': '1'}
    t.add('GET', '/rate_limit', {'message': 'API rate limit exceeded'}, status=403)
    with pytest.raises(GitHubError) as exc:
        GitHub(None, transport=t).rate_limit()
    assert 'rate limit' in exc.value.hint.lower()


def test_create_issue_requires_token(github):
    with pytest.raises(GitHubError) as exc:
        github.create_issue(REPO, 't', 'b', ['room'])
    assert exc.value.status == 401


def test_search_query_has_qualifiers(github, transport):
    github.search_rooms('apify probe', (REPO, 'other/repo'), 'room')
    url = transport.calls[-1][1]
    assert 'repo%3Aacme%2Frooms' in url and 'repo%3Aother%2Frepo' in url
    assert 'label%3Aroom' in url and 'advanced_search=true' in url


def test_repo_from_issue():
    assert repo_from_issue({'repository_url': 'https://api.github.com/repos/a/b'}) == 'a/b'
    assert repo_from_issue({'html_url': 'https://github.com/c/d/issues/7'}) == 'c/d'
