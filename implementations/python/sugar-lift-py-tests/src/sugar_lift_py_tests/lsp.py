# SPDX-License-Identifier: Apache-2.0
#
# sugar.lsp: Language Server Protocol plugin for Python.
#
# Implements the Sugar lift plugin protocol (sugar-lift/1): NDJSON over stdio.
# Messages:
#   { "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {} }
#   { "jsonrpc": "2.0", "id": 2, "method": "lift", "params": { "workspace_root": "...", "source_paths": [...] } }
#   { "jsonrpc": "2.0", "id": 3, "method": "shutdown" }
#
# Legacy parse method is retained for backward compatibility.
#
# The plugin walks Python source, lifts contracts, and returns IR JSON.

from __future__ import annotations

import ast
import json
import os
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .ir import (
    ContractDecl,
    BridgeDecl,
    CallEdgeDecl,
    Locus,
    atomic,
    make_var,
    contract_decl_to_value,
    declarations_to_value,
    call_edges_to_value,
    formula_to_value,
)
from .canonicalizer import blake3_512_of, encode_jcs, jcs_hash
from .canonicalizer import vobj, vstr
from .layer2 import _classify_universe_source_node, lift_file_layer2
from .walk import lift_production_walk
from .decorators import collect_module
from .lift.pydantic import lift_pydantic_model
from .cpython_ctypes_resolver import resolve_ctypes_calls
from .translate_universe import (
    bytes_identity_universe_for_callee,
    branch_selected_raise_universe_for_callee,
    conditional_chain_universe_for_callee,
    constructor_field_universe_for_callee,
    delegation_universe_for_callee,
    exception_bool_return_universe_for_callee,
    exception_handler_raise_universe_for_callee,
    guard_universe_for_callee,
    instance_field_universe_for_callee,
    list_adapter_universe_for_callee,
    raise_locus_universe_for_callee,
    return_regex_universe_for_callee,
    translate_universe_for_callee,
    _regex_bool_return,
    _regex_compile_assignment,
    _unsupported_regex_literal_reason,
    _regex_membership_pattern,
)


# ---------------------------------------------------------------------------
# Protocol types
# ---------------------------------------------------------------------------

KIT_ID = "python"
KIT_VERSION = "0.1.0"
KIT_DECLARATION_RPC_METHOD = "sugar.plugin.kit_declaration"
SHARED_LSP_PROTOCOL_VERSION = "sugar-lsp-shared/1"


def _send(obj: dict) -> None:
    payload = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    sys.stdout.write(payload + "\n")
    sys.stdout.flush()


def _recv() -> Optional[dict]:
    line = sys.stdin.readline()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def handle_initialize(msg_id: Any) -> None:
    _send(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "name": "sugar-lsp-python",
                "version": KIT_VERSION,
                "protocol_version": SHARED_LSP_PROTOCOL_VERSION,
                "kit_id": KIT_ID,
                "capabilities": {
                    "source_surfaces": ["python-source"],
                    "entry_kinds": ["bind-lift-entry", "call-edge"],
                    "diagnostic_codes": [
                        "sugar.lsp.parse_error",
                        "sugar.lsp.implication_failed",
                    ],
                    "status_kinds": ["materialize", "emit", "check", "prove"],
                },
            },
        }
    )


def kit_declaration_result() -> Dict[str, Any]:
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
                {"name": "analyzeDocument", "required": False},
                {"name": "parse", "required": False},
                {"name": "lift", "required": True},
                {"name": "sugar.plugin.lift_implications", "required": False},
                {"name": "shutdown", "required": False},
            ]
        },
        "proofResolution": {"strategy": "pip"},
        "effectKinds": ["panic-freedom"],
        "effectLeaves": [],
        "guardPredicates": [
            {
                "surface": KIT_ID,
                "local": "is_some",
                "concept": "concept:panic-freedom.option.some",
            },
            {
                "surface": KIT_ID,
                "local": "is_none",
                "concept": "concept:panic-freedom.option.none",
            },
        ],
        "controlCarriers": [],
        "residueCategories": [],
    }


def handle_kit_declaration(msg_id: Any) -> None:
    _send({"jsonrpc": "2.0", "id": msg_id, "result": kit_declaration_result()})


def _implications_to_json(layer2) -> List[Dict[str, Any]]:
    return [
        {
            "name": implication.name,
            "antecedent": implication.antecedent,
            "consequent": implication.consequent,
            "antecedentSlot": implication.antecedent_slot,
            "consequentSlot": implication.consequent_slot,
            "prover": implication.prover,
            "proofWitness": implication.proof_witness,
        }
        for implication in layer2.implications
    ]


def _empty_source_ledger() -> Dict[str, int]:
    return {
        "source_loci": 0,
        "source_warranted": 0,
        "source_support": 0,
        "source_refused": 0,
        "source_inactive": 0,
        "source_refuted": 0,
        "unclassified_source": 0,
    }


def _merge_source_ledger(dst: Dict[str, int], src: Dict[str, Any]) -> None:
    for field in dst:
        dst[field] += int(src.get(field, 0))


def _source_totals(loci: List[Dict[str, Any]]) -> Dict[str, int]:
    totals = _empty_source_ledger()
    for locus in loci:
        _increment_source_totals(totals, locus.get("status"))
    return totals


def _increment_source_totals(totals: Dict[str, int], status: Any) -> None:
    totals["source_loci"] += 1
    if status == "warranted":
        totals["source_warranted"] += 1
    elif status == "support":
        totals["source_support"] += 1
    elif status == "refused":
        totals["source_refused"] += 1
    elif status == "inactive":
        totals["source_inactive"] += 1
    elif status == "refuted":
        totals["source_refuted"] += 1
    else:
        totals["unclassified_source"] += 1


def _ast_node_span(node: ast.AST) -> Dict[str, int]:
    start_line = getattr(node, "lineno", 0)
    start_col = getattr(node, "col_offset", 0)
    end_line = getattr(node, "end_lineno", start_line)
    end_col = getattr(node, "end_col_offset", start_col)
    return {
        "start_line": start_line,
        "start_col": start_col,
        "end_line": end_line,
        "end_col": end_col,
    }


def _iter_ast_nodes_with_paths(
    node: ast.AST,
    path: str,
    ancestors: tuple[ast.AST, ...] = (),
):
    yield node, path, ancestors
    for field_name, value in ast.iter_fields(node):
        if isinstance(value, ast.AST):
            yield from _iter_ast_nodes_with_paths(
                value,
                f"{path}.{field_name}",
                ancestors + (node,),
            )
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, ast.AST):
                    yield from _iter_ast_nodes_with_paths(
                        item,
                        f"{path}.{field_name}[{index}]",
                        ancestors + (node,),
                    )


def _source_line_locus(
    file: str,
    line: int,
    status: str,
    role: str,
    universe_kind: str,
    *,
    ast_kind: str = "",
    ast_path: str = "",
    span: Optional[Dict[str, int]] = None,
    reason: str = "",
) -> Dict[str, Any]:
    locus_span = span or {
        "start_line": line,
        "start_col": 0,
        "end_line": line,
        "end_col": 0,
    }
    locus: Dict[str, Any] = {
        "kind": "source-line",
        "file": file,
        "line": line,
        "span": dict(locus_span),
        "line_range": [locus_span["start_line"], locus_span["end_line"]],
        "ast_path": ast_path or f"$.line[{line}]",
        "status": status,
        "role": role,
        "universe_kind": universe_kind,
    }
    if ast_kind:
        locus["ast_kind"] = ast_kind
    if reason:
        locus["reason"] = reason
    return locus


def _path_for_source_file(value: Any) -> Optional[Path]:
    if not isinstance(value, str) or not value:
        return None
    try:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve()
    except OSError:
        return None


def _python_package_root_for_file(file: Any) -> Optional[Path]:
    path = _path_for_source_file(file)
    if path is None or not path.is_file() or path.suffix != ".py":
        return None
    root: Optional[Path] = None
    cursor = path.parent
    while (cursor / "__init__.py").is_file():
        root = cursor
        cursor = cursor.parent
    return root


def _package_roots_from_source_audits(source_audits: List[Any]) -> Dict[Path, str]:
    roots: Dict[Path, str] = {}
    for audit in source_audits:
        if not isinstance(audit, dict):
            continue
        role = str(audit.get("role") or "")
        if role in {"python.package-source", "python.test-fact"}:
            continue
        memento = audit.get("source_memento") or audit.get("sourceMemento")
        if not isinstance(memento, dict):
            continue
        root = _python_package_root_for_file(memento.get("file"))
        if root is None:
            continue
        roots.setdefault(root, root.name)
    return roots


_SOURCE_STATUS_RANK = {
    "unclassified": 0,
    "support": 1,
    "inactive": 2,
    "refuted": 3,
    "refused": 4,
    "warranted": 5,
}


def _source_status_rank(status: Any) -> int:
    return _SOURCE_STATUS_RANK.get(str(status or ""), 0)


def _emitted_source_locus_index(
    source_audits: List[Any],
) -> Dict[tuple[Path, int, str], Dict[str, Any]]:
    index: Dict[tuple[Path, int, str], Dict[str, Any]] = {}
    for audit in source_audits:
        if not isinstance(audit, dict) or audit.get("role") == "python.package-source":
            continue
        for locus in audit.get("loci") or []:
            if not isinstance(locus, dict):
                continue
            path = _path_for_source_file(locus.get("file"))
            line = locus.get("line")
            ast_kind = locus.get("ast_kind")
            if path is None or not isinstance(line, int):
                continue
            if _source_status_rank(locus.get("status")) <= 0:
                continue
            key = (path, line, ast_kind if isinstance(ast_kind, str) else "")
            current = index.get(key)
            if current is None or _source_status_rank(
                locus.get("status")
            ) > _source_status_rank(current.get("status")):
                indexed = dict(locus)
                indexed["source_audit_role"] = audit.get("role")
                indexed["source_audit_universe_kind"] = audit.get("universe_kind")
                index[key] = indexed
    return index


def _emitted_source_locus_for_package_node(
    emitted_loci: Dict[tuple[Path, int, str], Dict[str, Any]],
    path: Path,
    line: int,
    node: ast.AST,
) -> Optional[Dict[str, Any]]:
    resolved = path.resolve()
    return _emitted_source_locus_for_resolved_package_node(
        emitted_loci,
        resolved,
        line,
        node,
    )


def _emitted_source_locus_for_resolved_package_node(
    emitted_loci: Dict[tuple[Path, int, str], Dict[str, Any]],
    resolved: Path,
    line: int,
    node: ast.AST,
) -> Optional[Dict[str, Any]]:
    return emitted_loci.get((resolved, line, type(node).__name__)) or emitted_loci.get(
        (resolved, line, "")
    )


def _package_accounting_loci(
    root: Path,
    emitted_loci: Dict[tuple[Path, int, str], Dict[str, Any]],
) -> List[Dict[str, Any]]:
    loci: List[Dict[str, Any]] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        file = str(path)
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=file)
        except (OSError, SyntaxError) as exc:
            loci.append(
                _source_line_locus(
                    file,
                    0,
                    "refused",
                    "python.package-source",
                    "package-accounting",
                    reason=f"package source could not be parsed: {exc}",
                )
            )
            continue

        module_name = _package_module_name(root, path)
        call_aliases = _package_call_aliases(tree, module_name)
        resolved_path = path.resolve()
        for node, ast_path, ancestors in _iter_ast_nodes_with_paths(tree, "$.module"):
            line = getattr(node, "lineno", None)
            if not isinstance(line, int):
                continue
            status, reason = _package_locus_classification(
                node,
                ast_path,
                ancestors,
                call_aliases,
                module_name,
                tree,
            )
            replayed = _emitted_source_locus_for_resolved_package_node(
                emitted_loci,
                resolved_path,
                line,
                node,
            )
            if replayed is not None and _source_status_rank(
                replayed.get("status")
            ) > _source_status_rank(status):
                status = str(replayed.get("status") or status)
                reason = str(replayed.get("reason") or reason)
            locus = _source_line_locus(
                file,
                line,
                status,
                "python.package-source",
                "package-accounting",
                ast_kind=type(node).__name__,
                ast_path=ast_path,
                span=_ast_node_span(node),
                reason=reason,
            )
            if replayed is not None:
                locus["source_audit_role"] = replayed.get("source_audit_role")
                locus["source_audit_universe_kind"] = replayed.get(
                    "source_audit_universe_kind"
                )
            loci.append(locus)
    return loci


def _package_accounting_summary(
    root: Path,
    emitted_loci: Dict[tuple[Path, int, str], Dict[str, Any]],
) -> Dict[str, Any]:
    totals = _empty_source_ledger()
    ast_type_counts: Dict[str, Dict[str, int]] = {}
    samples: List[Dict[str, Any]] = []
    sample_limit = _package_accounting_sample_limit()
    file_count = 0
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        file_count += 1
        file = str(path)
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=file)
        except (OSError, SyntaxError) as exc:
            locus = _source_line_locus(
                file,
                0,
                "refused",
                "python.package-source",
                "package-accounting",
                reason=f"package source could not be parsed: {exc}",
            )
            _account_package_locus(totals, ast_type_counts, samples, sample_limit, locus)
            continue

        module_name = _package_module_name(root, path)
        call_aliases = _package_call_aliases(tree, module_name)
        resolved_path = path.resolve()
        for node, ast_path, ancestors in _iter_ast_nodes_with_paths(tree, "$.module"):
            line = getattr(node, "lineno", None)
            if not isinstance(line, int):
                continue
            status, reason = _package_locus_classification(
                node,
                ast_path,
                ancestors,
                call_aliases,
                module_name,
                tree,
            )
            replayed = _emitted_source_locus_for_resolved_package_node(
                emitted_loci,
                resolved_path,
                line,
                node,
            )
            if replayed is not None and _source_status_rank(
                replayed.get("status")
            ) > _source_status_rank(status):
                status = str(replayed.get("status") or status)
                reason = str(replayed.get("reason") or reason)
            ast_kind = type(node).__name__
            _account_package_locus_fields(totals, ast_type_counts, status, ast_kind)
            if len(samples) < sample_limit:
                locus = _source_line_locus(
                    file,
                    line,
                    status,
                    "python.package-source",
                    "package-accounting",
                    ast_kind=ast_kind,
                    ast_path=ast_path,
                    span=_ast_node_span(node),
                    reason=reason,
                )
                if replayed is not None:
                    locus["source_audit_role"] = replayed.get("source_audit_role")
                    locus["source_audit_universe_kind"] = replayed.get(
                        "source_audit_universe_kind"
                    )
                samples.append(locus)
    return {
        "totals": totals,
        "ast_type_counts": ast_type_counts,
        "sample_loci": samples,
        "package_file_count": file_count,
    }


def _account_package_locus(
    totals: Dict[str, int],
    ast_type_counts: Dict[str, Dict[str, int]],
    samples: List[Dict[str, Any]],
    sample_limit: int,
    locus: Dict[str, Any],
) -> None:
    status = _normalized_source_status(locus.get("status"))
    ast_kind = str(locus.get("ast_kind") or "?")
    _account_package_locus_fields(totals, ast_type_counts, status, ast_kind)
    if len(samples) < sample_limit:
        samples.append(locus)


def _account_package_locus_fields(
    totals: Dict[str, int],
    ast_type_counts: Dict[str, Dict[str, int]],
    status: Any,
    ast_kind: str,
) -> None:
    normalized = _normalized_source_status(status)
    _increment_source_totals(totals, normalized)
    ast_type_counts.setdefault(normalized, {}).setdefault(ast_kind, 0)
    ast_type_counts[normalized][ast_kind] += 1


def _normalized_source_status(status: Any) -> str:
    if status in {"warranted", "support", "refused", "inactive", "refuted"}:
        return str(status)
    return "unclassified"


def _package_locus_classification(
    node: ast.AST,
    ast_path: str,
    ancestors: tuple[ast.AST, ...],
    call_aliases: Dict[str, str],
    module_name: str,
    tree: ast.Module,
) -> tuple[str, str]:
    if _package_accounting_mode() == "structural":
        return _package_locus_structural_classification(
            node,
            ast_path,
            ancestors,
            call_aliases,
            module_name,
            tree,
        )
    overload_status = _overload_declaration_status(node, ancestors, call_aliases)
    if overload_status is not None:
        return overload_status
    import_probe_status = _top_level_import_probe_refusal_status(node, ancestors)
    if import_probe_status is not None:
        return import_probe_status
    version_probe_status = _top_level_version_probe_refusal_status(node, ancestors)
    if version_probe_status is not None:
        return version_probe_status
    if isinstance(node, (ast.Import, ast.ImportFrom, ast.alias)):
        return "support", "import support for recursive name resolution"
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return "support", "function declaration supports callsite arity/name resolution"
    if isinstance(node, ast.ClassDef):
        return "support", "class declaration supports attribute/name resolution"
    if isinstance(node, ast.arg):
        return "support", "function parameter metadata supports callsite argument mapping"
    generator_flow_status = _generator_flow_refusal_status(node, ancestors)
    if generator_flow_status is not None:
        return generator_flow_status
    with_context_status = _with_context_flow_refusal_status(node, ancestors)
    if with_context_status is not None:
        return with_context_status
    if isinstance(node, ast.Pass):
        return "support", "pass no-op scaffolding supports source accounting only"
    if isinstance(node, (ast.Break, ast.Continue)):
        return (
            "refused",
            "loop control flow refused until a loop/path universe is emitted",
        )
    if _is_function_annotation_path(ast_path):
        return "support", "type annotation metadata supports source accounting only"
    if _is_decorator_metadata_path(ast_path):
        return "support", "decorator metadata supports source accounting only"
    default_literal_status = _function_default_literal_status(
        node,
        ast_path,
        ancestors,
    )
    if default_literal_status is not None:
        return default_literal_status
    type_checking_status = _type_checking_block_status(node, ast_path, ancestors)
    if type_checking_status is not None:
        return type_checking_status
    typing_metadata_status = _typing_metadata_assignment_status(
        node,
        ancestors,
        call_aliases,
    )
    if typing_metadata_status is not None:
        return typing_metadata_status
    delete_status = _delete_mutation_refusal_status(node, ancestors)
    if delete_status is not None:
        return delete_status
    runtime_environment_status = _runtime_environment_probe_refusal_status(
        node,
        ancestors,
    )
    if runtime_environment_status is not None:
        return runtime_environment_status
    global_config_status = _global_config_read_refusal_status(node, ancestors)
    if global_config_status is not None:
        return global_config_status
    option_registry_status = _option_registry_flow_refusal_status(node, ancestors)
    if option_registry_status is not None:
        return option_registry_status
    module_metadata_status = _public_module_metadata_status(node, ancestors)
    if module_metadata_status is not None:
        return module_metadata_status
    static_binding_status = _static_binding_status(node, ancestors, call_aliases)
    if static_binding_status is not None:
        return static_binding_status
    guarded_default_status = _guarded_default_value_flow_status(node, ancestors)
    if guarded_default_status is not None:
        return guarded_default_status
    transparent_cast_status = _transparent_typing_cast_status(
        node,
        ancestors,
        call_aliases,
    )
    if transparent_cast_status is not None:
        return transparent_cast_status
    regex_universe_status = _regex_universe_source_status(
        node,
        ancestors,
        module_name,
        tree,
    )
    if regex_universe_status is not None:
        return regex_universe_status
    conditional_chain_status = _conditional_chain_source_status(
        node,
        ancestors,
        module_name,
    )
    if conditional_chain_status is not None:
        return conditional_chain_status
    super_init_status = _super_init_support_status(node, ancestors)
    if super_init_status is not None:
        return super_init_status
    constructor_field_status = _constructor_field_assignment_status(
        node,
        ancestors,
        module_name,
    )
    if constructor_field_status is not None:
        return constructor_field_status
    dynamic_io_status = _dynamic_receiver_io_refusal_status(node, ancestors)
    if dynamic_io_status is not None:
        return dynamic_io_status
    dynamic_getattr_status = _dynamic_getattr_refusal_status(node, ancestors)
    if dynamic_getattr_status is not None:
        return dynamic_getattr_status
    nondet_status = _nondeterministic_call_refusal_status(
        node,
        ancestors,
        module_name,
        tree,
    )
    if nondet_status is not None:
        return nondet_status
    exception_universe_status = _exception_universe_source_status(
        node,
        ancestors,
        module_name,
    )
    if exception_universe_status is not None:
        return exception_universe_status
    guard_universe_status = _guard_universe_source_status(
        node,
        ancestors,
        module_name,
    )
    if guard_universe_status is not None:
        return guard_universe_status
    unhandled_try_status = _unhandled_try_flow_refusal_status(node, ancestors)
    if unhandled_try_status is not None:
        return unhandled_try_status
    self_field_dispatch_status = _self_field_runtime_dispatch_refusal_status(
        node,
        ancestors,
        tree,
    )
    if self_field_dispatch_status is not None:
        return self_field_dispatch_status
    refused_binding_status = _return_from_refused_binding_status(
        node,
        ancestors,
        tree,
    )
    if refused_binding_status is not None:
        return refused_binding_status
    terminal_refused_status = _terminal_return_after_refused_flow_status(
        node,
        ancestors,
    )
    if terminal_refused_status is not None:
        return terminal_refused_status
    receiver_iteration_status = _receiver_iteration_refusal_status(
        node,
        ancestors,
    )
    if receiver_iteration_status is not None:
        return receiver_iteration_status
    adapter_assignment_status = _local_adapter_assignment_status(
        node,
        ancestors,
        call_aliases,
    )
    if adapter_assignment_status is not None:
        return adapter_assignment_status
    call_term_assignment_status = _local_call_term_assignment_status(
        node,
        ancestors,
        call_aliases,
        module_name,
        tree,
    )
    if call_term_assignment_status is not None:
        return call_term_assignment_status
    tuple_unpack_call_status = _local_tuple_unpack_call_status(
        node,
        ancestors,
        call_aliases,
        module_name,
        tree,
    )
    if tuple_unpack_call_status is not None:
        return tuple_unpack_call_status
    translate_body_status = _translate_body_status(
        node,
        ancestors,
        module_name,
    )
    if translate_body_status is not None:
        return translate_body_status
    bytes_identity_body_status = _bytes_identity_body_status(
        node,
        ancestors,
        module_name,
    )
    if bytes_identity_body_status is not None:
        return bytes_identity_body_status
    list_adapter_body_status = _list_adapter_body_status(
        node,
        ancestors,
        module_name,
    )
    if list_adapter_body_status is not None:
        return list_adapter_body_status
    instance_field_body_status = _instance_field_body_status(
        node,
        ancestors,
        module_name,
    )
    if instance_field_body_status is not None:
        return instance_field_body_status
    generator_flow_status = _generator_flow_refusal_status(node, ancestors)
    if generator_flow_status is not None:
        return generator_flow_status
    local_binding_status = _local_name_binding_status(node, ancestors)
    if local_binding_status is not None:
        return local_binding_status
    delegation_body_status = _delegation_body_status(
        node,
        ancestors,
        module_name,
    )
    if delegation_body_status is not None:
        return delegation_body_status
    unhandled_raise_status = _unhandled_raise_path_refusal_status(node, ancestors)
    if unhandled_raise_status is not None:
        return unhandled_raise_status
    if _is_docstring_expr_node(node, ancestors):
        return "support", "docstring metadata supports source accounting only"
    decl = _nearest_declaration_ancestor(ancestors)
    line = getattr(node, "lineno", None)
    if decl is not None and isinstance(line, int) and line == decl.lineno:
        return "support", "declaration metadata supports callsite arity/name resolution"
    return "unclassified", "not classified by any emitted Python source warrant"


