#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""
Echo IR compiler: reference Sugar IR compiler plugin.

Demonstrates the JSON-RPC over stdio protocol defined in
protocol/specs/2026-04-30-ir-compiler-protocol.md.

Reads one JSON-RPC request per stdin line, writes one response per
stdout line. Implements `sugar.ir.handshake`, `sugar.ir.compile`,
`sugar.ir.shutdown` for a hypothetical "echo" dialect that just
stringifies the IR-JSON.

Conformance check:
    echo '{"jsonrpc":"2.0","id":1,"method":"sugar.ir.handshake","params":{}}' \\
      | python3 echo_compiler.py
"""
import json
import sys

NAME = "echo-compiler"
VERSION = "0.1.0"
PROTOCOL_VERSION = "sugar-ir-compiler/1"
DIALECT = "echo"


def handshake(_params):
    return {
        "name": NAME,
        "version": VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "dialects": [DIALECT],
        "supported_sorts": ["Int", "Bool", "Real", "String"],
        "supported_predicates": [
            "=", "distinct", "<", "<=", ">", ">=",
            "and", "or", "not", "implies", "forall", "exists",
        ],
    }


def compile_(params):
    dialect = params.get("target_dialect", "")
    if dialect != DIALECT:
        return ("error", 2000, "compile_error.unsupported_dialect", dialect)
    ir = params.get("ir_json")
    if ir is None:
        return ("error", -32602, "missing param: ir_json", None)
    body_str = json.dumps(ir, sort_keys=True, separators=(",", ":"))
    return ("ok", {
        "preamble": "; echo-compiler preamble\n",
        "body": f"ECHO {body_str}\n",
        "free_vars": [],
    })


def shutdown(_params):
    return ("ok", {})


def respond(rid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": rid}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            respond(None, error={"code": -32700, "message": f"parse error: {e}"})
            continue
        rid = req.get("id")
        method = req.get("method", "")
        params = req.get("params") or {}
        if method == "sugar.ir.handshake":
            respond(rid, result=handshake(params))
        elif method == "sugar.ir.compile":
            r = compile_(params)
            if r[0] == "ok":
                respond(rid, result=r[1])
            else:
                _, code, message, data = r
                err = {"code": code, "message": message}
                if data is not None:
                    err["data"] = data
                respond(rid, error=err)
        elif method == "sugar.ir.shutdown":
            respond(rid, result={})
            return
        else:
            respond(rid, error={"code": -32601, "message": f"method not found: {method}"})


if __name__ == "__main__":
    main()
