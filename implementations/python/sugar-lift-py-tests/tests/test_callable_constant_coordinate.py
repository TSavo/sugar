from __future__ import annotations

import pytest

from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import eq, make_var, num
from sugar_lift_py_tests.proofir.formulas import formula_from_ir
from sugar_lift_py_tests.proofir.scope import ScopedFormula
from sugar_lift_py_tests.proofir.sorts import IntSort


def test_actually_undeclared_variable_still_refuses_scope() -> None:
    formula = formula_from_ir(
        eq(make_var("ghost"), num(1)), var_sorts={"ghost": IntSort()}
    )
    with pytest.raises(ConstructionPanic, match="illegal free var.*ghost"):
        ScopedFormula(formula, allowed_vars={})
