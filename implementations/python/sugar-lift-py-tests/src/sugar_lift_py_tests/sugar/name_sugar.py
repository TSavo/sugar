from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class NameSugar(Sugar):
    """A name that survives to the meaning layer is a free formal or builtin.

    substitute runs before sugar (FunctionDef.sugar), so every temporal binding
    -- a local assignment, a conditional phi -- is already rewritten into the
    tree: a bound name has been replaced by its value node and never reaches
    here. Parameters are masked by substitute and stay free formals. Builtin
    type and callable names (``tuple``, ``isinstance``, …) also survive as
    Name nodes: they were never local bindings. When a reduction context
    carries the builtin temporal floor, those names resolve to their
    authenticated floor values; otherwise a free name is its symbolic Var.

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
        from sugar_lift_py_tests.floor import SymbolicValue
        from sugar_lift_py_tests.ir import make_var
        from sugar_lift_py_tests.outcome import Complete

        # Authenticated temporal bindings (builtins, formals already installed
        # into the reduction floor) are source-visible testimony, not free
        # formals. Following them is alias → defining source; minting a Var
        # that erases an existing binding is fabricated free-name testimony.
        temporal = getattr(ctx, "temporal", None) if ctx is not None else None
        if temporal is not None:
            bound = temporal.value_if_bound(self.name)
            if bound is not None:
                return Complete(bound)
        return Complete(SymbolicValue(make_var(self.name)))
