from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.claim import SugarCatalog, SugarRole
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import ArrayLiteral, FloorValue, TermValue
from sugar_lift_py_tests.ir import and_, eq, formula_to_value, make_var, num
from sugar_lift_py_tests.kit_rpc import (
    BodyUniverseDto,
    CallEdgeDto,
    CallsiteFactDto,
    FactoryAuditDto,
    FactoryWalkCompleteRowDto,
    FactoryWalkRowDto,
    LiftReportPayloadDto,
    SourceAuditDto,
    SourceMementoDto,
    SourceSpanDto,
)
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.proofir import (
    BridgeAtom,
    CallEdgeDecl,
    ConstructionSite,
    Derived,
    IntSort,
    Provenance,
    Sort,
    UniverseMint,
    claim_formula_from_ir,
)
from sugar_lift_py_tests.sugar.array_literal_sugar import ArrayLiteralSugar
from sugar_lift_py_tests.sugar.list_sugar import list_sugar

from .factory_build_context import FactoryBuildContext
from .source_fragment import SourceFragment


@dataclass(frozen=True)
class SourceReportBuild:
    payload: LiftReportPayloadDto


def build_array_map_report(
    *,
    source: str,
    filename: str,
    memento_file: str | None = None,
) -> SourceReportBuild | None:
    root = SourceFragment.from_source(source, filename)
    lines = source.splitlines(keepends=True)
    contracts: list[BodyUniverseDto] = []
    source_mementos: list[SourceMementoDto] = []
    source_audits: list[SourceAuditDto] = []
    factory_audits: list[FactoryAuditDto] = []
    factory_walk: list[FactoryWalkRowDto] = []
    call_edges: list[CallEdgeDto] = []
    functions_by_name = {
        frag.function_name(): frag
        for frag in root.walk()
        if frag.observed == "FunctionDef"
    }
    for fn in functions_by_name.values():
        for stmt in fn.function_body():
            if stmt.observed != "Assert":
                continue
            lifted = _lift_assert(
                stmt,
                fn=fn,
                filename=filename,
                memento_file=memento_file or filename,
                source_lines=lines,
                functions_by_name=functions_by_name,
                factory_audits=factory_audits,
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
            factory_audits=factory_audits,
            factory_walk=factory_walk,
            call_edges=call_edges,
        )
    )


def _lift_assert(
    stmt: SourceFragment,
    *,
    fn: SourceFragment,
    filename: str,
    memento_file: str,
    source_lines: list[str],
    functions_by_name: dict[str, SourceFragment],
    factory_audits: list[FactoryAuditDto],
) -> (
    tuple[
        list[BodyUniverseDto],
        list[SourceMementoDto],
        list[SourceAuditDto],
        list[FactoryWalkRowDto],
        list[CallEdgeDto],
    ]
    | None
):
    comparison = stmt.assert_test()
    if comparison.observed != "Compare" or len(comparison.compare_ops()) != 1:
        return None
    if (
        comparison.compare_ops()[0] != "Eq"
        or len(comparison.compare_comparators()) != 1
    ):
        return None
    lifted = _lift_fluent_array_map_assert(
        stmt,
        comparison=comparison,
        fn=fn,
        filename=filename,
        memento_file=memento_file,
        source_lines=source_lines,
        factory_audits=factory_audits,
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
        factory_audits=factory_audits,
    )


