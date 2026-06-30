from __future__ import annotations

import ast
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.claim import SugarCatalog, SugarRole
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.ir import and_, eq, formula_to_value, make_var, num
from sugar_lift_py_tests.kit_rpc import (
    BodyUniverseDto,
    CallsiteFactDto,
    FactoryWalkRowDto,
    LiftReportPayloadDto,
    SourceMementoDto,
    SourceSpanDto,
)
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.array_literal_sugar import ArrayLiteralSugar
from sugar_lift_py_tests.sugar.list_sugar import list_sugar

from .factory_build_context import FactoryBuildContext
from .source_fragment import SourceFragment
from .sugar_constructors import build_map_sugar


@dataclass(frozen=True)
class SourceReportBuild:
    payload: LiftReportPayloadDto


def build_array_map_report(
    *,
    source: str,
    filename: str,
    memento_file: str | None = None,
) -> SourceReportBuild | None:
    tree = ast.parse(source, filename=filename)
    lines = source.splitlines(keepends=True)
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
                memento_file=memento_file or filename,
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
    lifted = _lift_fluent_array_map_assert(
        stmt,
        comparison=comparison,
        fn=fn,
        filename=filename,
        memento_file=memento_file,
        source_lines=source_lines,
    )
    if lifted is not None:
        return lifted
    return _lift_native_list_map_assert(
        stmt,
        comparison=comparison,
        fn=fn,
        filename=filename,
        memento_file=memento_file,
        source_lines=source_lines,
        functions_by_name=functions_by_name,
    )


def _lift_fluent_array_map_assert(
    stmt: ast.Assert,
    *,
    comparison: ast.Compare,
    fn: ast.FunctionDef,
    filename: str,
    memento_file: str,
    source_lines: list[str],
) -> tuple[
    list[BodyUniverseDto],
    list[SourceMementoDto],
    list[dict[str, Any]],
    list[FactoryWalkRowDto],
    list[dict[str, Any]],
] | None:
    call = comparison.left
    if not (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "map"
        and len(call.args) == 1
    ):
        return None
    factory_ctx = FactoryBuildContext(filename=filename, catalog=_array_map_catalog())
    receiver = factory_ctx.build_body(call.func.value, SugarRole.TERM)
    if not isinstance(receiver.sugar, ArrayLiteralSugar):
        return None
    try:
        map_sugar = build_map_sugar(SourceFragment.from_node(call, filename), factory_ctx)
    except TypeError:
        return None
    expected_sugar = _array_literal_sugar(comparison.comparators[0], factory_ctx)
    if expected_sugar is None:
        return None
    reduce_ctx = ReduceContext(temporal=factory_ctx.temporal)
    actual = complete_value(map_sugar.desugar(reduce_ctx), owner="array-map actual")
    expected = complete_value(expected_sugar.desugar(), owner="array-map expected")
    if len(actual.items) != len(expected.items):
        return None

    function_memento = _function_source_memento(fn, memento_file, source_lines)
    statement_memento = _statement_source_memento(
        stmt,
        fn,
        memento_file,
        source_lines,
        contract_name=f"{Path(memento_file).stem}::{fn.name}::array-map-sugar",
    )
    formula = and_(
        [eq(num(len(actual.items)), num(len(expected.items)))]
        + [
            eq(num(left.value), num(right.value))
            for left, right in zip(actual.items, expected.items)
        ]
    )
    inv = json.loads(encode_jcs(formula_to_value(formula)))
    contract = BodyUniverseDto(
        name=f"{Path(memento_file).stem}::{fn.name}::array-map-sugar",
        out_binding="out",
        inv=inv,
        source_warrants=[statement_memento],
    )
    rows = [
        _walk_row(
            "ArrayLiteralSugar",
            "List",
            stmt,
            filename,
            statement_memento,
            "ArrayLiteral",
        ),
        _walk_row(
            "LambdaSugar",
            "Lambda",
            stmt,
            filename,
            statement_memento,
            "callable",
        ),
        _walk_row(
            "MapSugar",
            "Call",
            stmt,
            filename,
            statement_memento,
            "predicate",
            emitted_formula=inv,
        ),
    ]
    return (
        [contract],
        [function_memento, statement_memento],
        [_source_audit(stmt, fn, memento_file, contract.name, statement_memento)],
        rows,
        [],
    )


