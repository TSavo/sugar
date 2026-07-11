from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class InOpSugar(Sugar, role=SugarRole.TERM):
    """The ``in`` operator: ``needle in haystack``.

    Deeper floors for raises message checks:
    ``assert \"missing\" in str(exc_info.value)``.

    Emits ``py.in(needle, haystack)`` as a PredicateValue (coordinate), same
    emit-not-fold posture as EqualityOpSugar. NotIn stays a separate sugar.
    """

    left: SugarBody  # needle
    right: SugarBody  # haystack
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Compare"
            and site.compare_ops() == ["In"]
            and len(site.compare_comparators()) == 1
        )

    @classmethod
    def new(cls, site, ctx) -> "InOpSugar":
        return cls(
            left=ctx.build_body(site.compare_left(), SugarRole.TERM),
            right=ctx.build_body(site.compare_comparators()[0], SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n"
            "    if z in (1, 2, 3):\n"
            "        return 1\n"
            "    return 0\n"
            "\n"
        )
        return _call_pair(
            name="in_return",
            owner_sugar="InOpSugar",
            truthful=prefix + "def test_a():\n    assert A(2) == 1\n",
            lying=prefix + "def test_a():\n    assert A(2) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import atomic
        from sugar_lift_py_tests.outcome import Complete

        return self.left.reduce(ctx).and_then(
            lambda left: self.right.reduce(ctx).and_then(
                lambda right: Complete(
                    PredicateValue(
                        atomic(
                            "py.in",
                            [
                                left.to_term(owner=str(self.site)),
                                right.to_term(owner=str(self.site)),
                            ],
                        ),
                        self.site,
                        operand_callsites=(
                            *left.callsites(),
                            *right.callsites(),
                        ),
                    )
                )
            )
        )

    def walk_children(self):
        return (self.left, self.right)
