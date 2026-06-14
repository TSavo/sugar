"""Verify-facing Python lift surface (`sugar-lift-python-verify --rpc`).

The Python analog of `cmd/sugar-lift-go-verify` (PR #1445). It is the binary
the kit-dispatch `python` lift surface resolves for the `sugar verify`
pipeline. It speaks the `initialize`/`lift`/`shutdown` JSON-RPC the
language-neutral dispatcher drives and returns ONE `ir-document` combining two
real Python lift passes over the workspace:

  1. Body-derived function-contracts from the library's non-test `.py` files,
     lifted by the real source lifter (`lifter.lift_source`) then lowered to the
     VERIFY-FACING dialect (`verify_dialect.to_verify_dialect`): arithmetic /
     comparison ops are emitted with SMT-LIB core symbols (`*`, `+`, `<`),
     the result var is `result`, the `python:return` wrapper is stripped, and
     formal/return sorts come from the `: int` annotations -- so the
     body-derived `post = result == <body-expr>` is z3-dischargeable. This is
     the Python analog of Go's `LiftSourceCore`; the spine is NOT modified.

  2. Harvested callsite assertions from the library's test files
     (`leaf_assertions.harvest_source`): `assert double(3) == 6` lifts to a
     `contract` whose `inv = =(double(3), 6)`.

`sugar mint` then (#1443) auto-writes the `double -> targetContractCid`
bridge for the body-bearing function-contract (keyed on `bridgeSourceSymbol`),
and `sugar verify` reduces `double(3) == 6` through the body `(* x 2)` ->
`(* 3 2) == 6` -> z3 discharges (positive) / refutes (broken body, negative) /
refuses (division, undecidable).

HONEST: no contract or bridge is hand-written; both halves are real lifter
output, and any op with no faithful SMT-core mapping (div/mod/floordiv/...) is
left uninterpreted -> Undecidable, never a false witness. Supra omnia, rectum.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

from .leaf_assertions import harvest_source
from .bind_lifter import _local_op_cid
from .lifter import lift_source
from .verify_dialect import VerifyDialectRefusal, collect_int_signatures, to_verify_dialect

KIT_DECLARATION_RPC_METHOD = "sugar.plugin.kit_declaration"
SURFACE = "python-verify"
VERSION = "0.1.0"

_IGNORED_DIRS = {".git", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache", ".sugar"}


def _is_test_file(name: str) -> bool:
    return name.startswith("test_") and name.endswith(".py") or name.endswith("_test.py")


def initialize_result() -> dict[str, Any]:
    return {
        "name": "sugar-lift-python-verify",
        "version": VERSION,
        "protocol_version": "sugar-lift/1",
        "dialect": SURFACE,
        "capabilities": {
            "authoring_surfaces": [SURFACE],
            "ir_version": "v1.1.0",
            "emits_signed_mementos": False,
        },
    }


def kit_declaration_result() -> dict[str, Any]:
    return {
        "kit": {
            "id": SURFACE,
            "language": "python",
            "version": VERSION,
        },
        "rpc": {
            "methods": [
                {"name": "initialize", "required": True},
                {"name": KIT_DECLARATION_RPC_METHOD, "required": True},
                {"name": "lift", "required": True},
                {"name": "shutdown", "required": False},
            ]
        },
        "proofResolution": {"strategy": "pip"},
        "effectKinds": ["panic-freedom"],
        "effectLeaves": [],
        "guardPredicates": [
            {
                "surface": SURFACE,
                "local": "is_some",
                "concept": "concept:panic-freedom.option.some",
            },
            {
                "surface": SURFACE,
                "local": "is_none",
                "concept": "concept:panic-freedom.option.none",
            },
        ],
        "controlCarriers": [],
        "residueCategories": [],
    }


def _mode_from_options(options: dict[str, Any] | None) -> str:
    """bare | bindings | contracts, mirroring Go's liftMode. The two authoring
    surfaces emit different IR so the same function is not minted twice when
    both plugins run in one `sugar mint`."""
    if not options:
        return "bare"
    if options.get("layer") == "library-bindings":
        return "bindings"
    if options.get("emit") == "ir-document":
        return "contracts"
    return "bare"


def _iter_py_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIRS]
        for filename in sorted(filenames):
            if filename.endswith(".py"):
                yield Path(dirpath) / filename


def lift_workspace(root: str, mode: str) -> tuple[list[Json], list[Json]]:
    """Walk every `.py` under root, returning (ir_items, diagnostics).

    mode == "bindings": `library-sugar-binding-entry` per annotated function
      (declaration catalog; mint skips it). Delegates to the bind lifter.
    mode == "contracts": verify-facing function-contracts gated on the
      `@sugar.boundary`/`@sugar.sugar` declaration + harvested callsites.
    mode == "bare": verify-facing function-contracts for ALL functions +
      harvested callsites (the production-bridge behaviour).
    """
    Json = dict
    root_path = Path(root or ".").resolve()
    ir_items: list[Json] = []
    diagnostics: list[Json] = []
    seen_fn: set[str] = set()
    seen_contract: set[str] = set()
    annotated_only = mode != "bare"

    # The bindings surface is the declaration catalog only -- delegate wholly
    # to the existing bind lifter (it already emits library-sugar-binding-entry
    # from @sugar.bind / @sugar.boundary). No callsite harvesting.
    if mode == "bindings":
        from . import bind_lifter

        bind_result = bind_lifter.lift_paths(str(root_path), ["."], layer="library-bindings")
        return bind_result.ir, bind_result.diagnostics

    for path in _iter_py_files(root_path):
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            diagnostics.append({"path": str(path), "message": f"cannot read: {exc}"})
            continue
        rel = os.path.relpath(path, root_path).replace(os.sep, "/")

        if _is_test_file(path.name):
            harvest = harvest_source(source, rel)
            diagnostics.extend(harvest.diagnostics)
            for decl in harvest.ir:
                name = str(decl.get("name", ""))
                if name in seen_contract:
                    continue
                seen_contract.add(name)
                ir_items.append(decl)
            continue

        # Body-derived function-contracts (verify-facing dialect).
        annotations = _boundary_annotations(source)
        sorts_by_fn = collect_int_signatures(source)
        lifted = lift_source(source, rel)
        diagnostics.extend(lifted.diagnostics)
        for refusal in lifted.refusals:
            diagnostics.append({"path": rel, "message": json.dumps(refusal)})
        for contract in lifted.ir:
            if contract.get("kind") != "function-contract":
                continue
            fn_name = str(contract.get("fnName", ""))
            if fn_name.startswith("<source-unit"):
                continue
            if fn_name in seen_fn:
                continue
            bare = fn_name.rsplit(".", 1)[-1]
            declaration = annotations.get(bare)
            if annotated_only and declaration is None:
                continue
            sorts = sorts_by_fn.get(bare)
            if sorts is None:
                diagnostics.append({"path": rel, "message": f"{fn_name}: no signature parsed"})
                continue
            try:
                item = to_verify_dialect(contract, sorts)
            except VerifyDialectRefusal as exc:
                diagnostics.append(
                    {"path": rel, "message": f"verify-dialect refusal: {exc.reason}", "function": fn_name}
                )
                continue
            seen_fn.add(fn_name)
            # Tag the contract with the authoring declaration's canonical
            # operator CID; the authoring string itself is not transported as
            # identity.
            if declaration is not None:
                concept = declaration.get("concept", "")
                if concept:
                    item["opCid"] = _local_op_cid(concept)
                item["authoringKind"] = declaration.get("kind", "")
                if declaration.get("library"):
                    item["library"] = declaration["library"]
            ir_items.append(item)

    return ir_items, diagnostics


def _boundary_annotations(source: str) -> dict[str, dict[str, str]]:
    """Map bare function name -> {concept, kind, library} for functions
    decorated with `@sugar.boundary(...)` / `@boundary(...)` /
    `@sugar.sugar(...)` / `@sugar(...)`. This gates verify-facing contract
    emission in the `contracts` surface, mirroring Go's `AnnotatedOnly`.

    Note this is distinct from the existing `@sugar.bind(concept=, library=)`
    library-binding decorator the bind lifter consumes; `@boundary`/`@sugar`
    here is the verify-facing AUTHORING declaration: "this function's body is a
    contract I want discharged"."""
    import ast

    from .authoring import authoring_declaration

    out: dict[str, dict[str, str]] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            decl = authoring_declaration(decorator)
            if decl is not None:
                out[node.name] = decl
                break
    return out


