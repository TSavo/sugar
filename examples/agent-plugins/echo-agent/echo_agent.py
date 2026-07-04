#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""
Echo agent: reference Sugar agent plugin.

Demonstrates the JSON-RPC over stdio protocol defined by
protocol/specs/2026-04-30-agent-plugin-protocol.md.

Reads one JSON-RPC request per stdin line, writes one response per
stdout line. Covers handshake / lift / must / fix with canned responses
matching the kit's IR-JSON shape.

Conformance test:
    echo '{"jsonrpc":"2.0","id":1,"method":"sugar.agent.handshake","params":{}}' \
      | python3 echo_agent.py
"""
import json
import sys

NAME = "echo-agent"
VERSION = "0.1.0"
PROTOCOL_VERSION = "pep/1.7.0"

# Canonical IR-JSON for `out >= 0`, used as the safe fallback contract.
NONNEG_POST = (
    '{"kind":"atomic","name":">=","args":['
    '{"kind":"var","name":"out"},'
    '{"kind":"const","value":0,"sort":{"kind":"primitive","name":"Int"}}'
    "]}"
)

# Canonical IR-JSON for "forall txn. sumDebits(txn) == sumCredits(txn)".
DOUBLELEDGER_INV = (
    '{"kind":"forall","name":"txn",'
    '"sort":{"kind":"primitive","name":"Int"},'
    '"body":{"kind":"atomic","name":"=","args":['
    '{"kind":"ctor","name":"sumDebits","args":[{"kind":"var","name":"txn"}]},'
    '{"kind":"ctor","name":"sumCredits","args":[{"kind":"var","name":"txn"}]}'
    "]}}"
)


def provenance(confidence=0.5, rationale=None):
    return {
        "agent_name": NAME,
        "agent_version": VERSION,
        "model": None,
        "confidence": confidence,
        "rationale": rationale or "canned echo-agent response",
    }


def safe_post_candidate(name="echo_safe"):
    return {
        "name": name,
        "post": NONNEG_POST,
        "out_binding": "out",
        "provenance": provenance(),
    }


def doubleledger_candidate():
    return {
        "name": "doubleledger_conservation",
        "inv": DOUBLELEDGER_INV,
        "out_binding": "out",
        "provenance": provenance(0.95, "double-entry conservation invariant"),
    }


def handle_handshake(_params):
    return {
        "name": NAME,
        "version": VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "capabilities": ["lift", "must", "fix"],
    }


def handle_must(params):
    desc = (params.get("description") or "").lower()
    if any(k in desc for k in ("not lose money", "conservation", "double-entry")):
        return doubleledger_candidate()
    return safe_post_candidate()


def handle_lift(params):
    src = (params.get("source_path") or "").lower()
    out = []
    if "ledger" in src or "doubleledger" in src:
        out.append(doubleledger_candidate())
    out.append(safe_post_candidate())
    return out


def handle_fix(params):
    return {
        "patches": [],
        "new_contracts": [safe_post_candidate("echo_fix")],
        "commentary": "echo-agent: canned no-op fix; refine in a real plugin.",
    }


METHODS = {
    "sugar.agent.handshake": handle_handshake,
    "sugar.must.translate":  handle_must,
    "sugar.lift.propose":    handle_lift,
    "sugar.fix.patch":       handle_fix,
}


def make_response(req_id, result=None, error=None):
    resp = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        resp["error"] = error
    else:
        resp["result"] = result
    return resp


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            sys.stdout.write(json.dumps(make_response(
                None, error={"code": -32700, "message": f"parse error: {e}"}
            )) + "\n")
            sys.stdout.flush()
            continue

        rid = req.get("id")
        method = req.get("method", "")
        if method == "sugar.shutdown":
            sys.stdout.write(json.dumps(make_response(rid, result={"ok": True})) + "\n")
            sys.stdout.flush()
            return
        handler = METHODS.get(method)
        if handler is None:
            err = {"code": -32601, "message": f"method not found: {method}"}
            sys.stdout.write(json.dumps(make_response(rid, error=err)) + "\n")
            sys.stdout.flush()
            continue
        try:
            result = handler(req.get("params") or {})
            sys.stdout.write(json.dumps(make_response(rid, result=result)) + "\n")
        except Exception as e:
            err = {"code": -32603, "message": f"internal error: {e}"}
            sys.stdout.write(json.dumps(make_response(rid, error=err)) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
