"""NodeKind / OperatorKind: the typed observation vocabulary (Phase 1)."""

from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.factory.block import Block
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.node_kind import NodeKind, OperatorKind
from sugar_lift_py_tests.factory.source_fragment import SourceFragment


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


def test_primitive_literal_collapse_is_preserved() -> None:
    for source in ("1", "1.5", '"s"', "True", "None"):
        assert _fragment(source).observed is NodeKind.PRIMITIVE_LITERAL
        assert _fragment(source).observed == "PrimitiveLiteral"
    # Non-primitive constants stay CONSTANT, not PrimitiveLiteral.
    assert _fragment("b'raw'").observed is NodeKind.CONSTANT
    assert _fragment("...").observed is NodeKind.CONSTANT


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
        == "sugar_lift_py_tests.sugar.primitive_literal_sugar"
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
