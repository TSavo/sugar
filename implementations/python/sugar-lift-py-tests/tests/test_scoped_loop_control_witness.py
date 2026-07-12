from __future__ import annotations

import pytest

from sugar_lift_py_tests.ir import PrimitiveSort, eq, exists, make_var, str_const
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.proofir.formulas import formula_from_ir
from sugar_lift_py_tests.proofir.scope import ScopedFormula, ScopedLoopControlWitness


def test_loop_control_witness_existentially_closes_private_coordinate() -> None:
    witness = ScopedLoopControlWitness("break", "vendor.py:9:8")
    raw = eq(make_var(witness.variable), str_const("cited-loop-exit"))
    closed = witness.close(raw)
    formula = formula_from_ir(closed, var_sorts={})

    assert formula.free_vars == frozenset()
    assert ScopedFormula(formula, allowed_vars={}).ir_formula == closed


def test_loop_control_coordinate_cannot_use_a_wrong_sort_side_door() -> None:
    name = "loop-control:vendor.py:9:8"
    malformed = exists(name, PrimitiveSort("String"), eq(make_var(name), str_const("x")))
    formula = formula_from_ir(malformed, var_sorts={})

    with pytest.raises(FactoryPanic, match="ScopedLoopControlWitness"):
        ScopedFormula(formula, allowed_vars={})
