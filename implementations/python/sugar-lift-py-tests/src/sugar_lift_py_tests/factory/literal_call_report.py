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
from sugar_lift_py_tests.ir import Formula, and_, ctor, eq, formula_to_value, str_const
from sugar_lift_py_tests.kit_rpc import (
    BodyUniverseDto,
    FactoryWalkRowDto,
    LiftReportPayloadDto,
    SourceMementoDto,
    SourceSpanDto,
)
from sugar_lift_py_tests.layer2 import _canonical_term_sig
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.string_literal_sugar import string_literal_sugar

from .factory_build_context import FactoryBuildContext
from .source_site import SourceSite

# One lift, returned as five parallel lists: (contracts, source_mementos,
# source_audits, factory_walk_rows, call_edges).
LiftResult = tuple[
    list[BodyUniverseDto],
    list[SourceMementoDto],
    list[dict[str, Any]],
    list[FactoryWalkRowDto],
    list[dict[str, Any]],
]


@dataclass(frozen=True)
class SourceReportBuild:
    payload: LiftReportPayloadDto


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
    del contract_bindings  # composition is by #euf# callsite name, not a binding/CID
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
            )
            # _lift_assert never returns None now: it lifts the assert or PANICS
            # (FactoryGap). A silent skip here would be the cardinal crime.
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
) -> LiftResult | None:
    """One mechanism. An assertion `callee(args) == expected` is a fact -- a debt on
    `callee` -- and it WARRANTS a dig for `callee`'s contract.

    1. THE FACT (always): the assertion mints the euf callsite obligation
       `eq(call:callee(args), expected)`.
    2. THE DIG (warranted by the fact): resolve `callee`'s contract.
       - source present (`callee in functions_by_name`) -> the dig CONTINUES into the
         body, desugars it, and mints the universe post -- the same dig that warranted
         it discharges the fact.
       - source absent -> an imported `.proof` already SUPPLIES the contract (a memoized
         dig); the dig stops on that cache hit and we mint nothing here.

    Either way the verifier's ambient-post specialization joins the post (local or
    imported) to the fact and z3 decides `and(universe, fact)`."""
    comparison = stmt.test
    if not isinstance(comparison, ast.Compare) or len(comparison.ops) != 1:
        _panic_no_sugar(
            stmt, memento_file,
            observed=f"assert-test:{type(comparison).__name__}",
            requested="EqualityAssertion",
            fix="lift this assertion shape (only `call(...) == literal` is covered)",
        )
    if not isinstance(comparison.ops[0], ast.Eq) or len(comparison.comparators) != 1:
        _panic_no_sugar(
            stmt, memento_file,
            observed=f"assert-compare-op:{type(comparison.ops[0]).__name__}",
            requested="EqualityAssertion",
            fix="lift non-`==` comparison assertions",
        )
    callee_name = _callee_name(comparison.left)
    if callee_name is None:
        _panic_no_sugar(
            comparison.left, memento_file,
            observed=f"assert-eq-lhs:{type(comparison.left).__name__}",
            requested="CallsiteEquality",
            fix="lift `<lhs> == literal` where the lhs is not a call",
        )

    # _lift_callsite_assertion lifts or PANICS; it never returns None.
    assertion = _lift_callsite_assertion(
        stmt,
        comparison=comparison,
        callee_name=callee_name,
        fn=fn,
        filename=filename,
        memento_file=memento_file,
        source_lines=source_lines,
    )

    universe: LiftResult | None = None
    if callee_name in functions_by_name:
        universe = _dig_universe(
            comparison.left,
            functions_by_name=functions_by_name,
            filename=filename,
            memento_file=memento_file,
            source_lines=source_lines,
        )
    return _merge_lifts(universe, assertion)


def _lift_callsite_assertion(
    stmt: ast.Assert,
    *,
    comparison: ast.Compare,
    callee_name: str,
    fn: ast.FunctionDef,
    filename: str,
    memento_file: str,
    source_lines: list[str],
) -> LiftResult | None:
    """The fact. `callee(args) == expected` lifts to the euf callsite obligation
    `eq(call:callee(args), expected)`, contract-named `callee#euf#<arg_sig>::assertion`.
    `call:<callee>` is the callsite-ctor head the verifier recognizes
    (`is_callsite_ctor_term` requires the `call:` prefix) and the head the universe
    post specializes onto. Only concrete-literal args take this path; a symbolic arg
    returns None."""
    expected_sugar = string_literal_sugar(comparison.comparators[0])
    if expected_sugar is None:
        _panic_no_sugar(
            comparison.comparators[0], memento_file,
            observed=f"callsite-expected:{type(comparison.comparators[0]).__name__}",
            requested="StringLiteralExpected",
            fix="lift non-string-literal expected (e.g. numeric `== 32`, list `== [..]`)",
        )
    expected = complete_value(expected_sugar.desugar(), owner="callsite assertion expected")
    arg_terms = []
    for arg_node in comparison.left.args:
        arg_sugar = string_literal_sugar(arg_node)
        if arg_sugar is None:
            _panic_no_sugar(
                arg_node, memento_file,
                observed=f"callsite-arg:{type(arg_node).__name__}",
                requested="StringLiteralArg",
                fix="lift non-string-literal call args (e.g. variables, arrays, numerics)",
            )
        arg_value = complete_value(arg_sugar.desugar(), owner="callsite assertion arg")
        arg_terms.append(str_const(arg_value.value))
    euf_term = ctor(f"call:{callee_name}", arg_terms)
    assertion_contract_name = f"{callee_name}#euf#{_canonical_term_sig(euf_term)}::assertion"
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