def _lift_fluent_array_map_assert(
    stmt: SourceFragment,
    *,
    comparison: SourceFragment,
    fn: SourceFragment,
    filename: str,
    memento_file: str,
    source_lines: list[str],
    factory_audits: list[FactoryAuditDto],
) -> (
    tuple[
        list[BodyUniverseDto],
        list[SourceMementoDto],
        list[SourceAuditDto],
        list[FactoryWalkRowDto],
        list[CallEdgeDto],
    ]
    | None
):
    call = comparison.compare_left()
    if not (
        call.observed == "Call"
        and call.call_is_method_call()
        and call.call_target_name() == "map"
        and call.call_arg_count() == 1
    ):
        return None
    factory_ctx = FactoryBuildContext(
        filename=filename,
        catalog=_array_map_catalog(),
        audit_sink=factory_audits,
    )
    receiver = factory_ctx.build_body(call.call_receiver(), SugarRole.TERM)
    if not isinstance(receiver.sugar, ArrayLiteralSugar):
        return None
    map_body = factory_ctx.build_body(call, SugarRole.TERM)
    expected_sugar = _array_literal_sugar(
        comparison.compare_comparators()[0], factory_ctx
    )
    if expected_sugar is None:
        return None
    reduce_ctx = ReduceContext.derived(factory_ctx, owner="array_map_report")
    actual = complete_value(map_body.reduce(reduce_ctx), owner="array-map actual")
    expected = complete_value(expected_sugar.desugar(), owner="array-map expected")
    actual_items = _array_number_items(actual)
    expected_items = _array_number_items(expected)
    if actual_items is None or expected_items is None:
        return None
    if len(actual_items) != len(expected_items):
        return None

    function_memento = _function_source_memento(fn, memento_file, source_lines)
    statement_memento = _statement_source_memento(
        stmt,
        fn,
        memento_file,
        source_lines,
        contract_name=f"{Path(memento_file).stem}::{fn.function_name()}::array-map-sugar",
    )
    formula = and_(
        [eq(num(len(actual_items)), num(len(expected_items)))]
        + [
            eq(num(left), num(right))
            for left, right in zip(actual_items, expected_items)
        ]
    )
    inv = _claim_formula(
        formula,
        stmt,
        memento_file,
        role="python.array-map-sugar",
        node_class=UniverseMint.node_class,
    )
    contract = UniverseMint(
        name=f"{Path(memento_file).stem}::{fn.function_name()}::array-map-sugar",
        slot="inv",
        formula=inv,
        provenance=inv.provenance,
        out_binding="out",
        source_warrants=(statement_memento,),
    ).to_body_universe()
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
    stmt: SourceFragment,
    *,
    comparison: SourceFragment,
    fn: SourceFragment,
    filename: str,
    memento_file: str,
    source_lines: list[str],
    functions_by_name: dict[str, SourceFragment],
    factory_audits: list[FactoryAuditDto],
) -> (
    tuple[
        list[BodyUniverseDto],
        list[SourceMementoDto],
        list[SourceAuditDto],
        list[FactoryWalkRowDto],
        list[CallEdgeDto],
    ]
    | None
):
    left_frag = comparison.compare_left()
    blame = f"{filename}:{left_frag.line}:{left_frag.col}"
    list_sugar_value = list_sugar(left_frag, functions_by_name, blame=blame)
    if list_sugar_value is None:
        return None
    factory_ctx = FactoryBuildContext(
        filename=filename,
        catalog=_array_map_catalog(),
        audit_sink=factory_audits,
    )
    expected_sugar = _array_literal_sugar(
        comparison.compare_comparators()[0], factory_ctx
    )
    if expected_sugar is None:
        return None
    actual = complete_value(list_sugar_value.desugar(), owner="native list-map actual")
    expected = complete_value(
        expected_sugar.desugar(), owner="native list-map expected"
    )
    actual_items = _array_number_items(actual)
    expected_items = _array_number_items(expected)
    if actual_items is None or expected_items is None:
        return None
    if len(actual_items) != len(expected_items):
        return None

    callable_sugar = list_sugar_value.body.callable
    callable_name = callable_sugar.name
    callable_fn = functions_by_name[callable_name]
    callable_contract_name = f"{Path(memento_file).stem}::{callable_name}::callable"
    assertion_contract_name = (
        f"{Path(memento_file).stem}::{fn.function_name()}::array-map-sugar"
    )
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

    callable_post = _claim_formula(
        eq(make_var("out"), make_var(callable_sugar.return_name)),
        stmt,
        memento_file,
        role="python.callable-sugar",
        node_class=UniverseMint.node_class,
        var_sorts={"out": IntSort(), callable_sugar.return_name: IntSort()},
        allowed_vars=("out", callable_sugar.return_name),
    )
    formula = and_(
        [eq(num(len(actual_items)), num(len(expected_items)))]
        + [
            eq(num(left), num(right))
            for left, right in zip(actual_items, expected_items)
        ]
    )
    inv = _claim_formula(
        formula,
        stmt,
        memento_file,
        role="python.array-map-sugar",
        node_class=UniverseMint.node_class,
    )
    callable_contract = UniverseMint(
        name=callable_contract_name,
        slot="post",
        formula=callable_post,
        provenance=callable_post.provenance,
        out_binding="out",
        source_warrants=(callable_memento,),
    ).to_body_universe()
    callsite = _source_locus_string(
        memento_file,
        line=list_sugar_value.body.source_line,
        col=list_sugar_value.body.source_col,
    )
    assertion_contract = UniverseMint(
        name=assertion_contract_name,
        slot="inv",
        formula=inv,
        provenance=inv.provenance,
        out_binding="out",
        source_warrants=(statement_memento,),
        warranted_by=CallsiteFactDto(
            contract_name=callable_contract_name,
            callsite=callsite,
            fact=callable_post,
            source_memento=statement_memento,
        ),
    ).to_body_universe()
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
            _source_audit(
                stmt, fn, memento_file, assertion_contract.name, statement_memento
            ),
        ],
        rows,
        [
            CallEdgeDecl(
                bridge=BridgeAtom(
                    source_contract=callable_contract.name,
                    target_symbol=callable_name,
                    target_contract=assertion_contract.name,
                    callsite=callsite,
                ),
                provenance=Provenance(
                    node_class=CallEdgeDecl.node_class,
                    construction_site=ConstructionSite(
                        path=memento_file,
                        line=stmt.line,
                        column=stmt.col,
                    ),
                    warrant=Derived(floor_chain=("array-map-call-edge",)),
                ),
            ).to_declaration()
        ],
    )


