"""Collection displays: `[..]` list, `(..)` tuple, `{..}` set, `{k: v}` dict.

Each reduces its element sugars in source order and holds the reduced floor
values -- ListValue / TupleValue / SetValue / DictValue. The floor owns what the
collection then DOES (len, subscript, membership); this only constructs it. An
element that is itself an effect propagates -- a collection with an unresolvable
element is not a value. Star/double-star spreads (`*xs`, `**d`) stay loud until
their own sugar lands: a spread is not one element, and guessing would invent
membership the source never stated.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


def _reduce_into(element_sugars, ctx, build):
    """Reduce elements in source order, then hand the tuple of values to ``build``.

    LAW: an element's outcome is not one unconditional value. ``and_then`` is the
    one door every ``Outcome`` variant implements, and each variant states its own
    law through it -- ``Complete`` continues (a constructed raise keeps the
    control-flow value and evaluates no enclosing step), ``Incomplete`` propagates
    the effect and never runs the tail, ``ExitSet`` threads every completed arm
    while halted arms bypass, and a pending parameter-contract candidate keeps its
    demand attached while its carried value continues.

    Reading ``.value`` off the outcome instead assumed exactly one arm, which is
    false the moment an element can halt: `[a, d[k] := f()]`, an element whose
    store partitions, a comparison chain that raises on one face. That assumption
    was the `'ExitSet' object has no attribute 'value'` defect, and it also
    dropped a pending contract demand on the floor.
    """
    from sugar_lift_py_tests.floor.single_outcome_law import (
        pending_demand,
        rewrap_pending,
    )
    from sugar_lift_py_tests.outcome import true_guard
    from sugar_lift_py_tests.outcome.exit_set import factored_operand

    owner = f"collection {build.__name__}"
    reduced = tuple(element.desugar(ctx) for element in element_sugars)

    # An element that owes a parameter contract (`[p[0], 1]` for a formal `p`)
    # wraps its value rather than being one; the exit algebra has no arm for it,
    # so hoist the demand out of the fold and re-attach it to the built
    # collection. The element's demand is unconditional here -- a collection
    # display has no guard of its own -- so it hoists at `true_guard`.
    pending = None
    stripped = []
    for outcome in reduced:
        entry, plain = pending_demand(outcome, true_guard())
        if entry is not None and pending is not None:
            from sugar_lift_py_tests.gap.info import GapKind
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner=owner,
                blame=str(entry.source_node),
                observed="two collection elements enrolled a contract demand",
                requested="one pending demand per constructed value",
                fix=(
                    "widen ContractConditionalConstructionV1 to carry a demand SET "
                    "before building a collection from two pending elements"
                ),
                gap_kind=GapKind.FLOOR,
            )
        pending = entry if entry is not None else pending
        stripped.append(plain)

    # An element that PARTITIONS enters the fold with at most one completed arm
    # (#6324). `and_then` is `ExitSet.sequence`, which distributes the tail
    # under every completed arm of the prefix, so an unfactored element makes
    # the accumulator grow multiplicatively: `test_arrow.py` measured 133,104
    # arms arriving at one `normalize` call through this loop. Factoring moves
    # the element's partition onto its VALUE (a `GuardedValue`, which a list
    # holds like any other floor value) and leaves its halted arms at the exit
    # level. The accumulator itself cannot be factored -- its completed value is
    # the growing tuple this fold is building.
    outcome = Complete(())
    for element_outcome in stripped:
        outcome = outcome.and_then(
            lambda collected, got=factored_operand(element_outcome): got.and_then(
                lambda value: Complete((*collected, value))
            )
        )
    built = outcome.and_then(lambda values: Complete(build(values)))
    return rewrap_pending(pending, built, owner=owner, blame=owner)


@dataclass(frozen=True)
class ListSugar(Sugar):
    elements: tuple
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="list_len",
            owner_sugar="ListSugar",
            body="len([z, z, z])",
            truthful="3",
            lying="2",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.list_value import ListValue

        return _reduce_into(self.elements, ctx, ListValue)


@dataclass(frozen=True)
class TupleSugar(Sugar):
    elements: tuple
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="tuple_len",
            owner_sugar="TupleSugar",
            body="len((z, z))",
            truthful="2",
            lying="3",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.tuple_value import TupleValue

        return _reduce_into(self.elements, ctx, TupleValue)


@dataclass(frozen=True)
class SetSugar(Sugar):
    elements: tuple
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="set_len",
            owner_sugar="SetSugar",
            body="len({1, 2, 3})",
            truthful="3",
            lying="2",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.set_value import SetValue

        return _reduce_into(self.elements, ctx, SetValue)


@dataclass(frozen=True)
class DictSugar(Sugar):
    keys: tuple  # key sugars, in source order
    values: tuple  # value sugars, in source order
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="dict_len",
            owner_sugar="DictSugar",
            body="len({1: z, 2: z})",
            truthful="2",
            lying="3",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.dict_value import DictValue

        # Keys and values interleave in source order (`{k1: v1, k2: v2}`), so
        # they reduce as ONE element sequence and are re-paired afterwards. A
        # halt in `v1` must not be reported after `k2` was evaluated.
        interleaved = tuple(
            sugar for pair in zip(self.keys, self.values) for sugar in pair
        )

        def build(flat):
            return DictValue(tuple(zip(flat[0::2], flat[1::2])))

        return _reduce_into(interleaved, ctx, build)
