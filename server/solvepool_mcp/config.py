'''Settings for SolvePool: repositories, data directory, token discovery.

Precedence, highest first: explicit arguments (the hook passes them), environment
variables, ``~/.solvepool/config.json``, built-in defaults. Placeholders that the
host did not expand (anything containing ``${``) count as unset, so the same
files work inside a Claude Code plugin and when run by hand.
'''

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_REPO = 'Luca-003/solvepool-rooms'
ROOM_LABEL = 'room'
INDEX_TTL_S = 600
MAX_CANDIDATES = 3
HOOK_BUDGET_S = 3.0

_REPO_RE = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')


def clean(value: str | None) -> str | None:
    '''Return a stripped value, or None for empty strings and unexpanded ``${...}`` placeholders.'''
    if value is None:
        return None
    text = value.strip()
    if not text or '${' in text:
        return None
    return text


def parse_repos(value: str | None) -> tuple[str, ...]:
    '''Split a comma-separated ``owner/repo`` list, dropping malformed entries.'''
    text = clean(value)
    if text is None:
        return ()
    seen: list[str] = []
    for raw in text.split(','):
        repo = raw.strip().strip('/')
        if repo.startswith('https://github.com/'):
            repo = repo[len('https://github.com/'):].strip('/')
        if _REPO_RE.match(repo) and repo not in seen:
            seen.append(repo)
    return tuple(seen)


def home_dir() -> Path:
    '''The user's home, or the current directory when the environment cannot tell (stripped env in hooks/CI).'''
    try:
        return Path.home()
    except (RuntimeError, KeyError):
        return Path.cwd()


def user_config_path() -> Path:
    return home_dir() / '.solvepool' / 'config.json'


def load_user_config() -> dict:
    try:
        data = json.loads(user_config_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def discover_token(gh_path: str | None = None) -> str | None:
    '''Find a GitHub token: GITHUB_TOKEN, GH_TOKEN, then ``gh auth token`` if gh is available.'''
    for name in ('GITHUB_TOKEN', 'GH_TOKEN'):
        token = clean(os.environ.get(name))
        if token:
            return token
    gh = gh_path or shutil.which('gh')
    if not gh:
        return None
    try:
        proc = subprocess.run(
            [gh, 'auth', 'token'],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return clean(proc.stdout) if proc.returncode == 0 else None


@dataclass(slots=True, frozen=True)
class Settings:
    repos: tuple[str, ...]
    data_dir: Path
    token: str | None
    index_ttl_s: int = INDEX_TTL_S
    disabled: bool = False

    @classmethod
    def load(
        cls,
        *,
        repos: str | None = None,
        data_dir: str | None = None,
        want_token: bool = True,
    ) -> 'Settings':
        user_cfg = load_user_config()

        repo_list = (
            parse_repos(repos)
            or parse_repos(os.environ.get('SOLVEPOOL_REPOS'))
            or parse_repos(os.environ.get('CLAUDE_PLUGIN_OPTION_ROOMS_REPOS'))  # plugin option, as Claude Code exports it to hooks
        )
        if not repo_list:
            cfg_repos = user_cfg.get('repos')
            if isinstance(cfg_repos, list):
                repo_list = parse_repos(','.join(str(r) for r in cfg_repos))
            elif isinstance(cfg_repos, str):
                repo_list = parse_repos(cfg_repos)
        if not repo_list:
            repo_list = (DEFAULT_REPO,)

        data_text = clean(data_dir) or clean(os.environ.get('SOLVEPOOL_DATA_DIR')) or clean(os.environ.get('CLAUDE_PLUGIN_DATA'))
        data_path = Path(data_text) if data_text else home_dir() / '.solvepool'

        ttl = INDEX_TTL_S
        cfg_ttl = user_cfg.get('index_ttl_s')
        if isinstance(cfg_ttl, int) and cfg_ttl > 0:
            ttl = cfg_ttl

        disabled = clean(os.environ.get('SOLVEPOOL_DISABLE')) is not None or (data_path / 'disabled').exists()

        token = None
        if want_token:
            gh_path = user_cfg.get('gh_path') if isinstance(user_cfg.get('gh_path'), str) else None
            token = discover_token(gh_path)

        return cls(repos=repo_list, data_dir=data_path, token=token, index_ttl_s=ttl, disabled=disabled)

    def ensure_dirs(self) -> None:
        (self.data_dir / 'index').mkdir(parents=True, exist_ok=True)
