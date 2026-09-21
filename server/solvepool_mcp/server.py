'''Tool definitions and stdio entry point for the SolvePool MCP server (no third-party dependencies).'''

from __future__ import annotations

from typing import Any

from . import __version__
from .config import Settings
from .github import GitHub
from .mcp_stdio import Server, Tool
from .service import Service

INSTRUCTIONS = (
    'SolvePool: rooms of distilled, anonymized solutions stored as GitHub Issues. '
    'Search or list rooms before solving a recurring problem; read one with solvepool_get and say you reused it; '
    'share a new distilled solution with solvepool_share only after the user confirmed the anonymized draft.'
)

_STRING = {'type': 'string'}
_STRING_LIST = {'type': 'array', 'items': {'type': 'string'}}


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [v.strip() for v in value.splitlines() if v.strip()]
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


def build_tools(service: Service) -> list[Tool]:
    return [
        Tool(
            'solvepool_status',
            'Check SolvePool health: GitHub token, configured rooms repositories, cache age, rate limit, usage metrics.',
            {'type': 'object', 'properties': {}, 'additionalProperties': False},
            lambda a: service.status(),
        ),
        Tool(
            'solvepool_rooms',
            'List the most recently updated rooms (refreshes the local index). Optional repo as owner/repo.',
            {'type': 'object', 'properties': {'repo': _STRING, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}}},
            lambda a: service.rooms(a.get('repo') or None, _int(a.get('limit'), 20)),
        ),
        Tool(
            'solvepool_search',
            'Full-text search of rooms by problem description. Returns references to pass to solvepool_get.',
            {
                'type': 'object',
                'properties': {'query': _STRING, 'repo': _STRING, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 30}},
                'required': ['query'],
            },
            lambda a: service.search(str(a.get('query', '')), a.get('repo') or None, _int(a.get('limit'), 8)),
        ),
        Tool(
            'solvepool_get',
            'Read a room: the distilled solution and its latest discussion. room = "#12", "owner/repo#12" or the issue URL.',
            {
                'type': 'object',
                'properties': {'room': _STRING, 'comments': {'type': 'integer', 'minimum': 0, 'maximum': 50}},
                'required': ['room'],
            },
            lambda a: service.get(str(a.get('room', '')), _int(a.get('comments'), 10)),
        ),
        Tool(
            'solvepool_share',
            (
                'Open a new room (GitHub Issue) with an anonymized, reusable solution. Requires a GitHub token. '
                'title: the canonical problem in one sentence. problem: context and symptoms, depersonalized. '
                'solution: reusable steps with {{variables}} for what changes per person. variables: one entry per '
                '{{variable}} as "name — meaning · typical values". verification: how to check the result. '
                'example_prompts: anonymized prompts this room answers. tags: up to 5 short lowercase tags. '
                'Refuses text containing emails, keys, personal paths. Warns when a similar room exists unless force=true.'
            ),
            {
                'type': 'object',
                'properties': {
                    'title': _STRING,
                    'problem': _STRING,
                    'solution': _STRING,
                    'variables': _STRING_LIST,
                    'verification': _STRING,
                    'example_prompts': _STRING_LIST,
                    'tags': _STRING_LIST,
                    'repo': _STRING,
                    'force': {'type': 'boolean'},
                },
                'required': ['title', 'problem', 'solution'],
            },
            lambda a: service.share(
                str(a.get('title', '')),
                str(a.get('problem', '')),
                str(a.get('solution', '')),
                _str_list(a.get('variables')),
                str(a.get('verification') or ''),
                _str_list(a.get('example_prompts')),
                _str_list(a.get('tags')),
                a.get('repo') or None,
                bool(a.get('force', False)),
            ),
        ),
    ]


def build_server(service: Service | None = None) -> Server:
    if service is None:
        settings = Settings.load()
        settings.ensure_dirs()
        service = Service(settings, GitHub(settings.token))
    return Server('solvepool', __version__, build_tools(service), INSTRUCTIONS)


def main() -> None:
    build_server().serve_forever()
