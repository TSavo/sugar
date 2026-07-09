from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sugar_lift_py_tests.audit_only import collect_construction_gaps
from sugar_lift_py_tests.effect import SourceOracleEffect, effect_reason, effect_status
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.filename import cid_from_proof_stem
from sugar_lift_py_tests.kit_rpc import LiftReportPayloadDto
from sugar_lift_py_tests.kit_rpc.rpc_value import to_rpc_value
from sugar_lift_py_tests.lib import lift_source

KIT_ID = "python"
KIT_VERSION = "0.1.0"
NO_SOURCE_SITES_MESSAGE = "factory source contained no source sites"
LIFT_RPC_MODULE = "sugar_lift_py_tests.lift_rpc"
KIT_DECLARATION_RPC_METHOD = "sugar.plugin.kit_declaration"
COMPONENT_PLAN_RPC_METHOD = "sugar.component.plan"
RESOLVE_SOURCE_MEMENTO_RPC_METHOD = "sugar.plugin.resolve_source_memento"
ENUMERATE_RPC_METHOD = "sugar.enumerate"
COMPONENT_PROTOCOL_VERSION = "sugar-component/1"
LIFT_PROTOCOL_VERSION = "pep/1.7.0"
PYTHON_SURFACE = "python"
PYTHON_LIFT_NAME = "python-lift"
PYTHON_SOURCE_ORACLE_NAME = "python-source-oracle"
COMPONENT_PLAN_INTENTS = {"lift", "prove", "verify"}
PARSE_ERROR = object()


