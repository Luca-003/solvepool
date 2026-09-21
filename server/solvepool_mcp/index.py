'''Local room index: cached per repository, searched with BM25 in pure stdlib.

Shared by the MCP server and the prompt hook, so the two never disagree on what
"similar" means. The cache lives in ``<data_dir>/index/<owner>__<repo>.json`` and
is refreshed lazily; readers tolerate stale or missing caches.
'''

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from . import rooms
from .config import ROOM_LABEL, Settings
from .github import GitHub, GitHubError

_TOKEN_RE = re.compile(r'[^\W_]+', re.UNICODE)

STOPWORDS = frozenset('''
a ad agli ai al alla alle allo anche avere che chi ci come con cosa da dal dalla dalle dallo dei del della delle
dello di dove e ed essere fa fai fare fatto gli ha hai ho i il in io la le lo lui lei loro ma me mi mia mie miei
mio ne nei nel nella nelle nello noi non o per però più poi quale quali quando questa queste questi questo qui
se sei si sia siamo sono sta sto su sua sue sui suo sul sulla sulle sullo ti tu tua tue tuo tuoi un una uno vi
voi vorrei voglio vuoi devo deve dovrei posso puoi può bisogna serve ecco così già ancora sempre tutto tutti
crea creare fammi dammi mostrami spiegami aiutami aiuto grazie ciao
a an and are as at be been but by can could did do does for from had has have he her his how i if in into is
it its just me my no not of on or our she so some than that the their them then there these they this those to
us was we were what when where which who why will with would you your yours about also any because before
being between both each few get got here into more most other out over own same should such through under
until up very want wants wanted need needs please help make create build write show tell explain give let
using use used like something thing things way one two new
'''.split())


@dataclass(slots=True)
class RoomDoc:
    repo: str
    number: int
    title: str
    labels: list[str]
    summary: str
    url: str
    updated_at: str

    @property
    def ref(self) -> str:
        return f'{self.repo}#{self.number}'


def tokenize(text: str, *, bigrams: bool = True) -> list[str]:
    words = [w.lower() for w in _TOKEN_RE.findall(text)]
    kept = [w for w in words if len(w) > 1 and w not in STOPWORDS]
    if not bigrams:
        return kept
    return kept + [f'{a}_{b}' for a, b in zip(kept, kept[1:])]


def doc_tokens(doc: RoomDoc) -> list[str]:
    title = tokenize(doc.title)
    return title + title + tokenize(' '.join(doc.labels), bigrams=False) + tokenize(doc.summary)


class BM25:
    def __init__(self, docs: list[RoomDoc], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.docs = docs
        self.k1 = k1
        self.b = b
        self._tf: list[dict[str, int]] = []
        self._df: dict[str, int] = {}
        for doc in docs:
            counts: dict[str, int] = {}
            for tok in doc_tokens(doc):
                counts[tok] = counts.get(tok, 0) + 1
            self._tf.append(counts)
            for tok in counts:
                self._df[tok] = self._df.get(tok, 0) + 1
        self._len = [sum(c.values()) for c in self._tf]
        self._avg = (sum(self._len) / len(self._len)) if self._len else 0.0

    def _idf(self, tok: str) -> float:
        n = self._df.get(tok, 0)
        return math.log((len(self.docs) - n + 0.5) / (n + 0.5) + 1.0)

    def score(self, query_tokens: list[str]) -> list[tuple[int, float, int]]:
        '''Return (doc_index, score, matched_unigrams) sorted by score desc.'''
        unique = set(query_tokens)
        out: list[tuple[int, float, int]] = []
        for i, tf in enumerate(self._tf):
            score = 0.0
            matched = 0
            norm = self.k1 * (1 - self.b + self.b * (self._len[i] / self._avg if self._avg else 1.0))
            for tok in unique:
                f = tf.get(tok)
                if not f:
                    continue
                if '_' not in tok:
                    matched += 1
                score += self._idf(tok) * (f * (self.k1 + 1)) / (f + norm)
            if score > 0:
                out.append((i, score, matched))
        out.sort(key=lambda t: t[1], reverse=True)
        return out


def match(prompt: str, docs: list[RoomDoc], *, k: int = 3) -> list[tuple[RoomDoc, float]]:
    '''Top-k rooms that share enough vocabulary with the prompt to be worth showing.'''
    if not docs:
        return []
    query = tokenize(prompt)
    if not query:
        return []
    unigrams = {t for t in query if '_' not in t}
    need = 1 if len(unigrams) < 3 else 2
    ranked = BM25(docs).score(query)
    picked = [(docs[i], s) for i, s, matched in ranked if matched >= need]
    return picked[:k]


# ----- cache -----------------------------------------------------------------

def index_path(data_dir: Path, repo: str) -> Path:
    return data_dir / 'index' / (repo.replace('/', '__') + '.json')


def load_index(data_dir: Path, repo: str) -> tuple[list[RoomDoc], float | None]:
    '''Return (docs, age_seconds). age is None when there is no cache.'''
    path = index_path(data_dir, repo)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return [], None
    docs = [RoomDoc(**d) for d in data.get('docs', []) if isinstance(d, dict)]
    fetched = float(data.get('fetched_at', 0))
    return docs, max(0.0, time.time() - fetched)


def save_index(data_dir: Path, repo: str, docs: list[RoomDoc]) -> None:
    path = index_path(data_dir, repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {'repo': repo, 'fetched_at': time.time(), 'docs': [asdict(d) for d in docs]}
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding='utf-8')
    tmp.replace(path)


def docs_from_issues(repo: str, issues: list[dict]) -> list[RoomDoc]:
    docs: list[RoomDoc] = []
    for issue in issues:
        body = rooms.parse(issue.get('body') or '')
        summary = body.summary() if body else rooms.first_line(issue.get('body') or '')
        docs.append(RoomDoc(
            repo=repo,
            number=int(issue['number']),
            title=rooms.sanitize_for_context(issue.get('title') or '', 200),
            labels=[l['name'] for l in issue.get('labels', []) if isinstance(l, dict) and l.get('name') != ROOM_LABEL],
            summary=rooms.sanitize_for_context(summary, 200),
            url=issue.get('html_url', ''),
            updated_at=issue.get('updated_at', ''),
        ))
    return docs


def refresh_index(settings: Settings, github: GitHub, repo: str) -> list[RoomDoc]:
    issues = github.list_room_issues(repo, ROOM_LABEL)
    docs = docs_from_issues(repo, issues)
    save_index(settings.data_dir, repo, docs)
    return docs


def refresh_all(settings: Settings, github: GitHub) -> dict[str, str]:
    '''Refresh every configured repo; return per-repo outcome text (never raises).'''
    outcome: dict[str, str] = {}
    for repo in settings.repos:
        try:
            docs = refresh_index(settings, github, repo)
            outcome[repo] = f'{len(docs)} rooms'
        except GitHubError as exc:
            outcome[repo] = f'error: {exc}'
        except Exception as exc:  # noqa: BLE001 - background refresh must never crash the caller
            outcome[repo] = f'error: {exc!r}'
    return outcome


def load_all(settings: Settings) -> tuple[list[RoomDoc], list[str], list[str]]:
    '''Load cached docs for all repos. Returns (docs, stale_repos, missing_repos).'''
    docs: list[RoomDoc] = []
    stale: list[str] = []
    missing: list[str] = []
    for repo in settings.repos:
        repo_docs, age = load_index(settings.data_dir, repo)
        if age is None:
            missing.append(repo)
            continue
        if age > settings.index_ttl_s:
            stale.append(repo)
        docs.extend(repo_docs)
    return docs, stale, missing
