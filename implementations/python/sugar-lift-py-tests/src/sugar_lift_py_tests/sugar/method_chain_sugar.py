from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class MethodChainSugar(
    Sugar,
    role=SugarRole.TERM,
    comes_before=("KeywordCallSugar", "MethodCallSugar"),
):
    """Unroll ``x.first(...).second(...)`` as an unnamed temporal rewrite.

    The intermediate is an ordinary ``BoundVar`` whose source is the first
    call.  The second link is the existing ``MethodCallSugar`` over an ordinary
    ``NameSugar``.  This is precisely the two-statement spelling with the
    temporary name made factory-private; no receiver provenance side channel
    or new floor value is introduced.
    """

    intermediate_name: str
    intermediate: SugarBody
    continuation: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        receiver = site.call_receiver() if site.observed == "Call" else None
        return receiver is not None and receiver.observed == "Call"

    @classmethod
    def new(cls, site, ctx) -> "MethodChainSugar":
        from sugar_lift_py_tests.factory import factory_panic_gap
        from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar
        from sugar_lift_py_tests.sugar.name_sugar import NameSugar

        receiver_site = site.call_receiver()
        # The inner Call goes through the ordinary factory below. A plain-name
        # call is therefore as classified as a builtin or receiver method call:
        # CallSugar / ConstructorCallSugar owns it and supplies the cited
        # intermediate coordinate. Only a call whose callee has no factory
        # spelling (for example a direct lambda call) stays loud here.
        if receiver_site is None or (
            receiver_site.call_receiver() is None
            and receiver_site.call_target_name() is None
        ):
            factory_panic_gap(
                owner=cls.__name__,
                blame=site,
                observed="unclassified chained-call receiver",
                requested="method-call receiver with an ordinary bound self",
                fix="classify the receiver call before unrolling the method chain",
            )

        intermediate_name = f"__sugar_chain_{site.line}_{site.col}"
        intermediate = ctx.build_body(receiver_site, SugarRole.TERM)
        positional = tuple(
            ctx.build_body(arg, SugarRole.TERM) for arg in site.call_args()
        )
        keyword_names: list[str] = []
        keyword_bodies: list[SugarBody] = []
        for keyword in site.call_keywords():
            keyword_names.append(keyword.keyword_arg_name() or "**")
            keyword_bodies.append(
                ctx.build_body(keyword.keyword_value(), SugarRole.TERM)
            )
        name_body = SugarBody(
            sugar=NameSugar(intermediate_name, site), role=SugarRole.TERM
        )
        continuation = SugarBody(
            sugar=MethodCallSugar(
                method_name=site.call_target_name(),
                import_target=None,
                receiver=name_body,
                args=(*positional, *keyword_bodies),
                keyword_names=tuple(keyword_names),
                site=site,
            ),
            role=SugarRole.TERM,
        )
        return cls(intermediate_name, intermediate, continuation, site)

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n" "    sideways = z.replace().utcoffset()\n" "    return 1\n\n"
        )
        return _call_pair(
            name="method_chain_linear_temporal",
            owner_sugar=cls.__name__,
            truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor import BoundVar

        binding = BoundVar(
            self.intermediate_name,
            self.intermediate,
            scope=ctx,
        )
        temporal = ctx.temporal.bind_value(self.intermediate_name, binding)
        return self.continuation.reduce(replace(ctx, temporal=temporal))

    def walk_children(self):
        return (self.intermediate, self.continuation)
