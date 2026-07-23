"""`for x in xs: <asserts>` over a SYMBOLIC iterable -- the degenerate fold.

When xs is a hole (a formal), the loop cannot unroll (unknown length), so its
meaning is the FOL that was always there: a universal. An assert-only body has
no carried accumulator, so the fold collapses to `forall x in xs: P(x)` -- each
body fact P (reduced with the loop target x free, so a symbolic Var) rides under
membership: `forall x. member(x, xs) -> P(x)`. The element sort is unknown, so
it is an uninterpreted sort the compiler declares; membership and P constrain it.

This is the local fact A states -- post over the formal xs, exactly like
`out == z` is post over z. A concrete call fills xs and the dig unrolls the loop
(the AST-local machinery); a symbolic xs leaves the universal, honest FOL. A body
with a carried accumulator (`total = total + x`) is the non-degenerate fold and
is not written here yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class ForUniversalSugar(Sugar):
    target: str
    iterable: Sugar
    body: tuple  # the body statement sugars (assert-only, no carried binding)
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(xs):\n    for x in xs:\n        assert x == x\n    return xs\n\n"
        )
        return _call_pair(
            name="for_universal",
            owner_sugar="ForUniversalSugar",
            truthful=prefix + "def test_a():\n    assert A([1]) == [1]\n",
            lying=prefix + "def test_a():\n    assert A([1]) == [2]\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.floor.inv_value import InvValue
        from sugar_lift_py_tests.ir import (
            PrimitiveSort,
            atomic,
            forall,
            implies,
            make_var,
        )
        from sugar_lift_py_tests.outcome import Incomplete
        from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_statements

        it = self.iterable.desugar(ctx)
        if isinstance(it, Incomplete):
            return it  # the iterable is itself an effect -> the loop is that effect
        xs_term = it.value.to_term(owner=str(self.site))

        entries, _falls, _ft = reduce_statements(self.body)
        x = make_var(self.target)
        member = atomic("py.in", [x, xs_term])
        element_sort = PrimitiveSort("py.element")  # unknown -> uninterpreted sort

        wrapped: list = []
        for entry in entries:
            site = getattr(entry, "site", None) or self.site
            for formula in entry.inv_contribution():
                wrapped.append(
                    InvValue(
                        forall(self.target, element_sort, implies(member, formula)),
                        site,
                    )
                )
        return Complete(BlockValue(tuple(wrapped), can_fall_through=True))