def _send(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _recv() -> Optional[Dict[str, Any]] | object:
    line = sys.stdin.readline()
    if not line:
        return None
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return PARSE_ERROR
    return value if isinstance(value, dict) else PARSE_ERROR


def _kit_declaration_result() -> Dict[str, Any]:
    return {
        "kit": {
            "id": KIT_ID,
            "language": "python",
            "version": KIT_VERSION,
        },
        "rpc": {
            "methods": [
                {"name": "initialize", "required": True},
                {"name": KIT_DECLARATION_RPC_METHOD, "required": True},
                {"name": COMPONENT_PLAN_RPC_METHOD, "required": False},
                {"name": RESOLVE_SOURCE_MEMENTO_RPC_METHOD, "required": False},
                {"name": ENUMERATE_RPC_METHOD, "required": False},
                {"name": "lift", "required": True},
                {"name": "sugar.plugin.lift_implications", "required": False},
                {"name": "sugar.plugin.resolve_dependency_proofs", "required": False},
                {"name": "shutdown", "required": False},
            ]
        },
        # PART 6 FIX (2026-07-08, discovered by `Kit::rendezvous` against a
        # real python kit for the first time -- no prior rust test exercised
        # this path with the python kit; the strong `KitDeclaration` schema
        # (`sugar-claim-envelope`) requires `proofResolution.strategy`
        # non-empty; this kit's proof-resolution mechanism is exactly its
        # `sugar.plugin.resolve_dependency_proofs` handler below.
        "proofResolution": {
            "strategy": "rpc-proof-bytes",
            "rpcMethod": "sugar.plugin.resolve_dependency_proofs",
        },
        "residueCategories": [],
    }


def _iter_python_files(workspace_root: str, source_paths: List[Any]) -> List[str]:
    root = os.path.abspath(workspace_root)
    out: List[str] = []
    for raw_path in source_paths or ["."]:
        path = str(raw_path)
        full_path = os.path.abspath(
            path if os.path.isabs(path) else os.path.join(root, path)
        )
        if os.path.isfile(full_path):
            if full_path.endswith(".py"):
                out.append(full_path)
            continue
        for dirpath, _, filenames in os.walk(full_path):
            for filename in filenames:
                if filename.endswith(".py"):
                    out.append(os.path.abspath(os.path.join(dirpath, filename)))
    return sorted(set(out))


def _items_from_params(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for evidence_key in (
        "project_forensics",
        "projectForensics",
        "workspace_evidence",
        "workspaceEvidence",
    ):
        evidence = params.get(evidence_key)
        if not isinstance(evidence, dict):
            continue
        items = evidence.get("items")
        if not isinstance(items, list):
            continue
        out.extend(item for item in items if isinstance(item, dict))
    return out


def _language_evidence_from_params(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for evidence_key in ("workspace_evidence", "workspaceEvidence"):
        evidence = params.get(evidence_key)
        if not isinstance(evidence, dict):
            continue
        languages = evidence.get("languages")
        if not isinstance(languages, list):
            continue
        out.extend(item for item in languages if isinstance(item, dict))
    return out


def _path_is_python(path: Any) -> bool:
    return str(path).endswith(".py")


def _item_mentions_python(item: Dict[str, Any]) -> bool:
    language = item.get("language_hint", item.get("languageHint"))
    return language == "python" or _path_is_python(item.get("path", ""))


def _first_python_claim(params: Dict[str, Any], workspace_root: str) -> Optional[str]:
    for item in _items_from_params(params):
        if not _item_mentions_python(item):
            continue
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id:
            return item_id
        path = item.get("path")
        if isinstance(path, str) and path:
            return f"file:{path}"

    for language in _language_evidence_from_params(params):
        if language.get("language") != "python":
            continue
        path = language.get("path")
        if isinstance(path, str) and path:
            return f"file:{path}"

    root = Path(workspace_root)
    if root.is_dir():
        for path in sorted(root.rglob("*.py")):
            try:
                relative = path.relative_to(root)
            except ValueError:
                relative = path
            return f"file:{relative.as_posix()}"
    return None


def _component_plan_result(params: Dict[str, Any]) -> Dict[str, Any]:
    intent = str(params.get("intent", "lift"))
    if intent not in COMPONENT_PLAN_INTENTS:
        return {
            "decision": "decline",
            "languages": [PYTHON_SURFACE],
            "reason": f"unsupported plan intent: {intent}",
        }
    workspace_root = str(params.get("workspace_root", "."))
    claim_item = _first_python_claim(params, workspace_root)
    if claim_item is None:
        return {
            "decision": "decline",
            "reason": "no Python source evidence",
        }
    return {
        "decision": "claim",
        "claims": [
            {
                "item": claim_item,
                "role": "source-lifter",
                "surface": PYTHON_SURFACE,
            }
        ],
        "plugins": [
            {
                "name": PYTHON_LIFT_NAME,
                "kind": "lift",
                "surface": PYTHON_SURFACE,
                "emit": "ir-document",
            }
        ],
        "lift_manifests": [
            {
                "surface": PYTHON_SURFACE,
                "name": PYTHON_LIFT_NAME,
                "version": KIT_VERSION,
                "protocol_version": LIFT_PROTOCOL_VERSION,
                "kind": "lift",
                "command": _runtime_lift_command(),
                "working_dir": ".",
            }
        ],
        "source_oracles": [
            {
                "surface": PYTHON_SURFACE,
                "name": PYTHON_SOURCE_ORACLE_NAME,
                "version": KIT_VERSION,
                "method": RESOLVE_SOURCE_MEMENTO_RPC_METHOD,
                "command": _runtime_lift_command(),
                "working_dir": ".",
            }
        ],
        "diagnostics": [],
    }


def _runtime_lift_command() -> List[str]:
    return [sys.executable, str(Path(__file__).resolve()), "--rpc"]


def _source_oracle_api():
    try:
        from sugar_lift_python_source.source_oracle import (
            SourceOracleRefusal,
            resolve_source_memento,
        )
    except ModuleNotFoundError:
        sibling_src = (
            Path(__file__).resolve().parents[3] / "sugar-lift-python-source" / "src"
        )
        if str(sibling_src) not in sys.path:
            sys.path.insert(0, str(sibling_src))
        from sugar_lift_python_source.source_oracle import (
            SourceOracleRefusal,
            resolve_source_memento,
        )
    return SourceOracleRefusal, resolve_source_memento


def _python_source_verify_api():
    try:
        from sugar_lift_python_source.verify_rpc import lift_workspace
    except ModuleNotFoundError:
        sibling_src = (
            Path(__file__).resolve().parents[3] / "sugar-lift-python-source" / "src"
        )
        if str(sibling_src) not in sys.path:
            sys.path.insert(0, str(sibling_src))
        from sugar_lift_python_source.verify_rpc import lift_workspace
    return lift_workspace


def _python_source_lifter_api():
    try:
        from sugar_lift_python_source.lifter import lift_source as source_lift_source
    except ModuleNotFoundError:
        sibling_src = (
            Path(__file__).resolve().parents[3] / "sugar-lift-python-source" / "src"
        )
        if str(sibling_src) not in sys.path:
            sys.path.insert(0, str(sibling_src))
        from sugar_lift_python_source.lifter import lift_source as source_lift_source
    return source_lift_source


def _python_source_public_reexport_map(root: Path) -> dict[str, tuple[str, str]]:
    try:
        from sugar_lift_python_source.bind_lifter import _public_reexport_map
    except ModuleNotFoundError:
        sibling_src = (
            Path(__file__).resolve().parents[3] / "sugar-lift-python-source" / "src"
        )
        if str(sibling_src) not in sys.path:
            sys.path.insert(0, str(sibling_src))
        from sugar_lift_python_source.bind_lifter import _public_reexport_map
    return _public_reexport_map(root) or {}


def _is_python_test_file(path: Path) -> bool:
    name = path.name
    return (name.startswith("test_") and name.endswith(".py")) or name.endswith(
        "_test.py"
    )


def _is_true_formula(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("kind") == "atomic"
        and value.get("name") == "true"
        and value.get("args") in (None, [])
    )


def _source_precondition_only_contracts(
    workspace_root: str, existing_contracts: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    source_lift_source = _python_source_lifter_api()
    root = Path(workspace_root or ".").resolve()
    public_reexports = _python_source_public_reexport_map(root)
    existing_names = {
        str(item.get("fnName") or item.get("name"))
        for item in existing_contracts
        if isinstance(item, dict) and (item.get("fnName") or item.get("name"))
    }
    out: List[Dict[str, Any]] = []
    for filename in _iter_python_files(str(root), ["."]):
        path = Path(filename)
        if _is_python_test_file(path):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = path.name
        lifted = source_lift_source(source, rel)
        for item in lifted.ir:
            if not isinstance(item, dict) or item.get("kind") != "function-contract":
                continue
            fn_name = item.get("fnName")
            if not isinstance(fn_name, str) or fn_name.startswith("<source-unit"):
                continue
            if fn_name in existing_names:
                continue
            precondition = item.get("pre")
            if _is_true_formula(precondition):
                continue
            contract = {
                "schemaVersion": item.get("schemaVersion", "1"),
                "kind": "function-contract",
                "fnName": fn_name,
                "formals": list(item.get("formals") or []),
                "formalSorts": list(item.get("formalSorts") or []),
                "returnSort": item.get(
                    "returnSort", {"kind": "primitive", "name": "Value"}
                ),
                "pre": precondition,
                "bodyDischargeEligible": False,
                "bodyDischargeRefusalReason": (
                    "precondition-only source guard contract; report path imports "
                    "the source-lifter-owned precondition without importing the raw "
                    "Python body as a dischargeable post"
                ),
                "locus": item.get("locus"),
            }
            contract["bridgeSourceSymbol"] = _source_contract_bridge_symbol(
                fn_name, public_reexports
            )
            out.append(contract)
            existing_names.add(fn_name)
    return out


def _source_contract_bridge_symbol(
    fn_name: str, public_reexports: dict[str, tuple[str, str]]
) -> str:
    public = public_reexports.get(fn_name)
    if public is not None:
        return public[1]
    for constructor_suffix in (".__new__", ".__init__"):
        if not fn_name.endswith(constructor_suffix):
            continue
        class_symbol = fn_name[: -len(constructor_suffix)]
        public_class = public_reexports.get(class_symbol)
        if public_class is not None:
            return public_class[1]
    parts = fn_name.split(".")
    for index in range(len(parts) - 1, 0, -1):
        owner_symbol = ".".join(parts[:index])
        public_owner = public_reexports.get(owner_symbol)
        if public_owner is None:
            continue
        member_suffix = ".".join(parts[index:])
        return f"{public_owner[1]}.{member_suffix}"
    return fn_name


def _source_lifter_function_contracts(
    workspace_root: str,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    lift_workspace = _python_source_verify_api()
    ir_items, diagnostics = lift_workspace(workspace_root, "bare")
    contracts = [
        item
        for item in ir_items
        if isinstance(item, dict) and item.get("kind") == "function-contract"
    ]
    contracts.extend(_source_precondition_only_contracts(workspace_root, contracts))
    return contracts, diagnostics


def _source_memento_from_params(params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    raw = (
        params.get("memento")
        or params.get("sourceMemento")
        or params.get("source_memento")
    )
    if not isinstance(raw, dict):
        return None
    out = dict(raw)
    aliases = {
        "sourceFunctionName": "source_function_name",
        "sourceCid": "source_cid",
        "templateCid": "template_cid",
        "paramNames": "param_names",
    }
    for camel, snake in aliases.items():
        if snake not in out and camel in out:
            out[snake] = out[camel]
    out.setdefault("kind", "source-memento")
    return out


def _source_memento_response(
    original: Dict[str, Any], resolved: Dict[str, Any]
) -> Dict[str, Any]:
    out = dict(original)
    out["kind"] = "source-memento"
    for field_name in ("source_cid", "template_cid", "param_names"):
        if resolved.get(field_name) is not None:
            out[field_name] = resolved[field_name]
    for forbidden in (
        "body_text",
        "ast_template",
        "bodyText",
        "astTemplate",
        "sourceOracle",
    ):
        out.pop(forbidden, None)
    return out


def _source_lines_for_memento(
    workspace_root: str, memento: Dict[str, Any]
) -> List[Dict[str, Any]]:
    file_name = memento.get("file")
    span = memento.get("span") if isinstance(memento.get("span"), dict) else {}
    start_line = span.get("start_line")
    end_line = span.get("end_line", start_line)
    if not isinstance(file_name, str) or not isinstance(start_line, int):
        return []
    if not isinstance(end_line, int):
        end_line = start_line
    try:
        source_lines = (
            (Path(workspace_root) / file_name).read_text(encoding="utf-8").splitlines()
        )
    except OSError:
        return []
    start_index = max(start_line - 1, 0)
    end_index = max(end_line, start_line)
    return [
        {"line": start_index + offset + 1, "source": source.rstrip()}
        for offset, source in enumerate(source_lines[start_index:end_index])
    ]


def _source_memento_display(memento: Dict[str, Any]) -> str:
    file_name = str(memento.get("file", "<unknown>"))
    span = memento.get("span") if isinstance(memento.get("span"), dict) else {}
    start_line = span.get("start_line", "?")
    start_col = span.get("start_col", "?")
    end_line = span.get("end_line", "?")
    end_col = span.get("end_col", "?")
    name = memento.get("source_function_name") or memento.get("sourceFunctionName")
    source_cid = memento.get("source_cid") or memento.get("sourceCid")
    pieces = [f"{file_name}:{start_line}:{start_col}-{end_line}:{end_col}"]
    if isinstance(name, str) and name:
        pieces.append(name)
    if isinstance(source_cid, str) and source_cid:
        pieces.append(source_cid)
    return " ".join(pieces)


def _source_oracle_effect_result(
    effect: SourceOracleEffect,
    memento: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "status": effect_status(effect),
        "reason": effect_reason(effect),
        "memento": _source_memento_response(memento, {}),
    }


def _resolve_source_memento_result(params: Dict[str, Any]) -> Dict[str, Any]:
    workspace_root = str(params.get("workspace_root", "."))
    memento = _source_memento_from_params(params)
    if memento is None:
        return {
            "status": "absent",
            "reason": "invalid source memento shape",
        }
    SourceOracleRefusal, resolve_source_memento = _source_oracle_api()
    try:
        resolved = resolve_source_memento(workspace_root, memento)
    except SourceOracleRefusal as exc:
        return _source_oracle_effect_result(
            SourceOracleEffect(reason=str(exc)), memento
        )
    body_text = str(resolved.get("body_text") or "").strip()
    lean_memento = _source_memento_response(memento, resolved)
    return {
        "status": "resolved",
        "source": body_text,
        "bodyText": body_text,
        "sourceLines": _source_lines_for_memento(workspace_root, lean_memento),
        "display": _source_memento_display(lean_memento),
        "memento": lean_memento,
    }


def _degenerate_file_memento(rel_path: str) -> Dict[str, Any]:
    """The file-level locator (Part 6 Phase 2's "degenerate memento shape"):
    a `source-memento` with only `file` populated -- span/source_cid/
    template_cid absent (`null`), since a whole file has no single body/AST
    template to CID. `SourceFile` is the one node type whose locator does not
    name a function body."""
    return {
        "kind": "source-memento",
        "file": rel_path,
        "function_name": "",
        "span": None,
        "param_names": [],
        "source_cid": None,
        "template_cid": None,
    }


def _enumerate_file_of(at: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(at, dict):
        return None
    file_name = at.get("file")
    return file_name if isinstance(file_name, str) and file_name else None


def _memento_matches(candidate: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """Primary-key equality for the tree's locator (the plan's "memento is
    the primary key"): same file + same span + same source_cid. Only span
    fields present on BOTH sides are compared, so a degenerate (file-only)
    target matches on file alone."""
    if candidate.get("file") != target.get("file"):
        return False
    target_source_cid = target.get("source_cid") or target.get("sourceCid")
    if target_source_cid:
        if candidate.get("source_cid") != target_source_cid:
            return False
    target_span = target.get("span")
    # The Rust client's `SourceMemento` has no optional span -- a
    # degenerate (file-only) locator round-trips through it as an
    # all-zero span (`SrcSpan{0,0,0,0}`), not `null` (see `tree.rs`'s
    # `decode_memento` doc). Treat an all-zero span the SAME as "no span
    # constraint" so a file-level seek survives that round trip.
    if isinstance(target_span, dict) and any(
        target_span.get(key) not in (0, None)
        for key in ("start_line", "start_col", "end_line", "end_col")
    ):
        candidate_span = candidate.get("span") or {}
        for key in ("start_line", "start_col", "end_line", "end_col"):
            if key in target_span and candidate_span.get(key) != target_span.get(key):
                return False
    target_fn = (
        target.get("function_name")
        or target.get("sourceFunctionName")
        or target.get("source_function_name")
    )
    if target_fn:
        candidate_fn = (
            candidate.get("function_name")
            or candidate.get("sourceFunctionName")
            or candidate.get("source_function_name")
        )
        if candidate_fn != target_fn:
            return False
    return True


def _lift_file_for_enumeration(
    workspace_root: str, root: Path, file_rel: str
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Lift ONE file server-side (Part 6 Phase 3: "it is ACCEPTABLE ... for
    the first cut to lift the WHOLE file ... and slice/serve the requested
    level from that one parse" -- file-granular laziness, not per-node wire
    laziness).

    Returns `(ir_items, call_edges)` already through `to_rpc_value`:
    - `ir`: `kind="function-contract"` = function/universe rows;
      `kind="contract"` = claim rows that already bundle locus + formula
      (call-site ≡ assertion is **factory truth**, not a protocol fold —
      see protocol Section 4 / `_handle_enumerate`)
    - `callEdges`: batch join keys with first-class `targetSymbol`
      (`call:len`, `method:count`) — sliced onto call_sites audit as
      `bridgeSourceSymbol` (do not re-invent prefixes from FOL alone;
      method calls are `method:` on the edge even when FOL uses `call:`).
      Edges are join metadata, not a second site-record set.
    """
    full_path = (root / file_rel).resolve()
    source = full_path.read_text(encoding="utf-8")
    try:
        result = lift_source(str(full_path), source, memento_file=file_rel)
    except ValueError as exc:
        if "no source sites" in str(exc):
            return [], []
        raise
    ir_items = [to_rpc_value(item) for item in result.payload.ir]
    call_edges = [to_rpc_value(edge) for edge in result.payload.call_edges]
    return ir_items, call_edges


def _item_memento(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    warrants = item.get("sourceWarrants")
    if isinstance(warrants, list) and warrants and isinstance(warrants[0], dict):
        return warrants[0]
    return None


def _item_fact_formula(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return item.get("inv") if item.get("inv") is not None else item.get("post")


def _find_item_by_memento(
    items: List[Dict[str, Any]], target: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    if not isinstance(target, dict):
        return None
    for item in items:
        memento = _item_memento(item)
        if memento is not None and _memento_matches(memento, target):
            return item
    return None


def _first_bridge_ctor_name(node: Any) -> Optional[str]:
    """First `call:` / `method:` ctor head in a FOL term tree (depth-first)."""
    if not isinstance(node, dict):
        return None
    name = node.get("name")
    if (
        node.get("kind") == "ctor"
        and isinstance(name, str)
        and (name.startswith("call:") or name.startswith("method:"))
    ):
        return name
    for value in node.values():
        if isinstance(value, dict):
            found = _first_bridge_ctor_name(value)
            if found is not None:
                return found
        elif isinstance(value, list):
            for child in value:
                found = _first_bridge_ctor_name(child)
                if found is not None:
                    return found
    return None


def _contract_bridge_identity(item: Dict[str, Any]) -> Optional[str]:
    """Callee identity for a `kind=contract` assertion: FOL ctor head, else name.

    Used to join a call-site record to a `function-contract` universe via
    `bridgeSourceSymbol` (e.g. `call:add` → `mathy::add::callable`).
    Returns the `call:` / `method:` form with prefix preserved — never a bare
    name when a first-class bridge identity is available.
    """
    formula = _item_fact_formula(item)
    if isinstance(formula, dict):
        # Prefer the left-hand side of an equality assertion (the call).
        if formula.get("kind") == "atomic" and formula.get("name") == "=":
            args = formula.get("args")
            if isinstance(args, list) and args:
                found = _first_bridge_ctor_name(args[0])
                if found is not None:
                    return found
        found = _first_bridge_ctor_name(formula)
        if found is not None:
            return found
    raw_name = item.get("name")
    if isinstance(raw_name, str):
        for prefix in ("call:", "method:"):
            idx = raw_name.find(prefix)
            if idx < 0:
                continue
            rest = raw_name[idx:]
            end = 0
            while end < len(rest) and (
                rest[end].isalnum() or rest[end] in (":", "_")
            ):
                end += 1
            if end > len(prefix):
                return rest[:end]
    return None


def _edge_target_symbol_for_contract(
    item: Dict[str, Any], call_edges: Optional[List[Dict[str, Any]]]
) -> Optional[str]:
    """Batch `callEdges.targetSymbol` for this contract, if any.

    Joined by `sourceContract == item.name`. This is the first-class
    free-call vs method-call identity (`call:len` vs `method:count`);
    FOL ctor heads alone can say `call:count` for a method site.
    """
    if not call_edges:
        return None
    name = item.get("name")
    if not isinstance(name, str) or not name:
        return None
    for edge in call_edges:
        if not isinstance(edge, dict):
            continue
        source = edge.get("sourceContract") or edge.get("source_contract")
        if source != name:
            continue
        target = edge.get("targetSymbol") or edge.get("target_symbol")
        if isinstance(target, str) and (
            target.startswith("call:") or target.startswith("method:")
        ):
            return target
    return None


def _call_site_node_audit(
    item: Dict[str, Any],
    call_edges: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Enumerate audit for `call_sites` / `assertions` nodes.

    Stamps first-class `bridgeSourceSymbol` (`call:len`, `method:count`, …)
    onto the wire audit so the tree client can decode
    `CallSite.bridge_source_symbol` without re-mining FOL. Precedence:
    1. batch `callEdges.targetSymbol` for this contract (authoritative
       method:/call: split — do not invent prefixes)
    2. IR-stamped `bridgeSourceSymbol` already in call:/method: form
    3. FOL / name via `_contract_bridge_identity`
    The prefix is never normalized away. `name` rides along from the IR item.
    """
    audit = dict(item)
    edge_sym = _edge_target_symbol_for_contract(item, call_edges)
    if edge_sym is not None:
        audit["bridgeSourceSymbol"] = edge_sym
        return audit
    existing = audit.get("bridgeSourceSymbol")
    if isinstance(existing, str) and (
        existing.startswith("call:") or existing.startswith("method:")
    ):
        return audit
    bridge = _contract_bridge_identity(item)
    if bridge is not None:
        audit["bridgeSourceSymbol"] = bridge
    return audit


def _universe_node_from_item(
    item: Dict[str, Any], file_rel: str
) -> Dict[str, Any]:
    """Build a `level=universe` wire node from a function-contract IR row.

    Stamps the batch `name` (e.g. `len::builtin-universe`) onto the memento's
    function_name fields so client-side collectors that only see
    `SourceMemento::to_json()` still recover the universe member key.
    """
    name = item.get("name") if isinstance(item.get("name"), str) else ""
    base = _item_memento(item)
    if base is None:
        memento: Dict[str, Any] = {
            "kind": "source-memento",
            "file": file_rel,
            "function_name": name,
            "source_function_name": name,
            "sourceFunctionName": name,
            "span": None,
            "param_names": [],
            "source_cid": None,
            "template_cid": None,
        }
    else:
        memento = dict(base)
    if name:
        # Batch universe member key — must survive decode_memento → to_json.
        memento["function_name"] = name
        memento["source_function_name"] = name
        memento["sourceFunctionName"] = name
        memento["name"] = name
    return {
        "memento": memento,
        "audit": item,
        "payload": _item_fact_formula(item),
    }


def _send_enumerate_result(
    msg_id: Any,
    nodes: List[Dict[str, Any]],
    gaps: List[Dict[str, Any]],
) -> None:
    _send(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"nodes": nodes, "gaps": gaps},
        }
    )


def _handle_enumerate(msg_id: Any, params: Dict[str, Any]) -> None:
    """`sugar.enumerate`: the ONE wire method behind the Rust `tree` module's
    lazy accessors (Part 6 Phase 2,
    `protocol/specs/2026-07-08-enumeration-protocol.md`). `level` selects the
    granularity; `at` is the parent's (scan) or this node's own (seek)
    memento; `seek=true` asks for exactly the ONE node matching `at` rather
    than every child of it.
    """
    level = params.get("level")
    workspace_root = str(params.get("workspace_root", "."))
    at = params.get("at") if isinstance(params.get("at"), dict) else None
    seek = bool(params.get("seek", False))
    root = Path(workspace_root).resolve()

    try:
        if level == "source_files":
            nodes = []
            for full_path in _iter_python_files(workspace_root, ["."]):
                try:
                    rel_path = Path(full_path).resolve().relative_to(root).as_posix()
                except ValueError:
                    rel_path = Path(full_path).name
                memento = _degenerate_file_memento(rel_path)
                if seek and at is not None and not _memento_matches(memento, at):
                    continue
                nodes.append({"memento": memento, "audit": None, "payload": None})
            _send_enumerate_result(msg_id, nodes, [])
            return

        if level in ("functions", "call_sites", "assertions", "facts", "universe"):
            file_rel = _enumerate_file_of(at)
            if file_rel is None:
                _send_enumerate_result(
                    msg_id,
                    [],
                    [
                        {
                            "memento": at,
                            "reason": f"sugar.enumerate level={level!r} requires `at.file`",
                        }
                    ],
                )
                return
            full_path = root / file_rel
            # SECURITY (macroscope on #3862): a forged memento with an
            # absolute path (pathlib join discards root) or a ../ traversal
            # could enumerate files OUTSIDE the workspace. Require the
            # resolved path to stay under the resolved workspace root.
            resolved_root = root.resolve()
            resolved_full = full_path.resolve()
            if not (
                resolved_full == resolved_root
                or resolved_root in resolved_full.parents
            ):
                _send_enumerate_result(
                    msg_id,
                    [],
                    [
                        {
                            "memento": at,
                            "reason": (
                                "refused: memento file escapes the workspace root "
                                f"({file_rel!r})"
                            ),
                        }
                    ],
                )
                return
            if not full_path.is_file():
                _send_enumerate_result(
                    msg_id,
                    [],
                    [{"memento": at, "reason": f"no such file: {file_rel}"}],
                )
                return
            ir_items, call_edges = _lift_file_for_enumeration(
                workspace_root, root, file_rel
            )

            if level == "functions":
                # A function gets a node either because it OWNS a
                # function-contract (kind="function-contract") or because it
                # merely ENCLOSES a call-site assertion (kind="contract",
                # whose memento's own source_function_name names its caller
                # -- e.g. a test function with no contract of its own but
                # real assertions inside it). Both are real functions in the
                # source; a driver walking source_files -> functions must be
                # able to reach either kind of call site underneath.
                seen_names: set = set()
                nodes = []

                def _emit(memento, audit):
                    fn_name = memento.get("source_function_name") or memento.get(
                        "sourceFunctionName"
                    )
                    if fn_name in seen_names:
                        return
                    if seek and at is not None and not _memento_matches(memento, at):
                        return
                    seen_names.add(fn_name)
                    nodes.append({"memento": memento, "audit": audit, "payload": None})

                for item in ir_items:
                    if item.get("kind") != "function-contract":
                        continue
                    memento = _item_memento(item)
                    if memento is None:
                        continue
                    _emit(
                        memento,
                        {
                            "kind": item.get("kind"),
                            "name": item.get("name"),
                            "formals": item.get("formals"),
                            "bridgeSourceSymbol": item.get("bridgeSourceSymbol"),
                        },
                    )
                for item in ir_items:
                    if item.get("kind") != "contract":
                        continue
                    memento = _item_memento(item)
                    if memento is None:
                        continue
                    fn_name = memento.get("source_function_name") or memento.get(
                        "sourceFunctionName"
                    )
                    if not fn_name or fn_name in seen_names:
                        continue
                    _emit(
                        {
                            "kind": "source-memento",
                            "file": file_rel,
                            "function_name": fn_name,
                            "source_function_name": fn_name,
                            "span": None,
                            "param_names": [],
                            "source_cid": None,
                            "template_cid": None,
                        },
                        {
                            "kind": "function",
                            "name": fn_name,
                            "note": "no function-contract of its own; reachable "
                            "because it encloses a call-site assertion",
                        },
                    )
                _send_enumerate_result(msg_id, nodes, [])
                return

            if level == "call_sites":
                # GRANULARITY (reported, not hidden): `Function::call_sites()`
                # scopes to `kind="contract"` items whose own memento's
                # `source_function_name` matches the enclosing function's
                # name from `at` -- there is no per-function AST-scope index
                # kit-side yet beyond that name match, so two same-named
                # nested functions in one file would collide (flagged, not
                # hidden; out of scope for this fixture-sized cut).
                target_fn = (
                    at.get("function_name")
                    or at.get("sourceFunctionName")
                    or at.get("source_function_name")
                    if at
                    else None
                )
                built = []
                for item in ir_items:
                    if item.get("kind") != "contract":
                        continue
                    memento = _item_memento(item)
                    if memento is None:
                        continue
                    if target_fn:
                        item_fn = (
                            memento.get("source_function_name")
                            or memento.get("sourceFunctionName")
                            or memento.get("function_name")
                        )
                        if item_fn != target_fn:
                            continue
                    if seek and at is not None and not _memento_matches(memento, at):
                        continue
                    # First-class bridge identity on the wire audit
                    # (`call:` / `method:` — prefix preserved from callEdges).
                    built.append(
                        {
                            "memento": memento,
                            "audit": _call_site_node_audit(item, call_edges),
                            "payload": None,
                        }
                    )
                _send_enumerate_result(msg_id, built, [])
                return

            if level == "assertions":
                # Seek-only: a call site's own kind=contract item IS its
                # assertion. 1:1 is factory truth (batch IR has no dual
                # site/claim records) — protocol Section 4, not a collapse.
                # Same bridgeSourceSymbol stamp as call_sites.
                item = _find_item_by_memento(ir_items, at)
                if item is None:
                    _send_enumerate_result(
                        msg_id,
                        [],
                        [{"memento": at, "reason": "no call site for this memento"}],
                    )
                    return
                _send_enumerate_result(
                    msg_id,
                    [
                        {
                            "memento": _item_memento(item),
                            "audit": _call_site_node_audit(item, call_edges),
                            "payload": None,
                        }
                    ],
                    [],
                )
                return

            if level == "facts":
                item = _find_item_by_memento(ir_items, at)
                if item is None:
                    _send_enumerate_result(
                        msg_id,
                        [],
                        [{"memento": at, "reason": "no assertion for this memento"}],
                    )
                    return
                formula = _item_fact_formula(item)
                if formula is None:
                    _send_enumerate_result(
                        msg_id,
                        [],
                        [
                            {
                                "memento": _item_memento(item),
                                "reason": "assertion carries no post/inv fact",
                            }
                        ],
                    )
                    return
                _send_enumerate_result(
                    msg_id,
                    [
                        {
                            "memento": _item_memento(item),
                            "audit": item,
                            "payload": formula,
                        }
                    ],
                    [],
                )
                return

            if level == "universe":
                # Body/operator universes are `kind="function-contract"` rows
                # (including `len::builtin-universe`). CallSite::universe seeks
                # the universe linked to a call-site memento via
                # bridgeSourceSymbol / FOL callee identity. File-level scan
                # (`seek=false`) lists every universe in the file.
                universe_items = [
                    item
                    for item in ir_items
                    if isinstance(item, dict)
                    and item.get("kind") == "function-contract"
                ]

                if seek and at is not None:
                    # Call-site linkage path first: match a kind=contract
                    # assertion, then join on bridge identity.
                    #
                    # Dual-candidate (Task 9 / Important residual): try
                    # callEdges BSS first (`method:count`) and FOL
                    # `_contract_bridge_identity` second (`call:count`). A
                    # method site whose FOL ctor says `call:count` must still
                    # join a universe stamped `method:count` (and vice versa).
                    call_item = None
                    for item in ir_items:
                        if item.get("kind") != "contract":
                            continue
                        memento = _item_memento(item)
                        if memento is not None and _memento_matches(memento, at):
                            call_item = item
                            break
                    if call_item is not None:
                        candidates: List[str] = []
                        edge_sym = _edge_target_symbol_for_contract(
                            call_item, call_edges
                        )
                        if edge_sym is not None:
                            candidates.append(edge_sym)
                        fol_sym = _contract_bridge_identity(call_item)
                        if fol_sym is not None and fol_sym not in candidates:
                            candidates.append(fol_sym)
                        matched = None
                        matched_bridge = None
                        for bridge in candidates:
                            for universe_item in universe_items:
                                if universe_item.get("bridgeSourceSymbol") == bridge:
                                    matched = universe_item
                                    matched_bridge = bridge
                                    break
                            if matched is not None:
                                break
                        if matched is not None:
                            _send_enumerate_result(
                                msg_id,
                                [_universe_node_from_item(matched, file_rel)],
                                [],
                            )
                            return
                        callee = (
                            matched_bridge
                            if matched_bridge
                            else (candidates[0] if candidates else "unknown")
                        )
                        _send_enumerate_result(
                            msg_id,
                            [],
                            [
                                {
                                    "memento": at,
                                    "reason": (
                                        f"no universe sugar for callee {callee}"
                                    ),
                                }
                            ],
                        )
                        return

                    # Direct universe seek (scan/seek coherence on a universe
                    # node's own memento, including the stamped name).
                    nodes = []
                    for universe_item in universe_items:
                        node = _universe_node_from_item(universe_item, file_rel)
                        if _memento_matches(node["memento"], at):
                            nodes.append(node)
                    _send_enumerate_result(msg_id, nodes, [])
                    return

                # Scan: every function-contract universe in the file.
                nodes = [
                    _universe_node_from_item(universe_item, file_rel)
                    for universe_item in universe_items
                ]
                _send_enumerate_result(msg_id, nodes, [])
                return

        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32602,
                    "message": f"sugar.enumerate: unknown level {level!r}",
                },
            }
        )
    except Exception as exc:
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": str(exc),
                    "data": traceback.format_exc(),
                },
            }
        )


def _handle_initialize(msg_id: Any) -> None:
    _send(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "name": "sugar-lift-python",
                "version": KIT_VERSION,
                "kit_id": KIT_ID,
                "component_protocol_version": COMPONENT_PROTOCOL_VERSION,
            },
        }
    )


