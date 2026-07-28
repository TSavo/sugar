from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class SubscriptSugar(ConstructedTermSugar):
    """`<receiver>[<index>]`. Reduce the receiver and the index, then ask the
    receiver to subscript by the index -- the value owns what indexing means.
    Concrete containers fold (a string indexes to its character); a vendor
    object routes through its ``__getitem__``; decidable out-of-range indexes
    and missing keys stay loud until their exact exceptional exits are built;
    symbolic sides stand as the py.subscript coordinate.

    Meaning-only, node-constructed. Slice indexes are a narrower case (their
    own sugar): a Slice node here reduces to its own gap through the recursion,
    never silently handled by this parent.
    """

    receiver: ConstructedTermSugar
    index: ConstructedTermSugar
    site: object = dataclass_field(compare=False)

    def __post_init__(self) -> None:
        require_constructed_term_sugar(self.receiver, owner="SubscriptSugar.receiver")
        require_constructed_term_sugar(self.index, owner="SubscriptSugar.index")

    @classmethod
    def witnesses(cls):
        # The ground failing bounds check contributes exact exceptional-exit
        # testimony on one path; the continuing path gives the solver a
        # verdict-bearing truthful/lying pair.
        prefix = "def A(z):\n    if z < 0:\n        return [][0]\n    return z\n\n"
        return _call_pair(
            name="subscript_return",
            owner_sugar="SubscriptSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:subscript-construction",
            (
                self.occurrence_term(owner=owner),
                self.receiver.to_term(owner=owner),
                self.index.to_term(owner=owner),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: Any = None) -> Outcome:
        # THE INDEX CAN OWE A CONTRACT, and `and_then` has no arm for a carrier:
        # a carrier wraps a value together with an obligation, which is neither a
        # value nor a partition, so `outcome_to_exitset` panics NAMED on it
        # (#6352). `xs[p[0]:]` and `res.append(s[pos:ps.span()[0]])` both arrive
        # here that way -- the second is the `slice_sugar` family, whose demand
        # now survives its own fold instead of being read off with `.value`.
        #
        # So hoist both operands' obligations, fold the plain values exactly as
        # before, and re-attach the union to the result. `rewrap_pending` is the
        # sole re-attachment door and is itself loud when the joined outcome has
        # nowhere to carry the demand: nothing here drops an obligation quietly.
        #
        # Operand reduction may also publish a dual-edge ExitSet (undecided
        # Compare/BinOp dispatch: Halted raise face + Completed solver face).
        # Sequence those partitions so Halted faces bypass the subscript step;
        # an undecided completed face that cannot honestly subscript contributes
        # no face rather than aborting the partition with SugarNotWritten and
        # erasing the sibling halt.
        from dataclasses import replace

        from sugar_lift_py_tests.caller_parameter_contract import merge_demands
        from sugar_lift_py_tests.floor.single_outcome_law import (
            pending_demand,
            rewrap_pending,
        )
        from sugar_lift_py_tests.outcome import ExitSet, outcome_to_exitset, true_guard
        from sugar_source_tree.panic import SugarNotWritten

        # A subscript expression has no guard of its own, so both obligations
        # hoist unconditionally.
        pending = None
        plain = []
        for operand in (self.receiver, self.index):
            entry, value_outcome = pending_demand(operand.desugar(ctx), true_guard())
            if entry is not None:
                pending = (
                    entry
                    if pending is None
                    else replace(
                        pending,
                        demands=merge_demands(pending.demands, entry.demands),
                    )
                )
            plain.append(value_outcome)
        receiver_outcome, index_outcome = plain

        def _subscript_face(receiver, index):
            try:
                return outcome_to_exitset(self._subscript(receiver, index, ctx))
            except SugarNotWritten:
                # Completion path cannot decide the lookup. Sibling halt faces
                # from the index/receiver partition already survive sequence.
                return ExitSet(())

        from sugar_lift_py_tests.outcome import ExitSet as _ExitSet

        receiver_partitioned = isinstance(receiver_outcome, _ExitSet)
        index_partitioned = isinstance(index_outcome, _ExitSet)
        if receiver_partitioned or index_partitioned:
            subscripted = outcome_to_exitset(receiver_outcome).and_then(
                lambda receiver: outcome_to_exitset(index_outcome).and_then(
                    lambda index: _subscript_face(receiver, index)
                )
            )
            if isinstance(subscripted, _ExitSet) and not subscripted.exits:
                # Every completed face refused and no halt survived: surface the
                # undecided lookup as the named refusal (not an empty partition).
                raise SugarNotWritten(
                    owner="SubscriptSugar",
                    observed=(
                        "undecided subscript after partitioned operand faces "
                        "refused without a surviving halt"
                    ),
                    requested=(
                        "authenticated exceptional exit or named undecided "
                        "refusal at the receiver floor"
                    ),
                    fix=(
                        "preserve a Halted face from the index/receiver "
                        "partition, or name the undecided lookup on the "
                        "receiver floor"
                    ),
                )
        else:
            # Single-outcome path: undecided lookups raise SugarNotWritten
            # from the receiver floor (named refusal), exact exits Complete.
            subscripted = receiver_outcome.and_then(
                lambda receiver: index_outcome.and_then(
                    lambda index: self._subscript(receiver, index, ctx)
                )
            )
        return rewrap_pending(
            pending, subscripted, owner=type(self).__name__, blame=self.site
        )

    def _subscript(self, receiver, index, ctx):
        from sugar_lift_py_tests.floor import CallSiteValue, ObjectValue

        if isinstance(receiver, CallSiteValue):
            projected = receiver._dig_floor_or_none(
                ctx, owner="SubscriptSugar.receiver"
            )
            if projected is not None:
                receiver = projected
        if isinstance(index, CallSiteValue):
            projected = index._dig_floor_or_none(ctx, owner="SubscriptSugar.index")
            if projected is not None:
                index = projected

        if isinstance(receiver, ObjectValue):
            return receiver.call_method_value(
                "__getitem__",
                (index,),
                owner=type(self).__name__,
                blame=self.site,
                ctx=ctx,
            )
        return receiver.subscript(index, self.site)