def _lift_native_list_map_assert(
    stmt: ast.Assert,
    *,
    comparison: ast.Compare,
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
    blame = f"{filename}:{comparison.left.lineno}:{comparison.left.col_offset}"
    left_site = SourceFragment.from_node(comparison.left, filename)
    list_sugar_value = list_sugar(left_site, functions_by_name, blame=blame)
    if list_sugar_value is None:
        return None
    factory_ctx = FactoryBuildContext(filename=filename, catalog=_array_map_catalog())
    expected_sugar = _array_literal_sugar(comparison.comparators[0], factory_ctx)
    if expected_sugar is None:
        return None
    actual = complete_value(list_sugar_value.desugar(), owner="native list-map actual")
    expected = complete_value(expected_sugar.desugar(), owner="native list-map expected")
    if len(actual.items) != len(expected.items):
        return None

    callable_sugar = list_sugar_value.body.callable
    callable_name = callable_sugar.name
    callable_fn = functions_by_name[callable_name]
    callable_contract_name = f"{Path(memento_file).stem}::{callable_name}::callable"
    assertion_contract_name = f"{Path(memento_file).stem}::{fn.name}::array-map-sugar"
    callable_memento = _function_source_memento(
        callable_fn,
        memento_file,
        source_lines,
        role="python.callable-sugar",
        contract_name=callable_contract_name,
    )
    function_memento = _function_source_memento(
        fn,
        memento_file,
        source_lines,
        contract_name=assertion_contract_name,
    )
    statement_memento = _statement_source_memento(
        stmt,
        fn,
        memento_file,
        source_lines,
        contract_name=assertion_contract_name,
    )

    callable_post = json.loads(
        encode_jcs(
            formula_to_value(
                eq(make_var("out"), make_var(callable_sugar.return_name))
            )
        )
    )
    formula = and_(
        [eq(num(len(actual.items)), num(len(expected.items)))]
        + [
            eq(num(left.value), num(right.value))
            for left, right in zip(actual.items, expected.items)
        ]
    )
    inv = json.loads(encode_jcs(formula_to_value(formula)))
    callable_contract = BodyUniverseDto(
        name=callable_contract_name,
        out_binding="out",
        post=callable_post,
        source_warrants=[callable_memento],
    )
    callsite = _source_locus_string(
        memento_file,
        line=list_sugar_value.body.source_line,
        col=list_sugar_value.body.source_col,
    )
    assertion_contract = BodyUniverseDto(
        name=assertion_contract_name,
        out_binding="out",
        inv=inv,
        source_warrants=[statement_memento],
        warranted_by=CallsiteFactDto(
            contract_name=callable_contract_name,
            callsite=callsite,
            fact=callable_post,
            source_memento=statement_memento,
        ),
    )
    rows = [
        _walk_row(
            "FunctionRefSugar",
            "Name",
            stmt,
            filename,
            statement_memento,
            "callable",
            extra={"targetFunctionName": callable_name},
        ),
        _walk_row(
            "RangeSugar",
            "Call",
            stmt,
            filename,
            statement_memento,
            "Sequence",
        ),
        _walk_row(
            "MapBuiltinSugar",
            "Call",
            stmt,
            filename,
            statement_memento,
            "mapped-sequence",
        ),
        _walk_row(
            "ListSugar",
            "Call",
            stmt,
            filename,
            statement_memento,
            "ArrayLiteral",
            emitted_formula=inv,
        ),
    ]
    return (
        [callable_contract, assertion_contract],
        [callable_memento, function_memento, statement_memento],
        [
            _callable_source_audit(
                callable_fn,
                memento_file,
                callable_contract_name,
                callable_memento,
            ),
            _source_audit(stmt, fn, memento_file, assertion_contract.name, statement_memento),
        ],
        rows,
        [
            {
                "kind": "call-edge",
                "sourceContract": callable_contract.name,
                "targetSymbol": callable_name,
                "targetContract": assertion_contract.name,
                "callsite": callsite,
            }
        ],
    )


def _array_literal_sugar(node: ast.AST, ctx: FactoryBuildContext) -> ArrayLiteralSugar | None:
    if not isinstance(node, ast.List):
        return None
    sugar = ctx.build_child(node, SugarRole.TERM).sugar
    if not isinstance(sugar, ArrayLiteralSugar):
        return None
    return sugar


def _array_map_catalog() -> SugarCatalog:
    from sugar_lift_py_tests.sugar.array_literal_sugar import ARRAY_LITERAL_CLAIM
    from sugar_lift_py_tests.sugar.binop_sugar import BINOP_CLAIM
    from sugar_lift_py_tests.sugar.lambda_sugar import LAMBDA_CLAIM
    from sugar_lift_py_tests.sugar.name_sugar import NAME_CLAIM
    from sugar_lift_py_tests.sugar.primitive_literal_sugar import (
        PRIMITIVE_LITERAL_CLAIM,
    )

    return SugarCatalog(
        [
            PRIMITIVE_LITERAL_CLAIM,
            NAME_CLAIM,
            BINOP_CLAIM,
            LAMBDA_CLAIM,
            ARRAY_LITERAL_CLAIM,
        ]
    )


def _callsite_string(memento_file: str, node: ast.AST) -> str:
    return _source_locus_string(
        memento_file,
        line=getattr(node, "lineno"),
        col=getattr(node, "col_offset"),
    )


def _source_locus_string(memento_file: str, *, line: int, col: int) -> str:
    return (
        f"{memento_file.replace(os.sep, '/')}:"
        f"{line}:{col}"
    )


def _callable_source_audit(
    fn: ast.FunctionDef,
    memento_file: str,
    contract_name: str,
    memento: SourceMementoDto,
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
        "role": "python.callable-sugar",
        "contract": contract_name,
        "file": memento_file,
        "sourceFunctionName": fn.name,
        "totals": totals,
        "loci": [
            {
                "file": memento_file,
                "line": fn.lineno,
                "col": fn.col_offset,
                "status": "warranted",
                "ast_kind": "FunctionDef",
                "role": "python.callable-sugar",
                "contract": contract_name,
                "sourceMemento": memento,
            }
        ],
    }


def _source_audit(
    stmt: ast.Assert,
    fn: ast.FunctionDef,
    memento_file: str,
    contract_name: str,
    memento: SourceMementoDto,
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
        "role": "python.array-map-sugar",
        "contract": contract_name,
        "file": memento_file,
        "sourceFunctionName": fn.name,
        "totals": totals,
        "loci": [
            {
                "file": memento_file,
                "line": stmt.lineno,
                "col": stmt.col_offset,
                "status": "warranted",
                "ast_kind": "Assert",
                "role": "python.array-map-sugar",
                "contract": contract_name,
                "sourceMemento": memento,
            }
        ],
    }


def _walk_row(
    selected: str,
    ast_kind: str,
    stmt: ast.Assert,
    filename: str,
    memento: SourceMementoDto,
    output: str,
    emitted_formula: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> FactoryWalkRowDto:
    return FactoryWalkRowDto(
        file=filename,
        line=stmt.lineno,
        requested_role="term",
        ast_kind=ast_kind,
        selected=selected,
        status="warranted",
        output=output,
        source_memento=memento,
        span=SourceSpanDto(
            start_line=stmt.lineno,
            start_col=stmt.col_offset,
            end_line=stmt.end_lineno,
            end_col=stmt.end_col_offset or 0,
        ),
        emitted_formula=emitted_formula,
        extra=extra or {},
    )


def _function_source_memento(
    fn: ast.FunctionDef,
    memento_file: str,
    source_lines: list[str],
    *,
    role: str = "python.array-map-sugar",
    contract_name: str | None = None,
) -> SourceMementoDto:
    body_source = _body_source_locator(fn, memento_file, source_lines)
    span = body_source["span"]
    return SourceMementoDto(
        file=memento_file,
        span=SourceSpanDto(
            start_line=span["start_line"],
            start_col=span["start_col"],
            end_line=span["end_line"],
            end_col=span["end_col"],
        ),
        source_cid=body_source["source_cid"],
        template_cid=body_source["template_cid"],
        source_function_name=fn.name,
        role=role,
        contract_name=contract_name or f"{Path(memento_file).stem}::{fn.name}::array-map-sugar",
        param_names=body_source.get("param_names", []),
    )


def _statement_source_memento(
    stmt: ast.stmt,
    fn: ast.FunctionDef,
    memento_file: str,
    source_lines: list[str],
    *,
    contract_name: str,
    role: str = "python.array-map-sugar",
) -> SourceMementoDto:
    statement_source = _statement_source_locator(stmt, fn, memento_file, source_lines)
    span = statement_source["span"]
    return SourceMementoDto(
        file=memento_file,
        span=SourceSpanDto(
            start_line=span["start_line"],
            start_col=span["start_col"],
            end_line=span["end_line"],
            end_col=span["end_col"],
        ),
        source_cid=statement_source["source_cid"],
        template_cid=statement_source["template_cid"],
        source_function_name=fn.name,
        role=role,
        contract_name=contract_name,
        param_names=statement_source.get("param_names", []),
        extra={"source_kind": "python.ast-stmt"},
    )


def _body_source_locator(
    fn: ast.FunctionDef,
    memento_file: str,
    source_lines: list[str],
) -> dict[str, Any]:
    try:
        from sugar_lift_python_source.bind_lifter import _body_source_locator as locator
    except ModuleNotFoundError:
        sibling_src = (
            Path(__file__).resolve().parents[4] / "sugar-lift-python-source" / "src"
        )
        if str(sibling_src) not in sys.path:
            sys.path.insert(0, str(sibling_src))
        from sugar_lift_python_source.bind_lifter import _body_source_locator as locator
    return locator(fn, memento_file.replace(os.sep, "/"), source_lines)


def _statement_source_locator(
    stmt: ast.stmt,
    fn: ast.FunctionDef,
    memento_file: str,
    source_lines: list[str],
) -> dict[str, Any]:
    source = "".join(source_lines)
    source_text = ast.get_source_segment(source, stmt)
    if source_text is None:
        raise ValueError(f"could not extract source for statement at line {stmt.lineno}")
    function_param_names, stmt_to_template, blake3_512_of, template_cid_of_json = (
        _statement_source_api()
    )
    ast_template = stmt_to_template(stmt, function_param_names(fn))
    return {
        "file": memento_file.replace(os.sep, "/"),
        "source_cid": blake3_512_of(source_text.encode("utf-8")),
        "span": {
            "start_line": stmt.lineno,
            "start_col": stmt.col_offset,
            "end_line": stmt.end_lineno or stmt.lineno,
            "end_col": stmt.end_col_offset or 0,
        },
        "template_cid": template_cid_of_json(ast_template),
        "param_names": function_param_names(fn),
    }


def _statement_source_api():
    try:
        from sugar_lift_python_source.ast_template import (
            function_param_names,
            stmt_to_template,
        )
        from sugar_lift_python_source.canonical import (
            blake3_512_of,
            template_cid_of_json,
        )
    except ModuleNotFoundError:
        sibling_src = (
            Path(__file__).resolve().parents[4] / "sugar-lift-python-source" / "src"
        )
        if str(sibling_src) not in sys.path:
            sys.path.insert(0, str(sibling_src))
        from sugar_lift_python_source.ast_template import (
            function_param_names,
            stmt_to_template,
        )
        from sugar_lift_python_source.canonical import (
            blake3_512_of,
            template_cid_of_json,
        )
    return function_param_names, stmt_to_template, blake3_512_of, template_cid_of_json


def _source_ledger(source_loci: int) -> dict[str, int]:
    return {
        "source_loci": source_loci,
        "source_warranted": source_loci,
        "source_inactive": 0,
        "source_support": 0,
        "source_refused": 0,
        "source_unresolved": 0,
        "unclassified_source": 0,
    }
