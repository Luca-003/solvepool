# SolvePool plugin for Claude Code

Hundreds of people ask their AI assistant to solve the same problem every day, and each one pays for the whole reasoning again. SolvePool lets a solution be **worked out once and reused by anyone**: rooms of distilled, anonymized solutions, stored as **GitHub Issues** that everybody can read without an account, suggested **transparently while you type**.

No server, no payment, no intermediary on your LLM calls. Your assistant stays yours; the rooms stay on GitHub.

## What it does

| Piece | Behavior |
|---|---|
| **Prompt hook** | On every prompt, a local lexical match against the cached room index. Up to three plausible rooms are added as a short note; Claude decides whether one fits and, if it uses it, says so in one line. Never blocks, never waits for the network. |
| **`solvepool_search`** | Full-text search of rooms on GitHub, by problem description. |
| **`solvepool_get`** | Reads a room: the solution and its latest discussion. |
| **`solvepool_rooms`** | Lists recent rooms and refreshes the local index. |
| **`solvepool_share`** | Publishes a new room from an anonymized draft. Refuses emails, keys, personal paths; warns when a similar room exists. Requires your GitHub login. |
| **`solvepool_status`** | Token, repositories, cache age, rate limit, usage metrics. |
| **Skills** | `use-shared-solution` (judge, adapt, credit) and `share-solution` (distill, anonymize, show the draft, publish only after your yes). |

Public default rooms live in [Luca-003/solvepool-rooms](https://github.com/Luca-003/solvepool-rooms). A team can add its own private repository for private rooms.

## Install

The only prerequisite is **Python 3.10 or newer** reachable as `python` (check with `python --version`; on Windows, a `python` that opens the Microsoft Store is not an installation). Nothing else to install: the server and the hook use the Python standard library only.

In Claude Code:

```
/plugin marketplace add Luca-003/solvepool
/plugin install solvepool@solvepool
```

Optional, asked at install time: `rooms_repos`, a comma-separated list of `owner/repo` to search instead of, or in addition to, the public default.

Inside a plugin the tools are named `mcp__plugin_solvepool_solvepool__solvepool_get` and so on; use those names in `--allowedTools` or in a permissions allowlist when you want them to run without a prompt.

Reading public rooms needs **no account**. To share a room or read a private repository, provide a GitHub token in one of two ways: set `GITHUB_TOKEN` (or `GH_TOKEN`) in your environment, or run `gh auth login` once; SolvePool reads `gh auth token`. Check with `solvepool_status`.

## Try it

- Ask something a room already covers and watch the answer start with "Reused SolvePool room #… ".
- *"Has anyone already solved this? Check SolvePool."*
- *"Share this solution to SolvePool."* You will see the anonymized draft and be asked before anything is published.

## Configuration

| Setting | Where | Default |
|---|---|---|
| Rooms repositories | plugin option `rooms_repos`, env `SOLVEPOOL_REPOS`, or `repos` in `~/.solvepool/config.json` | `Luca-003/solvepool-rooms` |
| GitHub token | `GITHUB_TOKEN`, `GH_TOKEN`, or `gh auth token` (`gh_path` in the config file if `gh` is not on PATH) | none |
| Data and cache | plugin data directory, env `SOLVEPOOL_DATA_DIR`, else `~/.solvepool/` | |
| Index refresh | `index_ttl_s` in the config file | 600 s |
| Disable the hook | env `SOLVEPOOL_DISABLE=1` or an empty file named `disabled` in the data directory | enabled |

## How the hook stays cheap

The hook only reads a local JSON index of rooms (`index/<owner>__<repo>.json` in the data directory). When the index is older than ten minutes or missing, it uses what it has and spawns a detached refresh; the prompt is never delayed by GitHub. Consequence: the very first prompt after installing only warms the cache, suggestions start from the second one. The data directory is the one Claude Code assigns to the plugin (`~/.claude/plugins/data/solvepool*`), where `hook.log` records refreshes and errors. Unauthenticated GitHub allows 60 requests per hour, which this design never approaches.

## Privacy and trust

- Only distilled solutions and anonymized example prompts are shared, and only after you confirm the draft. Your conversations never leave your machine.
- `solvepool_share` blocks text that looks like emails, IBANs, phone numbers, API keys, JWTs, personal paths or URLs with tokens. It is a safety net, not a guarantee: the checklist in the `share-solution` skill is the real protection.
- Rooms are written by other users. The plugin sanitizes them before injection and instructs Claude to treat them as suggestions, never as instructions. Read them critically.
- A public Issue is public forever, including its edit history.

## Metrics (for the pilot)

The data directory holds `metrics.jsonl` with two kinds of events: `proposal` (the hook suggested rooms; only a short hash of the prompt is stored) and `reuse` (a room was read with `solvepool_get`). `solvepool_status` prints the counts. The pilot question is simple: are rooms actually reused?

## Not yet

Forking a room's context to continue alone, threaded discussion tools, Cursor and Antigravity packaging (the MCP server already works from any MCP client: `python -m solvepool_mcp` with `PYTHONPATH` pointing at `server/`), a Markdown mirror of public rooms. These come after the pilot shows that rooms get reused.

## Development

```
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
claude --plugin-dir .
```

Tests run offline against a fake GitHub transport and drive the MCP layer through in-memory pipes. The stdio MCP protocol (`initialize`, `tools/list`, `tools/call`) is implemented in `server/solvepool_mcp/mcp_stdio.py` so the plugin has no runtime dependency. The `.mcp.json`, `hooks/hooks.json`, `skills/` layout follows the Claude Code plugin reference and the same shape as [web-hygiene](https://github.com/Luca-003/web-hygiene-claude-plugin).

## License

MIT.