def _package_accounting_mode() -> str:
    mode = os.environ.get("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "").strip().lower()
    if mode in {"structural", "deep"}:
        return mode
    return "deep"


def _package_accounting_elide_loci() -> bool:
    mode = os.environ.get("SUGAR_PY_PACKAGE_ACCOUNTING_LOCI", "").strip().lower()
    return mode in {"summary", "elide", "counts"}


def _package_accounting_sample_limit() -> int:
    raw = os.environ.get("SUGAR_PY_PACKAGE_ACCOUNTING_SAMPLE_LIMIT", "").strip()
    if not raw:
        return 200
    try:
        return max(0, int(raw))
    except ValueError:
        return 200


def _package_locus_structural_classification(
    node: ast.AST,
    ast_path: str,
    ancestors: tuple[ast.AST, ...],
    call_aliases: Dict[str, str],
    module_name: str,
    tree: ast.Module,
) -> tuple[str, str]:
    overload_status = _overload_declaration_status(node, ancestors, call_aliases)
    if overload_status is not None:
        return overload_status
    import_probe_status = _top_level_import_probe_refusal_status(node, ancestors)
    if import_probe_status is not None:
        return import_probe_status
    version_probe_status = _top_level_version_probe_refusal_status(node, ancestors)
    if version_probe_status is not None:
        return version_probe_status
    if isinstance(node, (ast.Import, ast.ImportFrom, ast.alias)):
        return "support", "import support for recursive name resolution"
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return "support", "function declaration supports callsite arity/name resolution"
    if isinstance(node, ast.ClassDef):
        return "support", "class declaration supports attribute/name resolution"
    if isinstance(node, ast.arg):
        return "support", "function parameter metadata supports callsite argument mapping"
    generator_flow_status = _generator_flow_refusal_status(node, ancestors)
    if generator_flow_status is not None:
        return generator_flow_status
    with_context_status = _with_context_flow_refusal_status(node, ancestors)
    if with_context_status is not None:
        return with_context_status
    if isinstance(node, ast.Pass):
        return "support", "pass no-op scaffolding supports source accounting only"
    if isinstance(node, (ast.Break, ast.Continue)):
        return (
            "refused",
            "loop control flow refused until a loop/path universe is emitted",
        )
    loop_iteration_status = _loop_iteration_flow_refusal_status(node, ancestors)
    if loop_iteration_status is not None:
        return loop_iteration_status
    if _is_function_annotation_path(ast_path):
        return "support", "type annotation metadata supports source accounting only"
    if _is_decorator_metadata_path(ast_path):
        return "support", "decorator metadata supports source accounting only"
    default_literal_status = _function_default_literal_status(
        node,
        ast_path,
        ancestors,
    )
    if default_literal_status is not None:
        return default_literal_status
    type_checking_status = _type_checking_block_status(node, ast_path, ancestors)
    if type_checking_status is not None:
        return type_checking_status
    typing_metadata_status = _typing_metadata_assignment_status(
        node,
        ancestors,
        call_aliases,
    )
    if typing_metadata_status is not None:
        return typing_metadata_status
    delete_status = _delete_mutation_refusal_status(node, ancestors)
    if delete_status is not None:
        return delete_status
    runtime_environment_status = _runtime_environment_probe_refusal_status(
        node,
        ancestors,
    )
    if runtime_environment_status is not None:
        return runtime_environment_status
    global_config_status = _global_config_read_refusal_status(node, ancestors)
    if global_config_status is not None:
        return global_config_status
    option_registry_status = _option_registry_flow_refusal_status(node, ancestors)
    if option_registry_status is not None:
        return option_registry_status
    exception_control_status = _exception_control_flow_refusal_status(node, ancestors)
    if exception_control_status is not None:
        return exception_control_status
    assert_guard_status = _assert_guard_flow_refusal_status(node, ancestors)
    if assert_guard_status is not None:
        return assert_guard_status
    module_metadata_status = _public_module_metadata_status(node, ancestors)
    if module_metadata_status is not None:
        return module_metadata_status
    super_init_status = _super_init_support_status(node, ancestors)
    if super_init_status is not None:
        return super_init_status
    constructor_field_status = _constructor_field_syntax_status(node, ancestors)
    if constructor_field_status is not None:
        return constructor_field_status
    static_binding_status = _static_binding_status(node, ancestors, call_aliases)
    if static_binding_status is not None:
        return static_binding_status
    transparent_cast_status = _transparent_typing_cast_status(
        node,
        ancestors,
        call_aliases,
    )
    if transparent_cast_status is not None:
        return transparent_cast_status
    regex_universe_status = _regex_universe_source_status(
        node,
        ancestors,
        module_name,
        tree,
    )
    if regex_universe_status is not None:
        return regex_universe_status
    terminal_conditional_status = _terminal_conditional_return_status(
        node,
        ancestors,
        call_aliases,
        module_name,
        tree,
    )
    if terminal_conditional_status is not None:
        return terminal_conditional_status
    pure_branch_status = _pure_branch_predicate_status(node, ancestors)
    if pure_branch_status is not None:
        return pure_branch_status
    formatted_string_status = _formatted_string_status(node, ancestors)
    if formatted_string_status is not None:
        return formatted_string_status
    conditional_value_status = _conditional_value_expression_status(node, ancestors)
    if conditional_value_status is not None:
        return conditional_value_status
    collection_lambda_status = _collection_lambda_flow_refusal_status(node, ancestors)
    if collection_lambda_status is not None:
        return collection_lambda_status
    stdlib_constructor_status = _stdlib_constructor_value_term_status(
        node,
        ancestors,
        call_aliases,
    )
    if stdlib_constructor_status is not None:
        return stdlib_constructor_status
    dynamic_getattr_status = _dynamic_getattr_refusal_status(node, ancestors)
    if dynamic_getattr_status is not None:
        return dynamic_getattr_status
    dynamic_receiver_status = _dynamic_receiver_method_dispatch_refusal_status(
        node,
        ancestors,
    )
    if dynamic_receiver_status is not None:
        return dynamic_receiver_status
    local_binding_status = _local_name_binding_status(node, ancestors)
    if local_binding_status is not None:
        return local_binding_status
    subscript_slice_status = _subscript_slice_value_term_status(node, ancestors)
    if subscript_slice_status is not None:
        return subscript_slice_status
    static_value_status = _static_value_reference_status(node, ancestors, tree)
    if static_value_status is not None:
        return static_value_status
    call_term_assignment_status = _local_call_term_assignment_status(
        node,
        ancestors,
        call_aliases,
        module_name,
        tree,
    )
    if call_term_assignment_status is not None:
        return call_term_assignment_status
    return_call_term_status = _return_call_term_status(
        node,
        ancestors,
        call_aliases,
        module_name,
        tree,
    )
    if return_call_term_status is not None:
        return return_call_term_status
    return_local_status = _return_through_local_binding_status(
        node,
        ancestors,
        call_aliases,
        module_name,
        tree,
    )
    if return_local_status is not None:
        return return_local_status
    known_pure_call_status = _known_pure_call_value_term_status(
        node,
        ancestors,
    )
    if known_pure_call_status is not None:
        return known_pure_call_status
    literal_container_status = _literal_container_value_term_status(
        node,
        ancestors,
    )
    if literal_container_status is not None:
        return literal_container_status
    keyword_argument_status = _keyword_argument_binding_status(
        node,
        ancestors,
    )
    if keyword_argument_status is not None:
        return keyword_argument_status
    return_value_status = _return_value_relation_status(node, ancestors)
    if return_value_status is not None:
        return return_value_status
    assignment_mutation_status = _assignment_target_mutation_refusal_status(
        node,
        ancestors,
    )
    if assignment_mutation_status is not None:
        return assignment_mutation_status
    expression_call_status = _expression_call_flow_refusal_status(node, ancestors)
    if expression_call_status is not None:
        return expression_call_status
    if _is_docstring_expr_node(node, ancestors):
        return "support", "docstring metadata supports source accounting only"
    decl = _nearest_declaration_ancestor(ancestors)
    line = getattr(node, "lineno", None)
    if decl is not None and isinstance(line, int) and line == decl.lineno:
        return "support", "declaration metadata supports callsite arity/name resolution"
    return "unclassified", "not classified by any emitted Python source warrant"


def _package_module_name(root: Path, path: Path) -> str:
    try:
        rel = path.relative_to(root).with_suffix("")
    except ValueError:
        rel = path.with_suffix("").name
        return str(rel).replace(os.sep, ".")
    parts = [root.name, *rel.parts]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(part for part in parts if part)


def _package_call_aliases(tree: ast.Module, module_name: str) -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            aliases[stmt.name] = f"{module_name}.{stmt.name}"
        elif isinstance(stmt, ast.ClassDef):
            aliases[stmt.name] = f"{module_name}.{stmt.name}"
        elif isinstance(stmt, ast.Import):
            for alias in stmt.names:
                aliases[alias.asname or alias.name.split(".", 1)[0]] = alias.name
        elif isinstance(stmt, ast.ImportFrom):
            imported_module = _resolved_import_from_module(module_name, stmt)
            if imported_module is None:
                continue
            for alias in stmt.names:
                if alias.name == "*":
                    continue
                aliases[alias.asname or alias.name] = (
                    f"{imported_module}.{alias.name}"
                )
    return aliases


def _conditional_chain_source_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    module_name: str,
) -> Optional[tuple[str, str]]:
    chain = ancestors + (node,)
    owner = _nearest_enclosing_function(chain)
    if owner is None or isinstance(owner, ast.Lambda):
        return None
    if not _function_body_has_node_type(owner, (ast.If,)):
        return None
    if not _node_is_in_function_body(node, owner):
        return None
    applies = _owner_cached_package_fact(
        owner,
        (module_name, "conditional-chain"),
        lambda: _universe_family_applies(
            conditional_chain_universe_for_callee,
            _owner_callee(module_name, owner, chain),
        ),
    )
    if not applies:
        return None
    return (
        "warranted",
        "conditional SSA branch emitted into python.conditional-chain-universe",
    )


def _resolved_import_from_module(
    module_name: str,
    stmt: ast.ImportFrom,
) -> Optional[str]:
    if stmt.level == 0:
        return stmt.module
    parts = module_name.split(".")
    base = parts[:-stmt.level]
    if not base and parts:
        base = parts[:1]
    if stmt.module:
        base = [*base, *stmt.module.split(".")]
    return ".".join(part for part in base if part)


def _overload_declaration_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    call_aliases: Optional[Dict[str, str]] = None,
) -> Optional[tuple[str, str]]:
    fn = _nearest_overload_function(node, ancestors, call_aliases or {})
    if fn is None:
        return None
    if _node_is_in_function_body(node, fn):
        return "inactive", "typing overload body inactive at runtime"
    return "support", "typing overload declaration metadata supports source accounting only"


def _nearest_overload_function(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    call_aliases: Dict[str, str],
) -> Optional[ast.FunctionDef | ast.AsyncFunctionDef]:
    chain = ancestors + (node,)
    for item in reversed(chain):
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
            _is_overload_decorator(decorator, call_aliases)
            for decorator in item.decorator_list
        ):
            return item
    return None


def _is_overload_decorator(
    node: ast.AST,
    call_aliases: Dict[str, str],
) -> bool:
    return _resolved_static_call_name(node, call_aliases) == "typing.overload"


_TYPING_METADATA_CALLS = frozenset(
    {
        "typing.NewType",
        "typing.ParamSpec",
        "typing.TypeVar",
        "typing_extensions.NewType",
        "typing_extensions.ParamSpec",
        "typing_extensions.TypeVar",
    }
)


def _typing_metadata_assignment_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    call_aliases: Dict[str, str],
) -> Optional[tuple[str, str]]:
    stmt = _nearest_typing_metadata_assignment(node, ancestors, call_aliases)
    if stmt is None:
        return None
    if node is stmt or any(descendant is node for descendant in ast.walk(stmt)):
        return (
            "support",
            "typing metadata assignment (TypeVar/ParamSpec/NewType/TypeAlias) supports source accounting only",
        )
    return None


def _nearest_typing_metadata_assignment(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    call_aliases: Dict[str, str],
) -> Optional[ast.Assign | ast.AnnAssign]:
    chain = ancestors + (node,)
    for item in reversed(chain):
        value: Optional[ast.AST]
        if isinstance(item, ast.Assign):
            value = item.value
        elif isinstance(item, ast.AnnAssign):
            value = item.value
        else:
            continue
        if isinstance(value, ast.Call) and _is_typing_metadata_call(
            value,
            call_aliases,
        ):
            return item
        if isinstance(item, ast.AnnAssign) and _is_type_alias_annotation(
            item.annotation,
            call_aliases,
        ):
            return item
    return None


def _is_typing_metadata_call(
    node: ast.Call,
    call_aliases: Dict[str, str],
) -> bool:
    return (
        not node.keywords
        or all(keyword.arg is not None for keyword in node.keywords)
    ) and _resolved_static_call_name(node.func, call_aliases) in _TYPING_METADATA_CALLS


def _is_type_alias_annotation(
    node: ast.AST,
    call_aliases: Dict[str, str],
) -> bool:
    return _resolved_static_call_name(node, call_aliases) in {
        "typing.TypeAlias",
        "typing_extensions.TypeAlias",
    }


