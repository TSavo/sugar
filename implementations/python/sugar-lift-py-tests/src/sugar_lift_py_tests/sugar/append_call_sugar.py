from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ScopeRebind
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AppendCallSugar(Sugar, role=SugarRole.TERM):
    """`xs.append(v)`: mutation is a rebind. Reduce the argument, look up the
    receiver's current binding, ask its floor to append, and rebind the name to
    the updated value. Concrete list history folds; the statement is support
    (scope only). Aliasing stays a loud gap."""

    receiver_name: str
    value: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        # One method, one sugar: bare-Name receiver, one positional arg, no keywords.
        # Guard observed first -- Call accessors panic on non-Call sites.
        if site.observed != "Call" or site.call_target_name() != "append":
            return False
        receiver = site.call_receiver()
        return (
            receiver is not None
            and receiver.observed == "Name"
            and len(site.call_args()) == 1
            and not site.call_has_keywords()
        )

    @classmethod
    def new(cls, site, ctx) -> "AppendCallSugar":
        # The argument is factory-built (audited), never reduced here.
        return cls(
            receiver_name=site.call_receiver().name_id(),
            value=ctx.build_body(site.call_args()[0], SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Append rebinds the name; the return face carries z. Truthful/lying
        # twins discriminate on the returned face -- the mutation is just present.
        prefix = "def A(z):\n    xs = [1]\n    xs.append(z)\n    return z\n\n"
        return _call_pair(
            name="append_return",
            owner_sugar="AppendCallSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Reduce the arg, look up the receiver, append, rebind to the updated value.
        return self.value.reduce(ctx).and_then(
            lambda arg: ctx.temporal.value_for(self.receiver_name)
            .answer(ctx)
            .and_then(
                lambda receiver: receiver.append_with(arg, self.site).and_then(
                    lambda updated: Complete(ScopeRebind(self.receiver_name, updated))
                )
            )
        )
