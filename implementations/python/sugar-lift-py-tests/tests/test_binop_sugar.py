"""BinOpSugar folds a concrete `+`; a symbolic `+` has no sugar yet and must PANIC
(the false-discharge floor), never silently mislift."""
from __future__ import annotations

import pytest
from factory_reduce import fol, reduce_term

from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import make_var, num


def test_add_folds_concrete_literals():
    assert fol(reduce_term("2 + 3")) == fol(num(5))


def test_add_on_symbolic_operand_panics_not_mislifts():
    with pytest.raises((FactoryGap, TypeError)):
        reduce_term("x + 1", {"x": SymbolicValue(make_var("x"))})