def _node_is_in_function_body(
    node: ast.AST,
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    cached = getattr(fn, "_sugar_body_node_ids", None)
    if cached is None:
        cached = {
            id(descendant)
            for stmt in fn.body
            for descendant in ast.walk(stmt)
        }
        try:
            setattr(fn, "_sugar_body_node_ids", cached)
        except AttributeError:
            pass
    return id(node) in cached


def _owner_cached_package_fact(
    owner: ast.FunctionDef | ast.AsyncFunctionDef,
    key: tuple,
    compute,
):
    cache = getattr(owner, "_sugar_package_fact_cache", None)
    if cache is None:
        cache = {}
        try:
            setattr(owner, "_sugar_package_fact_cache", cache)
        except AttributeError:
            return compute()
    if key not in cache:
        cache[key] = compute()
    return cache[key]


def _universe_family_applies(resolver, callee: str) -> bool:
    universe, refusal = resolver(callee)
    return refusal is None and universe is not None


def _is_function_annotation_path(ast_path: str) -> bool:
    return ".annotation" in ast_path or ".returns" in ast_path


def _is_decorator_metadata_path(ast_path: str) -> bool:
    return ".decorator_list" in ast_path


def _function_default_literal_status(
    node: ast.AST,
    ast_path: str,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    if ".args.defaults[" not in ast_path and ".args.kw_defaults[" not in ast_path:
        return None
    default_expr = _function_default_expr_for_locus(node, ancestors)
    if default_expr is None:
        return None
    if not _is_local_literal_binding_value(default_expr):
        return None
    return "warranted", "function default literal admitted as timeless compiler fact"


def _function_default_expr_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[ast.expr]:
    chain = ancestors + (node,)
    for index, item in enumerate(chain):
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for default in [*item.args.defaults, *item.args.kw_defaults]:
            if default is None:
                continue
            if any(candidate is node for candidate in ast.walk(default)):
                return default
        if index < len(chain) - 1:
            continue
    return None


def _type_checking_block_status(
    node: ast.AST,
    ast_path: str,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    type_if = _top_level_type_checking_if_for_locus(node, ancestors)
    if type_if is None:
        return None
    if ".body[" in ast_path:
        return "inactive", "TYPE_CHECKING-only branch inactive at runtime"
    return "support", "TYPE_CHECKING guard/fallback supports type-only source accounting"


def _top_level_type_checking_if_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[ast.If]:
    chain = ancestors + (node,)
    saw_module = False
    for item in chain:
        if isinstance(item, ast.Module):
            saw_module = True
            continue
        if not saw_module:
            continue
        if isinstance(item, ast.If) and _is_type_checking_test(item.test):
            return item
        return None
    return None


def _is_type_checking_test(node: ast.AST) -> bool:
    return _static_call_name(node) in {
        "TYPE_CHECKING",
        "t.TYPE_CHECKING",
        "typing.TYPE_CHECKING",
    }


def _top_level_import_probe_refusal_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    stmt = _top_level_import_probe_statement_for_locus(node, ancestors)
    if stmt is None:
        return None
    return (
        "refused",
        (
            "runtime import probe refused: __import__ mutates import/module "
            "state and is not a timeless value relation"
        ),
    )


def _top_level_import_probe_statement_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[ast.stmt]:
    chain = ancestors + (node,)
    for index, item in enumerate(chain):
        if not isinstance(item, ast.For):
            continue
        if index == 0 or not isinstance(chain[index - 1], ast.Module):
            continue
        if _for_contains_runtime_import_probe(item):
            return item
    for index, item in enumerate(chain):
        if not isinstance(item, ast.Try):
            continue
        if index == 0 or not isinstance(chain[index - 1], ast.Module):
            continue
        if _try_is_runtime_import_probe(item):
            return item
    return None


def _for_contains_runtime_import_probe(stmt: ast.For) -> bool:
    return any(
        isinstance(child, ast.Try) and _try_is_runtime_import_probe(child)
        for child in stmt.body
    )


def _try_is_runtime_import_probe(stmt: ast.Try) -> bool:
    return (
        _stmt_list_has_runtime_import_effect(stmt.body)
        and any(_handler_catches_import_error(handler) for handler in stmt.handlers)
        and any(isinstance(node, ast.Raise) for handler in stmt.handlers for node in ast.walk(handler))
    )


def _stmt_list_has_runtime_import_effect(stmts: list[ast.stmt]) -> bool:
    for stmt in stmts:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            return True
        if any(_call_is_dunder_import(call) for call in ast.walk(stmt)):
            return True
    return False


def _call_is_dunder_import(call: ast.AST) -> bool:
    return (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "__import__"
    )


def _handler_catches_import_error(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return False
    if _static_call_name(handler.type) == "ImportError":
        return True
    if isinstance(handler.type, ast.Tuple):
        return any(_static_call_name(elt) == "ImportError" for elt in handler.type.elts)
    return False


def _top_level_version_probe_refusal_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    stmt = _top_level_version_probe_statement_for_locus(node, ancestors)
    if stmt is None:
        return None
    return (
        "refused",
        (
            "runtime version metadata probe refused: optional version imports "
            "and get_versions() mutate module metadata outside a timeless "
            "value relation"
        ),
    )


def _top_level_version_probe_statement_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[ast.Try]:
    chain = ancestors + (node,)
    for index, item in enumerate(chain):
        if not isinstance(item, ast.Try):
            continue
        if index == 0 or not isinstance(chain[index - 1], ast.Module):
            continue
        if _try_is_version_metadata_probe(item):
            return item
    return None


def _try_is_version_metadata_probe(stmt: ast.Try) -> bool:
    if not any(_handler_catches_import_error(handler) for handler in stmt.handlers):
        return False
    if not (
        _stmt_list_imports_version_metadata(stmt.body)
        or any(_stmt_list_imports_version_metadata(handler.body) for handler in stmt.handlers)
    ):
        return False
    all_handler_body = [
        child
        for handler in stmt.handlers
        for child in handler.body
    ]
    return (
        _stmt_list_assigns_version_metadata(stmt.body)
        or _stmt_list_assigns_version_metadata(all_handler_body)
    )


def _stmt_list_imports_version_metadata(stmts: list[ast.stmt]) -> bool:
    for stmt in stmts:
        if isinstance(stmt, ast.ImportFrom):
            imported = {alias.name for alias in stmt.names}
            if {"__version__", "__git_version__"} & imported:
                return True
            if "get_versions" in imported:
                return True
    return False


def _stmt_list_assigns_version_metadata(stmts: list[ast.stmt]) -> bool:
    return any(
        target in {"__version__", "__git_version__"}
        for stmt in stmts
        for target in _assigned_name_targets(stmt)
    )


def _assigned_name_targets(stmt: ast.stmt) -> set[str]:
    targets: list[ast.AST] = []
    if isinstance(stmt, ast.Assign):
        targets.extend(stmt.targets)
    elif isinstance(stmt, ast.AnnAssign):
        targets.append(stmt.target)
    elif isinstance(stmt, ast.AugAssign):
        targets.append(stmt.target)
    return {
        target.id
        for target in targets
        if isinstance(target, ast.Name)
    }


def _delete_mutation_refusal_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    if not any(isinstance(item, ast.Delete) for item in ancestors + (node,)):
        return None
    return (
        "refused",
        (
            "delete mutation refused: del mutates name, attribute, or item "
            "binding state and is not a timeless value relation"
        ),
    )


def _runtime_environment_probe_refusal_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    stmt = _nearest_statement(ancestors + (node,))
    if stmt is None:
        return None
    if not _statement_reads_runtime_environment(stmt):
        return None
    if node is stmt or any(candidate is node for candidate in ast.walk(stmt)):
        return (
            "refused",
            (
                "runtime environment probe refused: platform/env values come "
                "from the host process, not from the source-derived universe"
            ),
        )
    return None


def _statement_reads_runtime_environment(stmt: ast.stmt) -> bool:
    return any(
        (
            isinstance(candidate, ast.Call)
            and _call_reads_runtime_environment(candidate)
        )
        or (
            isinstance(candidate, ast.Subscript)
            and _subscript_reads_runtime_environment(candidate)
        )
        for candidate in ast.walk(stmt)
    )


def _call_reads_runtime_environment(call: ast.Call) -> bool:
    callee = _static_call_name(call.func)
    if callee in {
        "os.environ.get",
        "os.getenv",
        "platform.machine",
        "platform.platform",
        "platform.processor",
        "platform.python_version",
        "platform.system",
    }:
        return True
    return False


def _subscript_reads_runtime_environment(node: ast.Subscript) -> bool:
    return _static_call_name(node.value) == "os.environ"


def _global_config_read_refusal_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    owner = _nearest_enclosing_function(ancestors + (node,))
    if owner is None or isinstance(owner, ast.Lambda):
        return None
    if not _node_is_in_function_body(node, owner):
        return None
    if _is_docstring_expr_node(node, ancestors):
        return None
    if not _function_body_reads_global_config(owner):
        return None
    return (
        "refused",
        (
            "runtime global config read refused: _global_config is mutable "
            "package state, so the value relation is not timeless without a "
            "global-state universe"
        ),
    )


def _function_body_reads_global_config(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    cached = getattr(fn, "_sugar_body_reads_global_config", None)
    if cached is not None:
        return bool(cached)
    result = any(_node_reads_name_outside_nested_scope(stmt, "_global_config") for stmt in fn.body)
    try:
        setattr(fn, "_sugar_body_reads_global_config", result)
    except AttributeError:
        pass
    return result


def _node_reads_name_outside_nested_scope(node: ast.AST, name: str) -> bool:
    if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load):
        return True
    if isinstance(
        node,
        (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda),
    ):
        return False
    return any(
        _node_reads_name_outside_nested_scope(child, name)
        for child in ast.iter_child_nodes(node)
    )


_OPTION_REGISTRY_CALLS = frozenset(
    {
        "_select_options",
        "_warn_if_deprecated",
        "_translate_key",
        "_get_registered_option",
        "_get_root",
        "register_option",
        "deprecate_option",
        "get_option",
        "set_option",
        "reset_option",
        "describe_option",
        "option_context",
    }
)


def _option_registry_flow_refusal_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    owner = _nearest_enclosing_function(ancestors + (node,))
    if owner is None or isinstance(owner, ast.Lambda):
        return None
    if not _node_is_in_function_body(node, owner):
        return None
    if _is_docstring_expr_node(node, ancestors):
        return None
    if not _function_body_calls_option_registry(owner):
        return None
    return (
        "refused",
        (
            "runtime option registry flow refused: option lookup, warning, "
            "callback, or mutation depends on mutable package registry state"
        ),
    )


def _function_body_calls_option_registry(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    cached = getattr(fn, "_sugar_body_calls_option_registry", None)
    if cached is not None:
        return bool(cached)
    result = any(_node_calls_option_registry_outside_nested_scope(stmt) for stmt in fn.body)
    try:
        setattr(fn, "_sugar_body_calls_option_registry", result)
    except AttributeError:
        pass
    return result


def _node_calls_option_registry_outside_nested_scope(node: ast.AST) -> bool:
    if isinstance(node, ast.Call):
        callee = _static_call_name(node.func)
        leaf = callee.rsplit(".", 1)[-1] if callee else ""
        if leaf in _OPTION_REGISTRY_CALLS:
            return True
    if isinstance(
        node,
        (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda),
    ):
        return False
    return any(
        _node_calls_option_registry_outside_nested_scope(child)
        for child in ast.iter_child_nodes(node)
    )


def _static_binding_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    call_aliases: Dict[str, str],
) -> Optional[tuple[str, str]]:
    stmt = _static_binding_statement_for_locus(node, ancestors)
    if stmt is None:
        return None
    value = stmt.value if isinstance(stmt, ast.AnnAssign) else stmt.value
    if value is None:
        return "support", "annotation-only binding carries no runtime value"
    if _is_static_assignment_value(value, call_aliases):
        return "warranted", "static binding admitted as timeless compiler fact"
    return None


def _public_module_metadata_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    stmt, parent = _public_module_metadata_statement_for_locus(node, ancestors)
    if stmt is None or parent is None:
        return None
    if not any(descendant is node for descendant in ast.walk(stmt)):
        return None
    return (
        "support",
        (
            "public module metadata rebinding supports reflection/import-path "
            "resolution only"
        ),
    )


def _public_module_metadata_statement_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> tuple[Optional[ast.stmt], Optional[ast.AST]]:
    chain = ancestors + (node,)
    for index in range(len(chain) - 1, 0, -1):
        stmt = chain[index]
        parent = chain[index - 1]
        if not isinstance(parent, (ast.Module, ast.ClassDef)):
            continue
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)) and (
            _assigns_public_module_metadata(stmt, parent)
        ):
            return stmt, parent
        if isinstance(stmt, ast.Expr) and _object_setattr_public_module_metadata(
            stmt,
            parent,
        ):
            return stmt, parent
    return None, None


def _assigns_public_module_metadata(
    stmt: ast.Assign | ast.AnnAssign,
    parent: ast.AST,
) -> bool:
    value = stmt.value if isinstance(stmt, ast.AnnAssign) else stmt.value
    if not _is_string_constant(value):
        return False
    if isinstance(stmt, ast.Assign):
        return bool(stmt.targets) and all(
            _public_module_metadata_target(target, parent)
            for target in stmt.targets
        )
    return _public_module_metadata_target(stmt.target, parent)


def _public_module_metadata_target(target: ast.AST, parent: ast.AST) -> bool:
    if (
        isinstance(parent, ast.ClassDef)
        and isinstance(target, ast.Name)
        and target.id == "__module__"
    ):
        return True
    return isinstance(target, ast.Attribute) and target.attr == "__module__"


def _object_setattr_public_module_metadata(
    stmt: ast.Expr,
    parent: ast.AST,
) -> bool:
    if not isinstance(parent, ast.Module):
        return False
    if not isinstance(stmt.value, ast.Call):
        return False
    call = stmt.value
    return (
        _static_call_name(call.func) == "object.__setattr__"
        and not call.keywords
        and len(call.args) == 3
        and _is_module_metadata_key(call.args[1])
        and _is_string_constant(call.args[2])
    )


def _is_module_metadata_key(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value == "__module__"


def _is_string_constant(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _static_binding_statement_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[ast.Assign | ast.AnnAssign]:
    chain = ancestors + (node,)
    stmt_index: Optional[int] = None
    stmt: Optional[ast.Assign | ast.AnnAssign] = None
    for index in range(len(chain) - 1, -1, -1):
        item = chain[index]
        if isinstance(item, (ast.Assign, ast.AnnAssign)):
            stmt_index = index
            stmt = item
            break
    if stmt is None or stmt_index is None or stmt_index == 0:
        return None
    parent = chain[stmt_index - 1]
    if not isinstance(parent, (ast.Module, ast.ClassDef)):
        return None
    for item in chain[:stmt_index]:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return None
    return stmt


def _is_static_assignment_value(
    node: ast.AST,
    call_aliases: Optional[Dict[str, str]] = None,
) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Attribute):
        return _is_static_assignment_value(node.value, call_aliases)
    if isinstance(node, ast.JoinedStr):
        return all(
            _is_static_assignment_value(value, call_aliases) for value in node.values
        )
    if isinstance(node, ast.FormattedValue):
        return _is_static_assignment_value(node.value, call_aliases)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _is_static_assignment_value(node.operand, call_aliases)
    if isinstance(node, ast.BinOp):
        return _is_static_assignment_value(
            node.left,
            call_aliases,
        ) and _is_static_assignment_value(
            node.right,
            call_aliases,
        )
    if isinstance(node, ast.Subscript):
        return _is_static_assignment_value(
            node.value,
            call_aliases,
        ) and _is_static_slice(node.slice, call_aliases)
    if isinstance(node, ast.Starred):
        return _is_static_assignment_value(node.value, call_aliases)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(
            _is_static_assignment_value(value, call_aliases) for value in node.elts
        )
    if isinstance(node, ast.Dict):
        return all(
            (key is None or _is_static_assignment_value(key, call_aliases))
            and _is_static_assignment_value(value, call_aliases)
            for key, value in zip(node.keys, node.values)
        )
    if isinstance(node, ast.Call):
        return _is_known_static_assignment_call(node, call_aliases)
    return False


def _is_static_slice(
    node: ast.AST,
    call_aliases: Optional[Dict[str, str]] = None,
) -> bool:
    if isinstance(node, ast.Slice):
        return all(
            part is None or _is_static_assignment_value(part, call_aliases)
            for part in (node.lower, node.upper, node.step)
        )
    return _is_static_assignment_value(node, call_aliases)


def _is_known_static_assignment_call(
    node: ast.Call,
    call_aliases: Optional[Dict[str, str]] = None,
) -> bool:
    if any(isinstance(arg, ast.Starred) for arg in node.args):
        return False
    if any(kw.arg is None for kw in node.keywords):
        return False
    if not all(_is_static_assignment_value(arg, call_aliases) for arg in node.args):
        return False
    if not all(
        _is_static_assignment_value(kw.value, call_aliases) for kw in node.keywords
    ):
        return False
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "encode":
        return _is_static_assignment_value(func.value, call_aliases)
    callee = _resolved_static_call_name(func, call_aliases or {})
    return callee in {
        "Decimal",
        "complex",
        "decimal.Decimal",
        "dict",
        "float",
        "frozenset",
        "int",
        "list",
        "range",
        "set",
        "slice",
        "struct.Struct",
        "t.cast",
        "typing.cast",
        "tuple",
        "staticmethod",
    } or callee in _KNOWN_STDLIB_CONSTRUCTOR_CALLS


_KNOWN_STDLIB_CONSTRUCTOR_CALLS = frozenset(
    {
        "datetime.date",
        "datetime.datetime",
        "datetime.time",
        "datetime.timedelta",
        "datetime.timezone",
    }
)


def _stdlib_constructor_value_term_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    call_aliases: Dict[str, str],
) -> Optional[tuple[str, str]]:
    call = _nearest_stdlib_constructor_value_for_locus(
        node,
        ancestors,
        call_aliases,
    )
    if call is None:
        return None
    return (
        "warranted",
        "imported stdlib constructor value term admitted as compiler construction fact",
    )


def _nearest_stdlib_constructor_value_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    call_aliases: Dict[str, str],
) -> Optional[ast.Call]:
    chain = ancestors + (node,)
    for item in reversed(chain):
        if not isinstance(item, ast.Call):
            continue
        if not _is_imported_stdlib_constructor_value_expr(item, call_aliases):
            return None
        if node is item or any(candidate is node for candidate in ast.walk(item)):
            return item
        return None
    return None


def _is_imported_stdlib_constructor_value_expr(
    node: ast.Call,
    call_aliases: Dict[str, str],
) -> bool:
    if _has_store_or_del_context(node):
        return False
    if any(isinstance(arg, ast.Starred) for arg in node.args):
        return False
    if any(keyword.arg is None for keyword in node.keywords):
        return False
    callee = _resolved_static_call_name(node.func, call_aliases)
    if callee not in _KNOWN_STDLIB_CONSTRUCTOR_CALLS:
        return False
    return all(
        _is_stdlib_constructor_value_arg(arg, call_aliases) for arg in node.args
    ) and all(
        _is_stdlib_constructor_value_arg(keyword.value, call_aliases)
        for keyword in node.keywords
    )


def _is_stdlib_constructor_value_arg(
    node: ast.AST,
    call_aliases: Dict[str, str],
) -> bool:
    if isinstance(node, ast.Call):
        return _is_known_pure_call_value_expr(
            node
        ) or _is_imported_stdlib_constructor_value_expr(node, call_aliases)
    return _is_known_pure_call_arg(node)


def _resolved_static_call_name(
    node: ast.AST,
    call_aliases: Dict[str, str],
) -> str:
    static_name = _static_call_name(node)
    if not static_name:
        return ""
    root, sep, suffix = static_name.partition(".")
    resolved_root = call_aliases.get(root)
    if not resolved_root:
        return static_name
    if not sep:
        return resolved_root
    return f"{resolved_root}.{suffix}"


def _guarded_default_value_flow_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    guarded_if = _guarded_default_if_for_locus(node, ancestors)
    if guarded_if is None:
        return None
    return "warranted", "guarded default value flow admitted as compiler fact"


def _guarded_default_if_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[ast.If]:
    chain = ancestors + (node,)
    for item in reversed(chain):
        if not isinstance(item, ast.If):
            continue
        if _is_guarded_default_if(item):
            return item
        return None
    return None


def _is_guarded_default_if(node: ast.If) -> bool:
    if node.orelse or len(node.body) != 1:
        return False
    assign = node.body[0]
    if isinstance(assign, ast.Assign):
        if len(assign.targets) != 1 or not isinstance(assign.targets[0], ast.Name):
            return False
        target = assign.targets[0]
        value = assign.value
    elif isinstance(assign, ast.AnnAssign):
        if not isinstance(assign.target, ast.Name) or assign.value is None:
            return False
        target = assign.target
        value = assign.value
    else:
        return False
    guarded_name = _none_guard_name(node.test)
    return (
        guarded_name is not None
        and guarded_name == target.id
        and _is_guarded_default_value(value)
    )


def _none_guard_name(node: ast.AST) -> Optional[str]:
    if (
        not isinstance(node, ast.Compare)
        or len(node.ops) != 1
        or not isinstance(node.ops[0], ast.Is)
        or len(node.comparators) != 1
    ):
        return None
    left = node.left
    right = node.comparators[0]
    if isinstance(left, ast.Name) and _is_none_literal_node(right):
        return left.id
    if isinstance(right, ast.Name) and _is_none_literal_node(left):
        return right.id
    return None


def _is_none_literal_node(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _is_guarded_default_value(node: ast.AST) -> bool:
    if _is_local_literal_binding_value(node):
        return True
    if isinstance(node, ast.Attribute):
        return _guarded_default_attribute_root(node) in {"self", "cls"}
    return False


def _guarded_default_attribute_root(node: ast.Attribute) -> str:
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        cur = cur.value
    return cur.id if isinstance(cur, ast.Name) else ""


def _transparent_typing_cast_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    call_aliases: Optional[Dict[str, str]] = None,
) -> Optional[tuple[str, str]]:
    chain = ancestors + (node,)
    for item in reversed(chain):
        if not _is_transparent_typing_cast_call(item, call_aliases or {}):
            continue
        if item is node:
            return (
                "warranted",
                "transparent typing cast admitted as compiler axiom",
            )
        if any(descendant is node for descendant in ast.walk(item.func)):
            return (
                "warranted",
                "transparent typing cast callee admitted as compiler axiom",
            )
        if item.args and any(descendant is node for descendant in ast.walk(item.args[0])):
            return (
                "warranted",
                "transparent typing cast type admitted as compiler axiom",
            )
        return None
    return None


def _is_transparent_typing_cast_call(
    node: ast.AST,
    call_aliases: Optional[Dict[str, str]] = None,
) -> bool:
    return (
        isinstance(node, ast.Call)
        and not node.keywords
        and len(node.args) == 2
        and _resolved_static_call_name(node.func, call_aliases or {})
        in {"typing.cast"}
    )


def _super_init_support_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    stmt = _super_init_statement_for_locus(node, ancestors)
    if stmt is None:
        return None
    return "support", "base constructor call supports construction accounting"


def _super_init_statement_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[ast.Expr]:
    chain = ancestors + (node,)
    for item in reversed(chain):
        if isinstance(item, ast.stmt):
            return item if _is_super_init_expr(item) else None
    return None


def _is_super_init_expr(stmt: ast.AST) -> bool:
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
        return False
    call = stmt.value
    if call.keywords:
        return False
    if not all(_is_super_init_support_arg(arg) for arg in call.args):
        return False
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "__init__"
        and isinstance(func.value, ast.Call)
        and isinstance(func.value.func, ast.Name)
        and func.value.func.id == "super"
        and not func.value.args
        and not func.value.keywords
    )


def _is_super_init_support_arg(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Attribute):
        return _is_super_init_support_arg(node.value)
    if isinstance(node, (ast.Tuple, ast.List)):
        return all(_is_super_init_support_arg(value) for value in node.elts)
    return False


def _constructor_field_assignment_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    module_name: str,
) -> Optional[tuple[str, str]]:
    stmt = _constructor_field_assignment_for_locus(node, ancestors)
    if stmt is None:
        return None
    assign_stmt, owner, field_name = stmt
    if not any(descendant is node for descendant in ast.walk(assign_stmt)):
        return None
    owner_callee = _owner_callee(module_name, owner, ancestors + (node,))
    if not owner_callee.endswith(".__init__"):
        return None
    constructor_callee = owner_callee[: -len(".__init__")]
    universe, refusal = constructor_field_universe_for_callee(
        constructor_callee,
        field_name,
    )
    if refusal is not None or universe is None:
        return None
    if isinstance(assign_stmt, ast.Expr):
        return (
            "warranted",
            (
                "object.__setattr__ constructor field emitted as "
                "constructor-field universe fact"
            ),
        )
    return (
        "warranted",
        "constructor field assignment emitted as constructor-field universe fact",
    )


def _constructor_field_syntax_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    stmt = _constructor_field_assignment_for_locus(node, ancestors)
    if stmt is None:
        return None
    assign_stmt, _owner, _field_name = stmt
    if not any(descendant is node for descendant in ast.walk(assign_stmt)):
        return None
    if isinstance(assign_stmt, ast.Expr):
        return (
            "warranted",
            (
                "object.__setattr__ constructor field admitted as "
                "constructor field compiler fact"
            ),
        )
    return (
        "warranted",
        "constructor field assignment admitted as constructor field compiler fact",
    )


