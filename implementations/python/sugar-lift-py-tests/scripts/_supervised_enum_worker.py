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
_SOURCE_WORKSPACE_ROOT: Path | None = None
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

        time.sleep(30)

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
        source_workspace_root=_SOURCE_WORKSPACE_ROOT,
    )
    return {"kind": "lift-result", "file": rel, "terminal": terminal}


def _progress(phase: str, **fields: object) -> None:
    """Heartbeat so the supervisor can name a hung initialize phase."""
    payload: dict[str, object] = {
        "kind": "initialize-progress",
        "phase": phase,
        "coordinate": "supervised-enum-worker.construction-context",
    }
    payload.update(fields)
    print(json.dumps(payload), flush=True)


def _initialize(
    corpus_root: str,
    *,
    source_workspace_root: str | None = None,
) -> dict:
    """Freeze the worker's construction context on the workspace root.

    The context names the root and holds no table (#7757)."""
    global _CONSTRUCTION_CONTEXT, _CORPUS_ROOT, _SOURCE_WORKSPACE_ROOT
    import os

    # Test-only plant: hang after first progress so supervisor timeout names phase.
    if os.environ.get("SUGAR_SUPERVISOR_PLANT_INIT_HANG") == "1":
        _progress(
            "planted-init-hang",
            corpus_root=corpus_root or None,
            note="SUGAR_SUPERVISOR_PLANT_INIT_HANG",
        )
        import time

        time.sleep(30)
    if _CONSTRUCTION_CONTEXT is not None:
        return {
            "kind": "initialize-refusal",
            "coordinate": "supervised-enum-worker.construction-context",
            "reason": "frozen construction context was already initialized",
            "corpus_root": corpus_root or None,
            "phase": "already-initialized",
        }
    from sugar_lift_py_tests.lift_rpc import tree_construction_context_for_workspace

    if not corpus_root:
        return {
            "kind": "initialize-refusal",
            "coordinate": "supervised-enum-worker.construction-context",
            "reason": (
                "corpus_root is empty; cannot build TreeConstructionContext "
                "without a named population root"
            ),
            "corpus_root": None,
            "phase": "resolve-corpus-root",
        }

    root = Path(corpus_root).resolve()
    workspace_root = Path(source_workspace_root or corpus_root).resolve()
    if root != workspace_root and workspace_root not in root.parents:
        return {
            "kind": "initialize-refusal",
            "coordinate": "supervised-enum-worker.construction-context",
            "reason": (
                f"source_workspace_root does not contain corpus_root: "
                f"source_workspace_root={workspace_root} corpus_root={root}"
            ),
            "corpus_root": str(root),
            "source_workspace_root": str(workspace_root),
            "phase": "resolve-corpus-root",
        }
    _progress(
        "resolve-corpus-root",
        corpus_root=str(root),
        root_exists=root.exists(),
        root_is_dir=root.is_dir(),
    )
    if not root.exists():
        return {
            "kind": "initialize-refusal",
            "coordinate": "supervised-enum-worker.construction-context",
            "reason": (
                f"corpus_root does not exist: {root} "
                "(nothing to derive demands or freeze construction context against)"
            ),
            "corpus_root": str(root),
            "phase": "resolve-corpus-root",
        }

    _progress("freeze-construction-context", corpus_root=str(root))
    _CORPUS_ROOT = root
    _SOURCE_WORKSPACE_ROOT = workspace_root
    _CONSTRUCTION_CONTEXT = tree_construction_context_for_workspace(workspace_root)
    return {
        "kind": "context-ready",
        "corpus_root": str(root),
        "source_workspace_root": str(workspace_root),
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
            corpus_root = str(msg.get("corpus_root") or "")
            try:
                response = _initialize(
                    corpus_root,
                    source_workspace_root=(
                        str(msg["source_workspace_root"])
                        if msg.get("source_workspace_root")
                        else None
                    ),
                )
            except Exception as error:  # noqa: BLE001 — named refusal to parent
                response = {
                    "kind": "initialize-refusal",
                    "coordinate": "supervised-enum-worker.construction-context",
                    "reason": f"{type(error).__name__}: {error}",
                    "corpus_root": corpus_root or None,
                    "phase": "initialize-exception",
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
                # Always emit non-empty error_type and message — never None:None.
                err_type = type(error).__name__ or "Exception"
                err_msg = str(error)
                if not err_msg:
                    err_msg = f"(empty str({err_type})); coordinate=lift-error"
                print(
                    json.dumps(
                        {
                            "kind": "lift-error",
                            "file": rel,
                            "error_type": err_type,
                            "message": err_msg[-4000:],
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
