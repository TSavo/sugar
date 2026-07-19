from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import NoReturn

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.loop_control_scope_sugar import LoopControlScopeSugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody

STATIC_UNFOLD_LIMIT = 1024
# Static unfold × branch multiplies GuardedValue/scope state super-linearly
# (microbench: 8×(abs,)+If+InOp ~0.5s; 14× ~113s). Over-cap decidable work
# stays a typed loud terminal until an exact compact construction exists.
BRANCHED_STATIC_UNFOLD_LIMIT = 8


def is_ground_loop_datum(value) -> bool:
    """True when a bound value is safe to reduce inside a static for-unfold.

    Dig-opaque / callsite / predicate / symbolic carriers are non-ground: a
    nested While over them must not per-k Equality-reduce (#5338 family A /
    test_shortest_path pred-chain). Concrete numbers, bools, strings, None,
    and finite containers of those stay ground so pure for+while micros keep
    static discharge.
    """
    type_name = type(value).__name__
    if type_name in {
        "TermValue",
        "StringValue",
        "NoneValue",
        "TrueBoolLiteralSugar",
        "FalseBoolLiteralSugar",
    }:
        return True
    if type_name in {"ListValue", "TupleValue"}:
        return all(is_ground_loop_datum(item) for item in value.elements)
    if type_name == "ArrayLiteral":
        return all(is_ground_loop_datum(item) for item in value.items)
    if type_name == "TupleLiteralValue":
        return all(is_ground_loop_datum(item) for item in value.items)
    return False


