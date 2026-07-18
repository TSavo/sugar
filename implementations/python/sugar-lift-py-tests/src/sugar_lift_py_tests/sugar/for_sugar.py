from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.loop_control_scope_sugar import LoopControlScopeSugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody

STATIC_UNFOLD_LIMIT = 1024


@dataclass(frozen=True)
class ForSugar(Sugar, role=SugarRole.STATEMENT):
    """`for <name> in <iter>: <body>` -- thread the body over the iter element.

    Recognition + scope threading, not loop unrolling: reduce the iterable to
    its coordinate, bind the simple-Name target to an element coordinate
    ctor("py.iter_elem", [iter_term]), then reduce the body under that extended
    scope. The For is a scope+sequence construct: its outcome is the body's
    BlockValue, which splices into the enclosing record.

    Owns only simple-Name targets with empty orelse. Tuple/starred targets and
    non-empty `else:` clauses stay unowned (loud factory gap) -- never silently
    drop the iterable, body, or orelse. AsyncFor is a different observed kind
    and is not owned here.
    """

    target_name: str
    iterable: SugarBody
    body: SugarBody
    carried: tuple[str, ...]
    curried: bool
    unclassified_mutation: bool
    deferred_outputs: tuple[str, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "For":
            return False
        # Simple Name target only; tuple/starred stays a loud gap.
        if site.for_target_name() is None:
            return False
        # Non-empty else: is not threaded this arm -- require empty orelse.
        if site.for_orelse_count() != 0:
            return False
        return True

    @classmethod
    def new(cls, site, ctx) -> "ForSugar":
        # Iterable (TERM), target name, body block (STATEMENT). Never reduce here.
        target_name = site.for_target_name()
        scope = LoopControlScopeSugar.classify(site, target_name=target_name)
        return cls(
            target_name=target_name,
            iterable=ctx.build_body(site.for_iter(), SugarRole.TERM),
            body=ctx.build_body(site.for_body_block(), SugarRole.STATEMENT),
            carried=scope.carried_names,
            curried=scope.has_loop_control,
            unclassified_mutation=scope.has_unclassified_mutation,
            deferred_outputs=_finite_loop_output_names(site, target_name),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # The iteration-local assignment is not a carried input.  The continue
        # makes the loop curried; the post-loop return is still verdict-bearing.
        prefix = (
            "def A(z):\n"
            "    for x in z:\n"
            "        if x == 0:\n"
            "            continue\n"
            "        local = 1\n"
            "    return 0\n"
            "\n"
        )
        large_static_prefix = (
            "def B():\n"
            "    for x in range(1025):\n"
            "        pass\n"
            "    return 0\n"
            "\n"
        )
        bound_finite_getattr_prefix = (
            "class Box:\n"
            "    def __init__(self):\n"
            "        self.x = 7\n"
            "\n"
            "def C():\n"
            "    names = ['x']\n"
            "    for name in names:\n"
            "        return getattr(Box(), name)\n"
            "    return 0\n"
            "\n"
        )
        return (
            _call_pair(
                name="for_return",
                owner_sugar="ForSugar",
                truthful=prefix + "def test_a():\n    assert A(5) == 0\n",
                lying=prefix + "def test_a():\n    assert A(5) == 1\n",
            ),
            _call_pair(
                name="for_large_static_unfold",
                owner_sugar="ForSugar",
                truthful=large_static_prefix + "def test_b():\n    assert B() == 0\n",
                lying=large_static_prefix + "def test_b():\n    assert B() == 1\n",
            ),
            _call_pair(
                name="for_bound_finite_getattr_return",
                owner_sugar="ForSugar",
                truthful=bound_finite_getattr_prefix
                + "def test_c():\n    assert C() == 7\n",
                lying=bound_finite_getattr_prefix
                + "def test_c():\n    assert C() == 8\n",
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Reduce the iterable; bind target to the element coordinate; thread body.
        return self.iterable.reduce(ctx).and_then(
            lambda iterable: self._finish_iterable(iterable, ctx)
        )

    def _finish_iterable(self, iterable, ctx):
        from sugar_lift_py_tests.floor import (
            ArrayLiteral,
            ComprehensionValue,
            ListValue,
            TupleValue,
        )

        elements = None
        if type(iterable) in (ListValue, TupleValue):
            elements = iterable.elements
        elif type(iterable) is ArrayLiteral:
            elements = iterable.items
        elif (
            type(iterable) is ComprehensionValue
            and iterable.finite_elements is not None
        ):
            elements = iterable.finite_elements
        if elements is not None:
            if len(elements) > STATIC_UNFOLD_LIMIT:
                return self._bind_and_body(iterable, ctx, force_curry=True)
            return self._unfold_values(elements, ctx)
        return self._bind_and_body(iterable, ctx)

    def _unfold_values(self, values, ctx, entries=()):
        from sugar_lift_py_tests.floor import BlockValue, ScopeRebind

        accumulated = list(entries)
        current_ctx = ctx
        for value in values:
            iteration_ctx = ScopeRebind(self.target_name, value).extend_scope(
                current_ctx
            )
            record, current_ctx = self.body.sugar.reduce_with_scope(iteration_ctx)
            accumulated.extend(record.contribution())
        bindings = _post_loop_bindings(ctx, current_ctx)
        return Complete(BlockValue((*accumulated, *bindings)))

    def _bind_and_body(
        self, iterable, ctx: object, *, force_curry: bool = False
    ) -> Outcome:
        from sugar_lift_py_tests.floor import CallSiteValue, ScopeRebind
        from sugar_lift_py_tests.ir import ctor

        # Element of the iterable -- recognition coordinate, not unrolled history.
        elem = CallSiteValue(
            target_name="iter_elem",
            arg_values=(iterable,),
            parameters=(),
            term=ctor(
                "py.iter_elem",
                [iterable.to_term(owner=str(self.site))],
            ),
            body=None,
            site=self.site,
        )
        body_ctx = ScopeRebind(self.target_name, elem).extend_scope(ctx)
        if self.curried or force_curry:
            from sugar_lift_py_tests.floor import (
                CurriedLoopBody,
                CurriedLoopScope,
                FunctionCallable,
            )
            from sugar_lift_py_tests.sugar.install_source_dig import (
                _contextualized_dig_body,
            )

            if self.unclassified_mutation:
                from sugar_lift_py_tests.factory import factory_panic_gap

                factory_panic_gap(
                    owner="ForSugar",
                    blame=self.site,
                    observed="nonlocal mutation",
                    requested="classifiable loop-carried local state",
                    fix="rewrite attribute or subscript mutation as explicit carried locals",
                )

            input_names = self.carried
            output_names = self.deferred_outputs if force_curry else self.carried
            values = tuple(
                body_ctx.temporal.value_if_bound(name) for name in input_names
            )
            if all(value is not None for value in values):
                name = f"loop:{self.site}"
                body = _contextualized_dig_body(
                    SugarBody(
                        sugar=CurriedLoopBody(self.body, output_names),
                        role=SugarRole.TERM,
                    ),
                    body_ctx,
                )
                callable_value = FunctionCallable(
                    name=name,
                    parameters=input_names,
                    parameter_kinds=("positional",) * len(input_names),
                    body=body,
                )
                callsite = callable_value.callsite(values, (), self.site).value
                return Complete(CurriedLoopScope(callsite, output_names))
            from sugar_lift_py_tests.factory import factory_panic_gap

            factory_panic_gap(
                owner="ForSugar",
                blame=self.site,
                observed=self.carried,
                requested="statically bound loop-carried locals",
                fix="bind every carried local before currying the loop",
            )
        # Body is a BlockSugar; its BlockValue contribution splices outward.
        return self.body.reduce(body_ctx)

    def walk_children(self):
        return (self.iterable, self.body)


def _post_loop_bindings(initial_ctx, final_ctx):
    """Project exactly the bindings constructed by a non-empty static unfold."""
    from sugar_lift_py_tests.floor import ScopeRebind

    before = {binding.name: binding.value for binding in initial_ctx.temporal.bindings}
    return tuple(
        ScopeRebind(binding.name, binding.value)
        for binding in final_ctx.temporal.bindings
        if before.get(binding.name) is not binding.value
    )


def _finite_loop_output_names(site, target_name: str) -> tuple[str, ...]:
    """Names definitely rebound by a nonempty finite loop callable."""
    return (
        target_name,
        *LoopControlScopeSugar.own_scope_stored_names(site.for_body_block()),
    )
