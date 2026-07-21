from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.floor import BoundVar, ModuleBoundVar
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class AssignSugar(Sugar):
    """A `name = <rhs>` statement. The rhs is held as SUGAR (the SOURCE), never
    reduced here -- desugar yields a BoundVar aliasing the name to that source
    under the DEFINITION scope. The block threads the BoundVar as a let (a scope
    effect that contributes nothing to the record); a later reference to the
    name recomposes the source against the captured scope.

    Meaning-only, node-constructed: no owns/new/role, no SugarBody wrapper --
    the rhs is a tree sugar and the BoundVar reduces it through the Sugar.reduce
    alias. Single Name target only; the tree node keeps other target shapes as
    gaps.
    """

    name: str
    value: object  # the rhs sugar (the source), reduced only on reference
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        # `x = z; return x` aliases through the source: the truthful twin rides
        # the identity, the lying twin asserts another -- the pair discriminates.
        prefix = "def A(z):\n    x = z\n    return x\n\n"
        return _call_pair(
            name="assign_return",
            owner_sugar="AssignSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Capture the DEFINITION scope: ctx still holds the OLD binding for the
        # name (the block threads the new one AFTER this), so a self-referential
        # rebind (`x = x + 1`) reads the old value and terminates. The rhs stays
        # as source -- not reduced here.
        binding = ModuleBoundVar if self.name in ctx.global_names else BoundVar
        return Complete(binding(self.name, self.value, scope=ctx))
