from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class NotInOpSugar(Sugar, role=SugarRole.TERM):
    """The ``not in`` operator: ``needle not in haystack``.

    Emits ``not(py.in(needle, haystack))`` as a PredicateValue. Companion to
    InOpSugar for message / membership checks.
    """

    left: SugarBody
    right: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Compare"
            and site.compare_ops() == ["NotIn"]
            and len(site.compare_comparators()) == 1
        )

    @classmethod
    def new(cls, site, ctx) -> "NotInOpSugar":
        return cls(
            left=ctx.build_body(site.compare_left(), SugarRole.TERM),
            right=ctx.build_body(site.compare_comparators()[0], SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n"
            "    if z not in (1, 2, 3):\n"
            "        return 0\n"
            "    return 1\n"
            "\n"
        )
        return _call_pair(
            name="not_in_return",
            owner_sugar="NotInOpSugar",
            truthful=prefix + "def test_a():\n    assert A(9) == 0\n",
            lying=prefix + "def test_a():\n    assert A(9) == 1\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import atomic, not_

        return self.left.reduce(ctx).and_then(
            lambda left: self.right.reduce(ctx).and_then(
                lambda right: Complete(
                    PredicateValue(
                        not_(
                            atomic(
                                "py.in",
                                [
                                    left.to_term(owner=str(self.site)),
                                    right.to_term(owner=str(self.site)),
                                ],
                            )
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
