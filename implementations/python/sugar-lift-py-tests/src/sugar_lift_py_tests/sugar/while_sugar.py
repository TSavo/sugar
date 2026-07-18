from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class WhileSugar(Sugar, role=SugarRole.STATEMENT):
    """`while <test>: <body>` -- thread the body, carry the test coordinate.

    Recognition + scope threading, not loop unrolling: reduce the test to its
    coordinate (predicate/value via the usual truth/comparison floors), then
    reduce the body under the current scope. A while body does not bind a new
    name (unlike For). The outcome is the body's BlockValue, which splices
    into the enclosing record.

    Owns only empty-orelse While. Non-empty `else:` stays unowned (loud
    factory gap) -- never silently drop the orelse. Observed kind must be
    exactly "While".
    """

    test: SugarBody
    body: SugarBody
    carried: tuple[str, ...]
    deferred_outputs: tuple[str, ...]
    curried: bool
    unclassified_mutation: bool
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "While":
            return False
        # Non-empty else: is not threaded this arm -- require empty orelse.
        if site.while_orelse_count() != 0:
            return False
        return True

    @classmethod
    def new(cls, site, ctx) -> "WhileSugar":
        # Test (TERM) and body block (STATEMENT). Never reduce here.
        return cls(
            test=ctx.build_body(site.while_test(), SugarRole.TERM),
            body=ctx.build_body(site.while_body_block(), SugarRole.STATEMENT),
            carried=site.loop_carried_names(entry_reads=(site.while_test(),)),
            deferred_outputs=site.while_definite_break_output_names(),
            curried=site.has_loop_control(),
            unclassified_mutation=site.has_unclassified_loop_mutation(),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Body return face through a while: truthful rides 1, lying asserts 0.
        prefix = (
            "def A(z):\n"
            "    while z.ready():\n"
            "        return 1\n"
            "    return 0\n"
            "\n"
        )
        carried_prefix = (
            "def B(z):\n"
            "    value = 1\n"
            "    while z.ready():\n"
            "        local = value\n"
            "        value = local\n"
            "        break\n"
            "    return value\n"
            "\n"
        )
        definite_output_prefix = (
            "def test_c():\n" "    while True:\n" "        out = 7\n" "        break\n"
        )
        return (
            _call_pair(
                name="while_return",
                owner_sugar="WhileSugar",
                truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
                lying=prefix + "def test_a():\n    assert A(5) == 0\n",
            ),
            _call_pair(
                name="while_loop_carried",
                owner_sugar="WhileSugar",
                truthful=carried_prefix + "def test_b():\n    assert B(5) == 1\n",
                lying=carried_prefix + "def test_b():\n    assert B(5) == 0\n",
            ),
            _call_pair(
                name="while_true_definite_output",
                owner_sugar="WhileSugar",
                truthful=definite_output_prefix + "    assert out == 7\n",
                lying=definite_output_prefix + "    assert out == 8\n",
                family="while-definite-output",
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        if not self.curried:
            return self.test.reduce(ctx).and_then(lambda _test: self.body.reduce(ctx))
        from sugar_lift_py_tests.factory import factory_panic_gap
        from sugar_lift_py_tests.floor import (
            CurriedLoopBody,
            CurriedLoopScope,
            FunctionCallable,
        )
        from sugar_lift_py_tests.sugar.install_source_dig import (
            _contextualized_dig_body,
        )

        if self.unclassified_mutation:
            factory_panic_gap(
                owner="WhileSugar",
                blame=self.site,
                observed="nonlocal mutation",
                requested="classifiable loop-carried local state",
                fix="rewrite attribute or subscript mutation as explicit carried locals",
            )

        values = tuple(ctx.temporal.value_if_bound(name) for name in self.carried)
        if any(value is None for value in values):
            factory_panic_gap(
                owner="WhileSugar",
                blame=self.site,
                observed=self.carried,
                requested="statically bound loop-carried locals",
                fix="bind every carried local before currying the loop",
            )
        output_names = tuple(dict.fromkeys((*self.carried, *self.deferred_outputs)))
        name = f"loop:{self.site}"
        body = _contextualized_dig_body(
            SugarBody(
                sugar=CurriedLoopBody(self.body, output_names), role=SugarRole.TERM
            ),
            ctx,
        )
        callable_value = FunctionCallable(
            name=name,
            parameters=self.carried,
            parameter_kinds=("positional",) * len(self.carried),
            body=body,
        )
        callsite = callable_value.callsite(values, (), self.site).value
        return Complete(CurriedLoopScope(callsite, output_names))

    def walk_children(self):
        return (self.test, self.body)