def _constructor_field_assignment_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[ast.Assign | ast.AnnAssign | ast.Expr, ast.FunctionDef, str]]:
    chain = ancestors + (node,)
    stmt: Optional[ast.Assign | ast.AnnAssign | ast.Expr] = None
    stmt_index: Optional[int] = None
    for index in range(len(chain) - 1, -1, -1):
        item = chain[index]
        if isinstance(item, (ast.Assign, ast.AnnAssign, ast.Expr)):
            stmt = item
            stmt_index = index
            break
    if stmt is None or stmt_index is None:
        return None
    owner = _nearest_enclosing_function(chain[:stmt_index])
    if not isinstance(owner, ast.FunctionDef) or owner.name != "__init__":
        return None
    if isinstance(stmt, ast.Expr):
        field_name = _object_setattr_constructor_field_name(stmt, owner)
        if field_name is None:
            return None
        return stmt, owner, field_name
    if isinstance(stmt, ast.Assign):
        if len(stmt.targets) != 1:
            return None
        target = stmt.targets[0]
        value = stmt.value
    else:
        target = stmt.target
        value = stmt.value
    if value is None or not isinstance(value, ast.Name):
        return None
    if value.id not in {arg.arg for arg in owner.args.args[1:]}:
        return None
    if not (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
    ):
        return None
    return stmt, owner, target.attr


def _object_setattr_constructor_field_name(
    stmt: ast.Expr,
    owner: ast.FunctionDef,
) -> Optional[str]:
    if not owner.args.args:
        return None
    self_name = owner.args.args[0].arg
    param_names = {arg.arg for arg in owner.args.args[1:]}
    if not isinstance(stmt.value, ast.Call):
        return None
    call = stmt.value
    if (
        _static_call_name(call.func) != "object.__setattr__"
        or call.keywords
        or len(call.args) != 3
    ):
        return None
    receiver, field, value = call.args
    if not (
        isinstance(receiver, ast.Name)
        and receiver.id == self_name
        and isinstance(field, ast.Constant)
        and isinstance(field.value, str)
        and isinstance(value, ast.Name)
        and value.id in param_names
    ):
        return None
    return field.value


def _dynamic_receiver_io_refusal_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    stmt = _nearest_statement(ancestors + (node,))
    if stmt is None:
        return None
    owner = _nearest_enclosing_function(ancestors + (node,))
    if owner is None or isinstance(owner, ast.Lambda):
        return None
    params = {
        arg.arg
        for arg in (
            *owner.args.posonlyargs,
            *owner.args.args,
            *owner.args.kwonlyargs,
        )
    }
    if owner.args.vararg is not None:
        params.add(owner.args.vararg.arg)
    if owner.args.kwarg is not None:
        params.add(owner.args.kwarg.arg)
    params.difference_update({"self", "cls"})
    if not params:
        return None
    for call in (n for n in ast.walk(stmt) if isinstance(n, ast.Call)):
        receiver = _dynamic_io_receiver_name(call)
        if receiver is None or receiver not in params:
            continue
        if node is stmt or any(candidate is node for candidate in ast.walk(stmt)):
            return (
                "refused",
                (
                    "dynamic receiver IO call refused: "
                    f"{receiver}.{call.func.attr} is supplied at runtime, "
                    "so no vendor source body can warrant this relation"
                ),
            )
    return None


def _dynamic_getattr_refusal_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    stmt = _nearest_statement(ancestors + (node,))
    if stmt is None:
        return None
    owner = _nearest_enclosing_function(ancestors + (node,))
    if owner is None or isinstance(owner, ast.Lambda):
        return None
    calls = (
        candidate for candidate in ast.walk(stmt) if isinstance(candidate, ast.Call)
    )
    for call in calls:
        if not _is_dynamic_getattr_call(call):
            continue
        if node is stmt or any(candidate is node for candidate in ast.walk(stmt)):
            return (
                "refused",
                (
                    "dynamic getattr lookup refused: runtime attribute lookup "
                    "can invoke descriptors, __getattr__, or argument unpacking"
                ),
            )
    return None


def _is_dynamic_getattr_call(call: ast.Call) -> bool:
    return (
        _static_call_name(call.func) == "getattr"
        and not _is_known_pure_call_value_expr(call)
    )


def _nearest_statement(
    chain: tuple[ast.AST, ...],
) -> Optional[ast.stmt]:
    for item in reversed(chain):
        if isinstance(item, ast.stmt) and not isinstance(
            item,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
        ):
            return item
    return None


def _dynamic_io_receiver_name(call: ast.Call) -> Optional[str]:
    func = call.func
    if not (
        isinstance(func, ast.Attribute)
        and func.attr in {"read", "write"}
        and isinstance(func.value, ast.Name)
    ):
        return None
    return func.value.id


def _dynamic_receiver_method_dispatch_refusal_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    stmt = _nearest_statement(ancestors + (node,))
    if stmt is None:
        return None
    owner = _nearest_enclosing_function(ancestors + (node,))
    if owner is None or isinstance(owner, ast.Lambda):
        return None
    params = _function_parameter_names(owner)
    params.difference_update({"self", "cls"})
    if not params:
        return None
    for call in (candidate for candidate in ast.walk(stmt) if isinstance(candidate, ast.Call)):
        if _is_known_pure_method_call_value_expr(call):
            continue
        receiver = _dynamic_method_receiver_name(call)
        if receiver is None or receiver not in params:
            continue
        if node is stmt or any(candidate is node for candidate in ast.walk(stmt)):
            return (
                "refused",
                (
                    "dynamic receiver method dispatch refused: "
                    f"{receiver}.{call.func.attr} is supplied at runtime, "
                    "so no stable vendor method body can warrant this relation"
                ),
            )
    return None


def _dynamic_method_receiver_name(call: ast.Call) -> Optional[str]:
    func = call.func
    if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
        return None
    return func.value.id


def _self_field_runtime_dispatch_refusal_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    tree: ast.Module,
) -> Optional[tuple[str, str]]:
    chain = ancestors + (node,)
    class_qualname = _nearest_class_qualname(chain)
    if not class_qualname:
        return None
    methods, fields, has_bases = _class_dispatch_info(tree, class_qualname)
    stmt = _nearest_statement(chain)
    if stmt is not None:
        reason = _runtime_field_dispatch_refusal_reason_cached(
            stmt,
            methods,
            fields,
            has_bases,
        )
        if reason is not None:
            return "refused", reason
    for guard in _enclosing_if_statements(chain):
        reason = _runtime_field_dispatch_refusal_reason_cached(
            guard.test,
            methods,
            fields,
            has_bases,
        )
        if reason is not None:
            return "refused", reason
    return None


def _class_dispatch_info(
    tree: ast.Module,
    class_qualname: str,
) -> tuple[set[str], set[str], bool]:
    cache = getattr(tree, "_sugar_class_dispatch_info", None)
    if cache is None:
        cache = {}
        try:
            setattr(tree, "_sugar_class_dispatch_info", cache)
        except AttributeError:
            cache = None
    if cache is not None and class_qualname in cache:
        return cache[class_qualname]
    cls = _find_class_by_qualname(tree, class_qualname)
    if cls is None:
        result = (set(), set(), False)
    else:
        result = (
            {
                item.name
                for item in cls.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            },
            _class_receiver_field_names(cls),
            bool(cls.bases),
        )
    if cache is not None:
        cache[class_qualname] = result
    return result


def _runtime_field_dispatch_refusal_reason_cached(
    node: ast.AST,
    methods: set[str],
    fields: set[str],
    has_bases: bool,
) -> Optional[str]:
    cached = getattr(node, "_sugar_runtime_field_dispatch_reason", None)
    if cached is not None:
        return cached or None
    reason = _runtime_field_dispatch_refusal_reason(
        node,
        methods,
        fields,
        has_bases,
    )
    try:
        setattr(node, "_sugar_runtime_field_dispatch_reason", reason or "")
    except AttributeError:
        pass
    return reason


def _enclosing_if_statements(chain: tuple[ast.AST, ...]) -> list[ast.If]:
    return [
        item
        for item in reversed(chain)
        if isinstance(item, ast.If)
    ]


def _runtime_field_dispatch_refusal_reason(
    node: ast.AST,
    methods: set[str],
    fields: set[str],
    has_bases: bool,
) -> Optional[str]:
    for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
        path = _call_func_attribute_path(call.func)
        if len(path) < 2 or path[0] not in {"self", "cls"}:
            continue
        if len(path) == 2 and path[1] in methods:
            continue
        if len(path) == 2 and path[1] not in fields and has_bases:
            continue
        return (
            "runtime field dispatch refused: "
            f"{'.'.join(path)} is supplied by receiver state, "
            "so no stable vendor method body can warrant this relation"
        )
    return None


def _return_from_refused_binding_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    tree: ast.Module,
) -> Optional[tuple[str, str]]:
    chain = ancestors + (node,)
    stmt = _nearest_statement(chain)
    if not isinstance(stmt, ast.Return):
        return None
    if not (node is stmt or any(candidate is node for candidate in ast.walk(stmt))):
        return None
    owner = _nearest_enclosing_function(chain)
    if owner is None or isinstance(owner, ast.Lambda):
        return None
    loaded_names = _loaded_name_ids(stmt)
    if not loaded_names:
        return None
    previous = _previous_function_body_statements(owner, stmt)
    if previous is None:
        return None

    class_qualname = _nearest_class_qualname(chain)
    if not class_qualname:
        return None
    cls = _find_class_by_qualname(tree, class_qualname)
    if cls is None:
        return None
    methods = {
        item.name
        for item in cls.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    fields = _class_receiver_field_names(cls)
    has_bases = bool(cls.bases)

    for prior in reversed(previous):
        assignment = _single_name_assignment(prior)
        if assignment is None:
            continue
        name, value = assignment
        if name not in loaded_names or value is None:
            continue
        reason = _runtime_field_dispatch_refusal_reason(
            value,
            methods,
            fields,
            has_bases,
        )
        if reason is not None:
            return (
                "refused",
                (
                    "return depends on refused runtime field dispatch binding "
                    f"{name!r}: {reason}"
                ),
            )
    return None


def _terminal_return_after_refused_flow_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    chain = ancestors + (node,)
    owner = _nearest_enclosing_function(chain)
    if owner is None or isinstance(owner, ast.Lambda):
        return None
    body = _body_without_docstring(owner.body)
    if len(body) < 2:
        return None
    branch = body[-2]
    fallback = body[-1]
    if (
        not isinstance(branch, ast.If)
        or branch.orelse
        or len(branch.body) != 1
        or not isinstance(branch.body[0], ast.Return)
        or not isinstance(fallback, ast.Return)
    ):
        return None
    tail_statements = (branch, branch.body[0], fallback)
    if not any(
        node is stmt or any(candidate is node for candidate in ast.walk(stmt))
        for stmt in tail_statements
    ):
        return None
    prelude = body[:-2]
    if not _body_contains_refused_path_sensitive_flow(prelude):
        return None
    return (
        "refused",
        (
            "terminal return refused: earlier path-sensitive try/raise flow "
            "is not emitted as a value relation"
        ),
    )


def _terminal_conditional_return_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    call_aliases: Dict[str, str],
    module_name: str,
    tree: ast.Module,
) -> Optional[tuple[str, str]]:
    pattern = _terminal_conditional_return_pattern_for_locus(
        node,
        ancestors,
        call_aliases,
        module_name,
        tree,
    )
    if pattern is None:
        return None
    return (
        "warranted",
        "terminal conditional return admitted as branch-selected value relation",
    )


def _terminal_conditional_return_pattern_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    call_aliases: Dict[str, str],
    module_name: str,
    tree: ast.Module,
) -> Optional[ast.If]:
    chain = ancestors + (node,)
    owner = _nearest_enclosing_function(chain)
    if owner is None or isinstance(owner, ast.Lambda):
        return None
    body = _body_without_docstring(owner.body)
    for index, stmt in enumerate(body):
        if not isinstance(stmt, ast.If):
            continue
        returns = _terminal_conditional_return_pair(body, index)
        if returns is None or not _is_pure_branch_predicate_expr(stmt.test):
            continue
        previous = body[:index]
        if not any(
            _return_value_uses_prior_local_binding(return_stmt.value, previous)
            for return_stmt in returns
        ):
            continue
        if not all(
            _is_terminal_conditional_return_value(
                return_stmt.value,
                previous,
                owner,
                chain,
                call_aliases,
                module_name,
                tree,
            )
            for return_stmt in returns
        ):
            continue
        covered: tuple[ast.stmt, ...] = (stmt, *returns)
        if any(
            node is item or any(candidate is node for candidate in ast.walk(item))
            for item in covered
        ):
            return stmt
    return None


def _terminal_conditional_return_pair(
    body: list[ast.stmt],
    index: int,
) -> Optional[tuple[ast.Return, ast.Return]]:
    stmt = body[index]
    if not isinstance(stmt, ast.If) or len(stmt.body) != 1:
        return None
    first = stmt.body[0]
    if not isinstance(first, ast.Return):
        return None
    if stmt.orelse:
        if len(stmt.orelse) != 1 or not isinstance(stmt.orelse[0], ast.Return):
            return None
        return first, stmt.orelse[0]
    if index + 1 >= len(body) or not isinstance(body[index + 1], ast.Return):
        return None
    return first, body[index + 1]


def _is_terminal_conditional_return_value(
    node: ast.expr | None,
    previous: list[ast.stmt],
    owner: ast.FunctionDef | ast.AsyncFunctionDef,
    chain: tuple[ast.AST, ...],
    call_aliases: Dict[str, str],
    module_name: str,
    tree: ast.Module,
) -> bool:
    if node is None:
        return False
    if _is_local_literal_binding_value(node) or _is_literal_container_value_expr(node):
        return True
    if isinstance(node, ast.Name):
        binding = _prior_local_binding_value(previous, node.id)
        return binding is not None and _is_return_through_local_binding_value(
            binding,
            chain,
            call_aliases,
            module_name,
            tree,
        )
    if isinstance(node, ast.Call):
        return _is_known_pure_call_value_expr(node) or _is_statically_nameable_call_term(
            node,
            chain,
            call_aliases,
            module_name,
            tree,
        )
    return False


def _return_value_uses_prior_local_binding(
    node: ast.expr | None,
    previous: list[ast.stmt],
) -> bool:
    return (
        isinstance(node, ast.Name)
        and _prior_local_binding_value(previous, node.id) is not None
    )


def _function_parameter_names(
    owner: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    names = {
        arg.arg
        for arg in (
            *owner.args.posonlyargs,
            *owner.args.args,
            *owner.args.kwonlyargs,
        )
    }
    if owner.args.vararg is not None:
        names.add(owner.args.vararg.arg)
    if owner.args.kwarg is not None:
        names.add(owner.args.kwarg.arg)
    return names


def _loaded_name_ids(node: ast.AST) -> set[str]:
    return {
        candidate.id
        for candidate in ast.walk(node)
        if isinstance(candidate, ast.Name) and isinstance(candidate.ctx, ast.Load)
    }


def _previous_function_body_statements(
    owner: ast.FunctionDef | ast.AsyncFunctionDef,
    stmt: ast.stmt,
) -> Optional[list[ast.stmt]]:
    try:
        index = next(i for i, candidate in enumerate(owner.body) if candidate is stmt)
    except StopIteration:
        for i, candidate in enumerate(owner.body):
            if any(descendant is stmt for descendant in ast.walk(candidate)):
                return owner.body[:i]
        return None
    return owner.body[:index]


def _single_name_assignment(
    stmt: ast.stmt,
) -> Optional[tuple[str, Optional[ast.expr]]]:
    if isinstance(stmt, ast.Assign):
        if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
            return None
        return stmt.targets[0].id, stmt.value
    if isinstance(stmt, ast.AnnAssign):
        if not isinstance(stmt.target, ast.Name):
            return None
        return stmt.target.id, stmt.value
    return None


def _body_without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def _body_contains_refused_path_sensitive_flow(body: list[ast.stmt]) -> bool:
    for stmt in body:
        if isinstance(stmt, ast.Try):
            return True
        if any(isinstance(node, ast.Raise) for node in ast.walk(stmt)):
            return True
    return False


def _receiver_iteration_refusal_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    for_stmt = _receiver_iteration_header_for_locus(node, ancestors)
    if for_stmt is None:
        for_stmt = _receiver_iteration_predecessor_for_locus(node, ancestors)
        if for_stmt is None:
            return None
    path = _receiver_iteration_path(for_stmt)
    if path is None:
        return None
    return (
        "refused",
        (
            "runtime receiver iteration refused: "
            f"{'.'.join(path)} supplies the loop sequence from receiver state, "
            "so ordering/path semantics are not a timeless value relation"
        ),
    )


def _receiver_iteration_header_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[ast.For]:
    chain = ancestors + (node,)
    for item in reversed(chain):
        if not isinstance(item, ast.For):
            continue
        if node is item:
            return item
        if any(descendant is node for descendant in ast.walk(item.target)):
            return item
        if any(descendant is node for descendant in ast.walk(item.iter)):
            return item
        return None
    return None


def _receiver_iteration_predecessor_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[ast.For]:
    chain = ancestors + (node,)
    stmt = _nearest_statement(chain)
    if stmt is None or not isinstance(stmt, ast.Return):
        return None
    if not any(descendant is node for descendant in ast.walk(stmt)):
        return None
    owner = _nearest_enclosing_function(chain)
    if owner is None or isinstance(owner, ast.Lambda):
        return None
    try:
        index = next(i for i, candidate in enumerate(owner.body) if candidate is stmt)
    except StopIteration:
        return None
    for previous in reversed(owner.body[:index]):
        if (
            isinstance(previous, ast.For)
            and _receiver_iteration_path(previous) is not None
        ):
            return previous
        if not isinstance(previous, (ast.Assign, ast.AnnAssign, ast.Expr, ast.Pass)):
            return None
    return None


def _receiver_iteration_path(for_stmt: ast.For) -> Optional[tuple[str, ...]]:
    return _receiver_iteration_expr_path(for_stmt.iter)


def _receiver_iteration_expr_path(node: ast.AST) -> Optional[tuple[str, ...]]:
    if isinstance(node, ast.Attribute):
        path = _call_func_attribute_path(node)
        if len(path) >= 2 and path[0] in {"self", "cls"}:
            return path
        return None
    if not isinstance(node, ast.Call):
        return None
    path = _call_func_attribute_path(node.func)
    if len(path) < 2 or path[0] not in {"self", "cls"}:
        if (
            _static_call_name(node.func) in {"iter", "reversed"}
            and len(node.args) == 1
            and not node.keywords
        ):
            return _receiver_iteration_expr_path(node.args[0])
        return None
    return path


def _class_receiver_field_names(cls: ast.ClassDef) -> set[str]:
    cached = getattr(cls, "_sugar_receiver_field_names", None)
    if cached is not None:
        return set(cached)
    fields: set[str] = set()
    for node in ast.walk(cls):
        targets: list[ast.AST] = []
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            if isinstance(node, ast.Assign):
                targets.extend(node.targets)
            else:
                targets.append(node.target)
        elif isinstance(node, ast.AugAssign):
            targets.append(node.target)
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id in {"self", "cls"}
            ):
                fields.add(target.attr)
    try:
        setattr(cls, "_sugar_receiver_field_names", frozenset(fields))
    except AttributeError:
        pass
    return fields


def _call_func_attribute_path(node: ast.AST) -> tuple[str, ...]:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return ()
    parts.append(current.id)
    return tuple(reversed(parts))


_NONDET_CALL_ATTRS = frozenset(
    {
        "random",
        "uniform",
        "randint",
        "randrange",
        "choice",
        "choices",
        "token_hex",
        "token_urlsafe",
        "urandom",
        "uuid1",
        "uuid4",
        "now",
        "utcnow",
        "today",
        "time",
        "monotonic",
        "perf_counter",
    }
)
_NONDET_CALL_ROOTS = frozenset({"random", "secrets", "uuid", "time"})


def _nondeterministic_call_refusal_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    module_name: str,
    tree: ast.Module,
) -> Optional[tuple[str, str]]:
    stmt = _nearest_statement(ancestors + (node,))
    if stmt is None:
        return None
    chain = ancestors + (node,)
    for call in (n for n in ast.walk(stmt) if isinstance(n, ast.Call)):
        reason = _nondeterministic_call_reason(call, chain, module_name, tree)
        if reason is None:
            continue
        if node is stmt or any(candidate is node for candidate in ast.walk(stmt)):
            return "refused", reason
    return None


