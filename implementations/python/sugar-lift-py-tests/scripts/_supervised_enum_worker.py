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
_DISTRIBUTION: str | None = None
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
        distribution=_DISTRIBUTION,
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
    demand_table_path: str | None,
    *,
    allow_local_demand_derivation: bool,
    source_workspace_root: str | None = None,
) -> dict:
    global _CONSTRUCTION_CONTEXT, _CORPUS_ROOT, _SOURCE_WORKSPACE_ROOT, _DISTRIBUTION
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
            "demand_table_path": demand_table_path,
            "phase": "already-initialized",
        }
    from sugar_lift_py_tests.lift_rpc import (
        provisional_contract_refs_from_demand_rows,
        provisional_contract_refs_from_demands,
        tree_construction_context_for_workspace,
    )

    if not corpus_root:
        return {
            "kind": "initialize-refusal",
            "coordinate": "supervised-enum-worker.construction-context",
            "reason": (
                "corpus_root is empty; cannot build TreeConstructionContext "
                "without a named population root"
            ),
            "corpus_root": None,
            "demand_table_path": demand_table_path,
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
            "demand_table_path": demand_table_path,
            "phase": "resolve-corpus-root",
        }
    _progress(
        "resolve-corpus-root",
        corpus_root=str(root),
        demand_table_path=demand_table_path,
        allow_local_demand_derivation=allow_local_demand_derivation,
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
            "demand_table_path": demand_table_path,
            "phase": "resolve-corpus-root",
        }

    contract_refs = None
    demand_table_identity = None
    if demand_table_path:
        from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
        from sugar_lift_py_tests.no_call_body_attribution import SHARED_DEMAND_TABLE_CONTENT_KEY
        from sugar_lift_py_tests.prebuilt_demand_table import (
            DemandTableArtifactRefusal,
            load_prebuilt_demand_table,
            validate_prebuilt_demand_table,
        )

        table_path = Path(demand_table_path)
        _progress(
            "load-shared-demand-table",
            corpus_root=str(root),
            demand_table_path=str(table_path),
            table_exists=table_path.is_file(),
        )
        if not table_path.is_file():
            return {
                "kind": "initialize-refusal",
                "coordinate": "supervised-enum-worker.construction-context",
                "reason": (
                    f"demand_table_path is not a file: {table_path} "
                    "(shared python-demand-table testimony missing on disk)"
                ),
                "corpus_root": str(root),
                "demand_table_path": str(table_path),
                "phase": "load-shared-demand-table",
            }
        corpus = authenticated_pandas_corpus()
        if corpus.root != root:
            return {
                "kind": "initialize-refusal",
                "coordinate": "supervised-enum-worker.construction-context",
                "reason": (
                    f"authenticated demand table corpus root mismatch: "
                    f"worker={root} authenticated={corpus.root}"
                ),
                "corpus_root": str(root),
                "demand_table_path": str(table_path),
                "phase": "load-shared-demand-table",
            }
        table = load_prebuilt_demand_table(
            table_path,
            expected_corpus_pin={
                "distribution": corpus.distribution,
                "version": corpus.version,
                "fileCount": corpus.file_count,
                "aggregateHash": corpus.manifest_cid,
            },
        )
        if table.semantic_identity.content_key == SHARED_DEMAND_TABLE_CONTENT_KEY:
            raise DemandTableArtifactRefusal(
                "legacy shared demand table identity refused: "
                f"{SHARED_DEMAND_TABLE_CONTENT_KEY}"
            )
        validate_prebuilt_demand_table(table, corpus)
        _DISTRIBUTION = corpus.distribution
        contract_refs = provisional_contract_refs_from_demand_rows(list(table.rows))
        demand_table_identity = table.semantic_identity.content_key
    elif not allow_local_demand_derivation:
        return {
            "kind": "initialize-refusal",
            "coordinate": "supervised-enum-worker.construction-context",
            "reason": (
                "authenticated demand table testimony is absent and "
                "allow_local_demand_derivation is false; pass demand_table_path "
                "or allow local derivation"
            ),
            "corpus_root": str(root),
            "demand_table_path": None,
            "phase": "demand-table-required",
        }
    else:
        # Local derivation walks every *.py under corpus_root — authenticated
        # pandas (~1421 files) is multi-minute. Progress lands before the walk
        # so a supervisor timeout names this phase instead of refused: None.
        _progress(
            "derive-provisional-demands",
            corpus_root=str(root),
            demand_table_path=None,
            note=(
                "walking corpus_root for With/call demands; "
                "authenticated pandas is expected to take minutes"
            ),
        )
        contract_refs = provisional_contract_refs_from_demands(root)
    _progress(
        "freeze-construction-context",
        corpus_root=str(root),
        demand_table_identity=demand_table_identity,
        using_provisional_demands=demand_table_path is None,
    )
    _CORPUS_ROOT = root
    _SOURCE_WORKSPACE_ROOT = workspace_root
    _CONSTRUCTION_CONTEXT = tree_construction_context_for_workspace(
        workspace_root, contract_refs=contract_refs
    )
    return {
        "kind": "context-ready",
        "corpus_root": str(root),
        "source_workspace_root": str(workspace_root),
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
            corpus_root = str(msg.get("corpus_root") or "")
            demand_table_path = (
                str(msg["demand_table_path"]) if msg.get("demand_table_path") else None
            )
            try:
                response = _initialize(
                    corpus_root,
                    demand_table_path,
                    source_workspace_root=(
                        str(msg["source_workspace_root"])
                        if msg.get("source_workspace_root")
                        else None
                    ),
                    allow_local_demand_derivation=bool(
                        msg.get("allow_local_demand_derivation", False)
                    ),
                )
            except Exception as error:  # noqa: BLE001 — named refusal to parent
                response = {
                    "kind": "initialize-refusal",
                    "coordinate": "supervised-enum-worker.construction-context",
                    "reason": f"{type(error).__name__}: {error}",
                    "corpus_root": corpus_root or None,
                    "demand_table_path": demand_table_path,
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
