"""NameSugar reduces a bound name to its carrier's ProofIR term (a free var)."""

from __future__ import annotations

from factory_reduce import fol, reduce_term

from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import make_var


def test_name_reduces_to_its_bound_variable():
    got = reduce_term("x", {"x": SymbolicValue(make_var("x"))})
    assert fol(got) == fol(make_var("x"))