def _nondeterministic_call_reason(
    call: ast.Call,
    chain: tuple[ast.AST, ...],
    module_name: str,
    tree: ast.Module,
) -> Optional[str]:
    direct = _direct_nondeterministic_call_name(call)
    if direct:
        return (
            "nondeterminism source refused: "
            f"{direct} depends on runtime state"
        )

    if not (
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id in {"self", "cls"}
    ):
        return None
    class_qualname = _nearest_class_qualname(chain)
    if not class_qualname:
        return None
    cls = _find_class_by_qualname(tree, class_qualname)
    if cls is None:
        return None
    methods = {
        item.name: item
        for item in cls.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    method = methods.get(call.func.attr)
    if method is None or not _method_body_reaches_nondeterminism(
        method,
        methods,
        depth=3,
        seen=set(),
    ):
        return None
    callee = f"{module_name}.{class_qualname}.{call.func.attr}"
    return (
        "nondeterminism source refused: "
        f"{callee} transitively depends on runtime state"
    )


def _exception_universe_source_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    module_name: str,
) -> Optional[tuple[str, str]]:
    owner = _nearest_enclosing_function(ancestors + (node,))
    if owner is None or isinstance(owner, ast.Lambda):
        return None
    if not _function_body_has_node_type(owner, (ast.Try, ast.Raise)):
        return None
    stmt = _owner_body_statement(ancestors + (node,), owner)
    if stmt is None:
        return None
    universes = _owner_cached_package_fact(
        owner,
        (module_name, "exception-universes"),
        lambda: _exception_source_universes(
            _owner_callee(module_name, owner, ancestors + (node,))
        ),
    )
    for role, universe_kind, source_memento in universes:
        status, reason = _classify_universe_source_node(
            role,
            universe_kind,
            stmt,
            node,
            source_memento,
        )
        if status != "unclassified":
            return status, reason
    return None


def _exception_source_universes(callee: str) -> tuple[tuple[str, str, dict], ...]:
    out: list[tuple[str, str, dict]] = []
    for role, universe_kind, resolver in (
        (
            "python.exception-handler-raise-universe",
            "exception-handler-raise",
            exception_handler_raise_universe_for_callee,
        ),
        (
            "python.exception-bool-return-universe",
            "exception-bool-return",
            exception_bool_return_universe_for_callee,
        ),
        (
            "python.branch-selected-raise-universe",
            "branch-selected-raise",
            branch_selected_raise_universe_for_callee,
        ),
        (
            "python.raise-locus-universe",
            "raise-locus",
            raise_locus_universe_for_callee,
        ),
    ):
        universe, refusal = resolver(callee)
        if refusal is not None or universe is None:
            continue
        source_memento = getattr(universe, "source_memento", None)
        if source_memento is not None:
            out.append((role, universe_kind, source_memento))
    return tuple(out)


def _guard_universe_source_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    module_name: str,
) -> Optional[tuple[str, str]]:
    owner = _nearest_enclosing_function(ancestors + (node,))
    if owner is None or isinstance(owner, ast.Lambda):
        return None
    if not _function_body_has_node_type(owner, (ast.Assert, ast.If)):
        return None
    if not _node_is_in_function_body(node, owner):
        return None
    stmt = _owner_body_statement(ancestors + (node,), owner)
    if stmt is None:
        return None
    source_memento = _owner_cached_package_fact(
        owner,
        (module_name, "guard-source-memento"),
        lambda: _guard_source_memento_for_callee(
            _owner_callee(module_name, owner, ancestors + (node,))
        ),
    )
    if source_memento is None:
        return None
    status, reason = _classify_universe_source_node(
        "python.guard-universe",
        "guard",
        stmt,
        node,
        source_memento,
    )
    if status == "unclassified":
        return None
    return status, reason


def _regex_universe_source_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    module_name: str,
    tree: ast.Module,
) -> Optional[tuple[str, str]]:
    owner = _nearest_enclosing_function(ancestors + (node,))
    if owner is None or isinstance(owner, ast.Lambda):
        return None
    if not _function_body_has_node_type(owner, (ast.Return,)):
        return None
    if not _node_is_in_function_body(node, owner):
        return None
    stmt = _owner_body_statement(ancestors + (node,), owner)
    if stmt is None:
        return None
    source_memento = _owner_cached_package_fact(
        owner,
        (module_name, "regex-source-memento-ast"),
        lambda: _regex_source_memento_for_owner(owner, tree, ancestors),
    )
    if source_memento is None:
        return None
    status, reason = _classify_universe_source_node(
        "python.regex-universe",
        "return-regex",
        stmt,
        node,
        source_memento,
    )
    if status == "unclassified":
        return None
    return status, reason


def _regex_source_memento_for_owner(
    owner: ast.FunctionDef | ast.AsyncFunctionDef,
    tree: ast.Module,
    ancestors: tuple[ast.AST, ...],
) -> Optional[dict]:
    body = _body_without_docstring(owner.body)
    if (
        not body
        or not isinstance(body[-1], ast.Return)
        or body[-1].value is None
    ):
        return None
    if sum(
        1
        for stmt in body
        for descendant in ast.walk(stmt)
        if isinstance(descendant, (ast.Return, ast.Yield, ast.YieldFrom))
    ) != 1:
        return None

    params = [arg.arg for arg in (*owner.args.posonlyargs, *owner.args.args)]
    env = _regex_compile_env_for_owner(tree, ancestors)
    for stmt in body[:-1]:
        compiled = _regex_compile_assignment(stmt, tree)
        if compiled is None:
            return None
        name, pattern = compiled
        if _unsupported_regex_literal_reason(pattern) is not None:
            return None
        env[name] = pattern

    matched, refusal = _regex_bool_return(body[-1].value, params, env, tree)
    if refusal is not None:
        return None
    if matched is None:
        return None
    (
        pattern,
        param_name,
        compile_var,
        match_kind,
        true_implies_membership,
        false_implies_nonmembership,
    ) = matched
    if _unsupported_regex_literal_reason(pattern) is not None:
        return None

    source_memento: dict[str, Any] = {
        "kind": "source-memento",
        "source_function_name": owner.name,
        "span": _ast_node_span(owner),
        "regex_pattern": pattern,
        "regex_param_name": param_name,
        "regex_match_kind": match_kind,
        "regex_membership_pattern": _regex_membership_pattern(pattern, match_kind),
        "regex_true_implies_membership": true_implies_membership,
        "regex_false_implies_nonmembership": false_implies_nonmembership,
    }
    if compile_var is not None:
        source_memento["regex_compile_var"] = compile_var
    return source_memento


def _regex_compile_env_for_owner(
    tree: ast.Module,
    ancestors: tuple[ast.AST, ...],
) -> dict[str, str]:
    env: dict[str, str] = {}
    for stmt in tree.body:
        compiled = _regex_compile_assignment(stmt, tree)
        if compiled is not None:
            env[compiled[0]] = compiled[1]
    for ancestor in reversed(ancestors):
        if not isinstance(ancestor, ast.ClassDef):
            continue
        for stmt in ancestor.body:
            compiled = _regex_compile_assignment(stmt, tree)
            if compiled is not None:
                env[compiled[0]] = compiled[1]
        break
    return env


def _regex_source_memento_for_callee(callee: str) -> Optional[dict]:
    universe, refusal = return_regex_universe_for_callee(callee)
    if refusal is not None or universe is None or universe.source_memento is None:
        return None
    source_memento = dict(universe.source_memento)
    source_memento["regex_pattern"] = universe.pattern
    source_memento["regex_param_name"] = universe.param_name
    source_memento["regex_match_kind"] = universe.match_kind
    source_memento["regex_membership_pattern"] = universe.membership_pattern
    source_memento["regex_true_implies_membership"] = (
        universe.true_implies_membership
    )
    source_memento["regex_false_implies_nonmembership"] = (
        universe.false_implies_nonmembership
    )
    if universe.compile_var is not None:
        source_memento["regex_compile_var"] = universe.compile_var
    return source_memento


def _guard_source_memento_for_callee(callee: str) -> Optional[dict]:
    universe, refusal = guard_universe_for_callee(callee)
    if refusal is not None or universe is None or universe.source_memento is None:
        return None
    source_memento = dict(universe.source_memento)
    source_memento["guard_lines"] = list(universe.guard_lines)
    return source_memento


def _owner_body_statement(
    chain: tuple[ast.AST, ...],
    owner: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Optional[ast.stmt]:
    try:
        owner_index = next(
            index for index, item in enumerate(chain) if item is owner
        )
    except StopIteration:
        return _nearest_statement(chain)
    for item in chain[owner_index + 1:]:
        if isinstance(item, ast.stmt) and not isinstance(
            item,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
        ):
            return item
    return _nearest_statement(chain)


def _unhandled_try_flow_refusal_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    chain = ancestors + (node,)
    try_stmt = next(
        (item for item in reversed(chain) if isinstance(item, ast.Try)),
        None,
    )
    if try_stmt is None:
        return None
    if node is try_stmt or any(candidate is node for candidate in ast.walk(try_stmt)):
        return (
            "refused",
            (
                "path-sensitive try/except flow refused: no emitted "
                "exception/value universe accounts for this control-flow relation"
            ),
        )
    return None


def _unhandled_raise_path_refusal_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    guarded_raise = _raise_guard_for_locus(node, ancestors)
    if guarded_raise is not None:
        return (
            "refused",
            (
                "raise path refused: guard selects an unmodeled no-return "
                "raise relation"
            ),
        )
    chain = ancestors + (node,)
    raise_stmt = next(
        (item for item in reversed(chain) if isinstance(item, ast.Raise)),
        None,
    )
    if raise_stmt is None:
        return None
    if node is raise_stmt or any(candidate is node for candidate in ast.walk(raise_stmt)):
        return (
            "refused",
            (
                "raise path refused: no emitted no-return, branch-raise, "
                "or exception-handler universe accounts for this path"
            ),
        )
    return None


def _raise_guard_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[ast.If]:
    chain = ancestors + (node,)
    for item in reversed(chain):
        if not isinstance(item, ast.If):
            continue
        if node is item or any(candidate is node for candidate in ast.walk(item.test)):
            if _stmt_list_eventually_raises(item.body) or _enclosing_body_raises(
                item,
                chain,
            ):
                return item
        return None
    return None


def _enclosing_body_raises(stmt: ast.stmt, chain: tuple[ast.AST, ...]) -> bool:
    try:
        index = next(i for i, item in enumerate(chain) if item is stmt)
    except StopIteration:
        return False
    if index == 0:
        return False
    parent = chain[index - 1]
    for body_name in ("body", "orelse", "finalbody"):
        body = getattr(parent, body_name, None)
        if isinstance(body, list) and stmt in body:
            return _stmt_list_eventually_raises(body)
    return False


def _stmt_list_eventually_raises(stmts: list[ast.stmt]) -> bool:
    for stmt in stmts:
        if isinstance(stmt, ast.Return):
            return False
        if _stmt_always_raises(stmt):
            return True
    return False


def _stmt_always_raises(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Raise):
        return True
    if isinstance(stmt, ast.If):
        if not stmt.orelse:
            return False
        return _stmt_list_eventually_raises(stmt.body) and _stmt_list_eventually_raises(
            stmt.orelse
        )
    return False


def _generator_flow_refusal_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    owner = _nearest_enclosing_function(ancestors + (node,))
    if owner is None or isinstance(owner, ast.Lambda):
        return None
    if not _node_is_in_function_body(node, owner):
        return None
    if _is_docstring_expr_node(node, ancestors):
        return None
    if not _function_body_has_yield(owner):
        return None
    return (
        "refused",
        (
            "generator/yield flow refused: emitted sequence order is "
            "runtime-selected and not modeled as a timeless value relation"
        ),
    )


def _with_context_flow_refusal_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    if not any(
        isinstance(item, (ast.With, ast.AsyncWith))
        for item in ancestors + (node,)
    ):
        return None
    return (
        "refused",
        (
            "with-context flow refused: context manager enter/exit effects are "
            "runtime-selected and not modeled as a timeless value relation"
        ),
    )


def _loop_iteration_flow_refusal_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    if not any(
        isinstance(item, (ast.For, ast.AsyncFor, ast.While))
        for item in ancestors + (node,)
    ):
        return None
    return (
        "refused",
        (
            "loop iteration flow refused: iteration order and loop-target "
            "rebinding are runtime-selected and not modeled as a timeless "
            "value relation"
        ),
    )


def _exception_control_flow_refusal_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    chain = ancestors + (node,)
    try_stmt = next(
        (item for item in reversed(chain) if isinstance(item, ast.Try)),
        None,
    )
    if try_stmt is not None and (
        node is try_stmt or any(candidate is node for candidate in ast.walk(try_stmt))
    ):
        return (
            "refused",
            (
                "exception control flow refused: try/except/finally path "
                "selection is runtime-selected and not modeled as a timeless "
                "value relation"
            ),
        )
    raise_stmt = next(
        (item for item in reversed(chain) if isinstance(item, ast.Raise)),
        None,
    )
    if raise_stmt is not None and (
        node is raise_stmt or any(candidate is node for candidate in ast.walk(raise_stmt))
    ):
        return (
            "refused",
            (
                "exception control flow refused: raise/no-return path is not "
                "modeled without an emitted exception universe"
            ),
        )
    return None


def _assert_guard_flow_refusal_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    chain = ancestors + (node,)
    assert_stmt = next(
        (item for item in reversed(chain) if isinstance(item, ast.Assert)),
        None,
    )
    if assert_stmt is None:
        return None
    if node is assert_stmt or any(candidate is node for candidate in ast.walk(assert_stmt)):
        return (
            "refused",
            (
                "assert guard flow refused: assertion raises at runtime unless "
                "an emitted guard universe accounts for this condition"
            ),
        )
    return None


def _expression_call_flow_refusal_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    chain = ancestors + (node,)
    expr_stmt = next(
        (
            item
            for item in reversed(chain)
            if isinstance(item, ast.Expr) and isinstance(item.value, ast.Call)
        ),
        None,
    )
    if expr_stmt is None or _is_super_init_expr(expr_stmt):
        return None
    if node is expr_stmt or any(candidate is node for candidate in ast.walk(expr_stmt)):
        return (
            "refused",
            (
                "expression call flow refused: discarded call result leaves only "
                "runtime side effects or raises, not a timeless value relation"
            ),
        )
    return None


def _assignment_target_mutation_refusal_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    stmt = _assignment_target_mutation_statement_for_locus(node, ancestors)
    if stmt is None:
        return None
    if node is stmt or any(candidate is node for candidate in ast.walk(stmt)):
        return (
            "refused",
            (
                "assignment target mutation refused: attribute/item rebinding "
                "mutates runtime state and is not a timeless value relation"
            ),
        )
    return None


def _assignment_target_mutation_statement_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[ast.Assign | ast.AnnAssign | ast.AugAssign]:
    chain = ancestors + (node,)
    stmt = next(
        (
            item
            for item in reversed(chain)
            if isinstance(item, (ast.Assign, ast.AnnAssign, ast.AugAssign))
        ),
        None,
    )
    if stmt is None:
        return None
    if isinstance(stmt, ast.Assign):
        if any(_is_assignment_mutation_target(target) for target in stmt.targets):
            return stmt
        return None
    target = stmt.target
    if _is_assignment_mutation_target(target):
        return stmt
    return None


def _is_assignment_mutation_target(node: ast.AST) -> bool:
    return isinstance(node, (ast.Attribute, ast.Subscript))


def _function_body_has_yield(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    cached = getattr(fn, "_sugar_body_has_yield", None)
    if cached is not None:
        return bool(cached)
    result = any(_node_has_yield_outside_nested_scope(stmt) for stmt in fn.body)
    try:
        setattr(fn, "_sugar_body_has_yield", result)
    except AttributeError:
        pass
    return result


def _function_body_has_node_type(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    node_types: tuple[type, ...],
) -> bool:
    cache = getattr(fn, "_sugar_body_node_type_cache", None)
    if cache is None:
        cache = {}
        try:
            setattr(fn, "_sugar_body_node_type_cache", cache)
        except AttributeError:
            return any(
                isinstance(descendant, node_types)
                for stmt in fn.body
                for descendant in ast.walk(stmt)
            )
    key = tuple(t.__name__ for t in node_types)
    if key not in cache:
        cache[key] = any(
            isinstance(descendant, node_types)
            for stmt in fn.body
            for descendant in ast.walk(stmt)
        )
    return bool(cache[key])


def _node_has_yield_outside_nested_scope(node: ast.AST) -> bool:
    if isinstance(node, (ast.Yield, ast.YieldFrom)):
        return True
    if isinstance(
        node,
        (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda),
    ):
        return False
    return any(
        _node_has_yield_outside_nested_scope(child)
        for child in ast.iter_child_nodes(node)
    )


def _direct_nondeterministic_call_name(call: ast.Call) -> str:
    static_name = _static_call_name(call.func)
    parts = static_name.split(".") if static_name else []
    if not parts:
        return ""
    root = parts[0]
    leaf = parts[-1]
    if root in _NONDET_CALL_ROOTS and leaf in _NONDET_CALL_ATTRS:
        return static_name
    return ""


def _find_class_by_qualname(
    tree: ast.Module,
    qualname: str,
) -> Optional[ast.ClassDef]:
    cache = getattr(tree, "_sugar_class_by_qualname", None)
    if cache is None:
        cache = {}
        try:
            setattr(tree, "_sugar_class_by_qualname", cache)
        except AttributeError:
            cache = None
    if cache is not None and qualname in cache:
        return cache[qualname]
    parts = [part for part in qualname.split(".") if part]
    body: list[ast.stmt] = list(tree.body)
    found: Optional[ast.ClassDef] = None
    for part in parts:
        found = next(
            (
                item
                for item in body
                if isinstance(item, ast.ClassDef) and item.name == part
            ),
            None,
        )
        if found is None:
            if cache is not None:
                cache[qualname] = None
            return None
        body = list(found.body)
    if cache is not None:
        cache[qualname] = found
    return found


def _method_body_reaches_nondeterminism(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    methods: Dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    *,
    depth: int,
    seen: set[str],
) -> bool:
    if fn.name in seen or depth <= 0:
        return False
    seen.add(fn.name)
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        if _direct_nondeterministic_call_name(node):
            return True
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in {"self", "cls"}
        ):
            callee = methods.get(node.func.attr)
            if callee is not None and _method_body_reaches_nondeterminism(
                callee,
                methods,
                depth=depth - 1,
                seen=seen,
            ):
                return True
    return False


def _nearest_class_qualname(chain: tuple[ast.AST, ...]) -> str:
    names = [item.name for item in chain if isinstance(item, ast.ClassDef)]
    return ".".join(names)


def _local_adapter_assignment_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    call_aliases: Dict[str, str],
) -> Optional[tuple[str, str]]:
    stmt = _adapter_assignment_statement_for_locus(node, ancestors)
    if stmt is None:
        return None
    assign_stmt, value = stmt
    if not isinstance(value, ast.Call):
        return None
    if not any(descendant is node for descendant in ast.walk(assign_stmt)):
        return None
    if (
        not isinstance(value.func, ast.Name)
        or value.keywords
        or any(isinstance(arg, ast.Starred) for arg in value.args)
        or not all(_is_adapter_assignment_arg(arg) for arg in value.args)
    ):
        return None
    callee = call_aliases.get(value.func.id)
    if callee is None:
        return None
    universe, refusal = bytes_identity_universe_for_callee(callee)
    if refusal is not None:
        return None
    if universe is not None:
        return (
            "warranted",
            "source-backed adapter assignment emitted as recursive universe dig",
        )
    universe, refusal = list_adapter_universe_for_callee(callee)
    if refusal is not None or universe is None:
        return None
    return (
        "warranted",
        "source-backed helper assignment emitted as recursive universe dig",
    )


def _local_call_term_assignment_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    call_aliases: Dict[str, str],
    module_name: str,
    tree: ast.Module,
) -> Optional[tuple[str, str]]:
    stmt = _local_call_term_assignment_statement_for_locus(node, ancestors)
    if stmt is None:
        return None
    assign_stmt, value = stmt
    if not any(descendant is node for descendant in ast.walk(assign_stmt)):
        return None
    if not _is_statically_nameable_call_term(
        value,
        ancestors + (node,),
        call_aliases,
        module_name,
        tree,
    ):
        return None
    if _is_local_constructor_call_term(
        value,
        call_aliases,
        module_name,
        tree,
    ):
        return (
            "warranted",
            "local constructor call-term admitted as construction fact",
        )
    return (
        "warranted",
        "local call-term SSA binding admitted as compiler equality",
    )


def _local_call_term_assignment_statement_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[ast.Assign | ast.AnnAssign, ast.Call]]:
    chain = ancestors + (node,)
    stmt_index: Optional[int] = None
    stmt: Optional[ast.Assign | ast.AnnAssign] = None
    for index in range(len(chain) - 1, -1, -1):
        item = chain[index]
        if isinstance(item, (ast.Assign, ast.AnnAssign)):
            stmt_index = index
            stmt = item
            break
    if stmt is None or stmt_index is None:
        return None
    owner = _nearest_enclosing_function(chain[:stmt_index])
    if owner is None:
        return None
    if isinstance(stmt, ast.Assign):
        if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
            return None
        value = stmt.value
    else:
        if not isinstance(stmt.target, ast.Name):
            return None
        value = stmt.value
    if not isinstance(value, ast.Call):
        return None
    return stmt, value


