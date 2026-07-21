"""A computed callee call `<callee>(<args>)` -- the callee is an expression,
not a bare name or attribute (`fs[0](x)`, `d["k"](x)`). A COMPOSITION, not a
new mechanism: the callee reduces like any value (whatever sugar its own node
built -- SubscriptSugar for `fs[0]`, and so on), and the call stands as the
coordinate `py.call(callee, args)` with `symbol_kind="coordinate"`. There is no
receiver whose runtime type selects a method body here (the callee itself IS
the thing being invoked), so no `runtime_dispatch_receiver` rides this value --
unlike MethodCallSugar's attribute-callee case.

A callee whose own node has no `.sugar()` (a Lambda called inline, for example)
stays loud through the ordinary recursion: this sugar never masks that gap.

Keyword arguments stay loud (the tree node guards them), as on plain calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class ComputedCallSugar(Sugar):
    callee: Sugar
    args: tuple  # the argument sugars, in source order
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        # fs[0] is a real computed callee with a decidable shape: the
        # coordinate's identity against a contradicting asserted value.
        prefix = "def A(fs, x):\n    return fs[0](x)\n\n"
        return _call_pair(
            name="computed_call_return",
            owner_sugar="ComputedCallSugar",
            truthful=prefix + "def test_a():\n    assert A([lambda z: z], 5) == 5\n",
            lying=prefix + "def test_a():\n    assert A([lambda z: z], 5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.callee.desugar(ctx).and_then(
            lambda callee: self._collect(callee, self.args, (), ctx)
        )

    def _collect(self, callee, remaining: tuple, accumulated: tuple, ctx) -> Outcome:
        if remaining:
            head, *rest = remaining
            return head.desugar(ctx).and_then(
                lambda value: self._collect(
                    callee, tuple(rest), accumulated + (value,), ctx
                )
            )
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import ctor

        owner = str(self.site)
        term = ctor(
            "py.call",
            [callee.to_term(owner=owner)]
            + [value.to_term(owner=owner) for value in accumulated],
            symbol_kind="coordinate",
        )
        return Complete(
            CallSiteValue(
                target_name="py.call",
                arg_values=(callee, *accumulated),
                parameters=(),
                term=term,
                body=None,  # the dig is CUED, not inlined here
                site=self.site,
            )
        )
