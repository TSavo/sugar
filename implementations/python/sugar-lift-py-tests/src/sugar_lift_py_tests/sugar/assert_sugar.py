from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class AssertSugar(Sugar):
    """`assert <test>[, <message>]`. It desugars the test, and the
    result states itself: a symbolic predicate states an inv (the fact the
    record emits -- first encounter a fact to discharge, a later consumer
    meets it as a warrant, a constraint; that duality is protocol position,
    never this sugar's), ground True states nothing, ground False is the
    named halt. The sugar owns no distinction; the value answers.

    Message disposition (#4593 / #4594): the optional second operand is
    diagnostic packaging for AssertionError, not part of the proposition.
    CPython evaluates it only on the failing path. Even when the message is
    a runtime expression (`assert x, f(y)`), any effects of that evaluation
    are unobserved by the claim membrane (paper 26: unsworn effects are
    silence). The lift MUST NOT invent a conditional py.* effect gated on
    ¬test. Spelling rides `assertMessage` provenance on the source
    memento; AssertSugar never builds or reduces the message operand.
    """

    test: Sugar
    site: object = dataclass_field(compare=False)
    message: object | None = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        # The stated inv IS the discriminator: the truthful twin's assert holds
        # in the body's universe, the lying twin's contradicts it.
        return _call_pair(
            name="assert_return",
            owner_sugar="AssertSugar",
            truthful=(
                "def A(z):\n    return z\n\n" "def test_a():\n    assert A(5) == 5\n"
            ),
            lying=(
                "def A(z):\n    return z\n\n" "def test_a():\n    assert A(5) == 6\n"
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Desugar the test, and the result states itself.
        return self.test.desugar(ctx).and_then(lambda value: value.stated(self.site))