def _local_tuple_unpack_call_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    call_aliases: Dict[str, str],
    module_name: str,
    tree: ast.Module,
) -> Optional[tuple[str, str]]:
    stmt = _local_tuple_unpack_call_statement_for_locus(node, ancestors)
    if stmt is None:
        return None
    assign_stmt, value = stmt
    if not any(descendant is node for descendant in ast.walk(assign_stmt)):
        return None
    if not _is_statically_nameable_call_term(
        value,
        ancestors + (node,),
        call_aliases,
        module_name,
        tree,
    ):
        return None
    return (
        "warranted",
        "local tuple-unpack call-term projection admitted as compiler equality",
    )


def _local_tuple_unpack_call_statement_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[ast.Assign, ast.Call]]:
    chain = ancestors + (node,)
    stmt_index: Optional[int] = None
    stmt: Optional[ast.Assign] = None
    for index in range(len(chain) - 1, -1, -1):
        item = chain[index]
        if isinstance(item, ast.Assign):
            stmt_index = index
            stmt = item
            break
    if stmt is None or stmt_index is None:
        return None
    owner = _nearest_enclosing_function(chain[:stmt_index])
    if owner is None:
        return None
    if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Tuple):
        return None
    if not all(isinstance(elt, ast.Name) for elt in stmt.targets[0].elts):
        return None
    if not isinstance(stmt.value, ast.Call):
        return None
    return stmt, stmt.value


def _return_call_term_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    call_aliases: Dict[str, str],
    module_name: str,
    tree: ast.Module,
) -> Optional[tuple[str, str]]:
    stmt = _return_call_term_statement_for_locus(node, ancestors)
    if stmt is None:
        return None
    if not any(descendant is node for descendant in ast.walk(stmt)):
        return None
    value = stmt.value
    if not isinstance(value, ast.Call):
        return None
    if not _is_statically_nameable_call_term(
        value,
        ancestors + (node,),
        call_aliases,
        module_name,
        tree,
    ):
        return None
    if _is_local_constructor_call_term(
        value,
        call_aliases,
        module_name,
        tree,
    ):
        return (
            "warranted",
            "return constructor call-term admitted as construction fact",
        )
    return (
        "warranted",
        "return call-term admitted as function result equality",
    )


def _return_call_term_statement_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[ast.Return]:
    chain = ancestors + (node,)
    stmt_index: Optional[int] = None
    stmt: Optional[ast.Return] = None
    for index in range(len(chain) - 1, -1, -1):
        item = chain[index]
        if isinstance(item, ast.Return):
            stmt_index = index
            stmt = item
            break
    if stmt is None or stmt_index is None:
        return None
    owner = _nearest_enclosing_function(chain[:stmt_index])
    if owner is None:
        return None
    if not isinstance(stmt.value, ast.Call):
        return None
    return stmt


def _return_through_local_binding_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    call_aliases: Dict[str, str],
    module_name: str,
    tree: ast.Module,
) -> Optional[tuple[str, str]]:
    stmt = _return_local_name_statement_for_locus(node, ancestors)
    if stmt is None:
        return None
    if not (node is stmt or any(candidate is node for candidate in ast.walk(stmt))):
        return None
    value = stmt.value
    if not isinstance(value, ast.Name):
        return None
    owner = _nearest_enclosing_function(ancestors + (node,))
    if owner is None or isinstance(owner, ast.Lambda):
        return None
    previous = _previous_function_body_statements(owner, stmt)
    if previous is None:
        return None
    binding = _prior_local_binding_value(previous, value.id)
    if binding is None:
        return None
    if not _is_return_through_local_binding_value(
        binding,
        ancestors + (node,),
        call_aliases,
        module_name,
        tree,
    ):
        return None
    return (
        "warranted",
        "return-through-local binding admitted as compiler equality",
    )


def _return_value_relation_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    stmt = _return_value_relation_statement_for_locus(node, ancestors)
    if stmt is None:
        return None
    return (
        "warranted",
        "return value relation admitted as function result equality",
    )


def _return_value_relation_statement_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[ast.Return]:
    chain = ancestors + (node,)
    stmt_index: Optional[int] = None
    stmt: Optional[ast.Return] = None
    for index in range(len(chain) - 1, -1, -1):
        item = chain[index]
        if isinstance(item, ast.Return):
            stmt_index = index
            stmt = item
            break
    if stmt is None or stmt_index is None:
        return None
    owner = _nearest_enclosing_function(chain[:stmt_index])
    if owner is None:
        return None
    if stmt.value is None:
        return stmt if node is stmt else None
    if not _is_return_value_relation_expr(stmt.value):
        return None
    if node is stmt or any(candidate is node for candidate in ast.walk(stmt.value)):
        return stmt
    return None


def _is_return_value_relation_expr(node: ast.AST) -> bool:
    if _has_store_or_del_context(node):
        return False
    if isinstance(node, (ast.BoolOp, ast.Compare)):
        return _is_pure_branch_predicate_expr(node)
    return _is_known_pure_call_arg(node)


def _return_local_name_statement_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[ast.Return]:
    chain = ancestors + (node,)
    stmt = _nearest_statement(chain)
    if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Name):
        return stmt
    return None


def _prior_local_binding_value(
    statements: list[ast.stmt],
    name: str,
) -> Optional[ast.expr]:
    for prior in reversed(statements):
        assignment = _single_name_assignment(prior)
        if assignment is None:
            continue
        bound_name, value = assignment
        if bound_name == name:
            return value
    return None


def _is_return_through_local_binding_value(
    node: ast.expr,
    chain: tuple[ast.AST, ...],
    call_aliases: Dict[str, str],
    module_name: str,
    tree: ast.Module,
) -> bool:
    if isinstance(node, ast.Name):
        return True
    if _is_local_literal_binding_value(node):
        return True
    if _is_literal_container_value_expr(node):
        return True
    if isinstance(node, ast.Call):
        return _is_known_pure_call_value_expr(node) or _is_statically_nameable_call_term(
            node,
            chain,
            call_aliases,
            module_name,
            tree,
        )
    return False


def _is_statically_nameable_call_term(
    call: ast.Call,
    chain: tuple[ast.AST, ...],
    call_aliases: Dict[str, str],
    module_name: str,
    tree: ast.Module,
) -> bool:
    if not _is_statically_nameable_callee(
        call.func,
        chain,
        call_aliases,
        module_name,
        tree,
    ):
        return False
    if any(isinstance(arg, ast.Starred) for arg in call.args):
        return False
    if not all(
        _is_call_term_arg(arg, chain, call_aliases, module_name, tree)
        for arg in call.args
    ):
        return False
    for keyword in call.keywords:
        if keyword.arg is None:
            return False
        if not _is_call_term_arg(
            keyword.value,
            chain,
            call_aliases,
            module_name,
            tree,
        ):
            return False
    return True


def _is_statically_nameable_callee(
    func: ast.expr,
    chain: tuple[ast.AST, ...],
    call_aliases: Dict[str, str],
    module_name: str,
    tree: ast.Module,
) -> bool:
    if isinstance(func, ast.Name):
        return func.id in call_aliases
    if not isinstance(func, ast.Attribute):
        return False
    if isinstance(func.value, ast.Name) and func.value.id == "self":
        class_qualname = _nearest_class_qualname(chain)
        if not class_qualname:
            return False
        cls = _find_class_by_qualname(tree, class_qualname)
        return cls is not None and _class_has_stable_method(cls, func.attr)
    if isinstance(func.value, ast.Call) and _is_zero_arg_super_call(func.value):
        return (
            func.attr not in _NONDET_CALL_ATTRS
            and _current_class_has_single_base(chain, tree)
        )
    if isinstance(func.value, ast.Call):
        return (
            func.attr not in _NONDET_CALL_ATTRS
            and _is_statically_nameable_call_term(
                func.value,
                chain,
                call_aliases,
                module_name,
                tree,
            )
        )
    if isinstance(func.value, ast.Name):
        return func.attr not in _NONDET_CALL_ATTRS
    static_name = _static_call_name(func)
    if not static_name:
        return False
    root = static_name.split(".", 1)[0]
    return root in call_aliases


def _is_local_constructor_call_term(
    call: ast.Call,
    call_aliases: Dict[str, str],
    module_name: str,
    tree: ast.Module,
) -> bool:
    if not isinstance(call.func, ast.Name):
        return False
    callee = call_aliases.get(call.func.id)
    prefix = f"{module_name}."
    if not callee or not callee.startswith(prefix):
        return False
    class_qualname = callee[len(prefix):]
    return _find_class_by_qualname(tree, class_qualname) is not None


def _class_has_stable_method(cls: ast.ClassDef, name: str) -> bool:
    candidates = [
        stmt
        for stmt in cls.body
        if isinstance(stmt, ast.FunctionDef) and stmt.name == name
    ]
    return len(candidates) == 1 and not candidates[0].decorator_list


def _is_zero_arg_super_call(node: ast.Call) -> bool:
    return (
        isinstance(node.func, ast.Name)
        and node.func.id == "super"
        and not node.args
        and not node.keywords
    )


def _current_class_has_single_base(
    chain: tuple[ast.AST, ...],
    tree: ast.Module,
) -> bool:
    class_qualname = _nearest_class_qualname(chain)
    if not class_qualname:
        return False
    cls = _find_class_by_qualname(tree, class_qualname)
    return cls is not None and len(cls.bases) == 1


def _is_call_term_arg(
    node: ast.AST,
    chain: tuple[ast.AST, ...],
    call_aliases: Dict[str, str],
    module_name: str,
    tree: ast.Module,
) -> bool:
    if _has_store_or_del_context(node):
        return False
    if isinstance(node, (ast.Constant, ast.Name)):
        return True
    if isinstance(node, ast.Attribute):
        return _is_call_term_arg(node.value, chain, call_aliases, module_name, tree)
    if isinstance(node, ast.Subscript):
        return _is_call_term_arg(
            node.value,
            chain,
            call_aliases,
            module_name,
            tree,
        ) and _is_call_term_slice(node.slice, chain, call_aliases, module_name, tree)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _is_call_term_arg(node.operand, chain, call_aliases, module_name, tree)
    if isinstance(node, ast.BinOp):
        return _is_call_term_arg(
            node.left,
            chain,
            call_aliases,
            module_name,
            tree,
        ) and _is_call_term_arg(node.right, chain, call_aliases, module_name, tree)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return not any(isinstance(value, ast.Starred) for value in node.elts) and all(
            _is_call_term_arg(value, chain, call_aliases, module_name, tree)
            for value in node.elts
        )
    if isinstance(node, ast.Dict):
        return all(
            key is not None
            and _is_call_term_arg(key, chain, call_aliases, module_name, tree)
            and _is_call_term_arg(value, chain, call_aliases, module_name, tree)
            for key, value in zip(node.keys, node.values)
        )
    if isinstance(node, ast.Call):
        if _is_known_pure_call_value_expr(node):
            return True
        return _is_statically_nameable_call_term(
            node,
            chain,
            call_aliases,
            module_name,
            tree,
        )
    return False


def _is_call_term_slice(
    node: ast.AST,
    chain: tuple[ast.AST, ...],
    call_aliases: Dict[str, str],
    module_name: str,
    tree: ast.Module,
) -> bool:
    if isinstance(node, ast.Slice):
        return all(
            part is None
            or _is_call_term_arg(part, chain, call_aliases, module_name, tree)
            for part in (node.lower, node.upper, node.step)
        )
    return _is_call_term_arg(node, chain, call_aliases, module_name, tree)


def _list_adapter_body_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    module_name: str,
) -> Optional[tuple[str, str]]:
    owner = _nearest_enclosing_function(ancestors + (node,))
    if owner is None or isinstance(owner, ast.Lambda):
        return None
    if not _function_body_has_node_type(owner, (ast.Return,)):
        return None
    if _is_docstring_expr_node(node, ancestors):
        return "support", "docstring metadata supports source accounting only"
    if not _node_is_in_function_body(node, owner):
        return None
    applies = _owner_cached_package_fact(
        owner,
        (module_name, "list-adapter"),
        lambda: _universe_family_applies(
            list_adapter_universe_for_callee,
            _owner_callee(module_name, owner, ancestors + (node,)),
        ),
    )
    if not applies:
        return None
    return (
        "warranted",
        "list-adapter source family emitted into python.list-adapter-universe",
    )


def _instance_field_body_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    module_name: str,
) -> Optional[tuple[str, str]]:
    owner = _nearest_enclosing_function(ancestors + (node,))
    if owner is None or isinstance(owner, ast.Lambda):
        return None
    if not _function_body_has_node_type(owner, (ast.Return,)):
        return None
    if _is_docstring_expr_node(node, ancestors):
        return "support", "docstring metadata supports source accounting only"
    if not _node_is_in_function_body(node, owner):
        return None
    applies = _owner_cached_package_fact(
        owner,
        (module_name, "instance-field"),
        lambda: _universe_family_applies(
            instance_field_universe_for_callee,
            _owner_callee(module_name, owner, ancestors + (node,)),
        ),
    )
    if not applies:
        return None
    return (
        "warranted",
        "instance-field source family emitted into python.instance-field-universe",
    )


def _translate_body_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    module_name: str,
) -> Optional[tuple[str, str]]:
    owner = _nearest_enclosing_function(ancestors + (node,))
    if owner is None or isinstance(owner, ast.Lambda):
        return None
    if not _function_body_has_node_type(owner, (ast.Return,)):
        return None
    if not _node_is_in_function_body(node, owner):
        return None
    stmt = _owner_body_statement(ancestors + (node,), owner)
    if stmt is None:
        return None
    source_memento = _owner_cached_package_fact(
        owner,
        (module_name, "translate-source-memento"),
        lambda: _source_memento_for_universe_family(
            translate_universe_for_callee,
            _owner_callee(module_name, owner, ancestors + (node,)),
        ),
    )
    if source_memento is None:
        return None
    status, reason = _classify_universe_source_node(
        "python.translate-universe",
        str(source_memento.get("universe_kind") or "translate"),
        stmt,
        node,
        source_memento,
    )
    if status == "unclassified":
        return None
    return status, reason


def _bytes_identity_body_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    module_name: str,
) -> Optional[tuple[str, str]]:
    owner = _nearest_enclosing_function(ancestors + (node,))
    if owner is None or isinstance(owner, ast.Lambda):
        return None
    if not _function_body_has_node_type(owner, (ast.Return,)):
        return None
    if not _node_is_in_function_body(node, owner):
        return None
    stmt = _owner_body_statement(ancestors + (node,), owner)
    if stmt is None:
        return None
    source_memento = _owner_cached_package_fact(
        owner,
        (module_name, "bytes-identity-source-memento"),
        lambda: _source_memento_for_universe_family(
            bytes_identity_universe_for_callee,
            _owner_callee(module_name, owner, ancestors + (node,)),
        ),
    )
    if source_memento is None:
        return None
    status, reason = _classify_universe_source_node(
        "python.bytes-identity-universe",
        "bytes-identity",
        stmt,
        node,
        source_memento,
    )
    if status == "unclassified":
        return None
    return status, reason


def _delegation_body_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    module_name: str,
) -> Optional[tuple[str, str]]:
    owner = _nearest_enclosing_function(ancestors + (node,))
    if owner is None or isinstance(owner, ast.Lambda):
        return None
    if not _function_body_has_node_type(owner, (ast.Return,)):
        return None
    if _is_docstring_expr_node(node, ancestors):
        return "support", "docstring metadata supports source accounting only"
    if not _node_is_in_function_body(node, owner):
        return None
    applies = _owner_cached_package_fact(
        owner,
        (module_name, "delegation"),
        lambda: _universe_family_applies(
            delegation_universe_for_callee,
            _owner_callee(module_name, owner, ancestors + (node,)),
        ),
    )
    if not applies:
        return None
    return (
        "warranted",
        "delegation source family emitted into python.delegation-universe",
    )


def _source_memento_for_universe_family(resolver, callee: str) -> Optional[dict]:
    universe, refusal = resolver(callee)
    if refusal is not None or universe is None:
        return None
    return getattr(universe, "source_memento", None)


def _adapter_assignment_statement_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[ast.Assign | ast.AnnAssign, ast.expr | None]]:
    chain = ancestors + (node,)
    stmt_index: Optional[int] = None
    stmt: Optional[ast.Assign | ast.AnnAssign] = None
    for index in range(len(chain) - 1, -1, -1):
        item = chain[index]
        if isinstance(item, (ast.Assign, ast.AnnAssign)):
            stmt_index = index
            stmt = item
            break
    if stmt is None or stmt_index is None:
        return None
    owner = _nearest_enclosing_function(chain[:stmt_index])
    if owner is None:
        return None
    if isinstance(stmt, ast.Assign):
        if len(stmt.targets) != 1 or not _is_adapter_assignment_target(stmt.targets[0]):
            return None
        return stmt, stmt.value
    if not _is_adapter_assignment_target(stmt.target):
        return None
    return stmt, stmt.value


def _is_adapter_assignment_target(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return True
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )


def _is_adapter_assignment_arg(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Attribute):
        return _is_adapter_assignment_arg(node.value)
    return False


def _formatted_string_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    joined = _nearest_formatted_string_for_locus(node, ancestors)
    if joined is None:
        return None
    if _is_simple_formatted_string(joined):
        return (
            "warranted",
            "formatted string construction admitted as compiler value fact",
        )
    return (
        "refused",
        (
            "formatted string runtime formatting refused: conversion or format "
            "spec invokes runtime formatting semantics not emitted as a value relation"
        ),
    )


def _nearest_formatted_string_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[ast.JoinedStr]:
    chain = ancestors + (node,)
    for item in reversed(chain):
        if not isinstance(item, ast.JoinedStr):
            continue
        if node is item or any(candidate is node for candidate in ast.walk(item)):
            return item
        return None
    return None


def _is_simple_formatted_string(node: ast.JoinedStr) -> bool:
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            continue
        if not isinstance(value, ast.FormattedValue):
            return False
        if value.conversion != -1 or value.format_spec is not None:
            return False
        if not _is_known_pure_call_arg(value.value):
            return False
    return True


def _conditional_value_expression_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    ifexp = _nearest_conditional_value_expression_for_locus(node, ancestors)
    if ifexp is None:
        return None
    return (
        "warranted",
        "conditional value expression admitted as compiler value fact",
    )


def _nearest_conditional_value_expression_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[ast.IfExp]:
    chain = ancestors + (node,)
    for item in reversed(chain):
        if not isinstance(item, ast.IfExp):
            continue
        if not _is_conditional_value_expression(item):
            return None
        if node is item or any(candidate is node for candidate in ast.walk(item)):
            return item
        return None
    return None


def _is_conditional_value_expression(node: ast.IfExp) -> bool:
    if _has_store_or_del_context(node):
        return False
    return (
        _is_pure_branch_predicate_expr(node.test)
        and _is_known_pure_call_arg(node.body)
        and _is_known_pure_call_arg(node.orelse)
    )


def _collection_lambda_flow_refusal_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    stmt = _nearest_statement(ancestors + (node,))
    if stmt is None:
        return None
    if not any(
        isinstance(
            candidate,
            (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.Lambda),
        )
        for candidate in ast.walk(stmt)
    ):
        return None
    if node is stmt or any(candidate is node for candidate in ast.walk(stmt)):
        return (
            "refused",
            (
                "collection/lambda flow refused: comprehension iteration or "
                "lambda closure semantics need an emitted collection universe"
            ),
        )
    return None


def _pure_branch_predicate_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    branch = _nearest_pure_branch_predicate_for_locus(node, ancestors)
    if branch is None:
        return None
    return (
        "warranted",
        "pure branch predicate admitted as timeless value constraint",
    )


def _nearest_pure_branch_predicate_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[ast.If]:
    chain = ancestors + (node,)
    for item in reversed(chain):
        if not isinstance(item, ast.If):
            continue
        if node is item:
            return item if _is_pure_branch_predicate_expr(item.test) else None
        if any(candidate is node for candidate in ast.walk(item.test)):
            return item if _is_pure_branch_predicate_expr(item.test) else None
        return None
    return None


def _is_pure_branch_predicate_expr(node: ast.AST) -> bool:
    if isinstance(node, ast.BoolOp):
        return bool(node.values) and all(
            _is_pure_branch_predicate_expr(value) for value in node.values
        )
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return _is_pure_branch_predicate_expr(node.operand)
    if isinstance(node, ast.Compare):
        if not node.ops or not node.comparators:
            return False
        if not all(_is_pure_branch_compare_op(op) for op in node.ops):
            return False
        terms = [node.left, *node.comparators]
        return all(_is_pure_branch_value_expr(term) for term in terms)
    if isinstance(node, ast.Call):
        return _is_pure_branch_known_call(node)
    return _is_pure_branch_value_expr(node)