def _handle_lift(
    msg_id: Any, params: Dict[str, Any], *, audit_only: bool = False
) -> None:
    workspace_root = str(params.get("workspace_root", "."))
    source_paths = list(params.get("source_paths", ["."]))
    contract_bindings = params.get("contract_bindings") or []
    if not isinstance(contract_bindings, list):
        contract_bindings = []
    try:
        if audit_only:
            _handle_lift_audit_only(
                msg_id,
                workspace_root=workspace_root,
                source_paths=source_paths,
                contract_bindings=contract_bindings,
            )
            return
        payload = LiftReportPayloadDto(source_ledger={})
        bindings_backed_pass = bool(contract_bindings)
        root = Path(workspace_root).resolve()
        if not bindings_backed_pass:
            contracts, diagnostics = _source_lifter_function_contracts(workspace_root)
            payload.ir.extend(contracts)
            payload.diagnostics.extend(diagnostics)
        for path in _iter_python_files(workspace_root, source_paths):
            full_path = Path(path)
            try:
                rel_path = full_path.resolve().relative_to(root).as_posix()
            except ValueError:
                rel_path = full_path.name
            with open(path, "r", encoding="utf-8") as handle:
                try:
                    result = lift_source(
                        path,
                        handle.read(),
                        memento_file=rel_path,
                        contract_bindings=contract_bindings,
                    )
                except ValueError as exc:
                    if str(exc) == NO_SOURCE_SITES_MESSAGE:
                        continue
                    raise
            if hasattr(result, "payload"):
                file_payload = result.payload
                if bindings_backed_pass:
                    payload.call_edges.extend(file_payload.call_edges)
                    payload.implications.extend(file_payload.implications)
                    payload.diagnostics.extend(file_payload.diagnostics)
                    continue
                payload.ir.extend(file_payload.ir)
                payload.source_mementos.extend(file_payload.source_mementos)
                _merge_source_ledger(payload.source_ledger, file_payload.source_ledger)
                payload.source_audits.extend(file_payload.source_audits)
                payload.factory_audits.extend(file_payload.factory_audits)
                payload.factory_walk.extend(file_payload.factory_walk)
                payload.call_edges.extend(file_payload.call_edges)
                payload.implications.extend(file_payload.implications)
                payload.diagnostics.extend(file_payload.diagnostics)
        _send({"jsonrpc": "2.0", "id": msg_id, "result": payload.to_rpc()})
    except FactoryGap as exc:
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": str(exc),
                    "data": {
                        "info": exc.info.to_json(),
                        "factoryAudit": exc.audit_row.to_json(),
                    },
                },
            }
        )
    except Exception as exc:
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": str(exc),
                    "data": traceback.format_exc(),
                },
            }
        )


