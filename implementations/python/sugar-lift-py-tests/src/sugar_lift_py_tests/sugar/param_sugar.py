from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Optional

from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class ParamSugar(Sugar):
    """One formal parameter. Reduced, a parameter stands as its universe
    variable: a SymbolicValue over `make_var(name)` -- the same binding a
    function body's formals receive. A leaf: no child sugars.

    Meaning-only, node-constructed. (The body binds formals by name inside
    FunctionUniverseSugar; this sugar is what the parameter node itself answers,
    so a parameter is never an unwritten gap.)
    """

    name: str
    site: object = dataclass_field(compare=False)
    # The default expression's sugar, constructed through the same door the
    # source-visible call frame uses (``param.default.sugar()``). None for a
    # formal without a default. Carried, not reduced here: the formal still
    # stands as its universe variable; the caller-side frame applies defaults.
    default: Optional[Sugar] = None

    @classmethod
    def witnesses(cls):
        prefix = "def A(z):\n    return z\n\n"
        return _call_pair(
            name="param_return",
            owner_sugar="ParamSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx  # a formal stands as its symbolic universe variable
        return Complete(SymbolicValue(make_var(self.name)))