def dispatch(request: dict[str, Any]) -> dict[str, Any]:
    msg_id = request.get("id")
    method = request.get("method", "")
    params = request.get("params") or {}

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id, "result": initialize_result()}
    if method == KIT_DECLARATION_RPC_METHOD:
        return {"jsonrpc": "2.0", "id": msg_id, "result": kit_declaration_result()}
    if method == "lift":
        root = str(params.get("workspace_root", "."))
        mode = _mode_from_options(params.get("options"))
        ir_items, diagnostics = lift_workspace(root, mode)
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "kind": "ir-document",
                "ir": ir_items,
                "callEdges": [],
                "diagnostics": diagnostics,
                "opacityReport": [],
                "refusals": [],
            },
        }
    if method == "shutdown":
        return {"jsonrpc": "2.0", "id": msg_id, "result": None}
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"METHOD_NOT_FOUND: {method}"}}


def run_rpc() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = dispatch(request)
        except json.JSONDecodeError as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"PARSE_ERROR: {exc}"}}
        except Exception as exc:  # noqa: BLE001 -- surface as RPC error, never crash the loop
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": f"{exc}\n{traceback.format_exc()}"},
            }
        sys.stdout.write(json.dumps(response, separators=(",", ":"), ensure_ascii=False) + "\n")
        sys.stdout.flush()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rpc", action="store_true", help="run JSON-RPC over stdio")
    args = parser.parse_args(argv)
    if args.rpc:
        run_rpc()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
