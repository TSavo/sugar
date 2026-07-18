"""NodeKind / OperatorKind: the typed observation vocabulary (Phase 1)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.block import Block
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.node_kind import NodeKind, OperatorKind
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.idd.sugar_witness_instruments import evaluate_seed_witnesses
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.float_literal_sugar import FloatLiteralSugar
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.none_literal_sugar import NoneLiteralSugar
from sugar_lift_py_tests.sugar.string_literal_sugar import StringLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


def _fragment(source: str) -> SourceFragment:
    node = ast.parse(source).body[0]
    if isinstance(node, ast.Expr):
        node = node.value
    return SourceFragment.from_node(node, "node_kind_test.py", source=source)


def test_observed_returns_nodekind_and_string_comparisons_still_work() -> None:
    site = _fragment("x + 1")
    assert isinstance(site.observed, NodeKind)
    assert site.observed is NodeKind.BIN_OP
    assert site.observed == "BinOp"
    assert "BinOp" == site.observed
    assert site.observed in {"BinOp", "Name"}
    assert site.observed != "Call"


@pytest.mark.parametrize(
    ("source", "selected"),
    (
        ("1", "IntLiteralSugar"),
        ("1.5", "FloatLiteralSugar"),
        ('"s"', "StringLiteralSugar"),
        ("True", "TrueBoolLiteralSugar"),
        ("False", "FalseBoolLiteralSugar"),
        ("None", "NoneLiteralSugar"),
    ),
)
def test_constant_observation_is_structural_and_literal_sugar_owns_semantics(
    source: str, selected: str
) -> None:
    site = _fragment(source)
    assert site.observed is NodeKind.CONSTANT

    result = build_node(
        site,
        filename="node_kind_test.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(
            filename="node_kind_test.py",
            catalog=default_catalog(),
        ),
    )

    assert result.audit_row.selected == selected


def test_literal_sugar_construction_witnesses_refute_wrong_twins(
    tmp_path: Path,
) -> None:
    sugars = (
        IntLiteralSugar,
        FloatLiteralSugar,
        StringLiteralSugar,
        TrueBoolLiteralSugar,
        FalseBoolLiteralSugar,
        NoneLiteralSugar,
    )
    witnesses = tuple(sugar.witnesses() for sugar in sugars)

    assert evaluate_seed_witnesses(witnesses, tmp_path).is_zero


def test_block_is_an_explicit_member() -> None:
    assert NodeKind.of(Block([], 1, 0)) is NodeKind.BLOCK
    assert NodeKind.BLOCK == "Block"


def test_operator_kind_returns_operatorkind() -> None:
    binop = _fragment("a % b")
    assert binop.operator_kind() is OperatorKind.MOD
    assert binop.operator_kind() == "Mod"
    unary = _fragment("not a")
    assert unary.operator_kind() is OperatorKind.NOT
    assert unary.operator_kind() in {"Not", "USub"}


def test_nodekind_of_panics_on_unknown_node() -> None:
    class NotVocabulary(ast.AST):
        pass

    with pytest.raises(FactoryPanic) as caught:
        NodeKind.of(NotVocabulary())
    assert "NotVocabulary" in str(caught.value)
    assert "NodeKind" in str(caught.value)


def test_suggested_sugar_module_snake_case_projection_unchanged() -> None:
    assert (
        _fragment("1").suggested_sugar_module
        == "sugar_lift_py_tests.sugar.constant.constant_sugar"
    )
    assert (
        _fragment("x + 1").suggested_sugar_module
        == "sugar_lift_py_tests.sugar.bin_op.bin_op_sugar"
    )


def test_every_concrete_ast_leaf_is_a_member() -> None:
    concrete = {
        value
        for name, value in vars(ast).items()
        if not name.startswith("_")
        and isinstance(value, type)
        and issubclass(value, ast.AST)
        and value is not ast.AST
    }
    leaves = {
        cls
        for cls in concrete
        if not any(other is not cls and issubclass(other, cls) for other in concrete)
    }
    values = {member.value for member in NodeKind}
    missing = sorted(cls.__name__ for cls in leaves if cls.__name__ not in values)
    assert not missing, missing
