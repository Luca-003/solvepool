'''The hook is exercised as a real subprocess: stdin JSON in, JSON (or nothing) out, exit 0 always.'''

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from conftest import ISSUES, REPO, ROOT
from solvepool_mcp import index

HOOK = ROOT / 'hooks' / 'prompt_match.py'


def run_hook(stdin: str, data_dir: Path, *extra: str) -> tuple[int, str, float]:
    started = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, str(HOOK), '--data', str(data_dir), '--repos', REPO, *extra],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=20,
        env={'PATH': '', 'SYSTEMROOT': __import__('os').environ.get('SYSTEMROOT', '')},
    )
    return proc.returncode, proc.stdout, time.perf_counter() - started


def prepared(tmp_path: Path) -> Path:
    data = tmp_path / 'data'
    index.save_index(data, REPO, index.docs_from_issues(REPO, ISSUES))
    return data


def test_injects_candidates_for_similar_prompt(tmp_path):
    code, out, elapsed = run_hook(json.dumps({'prompt': 'my apify standby actor answers 502 until the readiness probe replies, how do I fix it?'}), prepared(tmp_path))
    assert code == 0
    payload = json.loads(out)
    ctx = payload['hookSpecificOutput']['additionalContext']
    assert payload['hookSpecificOutput']['hookEventName'] == 'UserPromptSubmit'
    assert 'acme/rooms#1' in ctx and 'solvepool_get' in ctx
    assert '{' not in ctx and '`' not in ctx
    assert elapsed < 5
    lines = (tmp_path / 'data' / 'metrics.jsonl').read_text(encoding='utf-8').splitlines()
    assert json.loads(lines[0])['kind'] == 'proposal'


def test_accepts_prompt_text_field(tmp_path):
    code, out, _ = run_hook(json.dumps({'prompt_text': 'choose a two bay nas for photo backup raid1 under 500 euro'}), prepared(tmp_path))
    assert code == 0 and 'acme/rooms#3' in out


def test_silent_for_unrelated_short_or_slash_prompts(tmp_path):
    data = prepared(tmp_path)
    for stdin in (
        json.dumps({'prompt': 'write a haiku about autumn leaves falling gently in the park'}),
        json.dumps({'prompt': 'hi'}),
        json.dumps({'prompt': '/plugin install something interesting please'}),
        'not json at all',
        '',
        json.dumps(['list', 'not', 'dict']),
    ):
        code, out, _ = run_hook(stdin, data)
        assert code == 0 and out == ''


def test_silent_without_cache_and_spawns_nothing_fatal(tmp_path):
    code, out, _ = run_hook(json.dumps({'prompt': 'my apify standby actor answers 502 until the probe replies'}), tmp_path / 'empty')
    assert code == 0 and out == ''


def test_disabled_flag_file(tmp_path):
    data = prepared(tmp_path)
    (data / 'disabled').write_text('', encoding='utf-8')
    code, out, _ = run_hook(json.dumps({'prompt': 'my apify standby actor answers 502 until the probe replies'}), data)
    assert code == 0 and out == ''
