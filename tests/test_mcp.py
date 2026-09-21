'''The stdio MCP layer, driven end-to-end with in-memory pipes and the fake GitHub transport.'''

from __future__ import annotations

import io
import json

from conftest import REPO
from solvepool_mcp.server import build_server
from solvepool_mcp.service import Service


def talk(server, messages: list[dict]) -> list[dict]:
    stdin = io.BytesIO(''.join(json.dumps(m) + '\n' for m in messages).encode('utf-8'))
    stdout = io.BytesIO()
    server.serve_forever(stdin=stdin, stdout=stdout)
    return [json.loads(line) for line in stdout.getvalue().decode('ascii').splitlines() if line]


def test_handshake_list_and_call(settings, github):
    server = build_server(Service(settings, github))
    out = talk(server, [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '0'}}},
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
        {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'solvepool_search', 'arguments': {'query': 'apify readiness probe'}}},
        {'jsonrpc': '2.0', 'id': 4, 'method': 'ping'},
    ])
    assert [m['id'] for m in out] == [1, 2, 3, 4]
    init = out[0]['result']
    assert init['protocolVersion'] == '2025-03-26' and init['serverInfo']['name'] == 'solvepool' and 'tools' in init['capabilities']
    names = [t['name'] for t in out[1]['result']['tools']]
    assert names == ['solvepool_status', 'solvepool_rooms', 'solvepool_search', 'solvepool_get', 'solvepool_share']
    assert all('inputSchema' in t and t['inputSchema']['type'] == 'object' for t in out[1]['result']['tools'])
    call = out[2]['result']
    assert call['isError'] is False and f'{REPO}#1' in call['content'][0]['text']
    assert out[3]['result'] == {}


def test_errors_are_jsonrpc_not_crashes(settings, github):
    server = build_server(Service(settings, github))
    out = talk(server, [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'nope'},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'missing', 'arguments': {}}},
        {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'solvepool_get', 'arguments': {'room': 'twelve'}}},
    ])
    assert out[0]['error']['code'] == -32601
    assert out[1]['result']['isError'] is True
    assert 'unrecognized room reference' in out[2]['result']['content'][0]['text']


def test_parse_error_and_blank_lines(settings, github):
    server = build_server(Service(settings, github))
    stdin = io.BytesIO(b'\n{not json}\n{"jsonrpc":"2.0","id":9,"method":"ping"}\n')
    stdout = io.BytesIO()
    server.serve_forever(stdin=stdin, stdout=stdout)
    lines = [json.loads(l) for l in stdout.getvalue().decode('ascii').splitlines()]
    assert lines[0]['error']['code'] == -32700 and lines[1]['id'] == 9


def test_output_is_ascii_only(settings, github):
    server = build_server(Service(settings, github))
    out_raw = io.BytesIO()
    server.serve_forever(io.BytesIO(b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"solvepool_get","arguments":{"room":"#2"}}}\n'), out_raw)
    raw = out_raw.getvalue()
    assert raw.decode('ascii') and b'\\u' in raw  # non-ASCII content (Italian text) is escaped, never raw
