from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any

from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1

from sugar_lift_py_tests.outcome import ExitSet
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

    def desugar(self, ctx: Any = None) -> ExitSet:
        # Operand reduction may publish a dual-edge ExitSet. Sequence its
        # completed faces through the receiver floor; a typed refusal remains a
        # refusal and must never be converted into an empty outcome. One plain
        # completed arm hands its value straight to the step (``and_then``),
        # as a deferred carrier the step answers; over any other shape a
        # carrier is refused by ``ExitSet.and_then``. An undecided lookup is the
        # receiver floor's two-faced unanswered read (``undecided_subscript``);
        # exact exits complete.
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            written_by,
        )

        # The receiver and the index are operands: a walrus in either
        # (``(xs := ys)[0]``, ``xs[(i := 0)]``) binds once, through the one
        # operand door.  The index is evaluated after the receiver, with its
        # writes applied (``written_by``: ``(y := g())[h(y)]``).
        def subscript(receiver, index):
            return consume_operands(
                lambda receiver, index: self._subscript(receiver, index, ctx),
                receiver,
                index,
            )

        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.index.desugar(
                written_by(receiver, ctx)
            ).and_then(lambda index: subscript(receiver, index))
        )

    def _subscript(self, receiver, index, ctx):
        """The one subscript door (``discharge_subscript``): prefer
        ``subscript_with`` (operation) over legacy ``subscript``.

        Several floors implement only ``subscript_with`` (DictLiteralValue,
        TupleLiteralValue, ObjectValue, StringValue, …); floors that only
        implement ``subscript`` answer through ``subscript_with_occurrence``.
        A formal's ``subscript`` carrier discharges through the same door.
        """
        from sugar_lift_py_tests.operations.subscript_operation import (
            discharge_subscript,
        )

        return discharge_subscript(
            receiver,
            index,
            self.site,
            ctx,
            owner=type(self).__name__,
            use_occurrence=self.use_occurrence,
        )
