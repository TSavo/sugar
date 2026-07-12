from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class FullSliceColumnSubscriptSugar(Sugar, role=SugarRole.TERM):
    """A two-axis ``receiver[:, integer]`` subscript coordinate.

    The index is the existing tuple literal containing a full SliceValue and
    an integer TermValue. Reduction delegates that complete index to the
    receiver's normal subscript floor. Other multi-axis forms stay loud.
    """

    receiver: SugarBody
    index: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Subscript":
            return False
        index = site.subscript_index()
        if index.observed != "Tuple":
            return False
        elements = index.tuple_elts()
        if len(elements) != 2 or elements[0].observed != "Slice":
            return False
        full_slice = elements[0]
        if any(
            bound is not None
            for bound in (
                full_slice.slice_lower(),
                full_slice.slice_upper(),
                full_slice.slice_step(),
            )
        ):
            return False
        column = elements[1]
        return (
            column.observed == "PrimitiveLiteral"
            and type(column.literal_value()) is int
        )

    @classmethod
    def new(cls, site, ctx) -> "FullSliceColumnSubscriptSugar":
        return cls(
            receiver=ctx.build_body(site.subscript_receiver(), SugarRole.TERM),
            index=ctx.build_body(site.subscript_index(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A(z):\n" "    selected = z[:, 0]\n" "    return 1\n\n"
        return _call_pair(
            name="full_slice_column_subscript_return",
            owner_sugar="FullSliceColumnSubscriptSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.receiver.reduce(ctx).and_then(
            lambda receiver: self.index.reduce(ctx).and_then(
                lambda index: receiver.subscript(index, self.site)
            )
        )

    def walk_children(self):
        return (self.receiver, self.index)
