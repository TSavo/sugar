from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.loop_control_scope_sugar import LoopControlScopeSugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ForElseSugar(Sugar, role=SugarRole.STATEMENT):
    """A loop ``else`` is the curried body projected through its no-break face."""

    targets: tuple[tuple[tuple[int, ...], str], ...]
    iterable: SugarBody
    body: SugarBody
    else_body: SugarBody
    carried: tuple[str, ...]
    has_break: bool
    unclassified_mutation: bool
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "For" or site.for_orelse_count() == 0:
            return False
        name = site.for_target_name()
        names = site.for_flat_tuple_target_names()
        paths = site.for_nested_tuple_target_paths()
        return name is not None or names is not None or paths is not None

    @classmethod
    def new(cls, site, ctx) -> "ForElseSugar":
        name = site.for_target_name()
        flat_names = site.for_flat_tuple_target_names()
        nested_paths = site.for_nested_tuple_target_paths()
        if name is not None:
            targets = (((), name),)
        elif flat_names is not None:
            targets = tuple(
                ((index,), target_name) for index, target_name in enumerate(flat_names)
            )
        else:
            assert nested_paths is not None
            targets = nested_paths
        target_names = tuple(target_name for _, target_name in targets)
        scope = LoopControlScopeSugar.classify(site)
        return cls(
            targets=targets,
            iterable=ctx.build_body(site.for_iter(), SugarRole.TERM),
            body=ctx.build_body(site.for_body_block(), SugarRole.STATEMENT),
            else_body=ctx.build_body(site.for_orelse_block(), SugarRole.STATEMENT),
            carried=tuple(
                name for name in scope.stored_names if name not in target_names
            ),
            has_break=scope.has_owned_break,
            unclassified_mutation=scope.has_unclassified_mutation,
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(items):\n"
            "    for item in items:\n"
            "        pass\n"
            "    else:\n"
            "        return 1\n"
            "    return 0\n\n"
        )
        nested_prefix = (
            "def B():\n"
            "    for index, (left, right) in []:\n"
            "        pass\n"
            "    else:\n"
            "        return 2\n"
            "    return 0\n\n"
        )
        return (
            _call_pair(
                name="for_else_no_break_return",
                owner_sugar=cls.__name__,
                truthful=prefix + "def test_a():\n    assert A([]) == 1\n",
                lying=prefix + "def test_a():\n    assert A([]) == 0\n",
            ),
            _call_pair(
                name="nested_tuple_for_else_return",
                owner_sugar=cls.__name__,
                truthful=nested_prefix + "def test_b():\n    assert B() == 2\n",
                lying=nested_prefix + "def test_b():\n    assert B() == 0\n",
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.iterable.reduce(ctx).and_then(
            lambda iterable: self._curry_loop(iterable, ctx)
        )

    def _curry_loop(self, iterable, ctx) -> Outcome:
        from sugar_lift_py_tests.factory import factory_panic_gap
        from sugar_lift_py_tests.floor import (
            CallSiteValue,
            CurriedLoopBody,
            CurriedLoopScope,
            FunctionCallable,
            LoopElseValue,
            PredicateValue,
        )
        from sugar_lift_py_tests.ir import atomic, ctor, num
        from sugar_lift_py_tests.sugar.install_source_dig import (
            _contextualized_dig_body,
        )
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        element = CallSiteValue(
            target_name="iter_elem",
            arg_values=(iterable,),
            parameters=(),
            term=ctor("py.iter_elem", [iterable.to_term(owner=str(self.site))]),
            body=None,
            site=self.site,
        )
        temporal = ctx.temporal
        for path, name in self.targets:
            if not path:
                target = element
            else:
                term = element.term
                for index in path:
                    term = ctor("py.subscript", [term, num(index)])
                target = CallSiteValue(
                    target_name="py.subscript",
                    arg_values=(element,),
                    parameters=(),
                    term=term,
                    body=None,
                    site=self.site,
                )
            temporal = temporal.bind_value(name, target)
        body_ctx = ctx.with_temporal(temporal)

        if self.unclassified_mutation:
            factory_panic_gap(
                owner=type(self).__name__,
                blame=self.site,
                observed="nonlocal mutation",
                requested="classifiable loop-carried local state",
                fix="rewrite attribute mutation as explicit carried locals",
            )
        values = tuple(body_ctx.temporal.value_if_bound(name) for name in self.carried)
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
            body_ctx,
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
        return (self.iterable, self.body, self.else_body)
