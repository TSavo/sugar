from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class IfSugar(Sugar, role=SugarRole.STATEMENT):
    """`if` is a condition and one or two bodies. `elif` is an `IfSugar` nested in
    the else. It reduces with no fork of its own: the condition floors to bool, and
    the standing (True/False) or the effect owns the binary conditional -- True
    emits the then-face, False emits the else-face (or nothing), an effect returns
    itself. The sugar owns the two emit faces (its bodies); the standing owns the
    decision. See floor/bool_floor.py."""

    condition: SugarBody
    then: SugarBody
    else_body: SugarBody | None
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "If"

    @classmethod
    def new(cls, site, ctx) -> "IfSugar":
        # The condition, the then-block, and the else-block (if present) are all
        # factory-built sugars. `elif` needs no special case: Python parses it as a
        # lone `If` inside the else-block, so building that block yields a nested
        # IfSugar -- a tower of sugar falls out of ordinary construction.
        blocks = site.statements()
        return cls(
            condition=ctx.build_body(site.if_test(), SugarRole.TERM),
            then=ctx.build_body(blocks[0], SugarRole.STATEMENT),
            else_body=(
                ctx.build_body(blocks[1], SugarRole.STATEMENT)
                if len(blocks) > 1
                else None
            ),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n" "    if z == 1:\n" "        return 7\n" "    return 0\n" "\n"
        )
        repeated = (
            "def A(z):\n"
            "    if z == 1:\n"
            "        answer = 7\n"
            "    if z == 1:\n"
            "        return answer\n"
            "    return 0\n"
            "\n"
        )
        existing_binding = (
            "def A(z):\n"
            "    answer = 3\n"
            "    if z == 1:\n"
            "        answer = 7\n"
            "    return answer\n"
            "\n"
        )
        guarded_raise = (
            "def A(z):\n"
            "    if z == 0:\n"
            "        raise ValueError('bad')\n"
            "    return 7\n"
            "\n"
        )
        guarded_raise_join = (
            "def A(z):\n"
            "    if z == 0:\n"
            "        raise ValueError('bad')\n"
            "    if z == 1:\n"
            "        answer = 7\n"
            "    else:\n"
            "        answer = 8\n"
            "    return answer\n"
            "\n"
        )
        return (
            _call_pair(
                name="if_return",
                owner_sugar="IfSugar",
                truthful=prefix + "def test_a():\n    assert A(1) == 7\n",
                lying=prefix + "def test_a():\n    assert A(1) == 0\n",
            ),
            _call_pair(
                name="if_repeated_guard_binding",
                owner_sugar="IfSugar",
                truthful=repeated + "def test_a():\n    assert A(1) == 7\n",
                lying=repeated + "def test_a():\n    assert A(1) == 8\n",
                family="repeated-guard-binding",
            ),
            _call_pair(
                name="if_one_arm_existing_binding_join",
                owner_sugar="IfSugar",
                truthful=existing_binding
                + "def test_a():\n    assert A(1) == 7\n    assert A(2) == 3\n",
                lying=existing_binding
                + "def test_a():\n    assert A(1) == 3\n    assert A(2) == 3\n",
                family="one-arm-existing-binding-join",
            ),
            _call_pair(
                name="if_raise_fallback_return",
                owner_sugar="IfSugar",
                truthful=guarded_raise + "def test_a():\n    assert A(1) == 7\n",
                lying=guarded_raise + "def test_a():\n    assert A(1) == 8\n",
                family="reduced-return-selection",
            ),
            _call_pair(
                name="if_raise_joined_binding_return",
                owner_sugar="IfSugar",
                truthful=guarded_raise_join + "def test_a():\n    assert A(1) == 7\n",
                lying=guarded_raise_join + "def test_a():\n    assert A(1) == 8\n",
                family="reduced-return-selection",
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.condition.reduce(ctx).binary_conditional(
            self.then, self.else_body, ctx, self.site
        )

    def walk_children(self):
        if self.else_body is None:
            return (self.condition, self.then)
        return (self.condition, self.then, self.else_body)
