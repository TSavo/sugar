from __future__ import annotations

import ast
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.ir import and_, eq, formula_to_value, num
from sugar_lift_py_tests.kit_rpc import (
    BodyUniverseDto,
    FactoryWalkRowDto,
    LiftReportPayloadDto,
    SourceMementoDto,
    SourceSpanDto,
)
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.array_literal_sugar import ArrayLiteralSugar
from sugar_lift_py_tests.sugar.map_sugar import MapSugar
from sugar_lift_py_tests.sugar.method_sugar import MethodSugar


@dataclass(frozen=True)
class ArrayMapLift:
    payload: LiftReportPayloadDto


def lift_array_map_assertions(
    *,
    source: str,
    filename: str,
    memento_file: str | None = None,
) -> ArrayMapLift | None:
    tree = ast.parse(source, filename=filename)
    lines = source.splitlines(keepends=True)
    contracts: list[BodyUniverseDto] = []
    source_mementos: list[SourceMementoDto] = []
    source_audits: list[dict[str, Any]] = []
    factory_walk: list[FactoryWalkRowDto] = []
    for fn in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]:
        for stmt in fn.body:
            if not isinstance(stmt, ast.Assert):
                continue
            lifted = _lift_assert(
                stmt,
                fn=fn,
                filename=filename,
                memento_file=memento_file or filename,
                source_lines=lines,
            )
            if lifted is None:
                continue
            contract, mementos, audit, rows = lifted
            contracts.append(contract)
            source_mementos.extend(mementos)
            source_audits.append(audit)
            factory_walk.extend(rows)
    if not contracts:
        return None
    return ArrayMapLift(
        LiftReportPayloadDto(
            ir=contracts,
            source_mementos=source_mementos,
            source_ledger=_source_ledger(len(source_audits)),
            source_audits=source_audits,
            factory_walk=factory_walk,
        )
    )


def _lift_assert(
    stmt: ast.Assert,
    *,
    fn: ast.FunctionDef,
    filename: str,
    memento_file: str,
    source_lines: list[str],
) -> tuple[
    BodyUniverseDto,
    list[SourceMementoDto],
    dict[str, Any],
    list[FactoryWalkRowDto],
] | None:
    comparison = stmt.test
    if not isinstance(comparison, ast.Compare) or len(comparison.ops) != 1:
        return None
    if not isinstance(comparison.ops[0], ast.Eq) or len(comparison.comparators) != 1:
        return None
    method = MethodSugar.from_call(comparison.left)
    if method is None:
        return None
    blame = f"{filename}:{method.call.lineno}:{method.call.col_offset}"
    map_sugar = MapSugar.from_method(method, blame=blame)
    if map_sugar is None:
        return None
    expected_sugar = ArrayLiteralSugar.from_node(comparison.comparators[0])
    if expected_sugar is None:
        return None
    actual = complete_value(map_sugar.desugar(), owner="array-map actual")
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
            "MethodSugar",
            "Call",
            stmt,
            filename,
            statement_memento,
            "method-call",
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
        contract,
        [function_memento, statement_memento],
        _source_audit(stmt, fn, memento_file, contract.name, statement_memento),
        rows,
    )


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
    )


def _function_source_memento(
    fn: ast.FunctionDef,
    memento_file: str,
    source_lines: list[str],
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
        role="python.array-map-sugar",
        contract_name=f"{Path(memento_file).stem}::{fn.name}::array-map-sugar",
        param_names=body_source.get("param_names", []),
    )


def _statement_source_memento(
    stmt: ast.stmt,
    fn: ast.FunctionDef,
    memento_file: str,
    source_lines: list[str],
    *,
    contract_name: str,
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
        role="python.array-map-sugar",
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
            Path(__file__).resolve().parents[3] / "sugar-lift-python-source" / "src"
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
            Path(__file__).resolve().parents[3] / "sugar-lift-python-source" / "src"
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
