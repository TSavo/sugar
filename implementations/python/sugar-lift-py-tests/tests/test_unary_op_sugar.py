"""UnaryOpSugar: fold ground -/+/not/~, emit the coordinate when symbolic."""

from __future__ import annotations

import ast

import pytest

from factory_reduce import fol, reduce_term, reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import SymbolicValue, TermValue
from sugar_lift_py_tests.ir import ctor, make_var, num
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.sugar.unary_op_sugar import UnaryOpSugar


def _site(expr: str):
    return SourceFragment.from_node(ast.parse(expr, mode="eval").body, "t.py")


def test_not_true_folds_false() -> None:
    assert isinstance(reduce_value("not True"), FalseBoolLiteralSugar)


def test_not_false_folds_true() -> None:
    assert isinstance(reduce_value("not False"), TrueBoolLiteralSugar)


def test_not_nonzero_folds_false_via_truth_floor() -> None:
    # Python `not 5` is False -- truth floor then negate.
    assert isinstance(reduce_value("not 5"), FalseBoolLiteralSugar)


def test_unary_minus_folds_concrete() -> None:
    assert reduce_value("-5") == TermValue(-5)


def test_unary_plus_folds_concrete() -> None:
    assert reduce_value("+3") == TermValue(3)


def test_bitwise_invert_folds_concrete() -> None:
    assert reduce_value("~0") == TermValue(-1)
    assert reduce_value("~5") == TermValue(~5)


def test_symbolic_minus_emits_py_neg() -> None:
    result = reduce_term("-x", {"x": SymbolicValue(make_var("x"))})
    assert fol(result) == fol(ctor("py.neg", [make_var("x")]))


def test_symbolic_invert_emits_py_invert() -> None:
    result = reduce_term("~x", {"x": SymbolicValue(make_var("x"))})
    assert fol(result) == fol(ctor("py.invert", [make_var("x")]))


def test_symbolic_plus_is_identity() -> None:
    # LAW (symbolic_term UAdd): unary plus returns the operand term.
    result = reduce_term("+x", {"x": SymbolicValue(make_var("x"))})
    assert fol(result) == fol(make_var("x"))


def test_symbolic_ops_discriminate() -> None:
    """(2) Different ops produce different terms for the same symbolic x."""
    neg = reduce_term("-x", {"x": SymbolicValue(make_var("x"))})
    inv = reduce_term("~x", {"x": SymbolicValue(make_var("x"))})
    assert fol(neg) == fol(ctor("py.neg", [make_var("x")]))
    assert fol(inv) == fol(ctor("py.invert", [make_var("x")]))
    assert fol(neg) != fol(inv)
    # Not a constant: the free var rides inside.
    assert fol(neg) != fol(num(0))


def test_owns_unary_not_binop_or_boolop() -> None:
    """(3) owns fires on UnaryOp, not on BinOp/BoolOp."""
    assert UnaryOpSugar.owns(_site("-x")) is True
    assert UnaryOpSugar.owns(_site("+x")) is True
    assert UnaryOpSugar.owns(_site("not x")) is True
    assert UnaryOpSugar.owns(_site("~x")) is True
    assert UnaryOpSugar.owns(_site("x + 1")) is False
    assert UnaryOpSugar.owns(_site("x and y")) is False

    catalog = default_catalog()
    cands = [c.name for c in catalog.candidates_for(SugarRole.TERM, _site("-1"))]
    assert "UnaryOpSugar" in cands
    assert "NotOpSugar" not in cands


def test_minus_one_term_is_negative_num() -> None:
    assert fol(reduce_term("-3")) == fol(num(-3))
