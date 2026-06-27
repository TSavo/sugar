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
            contract, memento, rows = lifted
            contracts.append(contract)
            source_mementos.append(memento)
            factory_walk.extend(rows)
    if not contracts:
        return None
    return ArrayMapLift(
        LiftReportPayloadDto(
            ir=contracts,
            source_mementos=source_mementos,
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
) -> tuple[BodyUniverseDto, SourceMementoDto, list[FactoryWalkRowDto]] | None:
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

    memento = _source_memento(fn, memento_file, source_lines)
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
        source_warrants=[memento],
    )
    rows = [
        _walk_row("ArrayLiteralSugar", "List", stmt, filename, memento, "ArrayLiteral"),
        _walk_row("MethodSugar", "Call", stmt, filename, memento, "method-call"),
        _walk_row("MapSugar", "Call", stmt, filename, memento, "predicate"),
    ]
    return contract, memento, rows


def _walk_row(
    selected: str,
    ast_kind: str,
    stmt: ast.Assert,
    filename: str,
    memento: SourceMementoDto,
    output: str,
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
    )


def _source_memento(
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