def finite_unfold_cap_panic(
    *,
    construction: str,
    site: object,
    observed: str,
    limit: int,
) -> NoReturn:
    """Keep decidable over-cap work loud until exact bounded IR exists."""
    from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap

    factory_panic_gap(
        owner="finite_unfold",
        blame=str(site),
        observed=observed,
        requested=f"{construction} within static cap={limit}",
        fix=(
            "construct an exact compact representation that preserves the "
            "finite Python semantics; do not return opaque Complete, force-curry, "
            "truncate, or mint RuntimeEffect authority"
        ),
    )


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

    When the body owns a While whose free names bind to non-ground (dig-opaque
    array / callsite) values, static unfold is refused: one CurriedLoopScope
    coordinates the whole for+while chain instead of per-k Equality reduce.
    """

    target_name: str
    iterable: SugarBody
    body: SugarBody
    carried: tuple[str, ...]
    curried: bool
    unclassified_mutation: bool
    deferred_outputs: tuple[str, ...]
    mutation_inputs: tuple[tuple[str, SugarBody], ...]
    mutation_outputs: tuple[str, ...]
    site: object = dataclass_field(compare=False)

    @staticmethod
    def recognize_target_name(site) -> str | None:
        from sugar_lift_py_tests.recognition.binding_shapes import (
            BindingShapeRecognition,
        )

        return BindingShapeRecognition.for_target_name(site)

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
        append_carried = set(scope.carried_names) & set(
            LoopControlScopeSugar.loop_append_rebind_names(site)
        )
        mutation_inputs = tuple(
            (
                binding.coordinate,
                ctx.build_body(binding.source, SugarRole.TERM),
            )
            for binding in scope.mutation_bindings
            if binding.requires_input
        )
        return cls(
            target_name=target_name,
            iterable=ctx.build_body(site.for_iter(), SugarRole.TERM),
            body=ctx.build_body(site.for_body_block(), SugarRole.STATEMENT),
            carried=scope.carried_names,
            curried=(
                scope.has_loop_control
                or bool(append_carried)
                or bool(scope.mutation_bindings)
            ),
            unclassified_mutation=scope.has_unclassified_mutation,
            deferred_outputs=_finite_loop_output_names(site, target_name),
            mutation_inputs=mutation_inputs,
            mutation_outputs=tuple(
                binding.coordinate for binding in scope.mutation_bindings
            ),
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
            # Finite history is decidable even when the body reads opaque
            # values (#5367). Never replace that finite construction with
            # opaque force-curry; hang avoidance stays a loud typed terminal
            # until an exact compact finite-loop coordinate exists.
            if self._body_has_while() and self._while_reads_non_ground_outer(ctx):
                finite_unfold_cap_panic(
                    construction="ForSugar finite for/while",
                    site=self.site,
                    observed=(
                        f"finite for/while body with "
                        f"iterable cardinality={len(elements)}"
                    ),
                    limit=STATIC_UNFOLD_LIMIT,
                )
            limit = STATIC_UNFOLD_LIMIT
            if self._body_has_branching_statement():
                limit = min(limit, BRANCHED_STATIC_UNFOLD_LIMIT)
            if len(elements) > limit:
                finite_unfold_cap_panic(
                    construction="ForSugar finite iterable",
                    site=self.site,
                    observed=f"iterable cardinality={len(elements)}",
                    limit=limit,
                )
            return self._unfold_values(elements, ctx)
        return self._bind_and_body(iterable, ctx)

    def _body_has_branching_statement(self) -> bool:
        """True when the loop body owns an if/match/if-exp face.

        Used only to choose the static-unfold budget; recognition is unchanged.
        """
        return self._body_owns_sugar_names({"IfSugar", "MatchSugar", "IfExpSugar"})

    def _body_has_while(self) -> bool:
        """True when the loop body owns a While face (empty-orelse or else)."""
        return self._body_owns_sugar_names({"WhileSugar", "WhileElseSugar"})

    def _body_owns_sugar_names(self, names: set[str]) -> bool:
        stack: list[object] = [self.body.sugar]
        seen: set[int] = set()
        while stack:
            sugar = stack.pop()
            sugar_id = id(sugar)
            if sugar_id in seen:
                continue
            seen.add(sugar_id)
            if type(sugar).__name__ in names:
                return True
            walk = getattr(sugar, "walk_children", None)
            if walk is None:
                continue
            for child in walk():
                inner = getattr(child, "sugar", child)
                if inner is not None:
                    stack.append(inner)
        return False

    def _while_reads_non_ground_outer(self, ctx) -> bool:
        """True when a nested While loads an outer name bound to non-ground.

        Walks sugar children only (no AST): NameSugar leaves under WhileSugar /
        WhileElseSugar whose temporal binding is dig-opaque / callsite /
        symbolic force the enclosing for to curry. Names unbound in the outer
        ctx (loop-locals assigned in the for body) are ignored here — the
        free outer carriers (pred, sources) are the hang signal.
        """
        stack: list[object] = [self.body.sugar]
        seen: set[int] = set()
        under_while = False
        while stack:
            item = stack.pop()
            if isinstance(item, tuple):
                sugar, under_while = item
            else:
                sugar = item
            sugar_id = id(sugar)
            if sugar_id in seen:
                continue
            seen.add(sugar_id)
            kind = type(sugar).__name__
            in_while = under_while or kind in {"WhileSugar", "WhileElseSugar"}
            if in_while and kind == "NameSugar":
                value = ctx.temporal.value_if_bound(sugar.name)
                if value is not None and not is_ground_loop_datum(value):
                    return True
            walk = getattr(sugar, "walk_children", None)
            if walk is None:
                continue
            for child in walk():
                inner = getattr(child, "sugar", child)
                if inner is not None:
                    stack.append((inner, in_while))
        return False

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
        return self._bind_mutation_inputs(
            iterable,
            ctx,
            force_curry=force_curry,
        )

    def _bind_mutation_inputs(
        self,
        iterable,
        ctx,
        *,
        force_curry: bool,
        remaining=None,
    ):
        from sugar_lift_py_tests.floor import ScopeRebind

        pending = self.mutation_inputs if remaining is None else remaining
        if not pending:
            return self._bind_and_body_ready(
                iterable,
                ctx,
                force_curry=force_curry,
            )
        (name, source), *tail = pending
        return source.reduce(ctx).and_then(
            lambda value: self._bind_mutation_inputs(
                iterable,
                ScopeRebind(name, value).extend_scope(ctx),
                force_curry=force_curry,
                remaining=tuple(tail),
            )
        )

    def _bind_and_body_ready(
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

            input_names = _unique_names(
                (*self.carried, *(name for name, _ in self.mutation_inputs))
            )
            output_names = (
                self.deferred_outputs
                if force_curry
                else _unique_names((*self.carried, *self.mutation_outputs))
            )
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
        return (
            self.iterable,
            self.body,
            *(source for _, source in self.mutation_inputs),
        )


def _post_loop_bindings(initial_ctx, final_ctx):
    """Project exactly the bindings constructed by a non-empty static unfold."""
    from sugar_lift_py_tests.floor import ScopeRebind

    before = {binding.name: binding.value for binding in initial_ctx.temporal.bindings}
    return tuple(
        ScopeRebind(binding.name, binding.value)
        for binding in final_ctx.temporal.bindings
        if before.get(binding.name) is not binding.value
    )


def _unique_names(names) -> tuple[str, ...]:
    return tuple(dict.fromkeys(names))


def _finite_loop_output_names(site, target_name: str) -> tuple[str, ...]:
    """Names definitely rebound by a nonempty finite loop callable."""
    return (
        target_name,
        *LoopControlScopeSugar.own_scope_stored_names(site.for_body_block()),
    )
