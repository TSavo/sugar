"""BinOpSugar folds a concrete `+` (via Python, the reference); a SYMBOLIC `+` EMITS the
operation as a sort-silent structural term `+(x, 1)` -- the universe warrant. We emit the
SHAPE, not a value; the SMT compiler derives x's carrier from the `+` it appears in. Never a
mislift, never folding what cannot be folded."""
from __future__ import annotations

from factory_reduce import fol, reduce_term

from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var, num


def test_add_folds_concrete_literals():
    assert fol(reduce_term("2 + 3")) == fol(num(5))


def test_add_on_symbolic_operand_emits_the_operation_sort_silent():
    # A free var is irreducible, so the `+` cannot fold to a value -- but it is not a panic.
    # BinOpSugar emits the operation `+(x, 1)` (the structural term the universe walk warrants).
    result = reduce_term("x + 1", {"x": SymbolicValue(make_var("x"))})
    assert fol(result) == fol(ctor("+", [make_var("x"), num(1)]))
