from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class SliceSubscriptSugar(Sugar, role=SugarRole.TERM, comes_before=("SubscriptSugar",)):
    """`x[a:b:c]` slice subscript.

    Deeper floors: SubscriptSugar leaves Slice indexes unowned. Own them as a
    Build the receiver and literal integer bounds, then ask the receiver's
    native subscript floor to consume a SliceValue. Concrete strings fold;
    symbolic receivers emit ``py.subscript(recv, py.slice(...))``.
    """

    receiver: SugarBody
    lower: SugarBody | None
    upper: SugarBody | None
    step: SugarBody | None
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Subscript":
            return False
        index = site.subscript_index()
        if index.observed != "Slice":
            return False
        return not any(
            _is_bitor_annotation(bound)
            for bound in (
                index.slice_lower(),
                index.slice_upper(),
                index.slice_step(),
            )
        )

    @classmethod
    def new(cls, site, ctx) -> "SliceSubscriptSugar":
        idx = site.subscript_index()
        lower_site = idx.slice_lower()
        upper_site = idx.slice_upper()
        step_site = idx.slice_step()
        return cls(
            receiver=ctx.build_body(site.subscript_receiver(), SugarRole.TERM),
            lower=(
                ctx.build_body(lower_site, SugarRole.TERM)
                if lower_site is not None
                else None
            ),
            upper=(
                ctx.build_body(upper_site, SugarRole.TERM)
                if upper_site is not None
                else None
            ),
            step=(
                ctx.build_body(step_site, SugarRole.TERM)
                if step_site is not None
                else None
            ),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A(z):\n" "    xs = [10, 20, 30, 40]\n" "    return xs[1:3]\n" "\n"
        return _call_pair(
            name="slice_subscript_return",
            owner_sugar="SliceSubscriptSugar",
            # Coordinate path: discriminate on a surrounding return face
            # that does not require ground slice fold.
            truthful=prefix + "def test_a():\n    assert A(5) is not None\n",
            lying=prefix + "def test_a():\n    assert A(5) is None\n",
        )

    def desugar(self, ctx: Any = None) -> Outcome:
        return self.receiver.reduce(ctx).and_then(
            lambda recv: self._reduce_bound(
                self.lower,
                ctx,
                lambda lo: self._reduce_bound(
                    self.upper,
                    ctx,
                    lambda hi: self._reduce_bound(
                        self.step, ctx, lambda st: self._emit(recv, lo, hi, st)
                    ),
                ),
            )
        )

    def _reduce_bound(self, body: SugarBody | None, ctx, cont) -> Outcome:
        if body is None:
            return cont(None)
        return body.reduce(ctx).and_then(cont)

    def _emit(self, recv, lo, hi, st) -> Outcome:
        from sugar_lift_py_tests.floor import SliceValue

        return recv.subscript(SliceValue(lo, hi, st), self.site)

    def walk_children(self):
        kids = [self.receiver]
        for b in (self.lower, self.upper, self.step):
            if b is not None:
                kids.append(b)
        return tuple(kids)


def _is_bitor_annotation(bound) -> bool:
    return (
        bound is not None
        and bound.observed == "BinOp"
        and bound.operator_kind() == "BitOr"
    )
