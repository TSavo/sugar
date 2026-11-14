from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any

from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1

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
    use_occurrence: SourceFragmentCoordinateV1 | None = dataclass_field(
        default=None, compare=False
    )

    def __post_init__(self) -> None:
        require_constructed_term_sugar(self.receiver, owner="SubscriptSugar.receiver")
        require_constructed_term_sugar(self.index, owner="SubscriptSugar.index")
        if (
            self.use_occurrence is not None
            and type(self.use_occurrence) is not SourceFragmentCoordinateV1
        ):
            raise TypeError(
                "SubscriptSugar.use_occurrence must be SourceFragmentCoordinateV1"
            )

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
        # Operand reduction may publish a dual-edge ExitSet. Sequence its
        # completed faces through the receiver floor; a typed refusal remains a
        # refusal and must never be converted into an empty outcome.
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
        )
        from sugar_lift_py_tests.outcome import outcome_to_exitset

        # The receiver and the index are operands: a walrus in either
        # (``(xs := ys)[0]``, ``xs[(i := 0)]``) binds once, through the one
        # operand door.
        def subscript(receiver, index):
            return consume_operands(
                lambda receiver, index: self._subscript(receiver, index, ctx),
                receiver,
                index,
            )

        receiver_outcome = self.receiver.desugar(ctx)
        index_outcome = self.index.desugar(ctx)

        from sugar_lift_py_tests.outcome import ExitSet as _ExitSet
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            plain_completed_value,
        )

        # One plain completed arm is the single-outcome path: its value is
        # handed straight to the step, as a deferred carrier the step answers.
        receiver_partitioned = (
            isinstance(receiver_outcome, _ExitSet)
            and plain_completed_value(receiver_outcome) is None
        )
        index_partitioned = (
            isinstance(index_outcome, _ExitSet)
            and plain_completed_value(index_outcome) is None
        )
        if receiver_partitioned or index_partitioned:
            subscripted = outcome_to_exitset(receiver_outcome).and_then(
                lambda receiver: outcome_to_exitset(index_outcome).and_then(
                    lambda index: outcome_to_exitset(subscript(receiver, index))
                )
            )
        else:
            # Single-outcome path: undecided lookups raise SugarNotWritten
            # from the receiver floor (named refusal), exact exits complete.
            subscripted = receiver_outcome.and_then(
                lambda receiver: index_outcome.and_then(
                    lambda index: subscript(receiver, index)
                )
            )
        return subscripted

    def _subscript(self, receiver, index, ctx):
        """One door: prefer ``subscript_with`` (operation) over legacy ``subscript``.

        Several floors implement only ``subscript_with`` (DictLiteralValue,
        ArrayLiteral, TupleLiteralValue, ObjectValue, StringValue, …). Routing
        solely through ``subscript`` left those as owner=subscript construction
        panics even though the operation edge was already written. Prefer the
        operation edge when the receiver overrides it; otherwise fall back to
        the legacy ``subscript`` / ``subscript_with_occurrence`` path so
        floors that only implement ``subscript`` keep working.
        """
        from sugar_lift_py_tests.floor.floor_value import FloorValue
        from sugar_lift_py_tests.operations.subscript_operation import (
            SubscriptOperation,
        )

        receiver = receiver.project_operation_receiver(
            ctx, owner="SubscriptSugar receiver"
        )
        index = index.project_operation_receiver(ctx, owner="SubscriptSugar index")

        operation = SubscriptOperation(
            index=index,
            owner=type(self).__name__,
            blame=self.site,
            use_occurrence=self.use_occurrence,
        )
        # Species that overrode subscript_with own the modern edge.
        if (
            isinstance(receiver, FloorValue)
            and type(receiver).subscript_with is not FloorValue.subscript_with
        ):
            return receiver.subscript_with(operation, ctx)
        return receiver.subscript_with_occurrence(index, self.site, self.use_occurrence)
