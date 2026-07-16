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

        then_record, then_scope = then.sugar.reduce_with_scope(ctx)
        then_own = then_record.contribution()
        then_effect = _conditional_effect(then_own, self.formula)
        if then_effect is not None:
            return then_effect
        then_exits = any(entry.post_contribution() for entry in then_own)
        then_entries = tuple(entry.guarded(self.formula) for entry in then_own)
        else_entries = ()
        else_exits = False
        joined_bindings = ()
        joined_effects = ()
        if else_body is not None:
            else_record, else_scope = else_body.sugar.reduce_with_scope(ctx)
            else_own = else_record.contribution()
            else_effect = _conditional_effect(else_own, not_(self.formula))
            if else_effect is not None:
                return else_effect
            else_exits = any(entry.post_contribution() for entry in else_own)
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
        return Complete(
            GuardedFaces(
                guard=self.formula,
                entries=(*then_entries, *else_entries, *joined_effects),
                then_exits=then_exits,
                else_exits=else_exits,
                joined_bindings=joined_bindings,
            )
        )

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
