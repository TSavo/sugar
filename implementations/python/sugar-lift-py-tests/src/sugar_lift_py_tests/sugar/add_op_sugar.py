from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair, typed_red_effect_witness
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AddOpSugar(Sugar, role=SugarRole.TERM):
    """The `+` operator. It reduces both sides and asks the left to add the right
    (the addition floor). The value owns what addition means -- numbers fold,
    strings concatenate; mixed types hit the honest gap. Its own sugar, its own
    type; the value owns the answer, no fork."""

    left: SugarBody
    right: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "BinOp" and site.operator_kind() == "Add"

    @classmethod
    def new(cls, site, ctx) -> "AddOpSugar":
        return cls(
            left=ctx.build_body(site.binop_left(), SugarRole.TERM),
            right=ctx.build_body(site.binop_right(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # `+` folds concrete numbers on the addition floor; the True/False face of
        # `1 + 1 == 2` picks the if-face. The truthful twin rides that face, the lying
        # twin asserts the other -- the pair proves the lift discriminates on the sum.
        prefix = (
            "def A(z):\n"
            "    if 1 + 1 == 2:\n"
            "        return z\n"
            "    return 0\n"
            "\n"
        )
        # CallSiteValue binary dispatch + install-source body dig: `g(2) + 1`
        # folds to ground post `out = 3`. Truthful asserts 3; lying asserts 4.
        dig_prefix = (
            "def g(x):\n" "    return x\n" "def A():\n" "    return g(2) + 1\n" "\n"
        )
        tuple_prefix = "def A():\n    return (1, 2) + (3,)\n\n"
        bool_prefix = "def A():\n    return False + 2\n\n"
        comprehension_call_prefix = (
            "def suffix():\n"
            "    return []\n"
        )
        return (
            _call_pair(
                name="add_return",
                owner_sugar="AddOpSugar",
                truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
                lying=prefix + "def test_a():\n    assert A(5) == 0\n",
            ),
            _call_pair(
                name="callsite_add_dig_return",
                owner_sugar="AddOpSugar",
                truthful=dig_prefix + "def test_a():\n    assert A() == 3\n",
                lying=dig_prefix + "def test_a():\n    assert A() == 4\n",
                family="callsite-binary-dig",
            ),
            _call_pair(
                name="tuple_concatenation_return",
                owner_sugar="AddOpSugar",
                truthful=tuple_prefix + "def test_a():\n    assert A() == (1, 2, 3)\n",
                lying=tuple_prefix + "def test_a():\n    assert A() == (1, 2)\n",
            ),
            _call_pair(
                name="bool_add",
                owner_sugar="AddOpSugar",
                truthful=bool_prefix + "def test_a():\n    assert A() == 2\n",
                lying=bool_prefix + "def test_a():\n    assert A() == 3\n",
            ),
            _call_pair(
                name="comprehension_callsite_add_coordinate",
                owner_sugar="AddOpSugar",
                truthful=(
                    comprehension_call_prefix
                    + "def test_a(xs):\n"
                    "    result = [x for x in xs] + suffix()\n"
                    "    assert result is result\n"
                ),
                lying=(
                    comprehension_call_prefix
                    + "def test_a(xs):\n"
                    "    result = [x for x in xs] + suffix()\n"
                    "    assert result is not result\n"
                ),
            ),
            typed_red_effect_witness(
                name="runtime_comprehension_sequence_concat",
                owner_sugar="AddOpSugar",
                source=("def A(xs):\n" "    return [x for x in xs] + ['tail']\n"),
                effect_class="SequenceConcatenationRuntimeEffect",
                reason_needle=(
                    "sequence concatenation depends on runtime comprehension members"
                ),
                blame_needle="test_witness.py:2:11",
                wrong_reason_needle="owner=ListValue.add",
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.left.reduce(ctx).and_then(
            lambda left: self.right.reduce(ctx).and_then(
                lambda right: left.add(right, self.site)
            )
        )

    def walk_children(self):
        return (self.left, self.right)
