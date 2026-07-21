from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class NameSugar(Sugar):
    """A name is nothing on its own: it asks the temporal context what stands
    at this name, and the binding answers. A concrete binding folds like any
    value; a symbolic binding (a parameter's SymbolicValue) stands as the term
    it projects. An unbound name panics loudly at reduce time -- exactly where
    Python would raise NameError.

    Meaning-only, node-constructed: no owns/new/role. The tree's Name node
    constructs this WITH its identifier; there is nothing to build eagerly (a
    name is a leaf), only to look up when the body reduces.
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
        # Ask the context what stands at this name; the binding answers.
        binding = ctx.temporal.value_for(
            self.name,
            blame=f"{self.site.filename}:{self.site.line}:{self.site.col}",
        )
        return binding.answer(ctx)