def _handle_lift_audit_only(
    msg_id: Any,
    *,
    workspace_root: str,
    source_paths: List[Any],
    contract_bindings: list,
) -> None:
    root = Path(workspace_root).resolve()
    walkers = []
    for path in _iter_python_files(workspace_root, source_paths):
        full_path = Path(path)
        try:
            rel_path = full_path.resolve().relative_to(root).as_posix()
        except ValueError:
            rel_path = full_path.name
        source = full_path.read_text(encoding="utf-8")

        def walk(
            *,
            path: str = path,
            source: str = source,
            rel_path: str = rel_path,
        ) -> object:
            try:
                return lift_source(
                    path,
                    source,
                    memento_file=rel_path,
                    contract_bindings=contract_bindings,
                )
            except ValueError as exc:
                if str(exc) == NO_SOURCE_SITES_MESSAGE:
                    return None
                raise

        walkers.append((path, walk))

    gaps = collect_construction_gaps(walkers)
    if gaps:
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": "audit-only construction gaps",
                    "data": {
                        "auditOnlyGaps": [gap.to_json() for gap in gaps],
                    },
                },
            }
        )
        return
    _send(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": LiftReportPayloadDto(source_ledger={}).to_rpc(),
        }
    )


def _merge_source_ledger(
    current: Dict[str, int],
    incoming: Dict[str, int] | None,
) -> None:
    if incoming is None:
        return
    for key, value in incoming.items():
        current[key] = current.get(key, 0) + int(value)


