from __future__ import annotations

from factory_reduce import fol, reduce_term

from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var, str_const


def test_str_builtin_folds_concrete_number() -> None:
    assert fol(reduce_term("str(12)")) == fol(str_const("12"))


def test_str_builtin_symbolic_argument_emits_structural_term() -> None:
    result = reduce_term("str(x)", {"x": SymbolicValue(make_var("x"))})

    assert fol(result) == fol(ctor("py.str", [make_var("x")]))
