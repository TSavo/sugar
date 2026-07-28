"""A slice `lower:upper:step` (as it appears in `xs[1:2]`, `xs[::2]`, ...).

A slice is a value: `slice(lower, upper, step)`. It reduces each present bound
and stands as the `py.slice` coordinate over their terms; an omitted bound is
`None` (its NoneValue term), exactly as Python fills it. The container's
subscript floor consumes this coordinate -- this only constructs it.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class SliceSugar(Sugar):
    lower: object  # sugar or None (omitted bound)
    upper: object
    step: object
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        # A BOUND IS AN ORDINARY OPERAND, and an operand does not answer with
        # exactly one unconditional value. `out.value` asked it to -- it read the
        # `Complete` field off whatever came back -- so a bound that PARTITIONS
        # (`pattern.search(s, pos).span()[0]`, whose method coordinate reduces to
        # an ExitSet) crashed with `'ExitSet' object has no attribute 'value'`,
        # and a bound owing a parameter contract (`xs[p[0]:]` for a formal `p`)
        # had its demand read off and dropped.
        #
        # This is the shape `collection_sugar._reduce_into` already owns and
        # names: reduce operands in source order, factor each so an arm count
        # does not multiply through the fold (#6324), accumulate every pending
        # demand into one set, and re-attach it to what gets built (#6352). A
        # slice is that same fold over its present bounds, so it goes through
        # that door rather than growing a second copy of the law.
        from sugar_lift_py_tests.sugar.collection_sugar import _reduce_into

        present = tuple(
            bound
            for bound in (self.lower, self.upper, self.step)
            if bound is not None
        )
        omitted = tuple(
            bound is None for bound in (self.lower, self.upper, self.step)
        )
        return _reduce_into(present, ctx, _slice_builder(omitted))


def _slice_builder(omitted: tuple):
    """The `build` the fold hands its reduced bound values.

    ``omitted`` is one flag per slice position, in source order. Every position
    is filled: a present bound contributes the next reduced value's term, an
    omitted one contributes Python's own ``None`` -- which is a VALUE Python
    fills in, not a missing operand, and so never reaches the fold. The two
    sequences are consumed in lockstep, and the arity is checked rather than
    assumed: a mismatch would silently shift a bound into a neighbouring
    position and mint a `py.slice` that means something else.
    """

    def slice_value(values: tuple):
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import ctor

        present = sum(1 for flag in omitted if not flag)
        if len(values) != present:
            raise AssertionError(
                "LAW (a slice fills every position it declares): "
                f"{len(values)} reduced bound(s) arrived for {present} present "
                "position(s) of `py.slice`. Consuming them out of lockstep "
                "would move a bound into a neighbouring position and mint a "
                "different slice."
            )
        remaining = list(values)
        terms = [
            NoneValue().to_term(owner="slice")
            if flag
            else remaining.pop(0).to_term(owner="slice")
            for flag in omitted
        ]
        return SymbolicValue(ctor("py.slice", terms))

    return slice_value
