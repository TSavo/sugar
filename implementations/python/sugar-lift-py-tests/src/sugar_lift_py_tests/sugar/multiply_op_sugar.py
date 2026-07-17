from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class MultiplyOpSugar(Sugar, role=SugarRole.TERM):
    """The `*` operator. It reduces both sides and asks the left to multiply by the
    right (the multiplication floor). Its own sugar, its own type; the value owns the
    product, no fork."""

    left: SugarBody
    right: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "BinOp" and site.operator_kind() == "Mult"

    @classmethod
    def new(cls, site, ctx) -> "MultiplyOpSugar":
        return cls(
            left=ctx.build_body(site.binop_left(), SugarRole.TERM),
            right=ctx.build_body(site.binop_right(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # `*` folds concrete numbers on the multiplication floor; the product feeds
        # `==`, and the True/False literal picks the if-face: the truthful twin rides
        # the face the product comparison picked, the lying twin asserts the other --
        # the pair proves the lift discriminates on the product.
        prefix = (
            "def A(z):\n"
            "    if 2 * 3 == 6:\n"
            "        return z\n"
            "    return 0\n"
            "\n"
        )
        return (
            _call_pair(
                name="multiply_return",
                owner_sugar="MultiplyOpSugar",
                truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
                lying=prefix + "def test_a():\n    assert A(5) == 0\n",
            ),
            _call_pair(
                name="list_repetition_length_return",
                owner_sugar="MultiplyOpSugar",
                truthful=(
                    "def A():\n"
                    "    return len([7] * 3)\n\n"
                    "def test_a():\n"
                    "    assert A() == 3\n"
                ),
                lying=(
                    "def A():\n"
                    "    return len([7] * 3)\n\n"
                    "def test_a():\n"
                    "    assert A() == 2\n"
                ),
            ),
            _call_pair(
                name="large_list_repetition_length_return",
                owner_sugar="MultiplyOpSugar",
                truthful=(
                    "def A():\n"
                    "    return len([7] * 65521)\n\n"
                    "def test_a():\n"
                    "    assert A() == 65521\n"
                ),
                lying=(
                    "def A():\n"
                    "    return len([7] * 65521)\n\n"
                    "def test_a():\n"
                    "    assert A() == 65520\n"
                ),
            ),
            _call_pair(
                name="test_loc_list_repetition_100000_length_return",
                owner_sugar="MultiplyOpSugar",
                truthful=(
                    "def A():\n"
                    "    return len([0] * 100000)\n\n"
                    "def test_a():\n"
                    "    assert A() == 100000\n"
                ),
                lying=(
                    "def A():\n"
                    "    return len([0] * 100000)\n\n"
                    "def test_a():\n"
                    "    assert A() == 99999\n"
                ),
            ),
            _call_pair(
                name="term_times_len_return",
                owner_sugar="MultiplyOpSugar",
                truthful=(
                    "def A():\n"
                    "    kinds = [1, 2]\n"
                    "    return 4 * len(kinds)\n\n"
                    "def test_a():\n"
                    "    assert A() == 8\n"
                ),
                lying=(
                    "def A():\n"
                    "    kinds = [1, 2]\n"
                    "    return 4 * len(kinds)\n\n"
                    "def test_a():\n"
                    "    assert A() == 9\n"
                ),
            ),
            _call_pair(
                name="numpy_maxdims_tuple_repetition_return",
                owner_sugar="MultiplyOpSugar",
                truthful=(
                    "from numpy._core import _multiarray_umath as ncu\n\n"
                    "def A():\n"
                    "    return len((1,) * ncu.MAXDIMS)\n\n"
                    "def test_a():\n"
                    "    assert A() == 64\n"
                ),
                lying=(
                    "from numpy._core import _multiarray_umath as ncu\n\n"
                    "def A():\n"
                    "    return len((1,) * ncu.MAXDIMS)\n\n"
                    "def test_a():\n"
                    "    assert A() == 63\n"
                ),
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.left.reduce(ctx).and_then(
            lambda left: self.right.reduce(ctx).and_then(
                lambda right: left.multiply(right, self.site)
            )
        )

    def walk_children(self):
        return (self.left, self.right)
