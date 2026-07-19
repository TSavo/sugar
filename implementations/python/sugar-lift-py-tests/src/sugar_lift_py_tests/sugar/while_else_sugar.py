from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.loop_control_scope_sugar import LoopControlScopeSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class WhileElseSugar(Sugar, role=SugarRole.STATEMENT):
    """A while ``else`` is the curried body projected through its no-break face.

    `WhileSugar` owns empty-orelse only. Non-empty ``else:`` is this arm —
    parallel to `ForElseSugar`. Never silently drop the orelse.
    """

    test: SugarBody
    body: SugarBody
    else_body: SugarBody
    carried: tuple[str, ...]
    has_break: bool
    unclassified_mutation: bool
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "While":
            return False
        return site.while_orelse_count() != 0

    @classmethod
    def new(cls, site, ctx) -> "WhileElseSugar":
        scope = LoopControlScopeSugar.classify(site, entry_reads=(site.while_test(),))
        return cls(
            test=ctx.build_body(site.while_test(), SugarRole.TERM),
            body=ctx.build_body(site.while_body_block(), SugarRole.STATEMENT),
            else_body=ctx.build_body(site.while_orelse_block(), SugarRole.STATEMENT),
            carried=scope.carried_names,
            has_break=scope.has_owned_break,
            unclassified_mutation=scope.has_unclassified_mutation,
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n"
            "    while z:\n"
            "        pass\n"
            "    else:\n"
            "        return 1\n"
            "    return 0\n\n"
        )
        return _call_pair(
            name="while_else_no_break_return",
            owner_sugar=cls.__name__,
            truthful=prefix + "def test_a():\n    assert A(False) == 1\n",
            lying=prefix + "def test_a():\n    assert A(False) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.test.reduce(ctx).and_then(lambda _test: self._curry_loop(ctx))

    def _curry_loop(self, ctx) -> Outcome:
        from sugar_lift_py_tests.factory import factory_panic_gap
        from sugar_lift_py_tests.floor import (
            CurriedLoopBody,
            CurriedLoopScope,
            FunctionCallable,
            LoopElseValue,
            PredicateValue,
        )
        from sugar_lift_py_tests.ir import atomic
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.install_source_dig import (
            _contextualized_dig_body,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        if self.unclassified_mutation:
            factory_panic_gap(
                owner=type(self).__name__,
                blame=self.site,
                observed="nonlocal mutation",
                requested="classifiable loop-carried local state",
                fix="rewrite attribute mutation as explicit carried locals",
            )
        values = tuple(ctx.temporal.value_if_bound(name) for name in self.carried)
        if any(value is None for value in values):
            factory_panic_gap(
                owner=type(self).__name__,
                blame=self.site,
                observed=self.carried,
                requested="statically bound loop-carried locals",
                fix="bind every carried local before currying the loop",
            )

        break_hole = "__break__"
        body = _contextualized_dig_body(
            SugarBody(
                sugar=CurriedLoopBody(self.body, self.carried),
                role=SugarRole.TERM,
            ),
            ctx,
        )
        callable_value = FunctionCallable(
            name=f"loop:{self.site}",
            parameters=(*self.carried, break_hole),
            parameter_kinds=("positional",) * (len(self.carried) + 1),
            body=body,
        )
        no_break = FalseBoolLiteralSugar(site=self.site)
        callsite = callable_value.callsite((*values, no_break), (), self.site).value
        loop_scope = CurriedLoopScope(callsite, self.carried)
        no_break_formula = atomic("py.loop.no_break", [callsite.term])
        else_ctx = loop_scope.extend_scope(ctx)
        condition = (
            PredicateValue(no_break_formula, self.site)
            if self.has_break
            else TrueBoolLiteralSugar(site=self.site)
        )
        else_faces = condition.binary_conditional(
            self.else_body, None, else_ctx, self.site
        )
        return else_faces.and_then(
            lambda faces: Complete(LoopElseValue(loop_scope, faces, no_break_formula))
        )

    def walk_children(self):
        return (self.test, self.body, self.else_body)
