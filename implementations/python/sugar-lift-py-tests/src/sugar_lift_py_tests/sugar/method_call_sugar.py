from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class MethodCallSugar(Sugar, role=SugarRole.TERM):
    """A method call `recv.method(<args>)`.

    Composes on the AttributeSugar coordinate family: the term is
    `call:<method>(receiver, *args)` -- receiver first, then positional
    args. Disjoint from CallSugar (plain-name, no receiver) and OsSugar
    (`os.exit`). Keyword arguments are not owned (loud factory gap).
    """

    method_name: str
    receiver: SugarBody
    args: tuple[SugarBody, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        # Method Call with a receiver Attribute func. OsSugar keeps os.exit.
        # Keywords stay unowned so they panic loud at recognition, not dropped.
        return (
            site.observed == "Call"
            and site.call_receiver() is not None
            and site.call_qualified_target_name() != "os.exit"
            and not site.call_has_keywords()
        )

    @classmethod
    def new(cls, site, ctx) -> "MethodCallSugar":
        # Receiver and positional args are factory-built (audited), never reduced.
        return cls(
            method_name=site.call_target_name(),
            receiver=ctx.build_body(site.call_receiver(), SugarRole.TERM),
            args=tuple(
                ctx.build_body(arg, SugarRole.TERM) for arg in site.call_args()
            ),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Coordinate rides inside the body; the pair discriminates on the
        # enclosing return face (coordinates stay symbolic -- no concrete fold).
        prefix = (
            "def A(z):\n"
            "    y = z.groupby(3)\n"
            "    return 1\n"
            "\n"
        )
        return _call_pair(
            name="method_call_return",
            owner_sugar="MethodCallSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Reduce receiver, then each arg; the result is the method coordinate.
        return self.receiver.reduce(ctx).and_then(
            lambda recv: self._collect(self.args, (recv,), ctx)
        )

    def _collect(self, remaining: tuple, accumulated: tuple, ctx: object) -> Outcome:
        if not remaining:
            from sugar_lift_py_tests.floor import CallSiteValue
            from sugar_lift_py_tests.ir import ctor

            return Complete(
                CallSiteValue(
                    target_name=self.method_name,
                    arg_values=accumulated,
                    parameters=(),
                    term=ctor(
                        f"call:{self.method_name}",
                        [
                            value.to_term(owner=str(self.site))
                            for value in accumulated
                        ],
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
        return (self.receiver, *self.args)
