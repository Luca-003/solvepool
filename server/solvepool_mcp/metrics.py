'''Append-only JSONL metrics for the dogfooding phase.

Two kinds matter: ``proposal`` (the hook surfaced candidates) and ``reuse`` (a
room was fetched with solvepool_get). Prompts are never stored, only a short hash.
'''

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from pathlib import Path


def metrics_path(data_dir: Path) -> Path:
    return data_dir / 'metrics.jsonl'


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.strip().lower().encode('utf-8')).hexdigest()[:12]


def record(data_dir: Path, kind: str, **payload: object) -> None:
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps({'ts': round(time.time()), 'kind': kind, **payload}, ensure_ascii=False, sort_keys=True)
        with metrics_path(data_dir).open('a', encoding='utf-8') as fh:
            fh.write(line + '\n')
    except OSError:
        pass


def summary(data_dir: Path) -> dict[str, int]:
    counts: Counter[str] = Counter()
    try:
        with metrics_path(data_dir).open(encoding='utf-8') as fh:
            for line in fh:
                try:
                    counts[json.loads(line).get('kind', '?')] += 1
                except ValueError:
                    continue
    except OSError:
        return {}
    return dict(counts)