def _dig_universe(
    call_node: ast.Call,
    *,
    functions_by_name: dict[str, ast.FunctionDef],
    filename: str,
    memento_file: str,
    source_lines: list[str],
) -> LiftResult | None:
    """The dig, when the source is present. Desugar `callee`'s body into the universe
    post (a forall over the function's formals) and mint it as a `function-contract`.
    `kind=function-contract` + `post` + `formals` makes the mint auto-mint a
    `call:<callee> -> this contract` bridge, which is exactly what `collect_ambient_posts`
    keys on -- so the post becomes an ambient universal the verifier specializes onto
    any matching `call:<callee>` callsite, local or imported."""
    from .build import default_catalog

    factory_ctx = FactoryBuildContext(
        filename=filename,
        catalog=default_catalog(),
        name_resolver=functions_by_name,
    )
    try:
        call_sugar = build_function_call_sugar(
            SourceSite.from_node(call_node, filename),
            factory_ctx,
        )
    except TypeError as exc:
        _panic_no_sugar(
            call_node, memento_file,
            observed=f"dig-body:{type(call_node).__name__}",
            requested="FunctionBodyConstraint",
            fix=f"lift this function body for the dig ({exc})",
        )
    target_fn = functions_by_name[call_sugar.target_name]
    body_steps = call_sugar.factory_steps(target_fn)
    body_formulas = call_sugar.constraint_formulas()
    body_formula_values = [_formula_to_rpc(formula) for formula in body_formulas]
    body_step_formulas = call_sugar.constraint_formula_steps()
    body_step_formula_values = [
        _formula_to_rpc(formula) if formula is not None else None
        for formula in body_step_formulas
    ]
    # The exported universe keeps `out` as its out-binding: the verifier substitutes
    # `out_binding -> callsite` and `formals -> call args`, turning
    # `str.eq-bv-blocks(out, value, ...)` into `str.eq-bv-blocks(call:enc(xyz), xyz, ...)`.
    # It must be CLOSED after those substitutions or the verifier skips it as "open", so
    # drop free-var DEFINITIONS (`eq(alphabet, "..")` whose var is neither a formal nor
    # `out`); the str.eq-bv-blocks payload already carries the alphabet constant.
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
    function_contract = BodyUniverseDto(
        name=function_contract_name,
        out_binding="out",
        post=function_post,
        source_warrants=[function_memento],
        formals=[arg.arg for arg in target_fn.args.args],
        kind="function-contract",
        # Must equal the callsite ctor head the fact emits (`call:<callee>`), which the
        # verifier matches via `post.source_symbol == callsite.name`.
        bridge_source_symbol=f"call:{target_fn.name}",
    )
    audit = _source_audit(
        target_fn,
        return_stmt,
        memento_file,
        function_contract_name,
        return_memento,
        role="python.literal-call-sugar",
        ast_kind="Return",
    )
    walk_rows = [
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
    return ([function_contract], [function_memento, *body_mementos], [audit], walk_rows, [])


def _merge_lifts(universe: LiftResult | None, assertion: LiftResult) -> LiftResult:
    """Universe first (the function-contract), then the assertion -- the order the
    consumers expect when both are present."""
    if universe is None:
        return assertion
    return tuple(  # type: ignore[return-value]
        [*u, *a] for u, a in zip(universe, assertion)
    )


def _panic_no_sugar(node, memento_file, *, observed, requested, fix):
    """The mouth. The lifter saw an assertion it could not lift and REFUSES to drop it
    silently -- it PANICS, naming the AST shape and the sugar that is missing. A silent
    `return None` here would be the cardinal crime (un-done work disguised as done), so
    the design forbids it: every give-up on a claim is a FactoryGap, never a None."""
    from .factory_audit_row import FactoryAuditRow
    from .factory_gap import FactoryGap
    from .factory_gap_info import FactoryGapInfo

    blame = f"{memento_file}:{getattr(node, 'lineno', 0)}:{getattr(node, 'col_offset', 0)}"
    info = FactoryGapInfo(
        owner="python.factory.literal-call",
        blame=blame,
        observed=observed,
        requested=requested,
        fix=fix,
    )
    raise FactoryGap(
        info,
        FactoryAuditRow(
            role=requested,
            status="sugar-gap",
            observed=observed,
            blame=blame,
            selected=None,
            candidates=[],
            message=info.message,
        ),
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
