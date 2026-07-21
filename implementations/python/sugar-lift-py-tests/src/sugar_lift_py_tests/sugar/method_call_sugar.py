"""A method call `<receiver>.<name>(<args>)` -- the attribute callee.

The pandas census's largest family (15,638 sites, 61% of the frontier), and it
is a COMPOSITION, not a new mechanism: the receiver reduces like any value (the
`py.getattr` discipline), and the call stands as the method coordinate
`call:<name>(receiver, args)` with `symbol_kind="method-coordinate"` -- the same
vocabulary `__format__`/`__getitem__` already use. The receiver rides as
`runtime_dispatch_receiver` on the CallSiteValue: the field that exists for
exactly this ("the receiver whose runtime type selects a method body"), so a
future type-aware dig can resolve the body; today the coordinate is honest EUF,
decidable where an equality consumes it.

Keyword arguments stay loud (the tree node guards them), as on plain calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class MethodCallSugar(Sugar):
    receiver: Sugar
    name: str
    args: tuple  # the argument sugars, in source order
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        # int.bit_length is a real method with a decidable shape: the pair rides
        # the coordinate's identity against a contradicting asserted value.
        prefix = "def A(z):\n    return z.bit_length()\n\n"
        return _call_pair(
            name="method_call_return",
            owner_sugar="MethodCallSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 3\n",
            lying=prefix + "def test_a():\n    assert A(5) == 4\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self._collect(receiver, self.args, (), ctx)
        )

    def _collect(self, receiver, remaining: tuple, accumulated: tuple, ctx) -> Outcome:
        if remaining:
            head, *rest = remaining
            return head.desugar(ctx).and_then(
                lambda value: self._collect(
                    receiver, tuple(rest), accumulated + (value,), ctx
                )
            )
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import ctor

        owner = str(self.site)
        term = ctor(
            f"call:{self.name}",
            [receiver.to_term(owner=owner)]
            + [value.to_term(owner=owner) for value in accumulated],
            symbol_kind="method-coordinate",
        )
        return Complete(
            CallSiteValue(
                target_name=self.name,
                arg_values=(receiver, *accumulated),
                parameters=(),
                term=term,
                body=None,  # the dig is CUED, not inlined here
                site=self.site,
                runtime_dispatch_receiver=receiver,
            )
        )
