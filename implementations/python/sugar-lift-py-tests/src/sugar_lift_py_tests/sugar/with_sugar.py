from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class WithSugar(Sugar, role=SugarRole.STATEMENT):
    """`with cm as y: body` -- thread the body over the enter coordinate.

    Single-item synchronous With only. Multi-item `with a, b:` and
    AsyncWith stay unowned (loud factory gap) -- this arm does not take
    the first item and drop the rest. Complex `as` targets (tuple, attr)
    are also unowned.

    Reduce the context expression; the entered value is the unary
    coordinate call:__enter__(cm), same head family as method calls.
    Bind optional `as y` via ScopeRebind, then reduce the body under
    that scope. The With is a scope+sequence construct: its outcome is
    the body's BlockValue, which splices into the enclosing record.
    """

    context: SugarBody
    as_name: str | None
    body: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "With":
            return False
        # One context manager only; multi-item stays a loud gap.
        if site.with_item_count() != 1:
            return False
        # Optional as-target is either absent or a simple Name.
        observed = site.with_optional_vars_observed()
        if observed is not None and site.with_optional_vars_name() is None:
            return False
        return True

    @classmethod
    def new(cls, site, ctx) -> "WithSugar":
        # Context expr (TERM), optional as-name, body block (STATEMENT).
        # Never reduce here.
        return cls(
            context=ctx.build_body(site.with_context_expr(0), SugarRole.TERM),
            as_name=site.with_optional_vars_name(0),
            body=ctx.build_body(site.with_body(), SugarRole.STATEMENT),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Coordinate rides inside the with-body; the pair discriminates on
        # the enclosing return face (no concrete CM fold yet).
        prefix = (
            "def A(z):\n"
            "    with z.lock() as g:\n"
            "        return 1\n"
            "    return 0\n"
            "\n"
        )
        return _call_pair(
            name="with_return",
            owner_sugar="WithSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Reduce the context; enter-coordinate + body under optional as-binding.
        return self.context.reduce(ctx).and_then(
            lambda cm: self._enter_and_body(cm, ctx)
        )

    def _enter_and_body(self, cm, ctx: object) -> Outcome:
        from sugar_lift_py_tests.floor import CallSiteValue, ScopeRebind
        from sugar_lift_py_tests.ir import ctor

        enter = CallSiteValue(
            target_name="__enter__",
            arg_values=(cm,),
            parameters=(),
            term=ctor(
                "call:__enter__",
                [cm.to_term(owner=str(self.site))],
            ),
            body=None,
            site=self.site,
        )
        body_ctx = ctx
        if self.as_name is not None:
            body_ctx = ScopeRebind(self.as_name, enter).extend_scope(ctx)
        # Body is a BlockSugar; its BlockValue contribution splices outward.
        return self.body.reduce(body_ctx)

    def walk_children(self):
        return (self.context, self.body)