def _array_literal_sugar(
    node: SourceFragment, ctx: FactoryBuildContext
) -> ArrayLiteralSugar | None:
    if node.observed != "List":
        return None
    sugar = ctx.build_child(node, SugarRole.TERM).sugar
    if not isinstance(sugar, ArrayLiteralSugar):
        return None
    return sugar


def _array_map_catalog() -> SugarCatalog:
    from sugar_lift_py_tests.sugar import array_literal_sugar  # noqa: F401
    from sugar_lift_py_tests.sugar import binop_sugar  # noqa: F401
    from sugar_lift_py_tests.sugar import lambda_sugar  # noqa: F401
    from sugar_lift_py_tests.sugar import map_sugar  # noqa: F401
    from sugar_lift_py_tests.sugar import name_sugar  # noqa: F401
    from sugar_lift_py_tests.sugar import primitive_literal_sugar  # noqa: F401
    from sugar_lift_py_tests.sugar.sugar_base import registered_claims

    names = {
        "PrimitiveLiteralSugar",
        "NameSugar",
        "BinOpSugar",
        "LambdaSugar",
        "ArrayLiteralSugar",
        "MapSugar",
    }
    return SugarCatalog([c for c in registered_claims() if c.name in names])


def _callsite_string(memento_file: str, node: SourceFragment) -> str:
    return _source_locus_string(
        memento_file,
        line=node.line,
        col=node.col,
    )


def _source_locus_string(memento_file: str, *, line: int, col: int) -> str:
    return f"{memento_file.replace(os.sep, '/')}:" f"{line}:{col}"


def _claim_formula(
    formula,
    stmt: SourceFragment,
    memento_file: str,
    *,
    role: str,
    node_class: str,
    var_sorts: dict[str, Sort] | None = None,
    allowed_vars: tuple[str, ...] | None = None,
):
    sorts = var_sorts or {}
    return claim_formula_from_ir(
        formula,
        var_sorts=sorts,
        allowed_vars=allowed_vars or tuple(sorts),
        provenance=Provenance(
            node_class=node_class,
            construction_site=ConstructionSite(
                path=memento_file,
                line=stmt.line,
                column=stmt.col,
            ),
            warrant=Derived(floor_chain=(role,)),
        ),
        role=role,
    )


