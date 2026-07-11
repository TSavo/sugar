from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class WhileSugar(Sugar, role=SugarRole.STATEMENT):
    """`while <test>: <body>` -- thread the body, carry the test coordinate.

    Recognition + scope threading, not loop unrolling: reduce the test to its
    coordinate (predicate/value via the usual truth/comparison floors), then
    reduce the body under the current scope. A while body does not bind a new
    name (unlike For). The outcome is the body's BlockValue, which splices
    into the enclosing record.

    Owns only empty-orelse While. Non-empty `else:` stays unowned (loud
    factory gap) -- never silently drop the orelse. Observed kind must be
    exactly "While".
    """

    test: SugarBody
    body: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "While":
            return False
        # Non-empty else: is not threaded this arm -- require empty orelse.
        if site.while_orelse_count() != 0:
            return False
        return True

    @classmethod
    def new(cls, site, ctx) -> "WhileSugar":
        # Test (TERM) and body block (STATEMENT). Never reduce here.
        return cls(
            test=ctx.build_body(site.while_test(), SugarRole.TERM),
            body=ctx.build_body(site.while_body_block(), SugarRole.STATEMENT),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Body return face through a while: truthful rides 1, lying asserts 0.
        prefix = (
            "def A(z):\n"
            "    while z.ready():\n"
            "        return 1\n"
            "    return 0\n"
            "\n"
        )
        return _call_pair(
            name="while_return",
            owner_sugar="WhileSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Reduce the test (carry its coordinate), then thread the body under
        # the same scope -- no new binding, no unrolling.
        return self.test.reduce(ctx).and_then(
            lambda _test: self.body.reduce(ctx)
        )

    def walk_children(self):
        return (self.test, self.body)
