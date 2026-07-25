"""BoolOpSugar ground operands fold via the shared predicate_formula path.

Permanent floor: a ground boolean (None → False, True, False) must not raise a
bare NotImplementedError — that was R_bare_exceptions=1 on import_binding.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor.predicate_value import PredicateValue
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.bool_op_sugar import BoolOpSugar
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.none_literal_sugar import NoneLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


@dataclass(frozen=True)
class _Site:
    filename: str = "test_bool_op_ground_operand.py"
    line: int = 1
    col: int = 0
    source: str = "None and True"


def test_none_and_true_folds_to_predicate() -> None:
    site = _Site()
    sugar = BoolOpSugar(
        op_kind="And",
        values=(NoneLiteralSugar(site=site), TrueBoolLiteralSugar(site=site)),
        site=site,
    )
    out = sugar.desugar(None)
    assert isinstance(out, Complete)
    assert isinstance(out.value, PredicateValue)


def test_true_and_false_folds_to_predicate() -> None:
    site = _Site()
    sugar = BoolOpSugar(
        op_kind="And",
        values=(TrueBoolLiteralSugar(site=site), FalseBoolLiteralSugar(site=site)),
        site=site,
    )
    out = sugar.desugar(None)
    assert isinstance(out, Complete)
    assert isinstance(out.value, PredicateValue)


def test_none_or_true_folds_to_predicate() -> None:
    site = _Site()
    sugar = BoolOpSugar(
        op_kind="Or",
        values=(NoneLiteralSugar(site=site), TrueBoolLiteralSugar(site=site)),
        site=site,
    )
    out = sugar.desugar(None)
    assert isinstance(out, Complete)
    assert isinstance(out.value, PredicateValue)
