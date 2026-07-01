from __future__ import annotations

from factory_reduce import fol, reduce_term

from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var, num


def test_unary_minus_folds_concrete_number() -> None:
    assert fol(reduce_term("-3")) == fol(num(-3))


def test_unary_minus_symbolic_operand_emits_structural_term() -> None:
    result = reduce_term("-x", {"x": SymbolicValue(make_var("x"))})

    assert fol(result) == fol(ctor("py.neg", [make_var("x")]))
