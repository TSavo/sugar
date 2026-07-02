from __future__ import annotations

import io
import json
import sys

from sugar_lift_py_tests import lift_rpc


def test_recv_distinguishes_garbage_from_eof(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("this is not json\n"))

    result = lift_rpc._recv()

    assert result is lift_rpc.PARSE_ERROR

    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert lift_rpc._recv() is None


def test_parse_error_replies_and_continues_to_next_message(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO('this is not json\n{"jsonrpc":"2.0","id":7,"method":"shutdown"}\n'),
    )

    lift_rpc.main(["--rpc"])

    replies = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert replies == [
        {
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": -32700,
                "message": "parse error: line was not a JSON-RPC object",
            },
        },
        {"jsonrpc": "2.0", "id": 7, "result": {"ok": True}},
    ]