def _handle_resolve_dependency_proofs(msg_id: Any, params: Dict[str, Any]) -> None:
    """Surface dependency `.proof` files from the project's `.sugar/imports/` so the
    rust verifier folds the vendor universe into the proof pool. Mirrors lsp.py's
    handler -- the factory kit must answer this for cross-project federation."""
    import base64

    project_root = str(
        params.get("project_root") or params.get("workspace_root") or "."
    )
    imports_dir = Path(project_root) / ".sugar" / "imports"
    proofs: List[Dict[str, Any]] = []
    if imports_dir.is_dir():
        for path in sorted(imports_dir.glob("blake3-512_*.proof")):
            if not path.is_file():
                continue
            # Normalize the on-disk filename stem (blake3-512_<hex>) to the
            # canonical colon form (blake3-512:<hex>) so the Rust verifier's
            # Rule-1 check (expected_cid == blake3_512_of(bytes)) compares
            # apples-to-apples.  The filename uses underscore for Windows
            # path-safety; the in-memory CID always uses colon.
            stem = path.name[: -len(".proof")]
            cid = cid_from_proof_stem(stem) or stem
            proofs.append(
                {
                    "cid": cid,
                    "bytes_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
                    "source": f"sugar-imports:{path.name}",
                }
            )
    _send({"jsonrpc": "2.0", "id": msg_id, "result": {"proofs": proofs}})


