"""``typing.cast(typ, val)``: both operands evaluated, the value is ``val``.

``typing.cast`` returns its second argument unchanged
(https://docs.python.org/3/library/typing.html#typing.cast), but it is an
ordinary call: Python evaluates ``typ`` and then ``val`` where the call runs,
so ``cast(Missing, v)`` raises ``NameError`` there.  The call constructs as
this sugar (``Call._construct_sugar``, the callee read from its binding,
never its spelling): ``typ`` is evaluated first, every face of it the call's,
its value discarded; ``val`` is evaluated after it, with its writes applied
(the one operand door, ``evaluated_after``), and the call completes with
``val``'s value.  No call-site value ever carries a cast for a later reader to
recognise by name.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class TypingCastSugar(ConstructedTermSugar):
    """``typing.cast(typ, val)``: ``typ`` evaluated and discarded, then
    ``val``, whose value the call completes with."""

    typ: object
    value: object
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        prefix = "from typing import cast\n\n\ndef A(z):\n    return cast(int, z)\n\n"
        return _call_pair(
            name="typing_cast_return",
            owner_sugar="TypingCastSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def to_term(self, *, owner: str):
        # The call's value is ``val`` unchanged: its term is ``val``'s.
        require_constructed_term_sugar(self.value, owner=f"{owner}.value")
        return self.value.to_term(owner=owner)

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            evaluated_after,
            written_by,
        )

        return self.typ.desugar(ctx).and_then(
            lambda typ: evaluated_after((typ,), self.value, written_by(typ, ctx)).and_then(
                lambda value: consume_operands(
                    lambda _typ, value: ExitSet.completed(value), typ, value
                )
            )
        )
