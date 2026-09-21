from __future__ import annotations

import json
import time

from conftest import ISSUES, REPO
from solvepool_mcp import index


def docs():
    return index.docs_from_issues(REPO, ISSUES)


def test_tokenize_drops_stopwords_and_adds_bigrams():
    toks = index.tokenize('Come faccio a calcolare la partita IVA?')
    assert 'come' not in toks and 'la' not in toks
    assert 'calcolare' in toks and 'partita_iva' in toks


def test_match_finds_paraphrase():
    got = index.match('il mio actor apify in standby risponde 502 finché la probe non risponde', docs())
    assert got and got[0][0].number == 1


def test_match_ignores_unrelated_prompt():
    assert index.match('write a haiku about autumn leaves falling gently', docs()) == []


def test_match_is_deterministic_and_capped():
    a = index.match('backup nas photo raid1 fastapi apify invoice vat', docs(), k=2)
    b = index.match('backup nas photo raid1 fastapi apify invoice vat', docs(), k=2)
    assert [d.number for d, _ in a] == [d.number for d, _ in b]
    assert len(a) <= 2


def test_cache_roundtrip_and_age(tmp_path):
    index.save_index(tmp_path, REPO, docs())
    loaded, age = index.load_index(tmp_path, REPO)
    assert [d.number for d in loaded] == [1, 2, 3]
    assert age is not None and age < 5
    path = index.index_path(tmp_path, REPO)
    data = json.loads(path.read_text(encoding='utf-8'))
    data['fetched_at'] = time.time() - 10_000
    path.write_text(json.dumps(data), encoding='utf-8')
    _, age = index.load_index(tmp_path, REPO)
    assert age > 9_000


def test_load_all_reports_stale_and_missing(settings):
    docs_, stale, missing = index.load_all(settings)
    assert docs_ == [] and missing == [REPO] and stale == []
    index.save_index(settings.data_dir, REPO, docs())
    docs_, stale, missing = index.load_all(settings)
    assert len(docs_) == 3 and not stale and not missing


def test_refresh_all_uses_github(settings, github, transport):
    outcome = index.refresh_all(settings, github)
    assert outcome == {REPO: '3 rooms'}
    assert any('/repos/acme/rooms/issues' in c[1] and 'labels=room' in c[1] for c in transport.calls)
    docs_, _ = index.load_index(settings.data_dir, REPO)
    assert docs_[0].labels == ['apify', 'fastapi'] and 'room' not in docs_[0].labels