def main(argv: Optional[List[str]] = None) -> None:
    argv = argv or []
    audit_only = "--audit-only" in argv
    while True:
        msg = _recv()
        if msg is None:
            break
        if msg is PARSE_ERROR:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": "parse error: line was not a JSON-RPC object",
                    },
                }
            )
            continue
        msg_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params", {})

        if method == "initialize":
            _handle_initialize(msg_id)
        elif method == KIT_DECLARATION_RPC_METHOD:
            _send({"jsonrpc": "2.0", "id": msg_id, "result": _kit_declaration_result()})
        elif method == COMPONENT_PLAN_RPC_METHOD:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": _component_plan_result(
                        params if isinstance(params, dict) else {}
                    ),
                }
            )
        elif method == RESOLVE_SOURCE_MEMENTO_RPC_METHOD:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": _resolve_source_memento_result(
                        params if isinstance(params, dict) else {}
                    ),
                }
            )
        elif method == "lift":
            _handle_lift(
                msg_id,
                params if isinstance(params, dict) else {},
                audit_only=audit_only,
            )
        elif method == "sugar.plugin.lift_implications":
            _handle_lift(
                msg_id,
                params if isinstance(params, dict) else {},
                audit_only=audit_only,
            )
        elif method == "sugar.plugin.resolve_dependency_proofs":
            _handle_resolve_dependency_proofs(
                msg_id, params if isinstance(params, dict) else {}
            )
        elif method == ENUMERATE_RPC_METHOD:
            _handle_enumerate(msg_id, params if isinstance(params, dict) else {})
        elif method == "shutdown":
            _send({"jsonrpc": "2.0", "id": msg_id, "result": {"ok": True}})
            break
        else:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"method '{method}' not found",
                    },
                }
            )


if __name__ == "__main__":
    main(sys.argv[1:])
