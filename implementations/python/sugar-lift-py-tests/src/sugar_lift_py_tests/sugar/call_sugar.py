from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class CallSugar(Sugar, role=SugarRole.TERM):
    """A plain-name call `f(<args>)`. A call is a COORDINATE into the vendor
    universe: reduce the arguments, and the result is the callsite -- a
    CallSiteValue whose term IS `call:f(<args>)`. The lift does not derive f
    (dig the universe, don't derive f); the coordinate is the stated address a
    dig lands on, and it rides inside any sentence built over the result.
    Method calls, receivers, and keyword arguments stay loud gaps."""

    target_name: str
    args: tuple[SugarBody, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        # Plain-name positional calls only; os.exit stays OsSugar's (it has a
        # receiver, so the shapes are disjoint).
        return (
            site.observed == "Call"
            and site.call_receiver() is None
            and site.call_target_name() is not None
            and not site.call_has_keywords()
        )

    @classmethod
    def new(cls, site, ctx) -> "CallSugar":
        # The arguments are factory-built (audited), never reduced here.
        return cls(
            target_name=site.call_target_name(),
            args=tuple(
                ctx.build_body(arg, SugarRole.TERM) for arg in site.call_args()
            ),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # The callsite coordinate discharges against the callee's contract: the
        # truthful twin's assert agrees with B's body, the lying twin's cannot.
        prefix = "def B(w):\n    return w\n\ndef A(z):\n    y = B(z)\n    return y\n\n"
        return _call_pair(
            name="call_return",
            owner_sugar="CallSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Reduce each argument, and the result is the callsite coordinate.
        return self._collect(self.args, (), ctx)

    def _collect(self, remaining: tuple, accumulated: tuple, ctx: object) -> Outcome:
        if not remaining:
            from sugar_lift_py_tests.floor import CallSiteValue
            from sugar_lift_py_tests.ir import ctor

            return Complete(
                CallSiteValue(
                    target_name=self.target_name,
                    arg_values=accumulated,
                    parameters=(),
                    term=ctor(
                        f"call:{self.target_name}",
                        [value.to_term(owner=str(self.site)) for value in accumulated],
                    ),
                    body=None,
                    site=self.site,
                )
            )
        head, *rest = remaining
        return head.reduce(ctx).and_then(
            lambda value: self._collect(tuple(rest), (*accumulated, value), ctx)
        )

    def walk_children(self):
        return self.args
