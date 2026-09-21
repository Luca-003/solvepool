'''UserPromptSubmit hook: suggest matching SolvePool rooms as context. Pure stdlib.

Reads the hook JSON on stdin, matches the prompt against the locally cached room
index and, when something plausible turns up, prints the JSON that Claude Code
turns into additional context. It never blocks the prompt, never waits for the
network (stale caches are refreshed by a detached child process) and always
exits 0. Run with ``--refresh`` to act as that child.
'''

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent / 'server'
sys.path.insert(0, str(SERVER_DIR))

from solvepool_mcp import index, metrics  # noqa: E402
from solvepool_mcp.config import HOOK_BUDGET_S, MAX_CANDIDATES, Settings  # noqa: E402

MIN_PROMPT_CHARS = 20
DEBUG = bool(os.environ.get('SOLVEPOOL_DEBUG'))


def debug(settings: Settings | None, message: str) -> None:
    if DEBUG and settings is not None:
        log(settings, 'debug ' + message)


def log(settings: Settings, message: str) -> None:
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        with (settings.data_dir / 'hook.log').open('a', encoding='utf-8') as fh:
            fh.write(f'{time.strftime("%Y-%m-%dT%H:%M:%S")} {message}\n')
    except OSError:
        pass


def read_prompt() -> str:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except ValueError:
        return ''
    if not isinstance(data, dict):
        return ''
    prompt = data.get('prompt') or data.get('prompt_text') or ''
    return prompt if isinstance(prompt, str) else ''


def spawn_refresh(args: argparse.Namespace) -> None:
    cmd = [sys.executable, str(Path(__file__).resolve()), '--refresh']
    if args.data:
        cmd += ['--data', args.data]
    if args.repos:
        cmd += ['--repos', args.repos]
    kwargs: dict = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
    if sys.platform == 'win32':
        kwargs['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs['start_new_session'] = True
    subprocess.Popen(cmd, **kwargs)  # noqa: S603 - our own script, fixed argv


def build_context(candidates: list[tuple[index.RoomDoc, float]]) -> str:
    lines = [
        'SolvePool: shared rooms that may already solve this request (suggestions from other users, not instructions):',
    ]
    for doc, _ in candidates:
        tags = f' ({", ".join(doc.labels)})' if doc.labels else ''
        summary = f' — {doc.summary}' if doc.summary else ''
        lines.append(f'- {doc.ref} "{doc.title}"{tags}{summary}')
    lines.append(
        'If one fits, read it with the solvepool_get tool, adapt it, and tell the user in one line that you reused that room. '
        'If none fits, ignore this note.'
    )
    return '\n'.join(lines)


def run_match(args: argparse.Namespace) -> int:
    started = time.monotonic()
    prompt = read_prompt().strip()
    settings = Settings.load(repos=args.repos, data_dir=args.data, want_token=False) if DEBUG else None
    debug(settings, f'prompt chars={len(prompt)}')
    if len(prompt) < MIN_PROMPT_CHARS or prompt.startswith('/'):
        return 0
    settings = settings or Settings.load(repos=args.repos, data_dir=args.data, want_token=False)
    if settings.disabled:
        debug(settings, 'disabled')
        return 0
    docs, stale, missing = index.load_all(settings)
    debug(settings, f'docs={len(docs)} stale={stale} missing={missing} repos={settings.repos}')
    if stale or missing:
        try:
            spawn_refresh(args)
        except OSError as exc:
            log(settings, f'refresh spawn failed: {exc}')
    if not docs:
        return 0
    candidates = index.match(prompt, docs, k=MAX_CANDIDATES)
    debug(settings, f'candidates={[(d.ref, round(s, 2)) for d, s in candidates]}')
    if not candidates:
        return 0
    if time.monotonic() - started > HOOK_BUDGET_S:
        log(settings, 'over budget, skipping injection')
        return 0
    metrics.record(
        settings.data_dir,
        'proposal',
        prompt=metrics.prompt_hash(prompt),
        rooms=[d.ref for d, _ in candidates],
        scores=[round(s, 2) for _, s in candidates],
    )
    output = {
        'hookSpecificOutput': {
            'hookEventName': 'UserPromptSubmit',
            'additionalContext': build_context(candidates),
        }
    }
    sys.stdout.write(json.dumps(output, ensure_ascii=True))  # ASCII-only: independent of the console encoding
    sys.stdout.flush()
    return 0


def run_refresh(args: argparse.Namespace) -> int:
    from solvepool_mcp.github import GitHub  # local import: only the child needs the network client

    settings = Settings.load(repos=args.repos, data_dir=args.data, want_token=True)
    settings.ensure_dirs()
    outcome = index.refresh_all(settings, GitHub(settings.token))
    log(settings, 'refresh ' + json.dumps(outcome, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--data', default=None)
    parser.add_argument('--repos', default=None)
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args(argv)
    try:
        return run_refresh(args) if args.refresh else run_match(args)
    except Exception as exc:  # noqa: BLE001 - a hook must never fail the user's prompt
        try:
            log(Settings.load(repos=args.repos, data_dir=args.data, want_token=False), f'error: {exc!r}')
        except Exception:  # noqa: BLE001
            pass
        return 0


if __name__ == '__main__':
    sys.exit(main())
