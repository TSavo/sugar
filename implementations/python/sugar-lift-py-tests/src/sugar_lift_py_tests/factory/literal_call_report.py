from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sugar_lift_py_tests.factory.array_map_report import (
    _callsite_string,
    _function_source_memento,
    _source_ledger,
    _statement_source_memento,
)
from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.factory.sugar_constructors import build_function_call_sugar
from sugar_lift_py_tests.ir import Formula, and_, eq, formula_to_value, make_var, str_const
from sugar_lift_py_tests.kit_rpc import (
    BodyUniverseDto,
    CallsiteFactDto,
    FactoryWalkRowDto,
    LiftReportPayloadDto,
    SourceMementoDto,
    SourceSpanDto,
)
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.string_literal_sugar import string_literal_sugar

from .factory_build_context import FactoryBuildContext
from .source_site import SourceSite


@dataclass(frozen=True)
class SourceReportBuild:
    payload: LiftReportPayloadDto


def _contracts_by_callee(contract_bindings: list | None) -> dict[str, dict[str, Any]]:
    """A vendor contract is in scope, keyed by the callee name (qualified + simple).
    Mirrors lsp.py `_contract_bindings_by_callee` so the factory resolves an
    imported call to the vendor `.proof` contract instead of a local body."""
    out: dict[str, dict[str, Any]] = {}
    for binding in contract_bindings or []:
        if not isinstance(binding, dict):
            continue
        name = binding.get("name")
        if not isinstance(name, str):
            continue
        stem = name.split("@", 1)[0].split("(", 1)[0].strip()
        if stem:
            out.setdefault(stem, binding)
            simple = stem.rsplit(".", 1)[-1]
            if simple:
                out.setdefault(simple, binding)
    return out


