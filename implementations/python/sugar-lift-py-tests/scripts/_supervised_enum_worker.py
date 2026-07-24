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

    terminal = production_lift_testimony(Path(path), rel)
    return {"kind": "lift-result", "file": rel, "terminal": terminal}


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
        if kind == "lift":
            path = str(msg.get("path") or "")
            rel = str(msg.get("rel") or path)
            try:
                print(json.dumps(_lift(path, rel)), flush=True)
            except BaseException as error:  # noqa: BLE001 -- parent classifies
                # Untyped failure: emit then re-raise so bare-exception path
                # can also see nonzero exit if the supervisor cares.
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
                # Stay alive after bare exceptions so the supervisor can
                # continue the census without a restart (typed path already
                # stays alive). Native crashes never reach here.
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
