'''Room body format (v1), parser, privacy filter and context sanitizer.

A room is a GitHub Issue whose body follows five fixed sections and ends with a
version marker. Headings are matched case-insensitively in English and Italian
so hand-written rooms still parse. Everything read from GitHub is untrusted:
``sanitize_for_context`` strips what could hide instructions before the text is
injected into a model's context.
'''

from __future__ import annotations

import re
from dataclasses import dataclass, field

MARKER = '<!-- solvepool:v1 -->'

SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('problem', ('problem', 'problema')),
    ('solution', ('solution', 'soluzione')),
    ('variables', ('open variables', 'variables', 'variabili aperte', 'variabili')),
    ('verification', ('verification', 'verify', 'verifica')),
    ('example_prompts', ('example prompts', 'examples', 'prompt di esempio', 'esempi')),
)
HEADINGS = {
    'problem': 'Problem',
    'solution': 'Solution',
    'variables': 'Open variables',
    'verification': 'Verification',
    'example_prompts': 'Example prompts',
}

_HEADING_RE = re.compile(r'^\s{0,3}#{2,3}\s+(.+?)\s*$', re.MULTILINE)
_HTML_COMMENT_RE = re.compile(r'<!--.*?-->', re.DOTALL)
_ZERO_WIDTH_RE = re.compile('[​-‏ -‮⁠-⁤﻿]')
_CONTROL_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


@dataclass(slots=True)
class RoomBody:
    problem: str
    solution: str
    variables: list[str] = field(default_factory=list)
    verification: str = ''
    example_prompts: list[str] = field(default_factory=list)

    def summary(self, limit: int = 160) -> str:
        return first_line(self.problem or self.solution, limit)


def first_line(text: str, limit: int = 160) -> str:
    for line in text.splitlines():
        stripped = line.strip().lstrip('-*# ').strip()
        if stripped:
            return stripped if len(stripped) <= limit else stripped[: limit - 1].rstrip() + '…'
    return ''


def _bullets(items: list[str]) -> str:
    return '\n'.join(f'- {item.strip()}' for item in items if item.strip())


def _unbullet(block: str) -> list[str]:
    out: list[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        out.append(re.sub(r'^([-*+]|\d+[.)])\s+', '', stripped))
    return out


def render(body: RoomBody) -> str:
    parts = [
        f'## {HEADINGS["problem"]}\n\n{body.problem.strip()}',
        f'## {HEADINGS["solution"]}\n\n{body.solution.strip()}',
        f'## {HEADINGS["variables"]}\n\n{_bullets(body.variables) or "- (none)"}',
        f'## {HEADINGS["verification"]}\n\n{body.verification.strip() or "(not specified)"}',
        f'## {HEADINGS["example_prompts"]}\n\n{_bullets(body.example_prompts) or "- (none)"}',
        MARKER,
    ]
    return '\n\n'.join(parts) + '\n'


def parse(text: str) -> RoomBody | None:
    '''Parse a room body. Returns None when the version marker is missing.'''
    if MARKER not in text:
        return None
    matches = list(_HEADING_RE.finditer(text))
    found: dict[str, str] = {}
    for idx, match in enumerate(matches):
        title = match.group(1).strip().lower().rstrip(':')
        key = next((k for k, aliases in SECTIONS if title in aliases), None)
        if key is None or key in found:
            continue
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        found[key] = text[start:end].replace(MARKER, '').strip()
    if 'solution' not in found:
        return None

    def clean_list(block: str) -> list[str]:
        items = _unbullet(block)
        return [i for i in items if i.lower() not in ('(none)', 'none', '(nessuna)')]

    verification = found.get('verification', '')
    if verification.lower() in ('(not specified)', '(non specificato)'):
        verification = ''
    return RoomBody(
        problem=found.get('problem', ''),
        solution=found['solution'],
        variables=clean_list(found.get('variables', '')),
        verification=verification,
        example_prompts=clean_list(found.get('example_prompts', '')),
    )


# ----- privacy filter --------------------------------------------------------

@dataclass(slots=True, frozen=True)
class Finding:
    kind: str
    sample: str


_SENSITIVE: tuple[tuple[str, re.Pattern[str]], ...] = (
    ('email', re.compile(r'\b[\w.+-]+@[\w-]+\.[\w.-]+\b')),
    ('iban', re.compile(r'\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\s?[A-Z0-9]{1,4}\b')),
    ('phone', re.compile(r'(?<![\w/.-])\+?\d{2,4}[\s.-]?\d{3,4}[\s.-]?\d{3,4}(?:[\s.-]?\d{2,4})?(?![\w/.-])')),
    ('api_key', re.compile(r'\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|apify_api_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|xox[baprs]-[A-Za-z0-9-]{10,})')),
    ('jwt', re.compile(r'\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}')),
    ('user_path', re.compile(r'(?:[A-Za-z]:\\Users\\|/home/|/Users/)[^\\/\s"\'`]+')),
    ('url_token', re.compile(r'[?&](?:token|access_token|api_key|apikey|key|secret|password)=[^&\s"\'`]+', re.IGNORECASE)),
    ('private_key', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----')),
)


def find_sensitive(text: str) -> list[Finding]:
    findings: list[Finding] = []
    for kind, pattern in _SENSITIVE:
        for match in pattern.finditer(text):
            sample = match.group(0)
            if kind == 'phone' and sum(ch.isdigit() for ch in sample) < 9:
                continue
            findings.append(Finding(kind, sample if len(sample) <= 40 else sample[:37] + '…'))
    return findings


# ----- untrusted input ------------------------------------------------------

def sanitize_for_context(text: str, limit: int = 400) -> str:
    '''Make room text safe to inject as plain prose: no comments, no invisible chars, no control chars.'''
    cleaned = _HTML_COMMENT_RE.sub('', text)
    cleaned = _ZERO_WIDTH_RE.sub('', cleaned)
    cleaned = _CONTROL_RE.sub('', cleaned)
    cleaned = cleaned.replace('`', "'").replace('{', '(').replace('}', ')')
    cleaned = ' '.join(cleaned.split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip() + '…'


def sanitize_block(text: str, limit: int = 20000) -> str:
    '''Sanitize a whole room body for display: drop hidden content but keep line breaks, code and {{variables}}.'''
    cleaned = _HTML_COMMENT_RE.sub('', text.replace('\r\n', '\n').replace('\r', '\n'))
    cleaned = _ZERO_WIDTH_RE.sub('', cleaned)
    cleaned = _CONTROL_RE.sub('', cleaned)
    cleaned = re.sub(r'[ \t]+\n', '\n', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip() + '…'


_TAG_RE = re.compile(r'[^a-z0-9-]+')


def normalize_tags(tags: list[str], *, limit: int = 5) -> list[str]:
    out: list[str] = []
    for tag in tags:
        slug = _TAG_RE.sub('-', tag.strip().lower()).strip('-')[:30]
        if slug and slug != 'room' and slug not in out:
            out.append(slug)
        if len(out) >= limit:
            break
    return out