def _imports_by_name(tree: ast.Module) -> dict[str, str]:
    """Map an imported symbol to its module stem, so the consumer can NAME the
    vendor universe contract: `from base64vendor import encodeBase64` lets us target
    `base64vendor::encodeBase64::callable` -- the vendor's `{stem}::{fn}::callable`."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            module = node.module.rsplit(".", 1)[-1]
            for alias in node.names:
                out[alias.asname or alias.name] = module
    return out


def _is_free_var_definition(formula_value: dict[str, Any], bound: set[str]) -> bool:
    """An `eq(var, _)` whose var is neither a formal nor `out` -- a free-variable
    definition that would leave an exported universe post OPEN, so the verifier's
    `linked_ambient_post_instances_for_inv` skips it. The str.eq-bv-blocks relation
    carries the alphabet as a constant payload, so dropping the definition is safe."""
    if not isinstance(formula_value, dict) or formula_value.get("name") != "=":
        return False
    args = formula_value.get("args")
    if not isinstance(args, list) or len(args) != 2 or not isinstance(args[0], dict):
        return False
    return args[0].get("kind") == "var" and args[0].get("name") not in bound


def build_literal_call_report(
    *,
    source: str,
    filename: str,
    memento_file: str | None = None,
    contract_bindings: list | None = None,
) -> SourceReportBuild | None:
    tree = ast.parse(source, filename=filename)
    lines = source.splitlines(keepends=True)
    rel_file = memento_file or filename
    contracts: list[BodyUniverseDto] = []
    source_mementos: list[SourceMementoDto] = []
    source_audits: list[dict[str, Any]] = []
    factory_walk: list[FactoryWalkRowDto] = []
    call_edges: list[dict[str, Any]] = []
    functions_by_name = {
        node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    contracts_by_callee = _contracts_by_callee(contract_bindings)
    imports_by_name = _imports_by_name(tree)
    for fn in functions_by_name.values():
        for stmt in fn.body:
            if not isinstance(stmt, ast.Assert):
                continue
            lifted = _lift_assert(
                stmt,
                fn=fn,
                filename=filename,
                memento_file=rel_file,
                source_lines=lines,
                functions_by_name=functions_by_name,
                contracts_by_callee=contracts_by_callee,
                imports_by_name=imports_by_name,
            )
            if lifted is None:
                continue
            lifted_contracts, mementos, audits, rows, edges = lifted
            contracts.extend(lifted_contracts)
            source_mementos.extend(mementos)
            source_audits.extend(audits)
            factory_walk.extend(rows)
            call_edges.extend(edges)
    if not contracts:
        return None
    return SourceReportBuild(
        LiftReportPayloadDto(
            ir=contracts,
            source_mementos=source_mementos,
            source_ledger=_source_ledger(len(source_audits)),
            source_audits=source_audits,
            factory_walk=factory_walk,
            call_edges=call_edges,
        )
    )


def _lift_assert(
    stmt: ast.Assert,
    *,
    fn: ast.FunctionDef,
    filename: str,
    memento_file: str,
    source_lines: list[str],
    functions_by_name: dict[str, ast.FunctionDef],
    contracts_by_callee: dict[str, dict[str, Any]] | None = None,
    imports_by_name: dict[str, str] | None = None,
) -> tuple[
    list[BodyUniverseDto],
    list[SourceMementoDto],
    list[dict[str, Any]],
    list[FactoryWalkRowDto],
    list[dict[str, Any]],
] | None:
    comparison = stmt.test
    if not isinstance(comparison, ast.Compare) or len(comparison.ops) != 1:
        return None
    if not isinstance(comparison.ops[0], ast.Eq) or len(comparison.comparators) != 1:
        return None
    # Cross-project: an IMPORTED callee whose vendor contract is in scope joins the
    # vendor universe by CID, rather than re-lifting a body that isn't local.
    callee_name = _callee_name(comparison.left)
    try:
        with open("/tmp/dbg_fed.txt", "a") as _d:  # DEBUG: does the federation branch fire?
            _d.write(
                f"{memento_file}: callee={callee_name!r} "
                f"local={callee_name in functions_by_name} "
                f"fed_fires={bool(callee_name and callee_name not in functions_by_name)}\n"
            )
    except Exception:
        pass
    if callee_name and callee_name not in functions_by_name:
        # Imported callee: emit the consumer's fact + a call-edge that the verifier
        # resolves to the vendor contract (by CID if a binding is in scope, else by
        # symbol against the proofs loaded from .sugar/imports/).
        binding = (contracts_by_callee or {}).get(callee_name)
        return _lift_federated_assert(
            stmt,
            comparison=comparison,
            callee_name=callee_name,
            binding=binding,
            fn=fn,
            filename=filename,
            memento_file=memento_file,
            source_lines=source_lines,
            imports_by_name=imports_by_name,
        )
    from .build import default_catalog

    factory_ctx = FactoryBuildContext(
        filename=filename,
        catalog=default_catalog(),
        name_resolver=functions_by_name,
    )
    try:
        call_sugar = build_function_call_sugar(
            SourceSite.from_node(comparison.left, filename),
            factory_ctx,
        )
    except TypeError:
        return None
    expected_sugar = string_literal_sugar(comparison.comparators[0])
    if expected_sugar is None:
        return None
    expected = complete_value(expected_sugar.desugar(), owner="literal call expected")

    target_fn = functions_by_name[call_sugar.target_name]
    body_steps = call_sugar.factory_steps(target_fn)
    try:
        actual = complete_value(call_sugar.desugar(), owner="literal function call actual")
    except TypeError:
        actual = None
        body_formulas = call_sugar.constraint_formulas()
        callsite_fact_formulas = call_sugar.callsite_fact_formulas(expected)
        assertion_formula = and_([*body_formulas, *callsite_fact_formulas])
        body_step_formulas = call_sugar.constraint_formula_steps()
    else:
        body_formulas = call_sugar.constraint_formulas(actual)
        callsite_fact_formulas = call_sugar.callsite_fact_formulas(expected)
        assertion_formula = eq(str_const(actual.value), str_const(expected.value))
        body_step_formulas = list(body_formulas)
    body_formula_values = [_formula_to_rpc(formula) for formula in body_formulas]
    body_step_formula_values = [
        _formula_to_rpc(formula) if formula is not None else None
        for formula in body_step_formulas
    ]
    callsite_fact = (
        _formula_to_rpc(callsite_fact_formulas[0])
        if len(callsite_fact_formulas) == 1
        else _formula_to_rpc(and_(callsite_fact_formulas))
    )
    # The exported universe keeps `out` as its out-binding: the verifier's
    # `linked_ambient_post_instances_for_inv` substitutes `out_binding -> callsite`
    # and `formals -> call args`, turning `str.eq-bv-blocks(out, value, ...)` into
    # `str.eq-bv-blocks(call:enc(xyz), xyz, ...)` specialized at the consumer's call.
    # It must be CLOSED after those substitutions or the verifier skips it as "open",
    # so drop free-var DEFINITIONS (`eq(alphabet, "..")` whose var is neither a formal
    # nor `out`); the str.eq-bv-blocks payload already carries the alphabet constant.
    _universe_bound = {arg.arg for arg in target_fn.args.args} | {"out"}
    _universe_formulas = [
        f
        for f, fv in zip(body_formulas, body_formula_values)
        if not _is_free_var_definition(fv, _universe_bound)
    ]
    function_post = (
        _formula_to_rpc(_universe_formulas[0])
        if len(_universe_formulas) == 1
        else _formula_to_rpc(and_(_universe_formulas))
    )
    function_contract_name = f"{Path(memento_file).stem}::{target_fn.name}::callable"
    assertion_contract_name = (
        f"{Path(memento_file).stem}::{fn.name}::literal-call-sugar::assertion"
    )
    function_memento = _function_source_memento(
        target_fn,
        memento_file,
        source_lines,
        role="python.literal-call-sugar",
        contract_name=function_contract_name,
    )
    body_mementos = [
        _statement_source_memento(
            step_stmt,
            target_fn,
            memento_file,
            source_lines,
            contract_name=function_contract_name,
            role="python.literal-call-sugar",
        )
        for _, _, step_stmt, _ in body_steps
    ]
    return_memento = body_mementos[-1]
    return_stmt = body_steps[-1][2]
    assertion_function_memento = _function_source_memento(
        fn,
        memento_file,
        source_lines,
        role="python.literal-call-sugar",
        contract_name=assertion_contract_name,
    )
    assertion_memento = _statement_source_memento(
        stmt,
        fn,
        memento_file,
        source_lines,
        contract_name=assertion_contract_name,
        role="python.literal-call-sugar",
    )

    assertion_inv = _formula_to_rpc(assertion_formula)
    function_contract = BodyUniverseDto(
        name=function_contract_name,
        out_binding="out",
        post=function_post,
        source_warrants=[function_memento],
        formals=[arg.arg for arg in target_fn.args.args],
        kind="function-contract",
        # Must equal the callsite ctor name (`linked_ambient_post_instances_for_inv`
        # matches `post.source_symbol == callsite.name`), which is `call:<callee>`.
        bridge_source_symbol=f"call:{target_fn.name}",
    )
    callsite = _callsite_string(memento_file, comparison.left)
    assertion_contract = BodyUniverseDto(
        name=assertion_contract_name,
        out_binding="out",
        inv=assertion_inv,
        source_warrants=[assertion_memento],
        warranted_by=CallsiteFactDto(
            contract_name=function_contract_name,
            callsite=callsite,
            fact=callsite_fact,
            source_memento=assertion_memento,
        ),
    )
    return (
        [function_contract, assertion_contract],
        [function_memento, *body_mementos, assertion_function_memento, assertion_memento],
        [
            _source_audit(
                target_fn,
                return_stmt,
                memento_file,
                function_contract_name,
                return_memento,
                role="python.literal-call-sugar",
                ast_kind="Return",
            ),
            _source_audit(
                fn,
                stmt,
                memento_file,
                assertion_contract_name,
                assertion_memento,
                role="python.literal-call-sugar",
                ast_kind="Assert",
            ),
        ],
        [
            _walk_row(
                selected,
                ast_kind,
                step_stmt,
                filename,
                step_memento,
                output,
                requested_role="FunctionBodyConstraint",
                emitted_formula=body_step_formula_values[index]
                if index < len(body_step_formula_values)
                else None,
            )
            for index, (
                (selected, ast_kind, step_stmt, output),
                step_memento,
            ) in enumerate(zip(body_steps, body_mementos))
        ]
        + [
            _walk_row(
                "FunctionCallSugar",
                "Call",
                stmt,
                filename,
                assertion_memento,
                "predicate",
                requested_role="AssertionSurface",
                emitted_formula=assertion_inv,
            ),
        ],
        [
            {
                "kind": "call-edge",
                "sourceContract": function_contract.name,
                "targetSymbol": call_sugar.target_name,
                "targetContract": assertion_contract.name,
                "callsite": callsite,
            }
        ],
    )


def _callee_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _lift_federated_assert(
    stmt: ast.Assert,
    *,
    comparison: ast.Compare,
    callee_name: str,
    binding: dict[str, Any] | None,
    fn: ast.FunctionDef,
    filename: str,
    memento_file: str,
    source_lines: list[str],
    imports_by_name: dict[str, str] | None = None,
):
    """The user's `encodeBase64("xyz") == "eHl6"` lifts to an EUF callsite obligation
    `callresult_encodeBase64_a1("xyz") == "eHl6"`, contract-named
    `encodeBase64#euf#<arg_sig>::assertion`. The consistency pass groups obligations
    by the `#euf#` scope and specializes the vendor's universe post (a forall over the
    same callresult ctor) into this one, so z3 decides `and(universe, fact)` -- no body
    re-lifted, no test run. Only concrete-literal args take this path; a symbolic arg
    falls back (returns None)."""
    del binding, imports_by_name  # composition is by #euf# name, not a bridge/CID
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.layer2 import _canonical_term_sig

    expected_sugar = string_literal_sugar(comparison.comparators[0])
    if expected_sugar is None:
        return None
    expected = complete_value(expected_sugar.desugar(), owner="federated call expected")
    call_node = comparison.left
    arg_terms = []
    for arg_node in call_node.args:
        arg_sugar = string_literal_sugar(arg_node)
        if arg_sugar is None:
            return None  # non-literal arg: outside the factory euf path
        arg_value = complete_value(arg_sugar.desugar(), owner="federated call arg")
        arg_terms.append(str_const(arg_value.value))
    # `call:<callee>` is the callsite-ctor form the verifier recognizes
    # (`is_callsite_ctor_term` requires the `call:` prefix); the universe post
    # below uses the same head so the ambient specialization matches.
    euf_term = ctor(f"call:{callee_name}", arg_terms)
    assertion_contract_name = (
        f"{callee_name}#euf#{_canonical_term_sig(euf_term)}::assertion"
    )
    assertion_memento = _statement_source_memento(
        stmt,
        fn,
        memento_file,
        source_lines,
        contract_name=assertion_contract_name,
        role="python.literal-call-sugar",
    )
    assertion_inv = _formula_to_rpc(eq(euf_term, str_const(expected.value)))
    assertion_contract = BodyUniverseDto(
        name=assertion_contract_name,
        out_binding="out",
        inv=assertion_inv,
        source_warrants=[assertion_memento],
    )
    walk = _walk_row(
        "FunctionCallSugar",
        "Call",
        stmt,
        filename,
        assertion_memento,
        "predicate",
        requested_role="AssertionSurface",
        emitted_formula=assertion_inv,
    )
    audit = _source_audit(
        fn,
        stmt,
        memento_file,
        assertion_contract_name,
        assertion_memento,
        role="python.literal-call-sugar",
        ast_kind="Assert",
    )
    return ([assertion_contract], [assertion_memento], [audit], [walk], [])


def _formula_to_rpc(formula: Formula) -> dict[str, Any]:
    return json.loads(encode_jcs(formula_to_value(formula)))


def _source_audit(
    fn: ast.FunctionDef,
    stmt: ast.stmt,
    memento_file: str,
    contract_name: str,
    memento: SourceMementoDto,
    *,
    role: str,
    ast_kind: str,
) -> dict[str, Any]:
    totals = {
        "source_loci": 1,
        "source_warranted": 1,
        "source_inactive": 0,
        "source_support": 0,
        "source_refused": 0,
        "source_unresolved": 0,
        "unclassified_source": 0,
    }
    return {
        "role": role,
        "contract": contract_name,
        "file": memento_file,
        "sourceFunctionName": fn.name,
        "totals": totals,
        "loci": [
            {
                "file": memento_file,
                "line": getattr(stmt, "lineno"),
                "col": getattr(stmt, "col_offset"),
                "status": "warranted",
                "ast_kind": ast_kind,
                "role": role,
                "contract": contract_name,
                "sourceMemento": memento,
            }
        ],
    }


def _walk_row(
    selected: str,
    ast_kind: str,
    stmt: ast.stmt,
    filename: str,
    memento: SourceMementoDto,
    output: str,
    *,
    requested_role: str = "term",
    emitted_formula: dict[str, Any] | None = None,
) -> FactoryWalkRowDto:
    return FactoryWalkRowDto(
        file=filename,
        line=getattr(stmt, "lineno"),
        requested_role=requested_role,
        ast_kind=ast_kind,
        selected=selected,
        status="warranted",
        output=output,
        source_memento=memento,
        span=SourceSpanDto(
            start_line=getattr(stmt, "lineno"),
            start_col=getattr(stmt, "col_offset"),
            end_line=getattr(stmt, "end_lineno") or getattr(stmt, "lineno"),
            end_col=getattr(stmt, "end_col_offset") or 0,
        ),
        emitted_formula=emitted_formula,
    )
