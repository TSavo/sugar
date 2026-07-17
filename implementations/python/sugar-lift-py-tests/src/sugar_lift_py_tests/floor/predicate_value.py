from __future__ import annotations

from dataclasses import field as dataclass_field, dataclass

from sugar_lift_py_tests.ir import Formula

from .floor_value import FloorValue


@dataclass(frozen=True)
class PredicateValue(FloorValue):
    """A boolean formula carried as a floor value.

    Atomic formulas project to a same-name constructor term. Connectives
    project recursively to the established ``py.<kind>`` constructor family.
    Quantifiers stay loud because the term algebra has no binder-bearing term
    shape, so projecting one would lose its bound variable or invent a parallel
    vocabulary.
    """

    formula: Formula
    site: object = dataclass_field(default=None, compare=False)
    # CallSiteValues that stood as operands when this formula was emitted --
    # carried so callEdges project from the collapse without a side channel.
    operand_callsites: tuple = dataclass_field(default=(), compare=False)
    derived_formulas: tuple = dataclass_field(default=(), compare=False)
    rewrite_chains: tuple[tuple[str, str, int], ...] = dataclass_field(
        default=(), compare=False
    )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import _Atomic, _Connective, ctor

        if isinstance(self.formula, _Atomic):
            return ctor(self.formula.name, list(self.formula.args))
        if isinstance(self.formula, _Connective):
            return ctor(
                f"py.{self.formula.kind}",
                [
                    PredicateValue(operand, self.site).to_term(owner=owner)
                    for operand in self.formula.operands
                ],
            )
        return super().to_term(owner=owner)

    def negate(self):
        # A predicate flips by wrapping its formula in not_ -- the formula owns
        # the polarity, the carrier stays PredicateValue; operand callsites ride.
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            PredicateValue(not_(self.formula), self.site, self.operand_callsites)
        )

    def truth(self, site):
        """An already-boolean predicate stands as its existing formula."""
        del site
        from sugar_lift_py_tests.outcome import Complete

        return Complete(self)

    def subscript(self, index, site):
        """Keep unknown scalar-versus-array predicate results visibly red.

        ``PredicateValue`` carries a formula, not enough Python type/shape
        evidence to decide whether indexing yields an element or raises.  The
        runtime effect is authenticated by the receiver formula and source
        site, so presence cannot masquerade as a verified result.
        """
        from sugar_lift_py_tests.effect import (
            SubscriptResultRuntimeEffect,
            runtime_effect_evidence,
        )
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            SubscriptResultRuntimeEffect(
                "predicate subscript runtime boundary: PredicateValue runtime "
                "result shape may be a scalar boolean or an indexable array; "
                "keep as typed red until the producing operation carries "
                f"container shape evidence. site={site}",
                **runtime_effect_evidence("py.subscript", self, site),
            )
        )

    def bitwise_or(self, other, site):
        if type(other) is not PredicateValue:
            return super().bitwise_or(other, site)
        del site
        from sugar_lift_py_tests.ir import or_
        from sugar_lift_py_tests.outcome import Complete

        return Complete(PredicateValue(or_([self.formula, other.formula])))

    def stated(self, site):
        # A symbolic predicate states an inv: the fact the record emits. Operand
        # callsites ride into the InvValue so edges project later.
        from sugar_lift_py_tests.floor.inv_value import InvValue
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            InvValue(
                self.formula,
                site,
                self.operand_callsites,
                self.derived_formulas,
                self.rewrite_chains,
            )
        )

    def binary_conditional(self, then, else_body, ctx=None, site=None):
        # A symbolic condition cannot pick a face, so it GUARDS: both faces
        # reduce, each entry rides under its polarity. Each face's own exits
        # (post_contribution before merge) decide what the continuation rides.
        del site
        from sugar_lift_py_tests.floor.guarded_faces import GuardedFaces
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome import Complete, complete_value

        then_ctx = ctx
        if ctx is not None:
            then_ctx = ctx.with_temporal(ctx.temporal.activate_guard(self.formula))
        then_record, then_scope = then.sugar.reduce_with_scope(then_ctx)
        then_own = then_record.contribution()
        then_effect = _conditional_effect(then_own, self.formula)
        if then_effect is not None:
            return then_effect
        then_exits = not then_record.can_fall_through
        then_entries = tuple(entry.guarded(self.formula) for entry in then_own)
        else_entries = ()
        else_exits = False
        else_record = None
        joined_bindings = ()
        guarded_bindings = ()
        joined_effects = ()
        if else_body is not None:
            else_guard = not_(self.formula)
            else_ctx = ctx
            if ctx is not None:
                else_ctx = ctx.with_temporal(ctx.temporal.activate_guard(else_guard))
            else_record, else_scope = else_body.sugar.reduce_with_scope(else_ctx)
            else_own = else_record.contribution()
            else_effect = _conditional_effect(else_own, not_(self.formula))
            if else_effect is not None:
                return else_effect
            else_exits = not else_record.can_fall_through
            else_entries = tuple(
                entry.guarded(not_(self.formula)) for entry in else_own
            )
            if not then_exits and not else_exits:
                joined_bindings, joined_effects = self._joined_bindings(
                    then_scope, else_scope, ctx
                )
            elif then_exits != else_exits:
                surviving_scope = else_scope if then_exits else then_scope
                joined_bindings, joined_effects = self._surviving_bindings(
                    surviving_scope, ctx
                )
        elif not then_exits and then_ctx is not None:
            guarded_bindings, joined_effects = self._guarded_bindings(
                self.formula, then_scope, then_ctx
            )
        can_fall_through, continuation_guard = _conditional_continuation(
            self.formula,
            then_record,
            else_record,
        )
        return Complete(
            GuardedFaces(
                guard=self.formula,
                entries=(*then_entries, *else_entries, *joined_effects),
                then_exits=then_exits,
                else_exits=else_exits,
                joined_bindings=joined_bindings,
                guarded_bindings=guarded_bindings,
                can_fall_through=can_fall_through,
                continuation_guard=continuation_guard,
            )
        )

    def _guarded_bindings(self, guard, branch_scope, before_scope):
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        before = {
            binding.name: binding.value for binding in before_scope.temporal.bindings
        }
        after = {
            binding.name: binding.value for binding in branch_scope.temporal.bindings
        }
        bindings = []
        effects = []
        for name, binding in sorted(after.items()):
            if before.get(name) is binding:
                continue
            answer = binding.answer(branch_scope)
            if isinstance(answer, Incomplete):
                effects.append(answer.guarded(guard))
                continue
            assert isinstance(answer, Complete)
            bindings.append((guard, name, answer.value))
        return tuple(bindings), tuple(effects)

    def _joined_bindings(self, then_scope, else_scope, ctx):
        from sugar_lift_py_tests.floor.guarded_value import GuardedValue
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        before = {binding.name: binding.value for binding in ctx.temporal.bindings}
        then_bindings = {
            binding.name: binding.value for binding in then_scope.temporal.bindings
        }
        else_bindings = {
            binding.name: binding.value for binding in else_scope.temporal.bindings
        }
        joined = []
        effects = []
        for name in sorted(then_bindings.keys() & else_bindings.keys()):
            then_binding = then_bindings[name]
            else_binding = else_bindings[name]
            if before.get(name) is then_binding and before.get(name) is else_binding:
                continue
            then_answer = then_binding.answer(then_scope)
            else_answer = else_binding.answer(else_scope)
            if isinstance(then_answer, Incomplete):
                effects.append(then_answer.guarded(self.formula))
            if isinstance(else_answer, Incomplete):
                effects.append(else_answer.guarded(not_(self.formula)))
            if isinstance(then_answer, Incomplete) or isinstance(
                else_answer, Incomplete
            ):
                joined.append(
                    (
                        name,
                        GuardedValue(
                            self.formula,
                            then_binding,
                            else_binding,
                        ),
                    )
                )
                continue
            assert isinstance(then_answer, Complete)
            assert isinstance(else_answer, Complete)
            joined.append(
                (
                    name,
                    GuardedValue(
                        self.formula,
                        then_answer.value,
                        else_answer.value,
                    ),
                )
            )
        return tuple(joined), tuple(effects)

    def _surviving_bindings(self, surviving_scope, ctx):
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        before = {binding.name: binding.value for binding in ctx.temporal.bindings}
        surviving = {
            binding.name: binding.value for binding in surviving_scope.temporal.bindings
        }
        bindings = []
        effects = []
        for name, binding in sorted(surviving.items()):
            if before.get(name) is binding:
                continue
            answer = binding.answer(surviving_scope)
            if isinstance(answer, Incomplete):
                effects.append(answer)
                continue
            assert isinstance(answer, Complete)
            bindings.append((name, answer.value))
        return tuple(bindings), tuple(effects)


def _conditional_continuation(formula, then_record, else_record):
    """Construct the guard under which reduced branch outcomes can continue."""
    from sugar_lift_py_tests.ir import and_, not_, or_

    then_can = then_record.can_fall_through
    else_can = else_record is None or else_record.can_fall_through
    if not then_can and not else_can:
        return False, None

    then_nested = then_record.fall_through
    else_nested = () if else_record is None else else_record.fall_through
    if then_can and else_can and not then_nested and not else_nested:
        return True, None

    paths = []
    if then_can:
        paths.append(formula if not then_nested else and_([formula, *then_nested]))
    if else_can:
        else_guard = not_(formula)
        paths.append(
            else_guard if not else_nested else and_([else_guard, *else_nested])
        )
    return True, paths[0] if len(paths) == 1 else or_(paths)


def _conditional_effect(entries: tuple, formula):
    """Propagate a branch-local named effect as the conditional's outcome."""
    from dataclasses import replace

    from sugar_lift_py_tests.outcome import Incomplete

    for entry in entries:
        if isinstance(entry, Incomplete):
            effect = replace(
                entry.effect,
                reason=(
                    f"{entry.reason}; effect occurs under branch condition "
                    f"{formula!r}"
                ),
            )
            return Incomplete(effect)
    return None
