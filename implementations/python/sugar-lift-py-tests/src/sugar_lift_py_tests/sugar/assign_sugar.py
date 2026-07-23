from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing, _call_pair


@dataclass(frozen=True)
class AssignSugar(Sugar):
    """A `name = <rhs>` statement -- SPENT by the time it reaches the meaning layer.

    substitute runs before sugar (FunctionDef.sugar), and an assignment IS a
    temporal binding: substitute threads it, inlining the rhs into every later
    reference of the name. So by the time this sugar reduces, the binding has
    already done its work in the tree -- there is nothing left to state. An
    assignment contributes no fact, no post, no effect; it is inert meaning.

    (The rhs is not re-stated either: wherever the name was used, the rhs node
    was substituted in and sugared THERE, in the position that consumes it.)

    Meaning-only, node-constructed: no owns/new/role. Single Name target only;
    other target shapes stay gaps on the tree node.
    """

    name: str
    value: object  # the rhs sugar -- provenance only; substitute already inlined it
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        # `x = z; return x` inlines to `return z` via substitute: the truthful
        # twin rides the identity, the lying twin asserts another.
        prefix = "def A(z):\n    x = z\n    return x\n\n"
        return _call_pair(
            name="assign_return",
            owner_sugar="AssignSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Inert: the binding was consumed by substitute. Contribute nothing.
        from sugar_lift_py_tests.floor.block_value import BlockValue

        return Complete(BlockValue((), can_fall_through=True))


@dataclass(frozen=True)
class MultiAssignSugar(Sugar):
    """More than one name bound by a single Assign statement -- either a
    destructured display (`a, b = <tuple/list display>`) or a chained
    assignment (`x = y = e`). Just like AssignSugar, substitute has already
    threaded every binding into the rest of the block by the time this sugar
    reduces: an assignment states no fact of its own, so this too is inert
    meaning. `bindings` holds each bound name with its own rhs sugar --
    provenance only, never re-stated.

    Meaning-only, node-constructed: no owns/new/role. Only shapes the tree
    node has already proven destructure (or chain) reach here; anything else
    stays a loud gap on the node.
    """

    bindings: tuple  # tuple of (name, value_sugar) pairs, in target order
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        # A destructuring bind that discriminates ON THE PAIRING: swap the
        # two names' rhs and the sum through both flips.
        prefix = "def A(p, q):\n    a, b = p, q\n    return a + b\n\n"
        return _call_pair(
            name="multi_assign_destructure",
            owner_sugar="MultiAssignSugar",
            truthful=prefix + "def test_a():\n    assert A(2, 3) == 5\n",
            lying=prefix + "def test_a():\n    assert A(2, 3) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Inert: every binding was consumed by substitute. Contribute nothing.
        from sugar_lift_py_tests.floor.block_value import BlockValue

        return Complete(BlockValue((), can_fall_through=True))


@dataclass(frozen=True)
class ChainedAssignSugar(Sugar):
    """One evaluated RHS distributed left-to-right across names and stores."""

    bindings: tuple
    stores: tuple
    value: object
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="typed store effect",
            reason="mixed chained stores stay red while lexical bindings continue",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_body
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.outcome import Complete

        return self.value.desugar(ctx).and_then(
            lambda _value: (
                reduce_body(self.stores, ctx)
                if self.stores
                else Complete(BlockValue((), can_fall_through=True))
            )
        )
