from __future__ import annotations

import json

import pytest

from conftest import REPO
from solvepool_mcp import metrics
from solvepool_mcp.service import Service, parse_room_ref


@pytest.mark.parametrize('ref,expected', [
    ('#12', (REPO, 12)),
    ('12', (REPO, 12)),
    ('other/repo#3', ('other/repo', 3)),
    ('https://github.com/x/y/issues/44', ('x/y', 44)),
])
def test_parse_room_ref(ref, expected):
    got = parse_room_ref(ref, REPO)
    assert (got.repo, got.number) == expected


def test_parse_room_ref_rejects_garbage():
    with pytest.raises(ValueError):
        parse_room_ref('twelve', REPO)


def test_status_without_token(settings, github):
    out = Service(settings, github).status()
    assert 'Token: none' in out and 'acme/rooms: reachable (public' in out and '58/60' in out


def test_rooms_refreshes_cache(settings, github):
    out = Service(settings, github).rooms()
    assert '3 rooms' in out and 'acme/rooms#1' in out
    assert (settings.data_dir / 'index' / 'acme__rooms.json').exists()


def test_search_returns_refs(settings, github):
    out = Service(settings, github).search('apify readiness probe')
    assert 'acme/rooms#1' in out and 'solvepool_get' in out


def test_search_falls_back_to_local_index(settings, github, transport):
    svc = Service(settings, github)
    svc.rooms()
    transport.routes.pop(('GET', '/search/issues'))
    out = svc.search('nas backup photo')
    assert 'local index' in out and 'acme/rooms#3' in out


def test_get_records_reuse_and_sanitizes(settings, github):
    out = Service(settings, github).get('#2')
    assert 'Room acme/rooms#2' in out and 'reverse charge' in out and '@bob' in out
    assert 'solvepool:v1' not in out
    assert metrics.summary(settings.data_dir) == {'reuse': 1}


def test_get_rejects_non_room(settings, github, transport):
    transport.add('GET', f'/repos/{REPO}/issues/50', {'number': 50, 'title': 'bug', 'body': 'x', 'labels': [], 'html_url': ''})
    transport.add('GET', f'/repos/{REPO}/issues/50/comments', [])
    assert 'not a SolvePool room' in Service(settings, github).get('#50')


GOOD = dict(
    title='Deploy a Django app to Postgres on a small VPS without downtime',
    problem='Migrating from SQLite to Postgres in production.',
    solution='Dump with dumpdata, create the Postgres database with {{db_name}}, run migrate, loaddata, switch DATABASES, run smoke tests, then cut over DNS. Keep the SQLite file for a week.',
    variables=['db_name — database name · app_prod'],
    verification='manage.py check and a login round-trip succeed',
    example_prompts=['move my django app from sqlite to postgres'],
    tags=['django', 'postgres'],
)


def test_share_requires_token(settings, github):
    assert 'needs a GitHub token' in Service(settings, github).share(**GOOD)


def test_share_blocks_sensitive(settings, github_auth):
    out = Service(settings, github_auth).share(**{**GOOD, 'solution': GOOD['solution'] + ' contact admin@corp.example'})
    assert out.startswith('Not shared') and 'email' in out


def test_share_dedup_nudge_then_force(settings, github_auth, transport):
    svc = Service(settings, github_auth)
    near = {**GOOD, 'title': 'Deploy a FastAPI app on Apify standby with readiness probe'}
    out = svc.share(**near)
    assert 'similar title already exists' in out and 'acme/rooms#1' in out
    out = svc.share(**near, force=True)
    assert out.startswith('Room created: acme/rooms#99')
    _, _, _, data = transport.calls[-1]
    body = json.loads(data)
    assert body['labels'] == ['room', 'django', 'postgres']
    assert '<!-- solvepool:v1 -->' in body['body']
    assert metrics.summary(settings.data_dir) == {'share': 1}


def test_share_creates_room(settings, github_auth):
    out = Service(settings, github_auth).share(**GOOD)
    assert out.startswith('Room created: acme/rooms#99')