def _callable_source_audit(
    fn: SourceFragment,
    memento_file: str,
    contract_name: str,
    memento: SourceMementoDto,
) -> SourceAuditDto:
    totals = {
        "source_loci": 1,
        "source_warranted": 1,
        "source_inactive": 0,
        "source_support": 0,
        "source_boundary": 0,
        "source_unresolved": 0,
        "unclassified_source": 0,
    }
    return {
        "role": "python.callable-sugar",
        "contract": contract_name,
        "file": memento_file,
        "sourceFunctionName": fn.function_name(),
        "totals": totals,
        "loci": [
            {
                "file": memento_file,
                "line": fn.line,
                "col": fn.col,
                "status": "warranted",
                "ast_kind": "FunctionDef",
                "role": "python.callable-sugar",
                "contract": contract_name,
                "sourceMemento": memento,
            }
        ],
    }


def _array_number_items(value: FloorValue) -> list[int] | None:
    if not isinstance(value, ArrayLiteral):
        return None
    numbers: list[int] = []
    for item in value.items:
        if not isinstance(item, TermValue):
            return None
        numbers.append(int(item.value))
    return numbers


def _source_audit(
    stmt: SourceFragment,
    fn: SourceFragment,
    memento_file: str,
    contract_name: str,
    memento: SourceMementoDto,
) -> SourceAuditDto:
    totals = {
        "source_loci": 1,
        "source_warranted": 1,
        "source_inactive": 0,
        "source_support": 0,
        "source_boundary": 0,
        "source_unresolved": 0,
        "unclassified_source": 0,
    }
    return {
        "role": "python.array-map-sugar",
        "contract": contract_name,
        "file": memento_file,
        "sourceFunctionName": fn.function_name(),
        "totals": totals,
        "loci": [
            {
                "file": memento_file,
                "line": stmt.line,
                "col": stmt.col,
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
    stmt: SourceFragment,
    filename: str,
    memento: SourceMementoDto,
    output: str,
    emitted_formula: Mapping[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> FactoryWalkRowDto:
    return FactoryWalkCompleteRowDto(
        file=filename,
        line=stmt.line,
        requested_role="term",
        ast_kind=ast_kind,
        selected=selected,
        status="warranted",
        output=output,
        source_memento=memento,
        span=SourceSpanDto(
            start_line=stmt.line,
            start_col=stmt.col,
            end_line=stmt.end_line,
            end_col=stmt.end_col,
        ),
        emitted_formula=emitted_formula,
        extra=extra or {},
    )


def _function_source_memento(
    fn: SourceFragment,
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
        source_function_name=fn.function_name(),
        role=role,
        contract_name=contract_name
        or f"{Path(memento_file).stem}::{fn.function_name()}::array-map-sugar",
        param_names=body_source.get("param_names", []),
    )


def _statement_source_memento(
    stmt: SourceFragment,
    fn: SourceFragment,
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
        source_function_name=fn.function_name(),
        role=role,
        contract_name=contract_name,
        param_names=statement_source.get("param_names", []),
        extra={"source_kind": "python.ast-stmt"},
    )


def _body_source_locator(
    fn: SourceFragment,
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
    return locator(fn.function_node(), memento_file.replace(os.sep, "/"), source_lines)


def _statement_source_locator(
    stmt: SourceFragment,
    fn: SourceFragment,
    memento_file: str,
    source_lines: list[str],
) -> dict[str, Any]:
    source = "".join(source_lines)
    source_text = stmt.source_text(source)
    if source_text is None:
        raise ValueError(f"could not extract source for statement at line {stmt.line}")
    function_param_names, stmt_to_template, blake3_512_of, template_cid_of_json = (
        _statement_source_api()
    )
    fn_node = fn.function_node()
    ast_template = stmt_to_template(stmt.stmt_node(), function_param_names(fn_node))
    return {
        "file": memento_file.replace(os.sep, "/"),
        "source_cid": blake3_512_of(source_text.encode("utf-8")),
        "span": {
            "start_line": stmt.line,
            "start_col": stmt.col,
            "end_line": stmt.end_line,
            "end_col": stmt.end_col,
        },
        "template_cid": template_cid_of_json(ast_template),
        "param_names": function_param_names(fn_node),
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
        "source_boundary": 0,
        "source_unresolved": 0,
        "unclassified_source": 0,
    }
