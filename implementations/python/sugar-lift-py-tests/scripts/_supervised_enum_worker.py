#!/usr/bin/env python3
"""Persistent enumeration worker for supervised floor scans.

Protocol (newline-delimited JSON on stdin/stdout):

  parent → worker:  {"kind":"lift","path":"<abs>","rel":"<rel>"}
  worker → parent:  {"kind":"lift-result","file":"<rel>","terminal":{...}}
                    or {"kind":"lift-error","file":"<rel>","error_type":"...","message":"..."}

  parent → worker:  {"kind":"ping"}
  worker → parent:  {"kind":"pong"}

  parent → worker:  {"kind":"shutdown"}
  worker exits 0

Enumeration door only: path_source → SourceFile → functions → sugar.
Never restores package preconstruction. Process stays warm across files
so oracle/module caches survive until the supervisor restarts us.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_CORPUS_ROOT: Path | None = None
_CONSTRUCTION_CONTEXT = None


def _bootstrap() -> str | None:
    scripts = Path(__file__).resolve().parent
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        from _production_lift_child import production_lift_bootstrap_error

        return production_lift_bootstrap_error()
    except Exception as error:  # noqa: BLE001
        return f"{type(error).__name__}: {error}"


def _lift(path: str, rel: str) -> dict:
    import os

    # Test-only plants (parent env, never production):
    #   SUGAR_SUPERVISOR_PLANT_BARE=<rel>     → untyped RuntimeError
    #   SUGAR_SUPERVISOR_PLANT_TIMEOUT=<rel>  → hang until supervisor kills us
    plant_bare = os.environ.get("SUGAR_SUPERVISOR_PLANT_BARE")
    if plant_bare and plant_bare == rel:
        raise RuntimeError("planted bare exception for supervisor test")
    plant_timeout = os.environ.get("SUGAR_SUPERVISOR_PLANT_TIMEOUT")
    if plant_timeout and plant_timeout == rel:
        import time

        time.sleep(3600)

    from _production_lift_child import production_lift_testimony

    if _CORPUS_ROOT is None or _CONSTRUCTION_CONTEXT is None:
        return {
            "kind": "lift-refusal",
            "file": rel,
            "coordinate": "supervised-enum-worker.construction-context",
            "reason": "authenticated frozen construction context was not initialized",
        }
    terminal = production_lift_testimony(
        Path(path),
        rel,
        corpus_root=_CORPUS_ROOT,
        construction_context=_CONSTRUCTION_CONTEXT,
    )
    return {"kind": "lift-result", "file": rel, "terminal": terminal}


def _initialize(
    corpus_root: str,
    demand_table_path: str | None,
    *,
    allow_local_demand_derivation: bool,
) -> dict:
    global _CONSTRUCTION_CONTEXT, _CORPUS_ROOT
    if _CONSTRUCTION_CONTEXT is not None:
        return {
            "kind": "initialize-refusal",
            "coordinate": "supervised-enum-worker.construction-context",
            "reason": "frozen construction context was already initialized",
        }
    from sugar_lift_py_tests.lift_rpc import (
        provisional_contract_refs_from_demand_rows,
        tree_construction_context_for_workspace,
    )

    root = Path(corpus_root).resolve()
    contract_refs = None
    demand_table_identity = None
    if demand_table_path:
        from sugar_lift_py_tests.no_call_body_attribution import (
            SHARED_DEMAND_TABLE_CONTENT_KEY,
            validate_shared_demand_table,
        )

        payload = validate_shared_demand_table(
            json.loads(Path(demand_table_path).read_text(encoding="utf-8")),
            expected_content_key=SHARED_DEMAND_TABLE_CONTENT_KEY,
        )
        contract_refs = provisional_contract_refs_from_demand_rows(payload["rows"])
        demand_table_identity = SHARED_DEMAND_TABLE_CONTENT_KEY
    elif not allow_local_demand_derivation:
        raise RuntimeError(
            "supervised-enum-worker.shared-demand-table: authenticated demand "
            "table testimony is absent"
        )
    _CORPUS_ROOT = root
    _CONSTRUCTION_CONTEXT = tree_construction_context_for_workspace(
        root, contract_refs=contract_refs
    )
    return {
        "kind": "context-ready",
        "corpus_root": str(root),
        "demand_table_identity": demand_table_identity,
    }


def main() -> int:
    err = _bootstrap()
    if err is not None:
        print(
            json.dumps(
                {
                    "kind": "bootstrap-error",
                    "message": err,
                }
            ),
            flush=True,
        )
        return 2
    print(json.dumps({"kind": "ready"}), flush=True)
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as error:
            print(
                json.dumps(
                    {
                        "kind": "protocol-error",
                        "message": f"invalid json: {error}",
                    }
                ),
                flush=True,
            )
            continue
        kind = msg.get("kind")
        if kind == "shutdown":
            return 0
        if kind == "ping":
            print(json.dumps({"kind": "pong"}), flush=True)
            continue
        if kind == "initialize":
            try:
                response = _initialize(
                    str(msg.get("corpus_root") or ""),
                    (
                        str(msg["demand_table_path"])
                        if msg.get("demand_table_path")
                        else None
                    ),
                    allow_local_demand_derivation=bool(
                        msg.get("allow_local_demand_derivation", False)
                    ),
                )
            except Exception as error:
                response = {
                    "kind": "initialize-refusal",
                    "coordinate": "supervised-enum-worker.construction-context",
                    "reason": f"{type(error).__name__}: {error}",
                }
            print(json.dumps(response), flush=True)
            continue
        if kind == "lift":
            path = str(msg.get("path") or "")
            rel = str(msg.get("rel") or path)
            try:
                print(json.dumps(_lift(path, rel)), flush=True)
            except Exception as error:
                # Bare Python failures only. ConstructionPanic is BaseException:
                # it is not caught here — the worker dies; the supervisor records
                # the active file and restarts a fresh worker.
                print(
                    json.dumps(
                        {
                            "kind": "lift-error",
                            "file": rel,
                            "error_type": type(error).__name__,
                            "message": str(error)[-4000:],
                        }
                    ),
                    flush=True,
                )
            continue
        print(
            json.dumps(
                {
                    "kind": "protocol-error",
                    "message": f"unknown kind {kind!r}",
                }
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