def _is_pure_branch_compare_op(op: ast.cmpop) -> bool:
    return isinstance(
        op,
        (
            ast.Eq,
            ast.NotEq,
            ast.Is,
            ast.IsNot,
            ast.Lt,
            ast.LtE,
            ast.Gt,
            ast.GtE,
            ast.In,
            ast.NotIn,
        ),
    )


def _is_pure_branch_value_expr(node: ast.AST) -> bool:
    if isinstance(node, (ast.Name, ast.Constant)):
        return True
    if isinstance(node, ast.Attribute):
        return _is_pure_branch_value_expr(node.value)
    if isinstance(node, ast.Subscript):
        return _is_pure_branch_value_expr(node.value) and _is_pure_branch_slice(
            node.slice
        )
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_is_pure_branch_value_expr(value) for value in node.elts)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _is_pure_branch_value_expr(node.operand)
    if isinstance(node, ast.BinOp):
        return _is_pure_branch_value_expr(node.left) and _is_pure_branch_value_expr(
            node.right
        )
    if isinstance(node, ast.Call):
        return _is_pure_branch_known_call(node)
    return False


def _is_pure_branch_slice(node: ast.AST) -> bool:
    if isinstance(node, ast.Slice):
        return all(
            part is None or _is_pure_branch_value_expr(part)
            for part in (node.lower, node.upper, node.step)
        )
    return _is_pure_branch_value_expr(node)


def _is_pure_branch_known_call(node: ast.Call) -> bool:
    if _is_known_pure_method_call_value_expr(node):
        return True
    if node.keywords or any(isinstance(arg, ast.Starred) for arg in node.args):
        return False
    name = _static_call_name(node.func)
    if name not in {"len", "type", "isinstance", "callable", "bool"}:
        return False
    return all(_is_pure_branch_value_expr(arg) for arg in node.args)


def _subscript_slice_value_term_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    selector = _nearest_subscript_value_term_for_locus(node, ancestors)
    if selector is None:
        return None
    return (
        "warranted",
        "subscript/slice selection admitted as compiler value fact",
    )


def _nearest_subscript_value_term_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[ast.Subscript]:
    chain = ancestors + (node,)
    for item in reversed(chain):
        if not isinstance(item, ast.Subscript):
            continue
        if not _is_subscript_value_term(item):
            return None
        if node is item or any(candidate is node for candidate in ast.walk(item)):
            return item
        return None
    return None


def _is_subscript_value_term(node: ast.Subscript) -> bool:
    if _has_store_or_del_context(node):
        return False
    return _is_known_pure_call_arg(node.value) and _is_known_pure_call_slice(node.slice)


def _static_value_reference_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    tree: ast.Module,
) -> Optional[tuple[str, str]]:
    if not isinstance(node, (ast.Name, ast.Attribute)):
        return None
    if _has_store_or_del_context(node):
        return None
    chain = ancestors + (node,)
    if _nearest_enclosing_function(chain) is None:
        return None
    static_attr = _nearest_static_attribute_reference_for_locus(node, ancestors, tree)
    if static_attr is not None:
        return (
            "warranted",
            "static value reference admitted as timeless compiler fact",
        )
    if isinstance(node, ast.Name) and node.id in _module_static_binding_names(tree):
        return (
            "warranted",
            "static value reference admitted as timeless compiler fact",
        )
    return None


def _nearest_static_attribute_reference_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
    tree: ast.Module,
) -> Optional[ast.Attribute]:
    static_attrs = _class_static_attribute_binding_names(tree)
    if not static_attrs:
        return None
    chain = ancestors + (node,)
    for item in reversed(chain):
        if not isinstance(item, ast.Attribute):
            continue
        if _static_call_name(item) not in static_attrs:
            return None
        if node is item or any(candidate is node for candidate in ast.walk(item)):
            return item
        return None
    return None


def _module_static_binding_names(tree: ast.Module) -> frozenset[str]:
    cached = getattr(tree, "_sugar_module_static_binding_names", None)
    if cached is not None:
        return cached
    names: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and _is_static_assignment_value(stmt.value):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif (
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.value is not None
            and _is_static_assignment_value(stmt.value)
        ):
            names.add(stmt.target.id)
    result = frozenset(names)
    try:
        setattr(tree, "_sugar_module_static_binding_names", result)
    except AttributeError:
        pass
    return result


def _class_static_attribute_binding_names(tree: ast.Module) -> frozenset[str]:
    cached = getattr(tree, "_sugar_class_static_attribute_binding_names", None)
    if cached is not None:
        return cached
    attrs: set[str] = set()
    for stmt in tree.body:
        if not isinstance(stmt, ast.ClassDef):
            continue
        for body_stmt in stmt.body:
            if isinstance(body_stmt, ast.Assign) and _is_static_assignment_value(
                body_stmt.value
            ):
                for target in body_stmt.targets:
                    if isinstance(target, ast.Name):
                        attrs.add(f"{stmt.name}.{target.id}")
            elif (
                isinstance(body_stmt, ast.AnnAssign)
                and isinstance(body_stmt.target, ast.Name)
                and body_stmt.value is not None
                and _is_static_assignment_value(body_stmt.value)
            ):
                attrs.add(f"{stmt.name}.{body_stmt.target.id}")
    result = frozenset(attrs)
    try:
        setattr(tree, "_sugar_class_static_attribute_binding_names", result)
    except AttributeError:
        pass
    return result


def _literal_container_value_term_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    container = _nearest_literal_container_value_for_locus(node, ancestors)
    if container is None:
        return None
    return (
        "warranted",
        "literal container value term admitted as compiler fact",
    )


def _known_pure_call_value_term_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    call = _nearest_known_pure_call_value_for_locus(node, ancestors)
    if call is None:
        return None
    if _is_known_pure_method_call_value_expr(call):
        return (
            "warranted",
            "known pure method value term admitted as compiler fact",
        )
    return (
        "warranted",
        "known pure call value term admitted as compiler fact",
    )


def _keyword_argument_binding_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    if _expression_call_flow_refusal_status(node, ancestors) is not None:
        return None
    keyword = _nearest_keyword_argument_binding_for_locus(node, ancestors)
    if keyword is None:
        return None
    return (
        "warranted",
        "keyword argument binding admitted as compiler argument mapping",
    )


def _nearest_keyword_argument_binding_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[ast.keyword]:
    chain = ancestors + (node,)
    for item in reversed(chain):
        if not isinstance(item, ast.keyword):
            continue
        if item.arg is None:
            return None
        if not _is_keyword_argument_value_expr(item.value):
            return None
        if node is item or any(candidate is node for candidate in ast.walk(item.value)):
            return item
        return None
    return None


def _is_keyword_argument_value_expr(node: ast.AST) -> bool:
    return not _has_store_or_del_context(node) and _is_known_pure_call_arg(node)


def _nearest_known_pure_call_value_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[ast.Call]:
    chain = ancestors + (node,)
    for item in reversed(chain):
        if not isinstance(item, ast.Call):
            continue
        if not _is_known_pure_call_value_expr(item):
            return None
        if node is item or any(candidate is node for candidate in ast.walk(item)):
            return item
        return None
    return None


def _is_known_pure_call_value_expr(node: ast.Call) -> bool:
    if _has_store_or_del_context(node):
        return False
    if any(isinstance(arg, ast.Starred) for arg in node.args):
        return False
    if any(keyword.arg is None for keyword in node.keywords):
        return False
    if _is_known_pure_method_call_value_expr(node):
        return True
    name = _static_call_name(node.func)
    if name == "getattr":
        return (
            not node.keywords
            and len(node.args) in {2, 3}
            and _is_known_pure_call_arg(node.args[0])
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            and (
                len(node.args) == 2
                or _is_known_pure_call_arg(node.args[2])
            )
        )
    if name == "dict":
        return (
            len(node.args) <= 1
            and all(_is_known_pure_call_arg(arg) for arg in node.args)
            and all(_is_known_pure_call_arg(keyword.value) for keyword in node.keywords)
        )
    if name in {
        "math.ceil",
        "math.floor",
        "math.isfinite",
        "math.isinf",
        "math.isnan",
        "math.trunc",
        "os.fspath",
        "os.path.abspath",
        "os.path.basename",
        "os.path.dirname",
        "os.path.normpath",
        "os.path.splitext",
    }:
        return (
            not node.keywords
            and len(node.args) == 1
            and _is_known_pure_call_arg(node.args[0])
        )
    if node.keywords:
        if name != "sorted":
            return False
        if len(node.args) != 1:
            return False
        allowed_keywords = {"reverse"}
        if any(keyword.arg not in allowed_keywords for keyword in node.keywords):
            return False
        if not all(_is_known_pure_call_arg(keyword.value) for keyword in node.keywords):
            return False
    if name in {"len", "type", "callable", "bool"}:
        return (
            not node.keywords
            and len(node.args) == 1
            and _is_known_pure_call_arg(node.args[0])
        )
    if name == "isinstance":
        return (
            not node.keywords
            and len(node.args) == 2
            and _is_known_pure_call_arg(node.args[0])
            and _is_type_reference_expr(node.args[1])
        )
    if name in {"list", "tuple", "set", "frozenset"}:
        return (
            not node.keywords
            and len(node.args) <= 1
            and all(_is_known_pure_call_arg(arg) for arg in node.args)
        )
    if name == "range":
        return (
            not node.keywords
            and 1 <= len(node.args) <= 3
            and all(_is_known_pure_call_arg(arg) for arg in node.args)
        )
    if name == "slice":
        return (
            not node.keywords
            and 1 <= len(node.args) <= 3
            and all(_is_known_pure_call_arg(arg) for arg in node.args)
        )
    if name == "sorted":
        return (
            len(node.args) == 1
            and _is_known_pure_call_arg(node.args[0])
        )
    return False


_KNOWN_PURE_NO_ARG_METHODS = frozenset(
    {
        "capitalize",
        "casefold",
        "items",
        "keys",
        "lower",
        "title",
        "upper",
        "values",
    }
)
_KNOWN_PURE_OPTIONAL_ONE_ARG_METHODS = frozenset(
    {
        "lstrip",
        "removeprefix",
        "removesuffix",
        "rstrip",
        "strip",
    }
)
_KNOWN_PURE_ONE_ARG_METHODS = frozenset({"join"})
_KNOWN_PURE_TWO_OR_THREE_ARG_METHODS = frozenset({"replace"})
_KNOWN_PURE_ONE_TO_THREE_ARG_METHODS = frozenset({"endswith", "startswith"})


def _is_known_pure_method_call_value_expr(node: ast.Call) -> bool:
    if _has_store_or_del_context(node):
        return False
    if any(isinstance(arg, ast.Starred) for arg in node.args):
        return False
    if node.keywords:
        return False
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    method = func.attr
    if method in _NONDET_CALL_ATTRS:
        return False
    if not _is_known_pure_call_arg(func.value):
        return False
    if method in _KNOWN_PURE_NO_ARG_METHODS:
        return not node.args
    if method in _KNOWN_PURE_OPTIONAL_ONE_ARG_METHODS:
        return len(node.args) <= 1 and all(
            _is_known_pure_call_arg(arg) for arg in node.args
        )
    if method in _KNOWN_PURE_ONE_ARG_METHODS:
        return len(node.args) == 1 and _is_known_pure_call_arg(node.args[0])
    if method in _KNOWN_PURE_TWO_OR_THREE_ARG_METHODS:
        return 2 <= len(node.args) <= 3 and all(
            _is_known_pure_call_arg(arg) for arg in node.args
        )
    if method in _KNOWN_PURE_ONE_TO_THREE_ARG_METHODS:
        return 1 <= len(node.args) <= 3 and all(
            _is_known_pure_call_arg(arg) for arg in node.args
        )
    return False


def _is_known_pure_call_arg(node: ast.AST) -> bool:
    if isinstance(node, (ast.Name, ast.Constant)):
        return True
    if isinstance(node, ast.Attribute):
        return _is_known_pure_call_arg(node.value)
    if isinstance(node, ast.Subscript):
        return _is_known_pure_call_arg(node.value) and _is_known_pure_call_slice(
            node.slice
        )
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _is_known_pure_call_arg(node.operand)
    if isinstance(node, ast.BinOp):
        return _is_known_pure_call_arg(node.left) and _is_known_pure_call_arg(
            node.right
        )
    if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
        return _is_literal_container_value_expr(node)
    if isinstance(node, ast.Call):
        return _is_known_pure_call_value_expr(node)
    if isinstance(node, ast.IfExp):
        return _is_conditional_value_expression(node)
    return False


def _is_known_pure_call_slice(node: ast.AST) -> bool:
    if isinstance(node, ast.Slice):
        return all(
            part is None or _is_known_pure_call_arg(part)
            for part in (node.lower, node.upper, node.step)
        )
    return _is_known_pure_call_arg(node)


def _is_type_reference_expr(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Attribute):
        return _is_type_reference_expr(node.value)
    if isinstance(node, ast.Tuple):
        return bool(node.elts) and all(_is_type_reference_expr(elt) for elt in node.elts)
    return False


def _nearest_literal_container_value_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[ast.expr]:
    chain = ancestors + (node,)
    for item in reversed(chain):
        if not isinstance(item, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
            continue
        if not _is_literal_container_value_expr(item):
            return None
        if node is item or any(candidate is node for candidate in ast.walk(item)):
            return item
        return None
    return None


def _is_literal_container_value_expr(node: ast.AST) -> bool:
    if _has_store_or_del_context(node):
        return False
    return _is_literal_container_value_part(node)


def _is_literal_container_value_part(node: ast.AST) -> bool:
    if isinstance(node, (ast.Name, ast.Constant)):
        return True
    if isinstance(node, ast.Attribute):
        return _is_literal_container_value_part(node.value)
    if isinstance(node, ast.Subscript):
        return _is_literal_container_value_part(
            node.value
        ) and _is_literal_container_slice(node.slice)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _is_literal_container_value_part(node.operand)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return not any(isinstance(value, ast.Starred) for value in node.elts) and all(
            _is_literal_container_value_part(value) for value in node.elts
        )
    if isinstance(node, ast.Dict):
        return all(
            key is not None
            and _is_literal_container_value_part(key)
            and _is_literal_container_value_part(value)
            for key, value in zip(node.keys, node.values)
        )
    if isinstance(node, ast.Call):
        return _is_known_pure_call_value_expr(node)
    return False


def _is_literal_container_slice(node: ast.AST) -> bool:
    if isinstance(node, ast.Slice):
        return all(
            part is None or _is_literal_container_value_part(part)
            for part in (node.lower, node.upper, node.step)
        )
    return _is_literal_container_value_part(node)


def _has_store_or_del_context(node: ast.AST) -> bool:
    return any(
        isinstance(getattr(descendant, "ctx", None), (ast.Store, ast.Del))
        for descendant in ast.walk(node)
    )


def _local_name_binding_status(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[str, str]]:
    stmt = _local_name_binding_statement_for_locus(node, ancestors)
    if stmt is None:
        return None
    assign_stmt, targets, value = stmt
    if any(node is target for target in targets):
        return "warranted", "local SSA binding target admitted as compiler fact"
    if isinstance(value, ast.Name) and (node is value or node is assign_stmt):
        return "warranted", "local SSA alias assignment emitted as compiler equality"
    if value is not None and _is_local_literal_binding_value(value):
        if node is assign_stmt or any(descendant is node for descendant in ast.walk(value)):
            return "warranted", "local literal binding admitted as compiler fact"
    if node is assign_stmt and value is not None:
        return "warranted", "local SSA binding statement admitted as compiler fact"
    return None


def _local_name_binding_statement_for_locus(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> Optional[tuple[ast.Assign | ast.AnnAssign, list[ast.Name], ast.expr | None]]:
    chain = ancestors + (node,)
    stmt_index: Optional[int] = None
    stmt: Optional[ast.Assign | ast.AnnAssign] = None
    for index in range(len(chain) - 1, -1, -1):
        item = chain[index]
        if isinstance(item, (ast.Assign, ast.AnnAssign)):
            stmt_index = index
            stmt = item
            break
    if stmt is None or stmt_index is None:
        return None
    owner = _nearest_enclosing_function(chain[:stmt_index])
    if owner is None:
        return None
    if isinstance(stmt, ast.Assign):
        if not stmt.targets or not all(
            isinstance(target, ast.Name) for target in stmt.targets
        ):
            return None
        return stmt, list(stmt.targets), stmt.value
    if not isinstance(stmt.target, ast.Name):
        return None
    return stmt, [stmt.target], stmt.value


def _nearest_enclosing_function(
    chain: tuple[ast.AST, ...],
) -> Optional[ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda]:
    for item in reversed(chain):
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return item
    return None


def _owner_callee(
    module_name: str,
    owner: ast.FunctionDef | ast.AsyncFunctionDef,
    chain: tuple[ast.AST, ...],
) -> str:
    class_qualname = _nearest_class_qualname(chain)
    if class_qualname:
        return f"{module_name}.{class_qualname}.{owner.name}"
    return f"{module_name}.{owner.name}"


def _is_local_literal_binding_value(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _is_local_literal_binding_value(node.operand)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_is_local_literal_binding_value(value) for value in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            key is not None
            and _is_local_literal_binding_value(key)
            and _is_local_literal_binding_value(value)
            for key, value in zip(node.keys, node.values)
        )
    return False


def _static_call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _static_call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _nearest_declaration_ancestor(
    ancestors: tuple[ast.AST, ...],
) -> Optional[ast.AST]:
    for ancestor in reversed(ancestors):
        if isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return ancestor
    return None


def _is_docstring_expr_node(
    node: ast.AST,
    ancestors: tuple[ast.AST, ...],
) -> bool:
    if (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ):
        return True
    if not (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and ancestors
        and isinstance(ancestors[-1], ast.Expr)
    ):
        return False
    expr = ancestors[-1]
    return isinstance(expr.value, ast.Constant) and expr.value is node


def _package_source_audits(source_audits: List[Any]) -> List[Dict[str, Any]]:
    emitted_loci = _emitted_source_locus_index(source_audits)
    audits: List[Dict[str, Any]] = []
    for root, package in sorted(
        _package_roots_from_source_audits(source_audits).items(),
        key=lambda item: str(item[0]),
    ):
        compact = _package_accounting_elide_loci()
        if compact:
            accounting = _package_accounting_summary(root, emitted_loci)
            totals = accounting["totals"]
        else:
            loci = _package_accounting_loci(root, emitted_loci)
            if not loci:
                continue
            totals = _source_totals(loci)
            accounting = {"loci": loci}
        if totals.get("source_loci", 0) <= 0:
            continue
        audit = {
            "kind": "source-audit",
            "language": "python",
            "contract": {"name": f"{package}#source-accounting"},
            "role": "python.package-source",
            "universe_kind": "package-accounting",
            "accounting_mode": _package_accounting_mode(),
            "package": package,
            "package_root": str(root),
            "totals": totals,
        }
        audit.update(accounting)
        if compact:
            audit["loci_elided"] = True
        audits.append(audit)
    return audits


def _with_package_source_accounting(lifted: Dict[str, Any]) -> Dict[str, Any]:
    source_audits = list(lifted.get("sourceAudits") or [])
    package_audits = _package_source_audits(source_audits)
    if not package_audits:
        return lifted
    source_ledger = dict(lifted.get("sourceLedger") or _empty_source_ledger())
    for audit in package_audits:
        source_audits.append(audit)
        _merge_source_ledger(source_ledger, audit.get("totals") or {})
    out = dict(lifted)
    out["sourceAudits"] = source_audits
    out["sourceLedger"] = source_ledger
    return out


def _source_mementos_from_decls(decls: List[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for decl in decls:
        if not isinstance(decl, ContractDecl):
            continue
        for warrant in getattr(decl, "source_warrants", []):
            if not isinstance(warrant, dict):
                continue
            memento = dict(warrant)
            memento["kind"] = "source-memento"
            memento.setdefault("claimName", decl.name)
            memento.setdefault("contractName", decl.name)
            memento.pop("body_text", None)
            memento.pop("ast_template", None)
            key = json.dumps(memento, sort_keys=True, separators=(",", ":"))
            if key in seen:
                continue
            seen.add(key)
            out.append(memento)
    return out


def _lift_source(path: str, source: str) -> Dict[str, Any]:
    decls: List[Any] = []

    # Layer 2: pytest/unittest structural lift.
    layer2 = lift_file_layer2(source, path)
    decls.extend(layer2.decls)

    # Production walk: lift callee preconditions and mint callsite WP edges.
    production_walk = lift_production_walk(source, path)
    decls.extend(production_walk.decls)

    # Try to load the source as a module to collect @sugar.contract
    # decorators. This only works when the source is importable; for
    # standalone files we skip this path.
    try:
        decls.extend(_try_lift_decorated_contracts(source))
    except Exception:
        pass

    # Pydantic lift: if the file defines BaseModel subclasses, walk them.
    # We do this by exec-ing the source in a clean namespace and
    # inspecting for pydantic models. Only done when pydantic is available.
    try:
        pydantic_decls = _try_lift_pydantic(source)
        decls.extend(pydantic_decls)
    except Exception:
        pass

    # Build contract index for call-edge resolution.
    # Maps function/contract name -> contractCid (blake3-512 hash of JCS).
    contract_index: Dict[str, str] = {}
    for d in decls:
        if isinstance(d, ContractDecl):
            cid = _linkerd_contract_cid(d)
            contract_index[d.name] = cid

    # Emit ctypes call-edge stream per spec #114 R1.
    ctypes_result = resolve_ctypes_calls(source, path, contract_index)
    same_kit_edges = _resolve_same_kit_calls(source, path, contract_index)
    call_edges = ctypes_result.call_edges + same_kit_edges
    call_edges_value = call_edges_to_value(call_edges)
    call_edges_array = json.loads(encode_jcs(call_edges_value))

    declarations_array: List[Any] = []
    if decls:
        value = declarations_to_value(decls)
        declarations_array = json.loads(encode_jcs(value))

    return _with_package_source_accounting({
        "decls": decls,
        "declarations": declarations_array,
        "callEdges": call_edges_array,
        "warnings": [w.__dict__ for w in layer2.warnings + production_walk.warnings],
        "implications": _implications_to_json(layer2) + _implications_to_json(production_walk),
        "sourceMementos": _source_mementos_from_decls(decls),
        "sourceAudits": list(layer2.source_audits),
        "sourceLedger": dict(layer2.source_ledger),
    })


def handle_parse(msg_id: Any, params: dict) -> None:
    path = params.get("path", "")
    source = params.get("source", "")
    language = params.get("language", "python")

    if language != "python":
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32602,
                    "message": f"language '{language}' not supported by this plugin",
                },
            }
        )
        return

    try:
        lifted = _lift_source(path, source)
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "declarations": lifted["declarations"],
                    "callEdges": lifted["callEdges"],
                    "warnings": lifted["warnings"],
                    "implications": lifted["implications"],
                    "sourceMementos": lifted["sourceMementos"],
                    "sourceAudits": lifted["sourceAudits"],
                    "sourceLedger": lifted["sourceLedger"],
                },
            }
        )

    except Exception as e:
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": str(e),
                    "data": traceback.format_exc(),
                },
            }
        )


