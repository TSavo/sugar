from __future__ import annotations

import ast
from dataclasses import replace

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import SymbolicValue, TermValue
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.temporal import TemporalContext


def _reduce_sourced(source: str):
    node = ast.parse(source, mode="eval").body
    site = SourceFragment.from_node(node, "t.py", source=source)
    temporal = TemporalContext.empty()
    for name in ("x", "y"):
        temporal = temporal.bind_value(name, SymbolicValue(make_var(name)))
    ctx = replace(
        FactoryBuildContext(filename="t.py", catalog=default_catalog()),
        temporal=temporal,
    )
    return complete_value(
        build_node(site, filename="t.py", role=SugarRole.TERM, ctx=ctx).sugar.desugar(
            ctx
        ),
        owner="test",
    )


def test_runtime_bit_or_uses_native_operator_coordinate() -> None:
    assert _reduce_sourced("x | y") == SymbolicValue(
        ctor("|", [make_var("x"), make_var("y")])
    )


def test_runtime_bit_or_truthful_and_lying_twins_discriminate() -> None:
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    assert _reduce_sourced("6 | 3") == TermValue(7)
    assert isinstance(_reduce_sourced("(6 | 3) == 7"), TrueBoolLiteralSugar)
    assert isinstance(_reduce_sourced("(6 | 3) == 6"), FalseBoolLiteralSugar)


def test_matrix_multiply_uses_native_operator_coordinate() -> None:
    assert reduce_value(
        "x @ y",
        {"x": SymbolicValue(make_var("x")), "y": SymbolicValue(make_var("y"))},
    ) == SymbolicValue(ctor("@", [make_var("x"), make_var("y")]))


def test_concrete_number_matrix_multiply_is_loud_decidable_type_error() -> None:
    """Concrete scalar ``@`` is decided at lift time, never a RuntimeEffect."""
    from sugar_lift_py_tests.factory.factory_gap import FactoryPanic

    node = ast.parse("2 @ 3", mode="eval").body
    site = SourceFragment.from_node(node, "t.py", source="2 @ 3")
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    with pytest.raises(FactoryPanic, match="genuine runtime-dependent operand"):
        build_node(site, filename="t.py", role=SugarRole.TERM, ctx=ctx).sugar.desugar(
            ctx
        )


def test_production_lift_constructs_matrix_multiply_return_without_factory_panic() -> (
    None
):
    """#4387 wave-5: ObjectValue.__matmul__ dig body + Derived residue pin."""
    from sugar_lift_py_tests.lift_rpc import audit_lift_file

    source = (
        "class Box:\n"
        "    def __matmul__(self, other):\n"
        "        return 6\n"
        "\n"
        "def A():\n"
        "    return Box() @ Box()\n"
        "\n"
        "def test_a():\n"
        "    assert A() == 6\n"
    )

    payload, gaps = audit_lift_file(source, "matrix_multiply_return.py")
    rpc = payload.to_rpc()
    selected = {
        row["selected"]
        for row in [
            *rpc.get("factoryAuditSummary", {}).get("factoryWalk", []),
            *rpc.get("factoryAudits", []),
        ]
        if isinstance(row, dict) and isinstance(row.get("selected"), str)
    }

    assert gaps == []
    assert "MatrixMultiplyOpSugar" in selected
    assert "ConstructorCallSugar" in selected
    assert rpc.get("ir"), "matrix multiply return must emit proof-bearing IR"
    recovered = audit_lift_file(
        source, "matrix_multiply_return.py", recover_panics=True
    )
    assert recovered.panics == []


def test_bit_or_annotation_union_uses_its_annotation_owner() -> None:
    source = "def f(value: int | str):\n    return value\n"
    module = ast.parse(source)
    node = next(node for node in ast.walk(module) if isinstance(node, ast.BinOp))
    site = SourceFragment.from_node(node, "t.py", source=source)

    result = build_node(site, filename="t.py", role=SugarRole.TERM)

    assert result.audit_row.selected == "AnnotationUnionSugar"


def test_matmult_owner_does_not_claim_an_unowned_operator() -> None:
    with pytest.raises(FactoryPanic, match="observed=BinOp requested=term"):
        reduce_value(
            "x | y",
            {"x": SymbolicValue(make_var("x")), "y": SymbolicValue(make_var("y"))},
        )
