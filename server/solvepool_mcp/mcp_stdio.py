'''Minimal MCP server over stdio in pure stdlib: newline-delimited JSON-RPC 2.0.

Implements exactly what a tools-only server needs: ``initialize``,
``notifications/initialized``, ``ping``, ``tools/list`` and ``tools/call``.
Keeping this in the standard library means the plugin installs with no
``pip install`` step; the protocol surface is small and stable enough for that.
'''

from __future__ import annotations

import json
import os
import sys
import traceback
from dataclasses import dataclass
from typing import Any, Callable

DEFAULT_PROTOCOL = '2025-06-18'

Handler = Callable[[dict[str, Any]], str]


@dataclass(slots=True, frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Handler

    def descriptor(self) -> dict[str, Any]:
        return {'name': self.name, 'description': self.description, 'inputSchema': self.input_schema}


class Server:
    def __init__(self, name: str, version: str, tools: list[Tool], instructions: str = '') -> None:
        self.name = name
        self.version = version
        self.tools = {t.name: t for t in tools}
        self.instructions = instructions
        self.debug = bool(os.environ.get('SOLVEPOOL_DEBUG'))

    # ----- dispatch -----------------------------------------------------------

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        '''Return the response for a request, or None for notifications.'''
        method = message.get('method')
        msg_id = message.get('id')
        params = message.get('params') or {}
        if method is None:
            return None
        if msg_id is None:
            return None  # notification: nothing to answer
        try:
            if method == 'initialize':
                result = {
                    'protocolVersion': params.get('protocolVersion') or DEFAULT_PROTOCOL,
                    'capabilities': {'tools': {'listChanged': False}},
                    'serverInfo': {'name': self.name, 'version': self.version},
                }
                if self.instructions:
                    result['instructions'] = self.instructions
                return self._ok(msg_id, result)
            if method == 'ping':
                return self._ok(msg_id, {})
            if method == 'tools/list':
                return self._ok(msg_id, {'tools': [t.descriptor() for t in self.tools.values()]})
            if method == 'tools/call':
                return self._ok(msg_id, self._call(params))
            return self._error(msg_id, -32601, f'method not found: {method}')
        except Exception as exc:  # noqa: BLE001 - never let one request kill the server
            if self.debug:
                traceback.print_exc(file=sys.stderr)
            return self._error(msg_id, -32603, f'internal error: {exc!r}')

    def _call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get('name', '')
        tool = self.tools.get(name)
        if tool is None:
            return {'content': [{'type': 'text', 'text': f'unknown tool: {name}'}], 'isError': True}
        arguments = params.get('arguments') or {}
        if not isinstance(arguments, dict):
            return {'content': [{'type': 'text', 'text': 'arguments must be an object'}], 'isError': True}
        try:
            text = tool.handler(arguments)
        except TypeError as exc:
            return {'content': [{'type': 'text', 'text': f'bad arguments for {name}: {exc}'}], 'isError': True}
        except Exception as exc:  # noqa: BLE001 - report tool failures to the model, keep serving
            if self.debug:
                traceback.print_exc(file=sys.stderr)
            return {'content': [{'type': 'text', 'text': f'{name} failed: {exc!r}'}], 'isError': True}
        return {'content': [{'type': 'text', 'text': text}], 'isError': False}

    @staticmethod
    def _ok(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {'jsonrpc': '2.0', 'id': msg_id, 'result': result}

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
        return {'jsonrpc': '2.0', 'id': msg_id, 'error': {'code': code, 'message': message}}

    # ----- transport ----------------------------------------------------------

    def serve_forever(self, stdin=None, stdout=None) -> None:
        '''Read one JSON message per line, write one JSON response per line. Returns on EOF.'''
        inp = stdin if stdin is not None else sys.stdin.buffer
        out = stdout if stdout is not None else sys.stdout.buffer
        for raw in inp:
            line = raw.strip()
            if not line:
                continue
            try:
                message = json.loads(line.decode('utf-8'))
            except (ValueError, UnicodeDecodeError):
                self._write(out, self._error(None, -32700, 'parse error'))
                continue
            if isinstance(message, list):  # batch
                responses = [r for r in (self.handle(m) for m in message if isinstance(m, dict)) if r is not None]
                if responses:
                    self._write(out, responses)
                continue
            if not isinstance(message, dict):
                continue
            response = self.handle(message)
            if response is not None:
                self._write(out, response)

    @staticmethod
    def _write(out, payload: Any) -> None:
        out.write(json.dumps(payload, ensure_ascii=True).encode('ascii') + b'\n')
        out.flush()
