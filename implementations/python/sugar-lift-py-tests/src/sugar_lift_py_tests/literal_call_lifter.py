from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sugar_lift_py_tests.array_map_lifter import (
    _callsite_string,
    _function_source_memento,
    _source_ledger,
    _statement_source_memento,
)
from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.factory import FactoryBuildContext, SourceSite, default_catalog
from sugar_lift_py_tests.factory.sugar_constructors import build_function_call_sugar
from sugar_lift_py_tests.ir import Formula, and_, eq, formula_to_value, str_const
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


@dataclass(frozen=True)
class LiteralCallLift:
    payload: LiftReportPayloadDto


def lift_literal_call_assertions(
    *,
    source: str,
    filename: str,
    memento_file: str | None = None,
) -> LiteralCallLift | None:
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
    return LiteralCallLift(
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
    actual = complete_value(call_sugar.desugar(), owner="literal function call actual")
    expected = complete_value(expected_sugar.desugar(), owner="literal call expected")

    target_fn = functions_by_name[call_sugar.target_name]
    body_steps = call_sugar.factory_steps(target_fn)
    body_formulas = call_sugar.constraint_formulas(actual)
    body_formula_values = [_formula_to_rpc(formula) for formula in body_formulas]
    function_post = (
        body_formula_values[0]
        if len(body_formulas) == 1
        else _formula_to_rpc(and_(body_formulas))
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

    assertion_inv = _formula_to_rpc(eq(str_const(actual.value), str_const(expected.value)))
    function_contract = BodyUniverseDto(
        name=function_contract_name,
        out_binding="out",
        post=function_post,
        source_warrants=[function_memento],
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
            fact=function_post,
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
                emitted_formula=body_formula_values[index]
                if index < len(body_formula_values)
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
