from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class NameSugar(Sugar):
    """A name that survives to the meaning layer is a free FORMAL.

    substitute runs before sugar (FunctionDef.sugar), so every temporal binding
    -- a local assignment, a conditional phi -- is already rewritten into the
    tree: a bound name has been replaced by its value node and never reaches
    here. The only Name left standing is a function parameter, which is masked
    by substitute and therefore free. So a name IS its symbolic universe
    variable -- the term a parameter projects. There is no context to consult
    (ctx.temporal is gone): the name resolves to its own Var, always.

    Meaning-only, node-constructed: no owns/new/role. A name is a leaf.
    """

    name: str
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        # A parameter flows through its name to the return: the truthful twin
        # rides the identity, the lying twin asserts a different value -- the
        # pair proves the lift discriminates on what the name is bound to.
        prefix = "def A(z):\n    return z\n\n"
        return _call_pair(
            name="name_return",
            owner_sugar="NameSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # A surviving name is a free formal: it IS its symbolic universe variable.
        from sugar_lift_py_tests.floor import SymbolicValue
        from sugar_lift_py_tests.ir import make_var
        from sugar_lift_py_tests.outcome import Complete

        return Complete(SymbolicValue(make_var(self.name)))
