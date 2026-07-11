from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class NameSugar(Sugar, role=SugarRole.TERM):
    """A name is nothing: it asks the temporal context what stands there, and
    the binding answers. A concrete binding folds like any value; a symbolic
    binding (a parameter's SymbolicValue) carries its provenance as the term it
    projects. An unbound name panics -- the same way it would for Python."""

    name: str
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Name"

    @classmethod
    def new(cls, site, ctx) -> "NameSugar":
        del ctx  # a name is a leaf: nothing to build, only to look up at reduce time
        return cls(name=site.name_id(), site=site)

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
        # Ask the context what stands at this name; the binding answers.
        # A BoundVar recomposes its source against its definition scope; a
        # concrete or symbolic binding stands as itself.
        return ctx.temporal.value_for(self.name).answer(ctx)
