from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


def _carried_names(site) -> tuple[str, ...]:
    import ast

    names: list[str] = []
    for node in ast.walk(site.node):
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Store)
            and node.id not in names
        ):
            names.append(node.id)
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, ast.Store)
            and isinstance(node.value, ast.Name)
            and node.value.id not in names
        ):
            names.append(node.value.id)
    return tuple(names)


def _has_loop_control(site) -> bool:
    import ast

    return any(
        isinstance(node, (ast.Break, ast.Continue)) for node in ast.walk(site.node)
    )


def _has_unclassified_mutation(site) -> bool:
    import ast

    for node in ast.walk(site.node):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            for target in targets:
                if isinstance(target, (ast.Name, ast.Tuple)):
                    continue
                if isinstance(target, ast.Subscript) and isinstance(
                    target.value, ast.Name
                ):
                    continue
                return True
    return False


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
            carried=_carried_names(site),
            curried=_has_loop_control(site),
            unclassified_mutation=_has_unclassified_mutation(site),
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
        return _call_pair(
            name="while_return",
            owner_sugar="WhileSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
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
                blame=str(self.site),
                observed="nonlocal mutation",
                requested="classifiable loop-carried local state",
                fix="rewrite attribute or subscript mutation as explicit carried locals",
            )

        values = tuple(ctx.temporal.value_if_bound(name) for name in self.carried)
        if any(value is None for value in values):
            factory_panic_gap(
                owner="WhileSugar",
                blame=str(self.site),
                observed=self.carried,
                requested="statically bound loop-carried locals",
                fix="bind every carried local before currying the loop",
            )
        name = f"loop:{self.site}"
        body = _contextualized_dig_body(
            SugarBody(
                sugar=CurriedLoopBody(self.body, self.carried), role=SugarRole.TERM
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
        return Complete(CurriedLoopScope(callsite, self.carried))

    def walk_children(self):
        return (self.test, self.body)
