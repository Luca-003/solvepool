'''FastMCP stdio server exposing the SolvePool tools.'''

from __future__ import annotations

from fastmcp import FastMCP

from .config import Settings
from .github import GitHub
from .service import Service

mcp = FastMCP(
    'solvepool',
    instructions=(
        'SolvePool: rooms of distilled, anonymized solutions stored as GitHub Issues. '
        'Search or list rooms before solving a recurring problem; read one with solvepool_get and say you reused it; '
        'share a new distilled solution with solvepool_share only after the user confirmed the anonymized draft.'
    ),
)

_service: Service | None = None


def service() -> Service:
    global _service
    if _service is None:
        settings = Settings.load()
        settings.ensure_dirs()
        _service = Service(settings, GitHub(settings.token))
    return _service


@mcp.tool()
def solvepool_status() -> str:
    '''Check SolvePool health: GitHub token, configured rooms repositories, cache age, rate limit, usage metrics.'''
    return service().status()


@mcp.tool()
def solvepool_rooms(repo: str | None = None, limit: int = 20) -> str:
    '''List the most recently updated rooms (refreshes the local index). Optional repo as owner/repo.'''
    return service().rooms(repo, limit)


@mcp.tool()
def solvepool_search(query: str, repo: str | None = None, limit: int = 8) -> str:
    '''Full-text search of rooms by problem description. Returns references to pass to solvepool_get.'''
    return service().search(query, repo, limit)


@mcp.tool()
def solvepool_get(room: str, comments: int = 10) -> str:
    '''Read a room: the distilled solution and its latest discussion. room = "#12", "owner/repo#12" or the issue URL.'''
    return service().get(room, comments)


@mcp.tool()
def solvepool_share(
    title: str,
    problem: str,
    solution: str,
    variables: list[str] | None = None,
    verification: str = '',
    example_prompts: list[str] | None = None,
    tags: list[str] | None = None,
    repo: str | None = None,
    force: bool = False,
) -> str:
    '''Open a new room (GitHub Issue) with an anonymized, reusable solution. Requires a GitHub token.

    title: the canonical problem in one sentence. problem: context and symptoms, depersonalized.
    solution: reusable steps with {{variables}} for what changes per person. variables: one entry per
    {{variable}} as "name — meaning · typical values". verification: how to check the result.
    example_prompts: anonymized prompts this room answers. tags: up to 5 short lowercase tags.
    Refuses text containing emails, keys, personal paths. Warns when a similar room exists unless force=true.
    '''
    return service().share(title, problem, solution, variables, verification, example_prompts, tags, repo, force)


def main() -> None:
    mcp.run(show_banner=False)  # stdio: anything on stderr shows up as an error in the host's logs
