from __future__ import annotations

import io
import json
import re
import sys

from sugar_lift_py_tests import lift_rpc

# serde_json rejects unpaired UTF-16 surrogates with this exact diagnostic
# (reproduced in #4155: "unexpected end of hex escape at line 1 column N").
_LONE_SURROGATE_ESCAPE = re.compile(
    r"\\u[dD][89aAbB][0-9a-fA-F]{2}(?!\\u[dD][c-fC-F][0-9a-fA-F]{2})"
)


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


def test_bare_python_dumps_emits_lone_surrogate_escape_that_breaks_serde():
    """Instrument: unsanitized dumps is the #4155 poison the scrub removes."""
    bare = json.dumps({"value": "\ud83d"}, separators=(",", ":"))
    assert bare == '{"value":"\\ud83d"}'
    assert _LONE_SURROGATE_ESCAPE.search(bare) is not None


def test_send_scrubs_lone_surrogates_for_serde_json(capsys):
    """#4155: RPC stdout must not carry unpaired \\udxxx that kill serde_json.

    Python json.dumps emits lone surrogates as \\ud83d; the Rust lift client
    then fails the whole response with 'unexpected end of hex escape'. The
    wall never writes report.json/summary.json. Scrub at _send.
    """
    lone = "\ud83d"  # high surrogate alone (pandas unicode_surrogate tests)
    lift_rpc._send(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "kind": "ir-document",
                "value": lone,
                "nested": {"text": f"pre{lone}post"},
                "list": [lone],
            },
        }
    )
    line = capsys.readouterr().out.strip()
    assert _LONE_SURROGATE_ESCAPE.search(line) is None, line[:200]
    parsed = json.loads(line)
    assert parsed["result"]["value"] == "\ufffd"
    assert parsed["result"]["nested"]["text"] == "pre\ufffdpost"
    assert parsed["result"]["list"] == ["\ufffd"]