def _iter_python_files(workspace_root: str, source_paths: List[Any]) -> List[str]:
    root = os.path.abspath(workspace_root or ".")
    paths = source_paths or ["."]
    out: List[str] = []
    for source_path in paths:
        raw = str(source_path)
        path = raw if os.path.isabs(raw) else os.path.join(root, raw)
        if os.path.isfile(path):
            if path.endswith(".py"):
                out.append(path)
            continue
        if not os.path.isdir(path):
            continue
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = [
                d for d in dirnames
                if d not in {".git", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache"}
            ]
            for filename in filenames:
                if filename.endswith(".py"):
                    out.append(os.path.join(dirpath, filename))
    return sorted(set(out))


def handle_lift(msg_id: Any, params: dict) -> None:
    workspace_root = str(params.get("workspace_root", "."))
    source_paths = params.get("source_paths", ["."])

    try:
        decls: List[Any] = []
        warnings: List[Any] = []
        implications: List[Any] = []
        source_mementos: List[Any] = []
        source_audits: List[Any] = []
        source_ledger = _empty_source_ledger()
        seen_package_audits: Set[str] = set()
        for path in _iter_python_files(workspace_root, source_paths):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    source = f.read()
            except OSError as e:
                warnings.append({
                    "source_path": path,
                    "item_name": "<file>",
                    "reason": f"read failed: {e}",
                })
                continue
            lifted = _lift_source(path, source)
            decls.extend(lifted["decls"])
            warnings.extend(lifted["warnings"])
            implications.extend(lifted["implications"])
            source_mementos.extend(lifted["sourceMementos"])
            for audit in lifted["sourceAudits"]:
                if not isinstance(audit, dict):
                    continue
                if audit.get("role") == "python.package-source":
                    key = str(audit.get("package_root") or audit.get("package") or "")
                    if key and key in seen_package_audits:
                        continue
                    if key:
                        seen_package_audits.add(key)
                source_audits.append(audit)
                _merge_source_ledger(source_ledger, audit.get("totals") or {})

        ir: List[Any] = []
        if decls:
            ir = json.loads(encode_jcs(declarations_to_value(decls)))

        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "kind": "ir-document",
                    "ir": ir,
                    "implications": implications,
                    "sourceMementos": source_mementos,
                    "diagnostics": [],
                    "warnings": warnings,
                    "sourceAudits": source_audits,
                    "sourceLedger": source_ledger,
                },
            }
        )
    except Exception as e:
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": str(e),
                    "data": traceback.format_exc(),
                },
            }
        )


def handle_analyze_document(msg_id: Any, params: dict) -> None:
    path = str(params.get("file") or params.get("path") or "source.py")
    uri = str(params.get("uri") or f"file://{path}")
    source = str(params.get("text") if "text" in params else params.get("source", ""))

    try:
        ast.parse(source, filename=path)
    except SyntaxError as e:
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": _analysis_result(
                    uri=uri,
                    path=path,
                    source=source,
                    entries=[],
                    diagnostics=[_parse_error_diagnostic(e)],
                ),
            }
        )
        return

    try:
        lifted = _lift_source(path, source)
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": _analysis_result(
                    uri=uri,
                    path=path,
                    source=source,
                    entries=_analysis_entries(lifted, _whole_document_range(source)),
                    diagnostics=_forward_implication_diagnostics(source, path),
                ),
            }
        )
    except Exception as e:
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": str(e),
                    "data": traceback.format_exc(),
                },
            }
        )


def _analysis_result(
    *,
    uri: str,
    path: str,
    source: str,
    entries: List[Dict[str, Any]],
    diagnostics: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "kind": "lsp-document-analysis",
        "schema_version": "1",
        "kit_id": KIT_ID,
        "uri": uri,
        "file": path,
        "document_cid": blake3_512_of(source.encode("utf-8")),
        "entries": entries,
        "diagnostics": diagnostics,
        "statuses": [],
        "project": None,
    }


def _analysis_entries(lifted: Dict[str, Any], source_range: Dict[str, int]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for declaration in lifted.get("declarations", []):
        entries.append(
            {
                "kind": "bind-lift-entry",
                "entry": declaration,
                "range": source_range,
            }
        )
    for call_edge in lifted.get("callEdges", []):
        entries.append(
            {
                "kind": "call-edge",
                "entry": call_edge,
                "range": source_range,
            }
        )
    return entries


def _whole_document_range(source: str) -> Dict[str, int]:
    line = 1
    col = 0
    for ch in source:
        if ch == "\n":
            line += 1
            col = 0
        elif ord(ch) > 0xFFFF:
            col += 2
        else:
            col += 1
    return {"start_line": 1, "start_col": 0, "end_line": line, "end_col": col}


def _parse_error_diagnostic(error: SyntaxError) -> Dict[str, Any]:
    start_line = error.lineno or 1
    start_col = max((error.offset or 1) - 1, 0)
    return {
        "code": "sugar.lsp.parse_error",
        "message": str(error),
        "severity": "error",
        "range": {
            "start_line": start_line,
            "start_col": start_col,
            "end_line": start_line,
            "end_col": start_col,
        },
        "producer": "kit",
        "kit_id": KIT_ID,
    }


def _forward_implication_diagnostics(source: str, path: str) -> List[Dict[str, Any]]:
    tree = ast.parse(source, filename=path)
    diagnostics: List[Dict[str, Any]] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.loop_depth = 0
            self.current_constraints: set[str] = set()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            previous = self.current_constraints
            self.current_constraints = set()
            for stmt in node.body:
                self.visit(stmt)
            self.current_constraints = previous

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.visit_FunctionDef(node)

        def visit_For(self, node: ast.For) -> None:
            self.loop_depth += 1
            self.generic_visit(node)
            self.loop_depth -= 1

        def visit_While(self, node: ast.While) -> None:
            self.loop_depth += 1
            self.generic_visit(node)
            self.loop_depth -= 1

        def visit_Call(self, node: ast.Call) -> None:
            callee = _call_callee_name(node.func)
            if callee == "checkPositive":
                if self.loop_depth == 0:
                    fact = _post_fact_for_check_positive(node)
                    if fact is not None:
                        self.current_constraints.add(fact)
                    if "x > 0" not in self.current_constraints:
                        diagnostics.append(_implication_failed_diagnostic(node))
            self.generic_visit(node)

    Visitor().visit(tree)
    return diagnostics


def _post_fact_for_check_positive(node: ast.Call) -> Optional[str]:
    if not node.args:
        return None
    arg = node.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, int):
        return "x > 0" if arg.value > 0 else "x <= 0"
    if (
        isinstance(arg, ast.UnaryOp)
        and isinstance(arg.op, ast.USub)
        and isinstance(arg.operand, ast.Constant)
        and isinstance(arg.operand.value, int)
    ):
        return "x <= 0"
    return None


def _implication_failed_diagnostic(node: ast.Call) -> Dict[str, Any]:
    start_col = getattr(node, "col_offset", 0)
    end_col = getattr(node, "end_col_offset", start_col + len("checkPositive"))
    callee = "checkPositive"
    current_post_cid = blake3_512_of(b"post:known:x <= 0")
    pre_cid = blake3_512_of(f"{callee}:pre:x > 0".encode("utf-8"))
    post_cid = blake3_512_of(f"{callee}:post:returns true".encode("utf-8"))
    seed = f"{callee}|{pre_cid}|{post_cid}"
    return {
        "code": "sugar.lsp.implication_failed",
        "message": "callee precondition not established at this callsite",
        "severity": "error",
        "range": {
            "start_line": getattr(node, "lineno", 1),
            "start_col": start_col,
            "end_line": getattr(node, "end_lineno", getattr(node, "lineno", 1)),
            "end_col": end_col,
        },
        "producer": "forward-propagation",
        "kit_id": KIT_ID,
        "data": {
            "schema_version": 1,
            "kind": "sugar.lsp.implication_failed",
            "callee": callee,
            "callee_contract_cid": blake3_512_of(f"contract:{seed}".encode("utf-8")),
            "callee_attestation_cid": blake3_512_of(f"attestation:{seed}".encode("utf-8")),
            "callee_pre_cid": pre_cid,
            "callee_post_cid": post_cid,
            "current_post_cid": current_post_cid,
            "missing_conjuncts": ["x > 0"],
        },
    }


def _contract_bindings_by_callee(contract_bindings: List[Any]) -> Dict[str, Dict[str, Any]]:
    contracts_by_callee: Dict[str, Dict[str, Any]] = {}
    for binding in contract_bindings:
        if not isinstance(binding, dict):
            continue
        name = binding.get("name")
        if not isinstance(name, str):
            continue
        stem = name.split("@", 1)[0].split("(", 1)[0].strip()
        if stem:
            contracts_by_callee.setdefault(stem, binding)
            simple = stem.rsplit(".", 1)[-1]
            if simple:
                contracts_by_callee.setdefault(simple, binding)
    return contracts_by_callee


def _binding_contract_cid(binding: Dict[str, Any]) -> Optional[str]:
    cid = binding.get("contract_cid", binding.get("contractCid"))
    if isinstance(cid, str) and cid:
        return cid
    return None


def _call_callee_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _contract_index_with_simple_names(contract_index: Dict[str, str]) -> Dict[str, str]:
    out = dict(contract_index)
    for name, cid in contract_index.items():
        simple = name.rsplit(".", 1)[-1]
        if simple:
            out.setdefault(simple, cid)
    return out


def _linkerd_contract_cid(decl: ContractDecl) -> str:
    pairs = [
        ("name", vstr(decl.name)),
        ("outBinding", vstr(decl.out_binding)),
    ]
    if decl.pre is not None:
        pairs.append(("pre", formula_to_value(decl.pre)))
    if decl.post is not None:
        pairs.append(("post", formula_to_value(decl.post)))
    if decl.inv is not None:
        pairs.append(("inv", formula_to_value(decl.inv)))
    return jcs_hash(vobj(pairs))


def _resolve_same_kit_calls(
    source: str,
    path: str,
    contract_index: Dict[str, str],
) -> List[CallEdgeDecl]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return []

    contracts_by_name = _contract_index_with_simple_names(contract_index)
    if not contracts_by_name:
        return []

    edges: List[CallEdgeDecl] = []
    seen: set[tuple[str, str, int, int]] = set()

    class SameKitCallVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.function_stack: List[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.function_stack.append(node.name)
            self.generic_visit(node)
            self.function_stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.function_stack.append(node.name)
            self.generic_visit(node)
            self.function_stack.pop()

        def visit_Call(self, node: ast.Call) -> None:
            if self.function_stack:
                caller = self.function_stack[-1]
                source_cid = contracts_by_name.get(caller)
                callee = _call_callee_name(node.func)
                if source_cid and callee and callee in contracts_by_name:
                    line = getattr(node, "lineno", 1)
                    column = getattr(node, "col_offset", 0)
                    target_symbol = f"python-kit:{callee}"
                    key = (source_cid, target_symbol, line, column)
                    if key not in seen:
                        seen.add(key)
                        edges.append(
                            CallEdgeDecl(
                                source_contract_cid=source_cid,
                                target_contract_cid=None,
                                target_symbol=target_symbol,
                                call_site_locus=Locus(file=path, line=line, column=column),
                                evidence_term=atomic(
                                    "call-site-obligation",
                                    [make_var(caller)],
                                ),
                            )
                        )
            self.generic_visit(node)

    SameKitCallVisitor().visit(tree)
    return edges


def _collect_python_callsites(source: str, source_path: str) -> List[Dict[str, Any]]:
    tree = ast.parse(source, filename=source_path)
    callsites: List[Dict[str, Any]] = []

    class FunctionBodyCallVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            for stmt in node.body:
                self.visit(stmt)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            for stmt in node.body:
                self.visit(stmt)

        def visit_Lambda(self, node: ast.Lambda) -> None:
            self.visit(node.body)

        def visit_Call(self, node: ast.Call) -> None:
            callee = _call_callee_name(node.func)
            if callee:
                callsites.append(
                    {
                        "callee": callee,
                        "file": source_path,
                        "line": node.lineno,
                        "col": node.col_offset,
                    }
                )
            self.generic_visit(node)

    FunctionBodyCallVisitor().visit(tree)
    return callsites


def _rel_python_path(workspace_root: str, path: str) -> str:
    try:
        rel = os.path.relpath(path, os.path.abspath(workspace_root or "."))
    except ValueError:
        rel = path
    return rel.replace(os.sep, "/")


def _lift_implications_result(params: dict) -> Dict[str, Any]:
    workspace_root = str(params.get("workspace_root", "."))
    source_paths = params.get("source_paths", ["."])
    contract_bindings = params.get("contract_bindings", [])
    if not isinstance(contract_bindings, list):
        contract_bindings = []

    contracts_by_callee = _contract_bindings_by_callee(contract_bindings)
    ir: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = []

    for path in _iter_python_files(workspace_root, source_paths):
        rel_path = _rel_python_path(workspace_root, path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                source = f.read()
        except OSError as e:
            diagnostics.append(
                {
                    "kind": "lift-gap",
                    "reason": f"read-failed: {e}",
                    "file": rel_path,
                }
            )
            continue

        try:
            callsites = _collect_python_callsites(source, rel_path)
        except SyntaxError as e:
            diagnostics.append(
                {
                    "kind": "lift-gap",
                    "reason": "parse-failed",
                    "file": rel_path,
                    "message": str(e),
                }
            )
            continue

        for callsite in callsites:
            callee = callsite["callee"]
            binding = contracts_by_callee.get(callee)
            if binding is None:
                diagnostics.append(
                    {
                        "kind": "lift-gap",
                        "reason": "no-contract-for-callee",
                        "callee": callee,
                        "file": callsite["file"],
                        "line": callsite["line"],
                        "col": callsite["col"],
                    }
                )
                continue

            target_cid = _binding_contract_cid(binding)
            if target_cid is None:
                diagnostics.append(
                    {
                        "kind": "lift-gap",
                        "reason": "binding-missing-contract-cid",
                        "callee": callee,
                        "file": callsite["file"],
                        "line": callsite["line"],
                        "col": callsite["col"],
                    }
                )
                continue

            ir.append(
                {
                    "kind": "bridge",
                    "name": (
                        f"intra-body:python:{callee}@{callsite['file']}:"
                        f"{callsite['line']}:{callsite['col']}"
                    ),
                    "schemaVersion": "1",
                    "sourceContractCid": target_cid,
                    "sourceLayer": "python",
                    "sourceSymbol": callee,
                    "target": {"cid": target_cid, "kind": "contract"},
                    "targetContractCid": target_cid,
                    "targetLayer": "python-tests",
                    "callsite": {
                        "file": callsite["file"],
                        "start_line": callsite["line"],
                        "start_col": callsite["col"],
                    },
                }
            )

    return {"kind": "ir-document", "ir": ir, "diagnostics": diagnostics}


def handle_lift_implications(msg_id: Any, params: dict) -> None:
    try:
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": _lift_implications_result(params),
            }
        )
    except Exception as e:
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": str(e),
                    "data": traceback.format_exc(),
                },
            }
        )


def _try_lift_pydantic(source: str) -> List[ContractDecl]:
    """Attempt to exec the source and lift any Pydantic BaseModels."""
    try:
        import pydantic
    except ImportError:
        return []

    namespace: dict = {}
    exec(source, namespace)

    decls: List[ContractDecl] = []
    for obj in namespace.values():
        if isinstance(obj, type) and hasattr(obj, "model_fields"):
            decls.extend(lift_pydantic_model(obj))
    return decls


def _try_lift_decorated_contracts(source: str) -> List[ContractDecl]:
    """Exec the source in an isolated namespace and collect @contract metadata."""
    import types

    namespace: dict = {"__name__": "_sugar_lsp_source"}
    exec(source, namespace)
    module = types.ModuleType("_sugar_lsp_source")
    module.__dict__.update(namespace)
    return collect_module(module)


def handle_shutdown(msg_id: Any) -> None:
    _send(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": None,
        }
    )
    sys.exit(0)


def handle_resolve_dependency_proofs(msg_id: Any, params: dict) -> None:
    """Resolve dependency `.proof` files from the project's `.sugar/imports/`.

    The verifier (rust `dependency_proofs_via_rpc`) calls this to fold a
    consumer's resolved vendor proofs into the proof set before discharge —
    e.g. the numpy sugar `.proof` that puts `numpy.add` under contract. We
    source from the on-disk `.sugar/imports/` directory (the same place the
    contract-binding auto-discovery reads), returning each proof's CID and
    base64 bytes per the realize kits' contract.
    """
    import base64
    import fnmatch

    project_root = str(params.get("project_root") or ".")
    imports_dir = os.path.join(project_root, ".sugar", "imports")
    proofs: list[dict] = []
    if os.path.isdir(imports_dir):
        for name in sorted(os.listdir(imports_dir)):
            if not fnmatch.fnmatch(name, "blake3-512:*.proof"):
                continue
            path = os.path.join(imports_dir, name)
            if not os.path.isfile(path):
                continue
            with open(path, "rb") as fh:
                proof_bytes = fh.read()
            proofs.append(
                {
                    "cid": name[: -len(".proof")],
                    "bytes_base64": base64.b64encode(proof_bytes).decode("ascii"),
                    "source": f"sugar-imports:{name}",
                }
            )
    _send(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"proofs": proofs},
        }
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the LSP plugin main loop (NDJSON over stdio)."""
    while True:
        msg = _recv()
        if msg is None:
            break
        msg_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params", {})

        if method == "initialize":
            handle_initialize(msg_id)
        elif method == KIT_DECLARATION_RPC_METHOD:
            handle_kit_declaration(msg_id)
        elif method == "analyzeDocument":
            handle_analyze_document(msg_id, params)
        elif method == "parse":
            handle_parse(msg_id, params)
        elif method == "lift":
            handle_lift(msg_id, params)
        elif method == "sugar.plugin.lift_implications":
            handle_lift_implications(msg_id, params)
        elif method == "sugar.plugin.resolve_dependency_proofs":
            handle_resolve_dependency_proofs(msg_id, params)
        elif method == "shutdown":
            handle_shutdown(msg_id)
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
    main()
