"""A mutating method call on a built-in container, and the receiver it leaves.

``r.append(x)`` on a receiver whose type is decided as ``builtins.list`` (or
``dict``/``set``) has two products: the call's value and the receiver's
contents afterwards. ``BuiltinContainerCallSugar`` evaluates the receiver and
the operands once, in Python's order, and answers both as one pair
``(post-state, result)`` from the cited law (``floor/builtin_container_method``):
a decided exceptional exit is the call's own halt, at the call.

When the operands do not decide the effect, the call is two-faced like every
call with no projected body: it completes under the opaque atom
``python:builtin_method.completes(python:builtin_method(<type>.<name>, site))``
and halts with an ``UndeterminedRaiseEffect`` under the complement. Its
completed pair names an unknown result and an unknown post-state keyed on the
same occurrence -- the receiver's prior contents are never kept.

``ReceiverAfterCallSugar`` is a receiver an opaque call (or a call that may
reach it through an alias) can have changed: an unknown value keyed on that
call's occurrence. The statement evaluates it there, so a later read sees the
one value minted at the call (``sugar/assigned_value.py``).

The statement (``ContainerMutationStatementSugar``) evaluates the pair (and any
havoc) at the statement; the receiver and the call's target read projections
of it, which answer from that one evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import ClassVar

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar, Sugar


def _not_verdict(cls, floor_name, reason):
    from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

    return NotVerdictBearing(
        sugar_name=cls.__name__, floor_name=floor_name, reason=reason
    )


def _opaque_pair(kind, method, site):
    """Two faces for an undecided call: an opaque completion or a raise."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue
    from sugar_lift_py_tests.ir import atomic, ctor, str_const
    from sugar_lift_py_tests.occurrence import occurrence_key
    from sugar_lift_py_tests.outcome.exit_set import (
        Completed,
        ExitSet,
        Halted,
        complement_guard,
    )

    key = occurrence_key(site)
    target = f"{kind}.{method}"
    call = ctor("python:builtin_method", (str_const(target), str_const(key)))
    completes = atomic("python:builtin_method.completes", [call])
    pair = TupleValue(
        (
            SymbolicValue(ctor("python:builtin_method.post_state", (call,))),
            SymbolicValue(ctor("python:builtin_method.result", (call,))),
        )
    )
    return ExitSet(
        (
            Completed(completes, pair),
            Halted(
                complement_guard(completes),
                UndeterminedRaiseEffect(
                    blame=str(site) if site is not None else None,
                    occurrence=key if site is not None else None,
                    producer_node_owner=f"BuiltinMethodCall:{target}",
                ),
                None,
            ),
        )
    ).normalize()


@dataclass(frozen=True)
class BuiltinContainerCallSugar(ConstructedTermSugar):
    """``receiver.<method>(*args)`` on a decided list/dict/set: ``(post, result)``."""

    receiver: Sugar
    method: str
    args: tuple
    kind: str
    site: object = dataclass_field(compare=False)
    # ``d[k] = v`` evaluates ``v`` before the target ``d`` and key ``k``.
    value_first: bool = False
    # One per substituted call: iterations of an unrolled loop share the site.
    evaluation_token: object = dataclass_field(default=None, compare=False)

    @classmethod
    def witnesses(cls):
        return _not_verdict(
            cls,
            "TupleValue",
            "the pair is consumed by the receiver and result projections",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:builtin-container-call",
            (
                self.occurrence_term(owner=owner),
                str_const(f"{self.kind}.{self.method}"),
                self.receiver.to_term(owner=owner),
                *(arg.to_term(owner=owner) for arg in self.args),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        if self.value_first:
            *keys, value = self.args
            return value.desugar(ctx).and_then(
                lambda stored: self.receiver.desugar(ctx).and_then(
                    lambda receiver: self._operands(tuple(keys), (), ctx).and_then(
                        lambda operands: self._apply(receiver, (*operands, stored))
                    )
                )
            )
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self._operands(self.args, (), ctx).and_then(
                lambda operands: self._apply(receiver, operands)
            )
        )

    def _operands(self, pending, done, ctx):
        if not pending:
            return Complete(done)
        return (
            pending[0]
            .desugar(ctx)
            .and_then(lambda value: self._operands(pending[1:], (*done, value), ctx))
        )

    def _apply(self, receiver, operands):
        from sugar_lift_py_tests.floor import builtin_container_method as law

        if law.container_kind(receiver) == self.kind:
            decided = law.apply(self.kind, self.method, receiver, operands, self.site)
            if decided is not None:
                return decided
        return _opaque_pair(self.kind, self.method, self.site)


@dataclass(frozen=True)
class BuiltinContainerProjectionSugar(ConstructedTermSugar):
    """Element ``index`` of the pair: 0 the post-state, 1 the call's value."""

    call: Sugar
    index: int
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return _not_verdict(
            cls, "FloorValue", "projects the one evaluated mutating call"
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, num

        return ctor(
            "python:builtin-container-projection",
            (self.call.to_term(owner=owner), num(self.index)),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.tuple_value import TupleValue

        def project(pair):
            if type(pair) is not TupleValue or len(pair.elements) != 2:
                return Complete(pair)
            return Complete(pair.elements[self.index])

        return self.call.desugar(ctx).and_then(project)


@dataclass(frozen=True)
class ReceiverAfterCallSugar(ConstructedTermSugar):
    """A receiver a call may have changed: unknown after that call."""

    label: str
    site: object = dataclass_field(compare=False)
    evaluation_token: object = dataclass_field(default=None, compare=False)

    @classmethod
    def witnesses(cls):
        return _not_verdict(
            cls, "SymbolicValue", "an unknown post-state names no claim"
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:receiver-after-call",
            (self.occurrence_term(owner=owner), str_const(self.label)),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.occurrence import occurrence_key

        return Complete(
            SymbolicValue(
                ctor(
                    "python:receiver_after_call",
                    (str_const(occurrence_key(self.site)), str_const(self.label)),
                )
            )
        )


@dataclass(frozen=True)
class ContainerMutationStatementSugar(Sugar):
    """Evaluate the statement's call (then any havoc) here, once, in order."""

    evaluated: tuple
    site: object = dataclass_field(compare=False)
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        return _not_verdict(
            cls,
            "BlockValue",
            "the mutation is read through the receiver's post-state",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.sugar.assigned_value import (
            evaluate_assignment_values,
        )

        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

        def record(active, completed):
            # The receiver's post-state is this statement's store testimony,
            # as a subscript store's updated container always was.
            pair = completed[0]
            entries = ()
            if type(pair) is TupleValue and len(pair.elements) == 2:
                entries = (pair.elements[0],)
            return ExitSet.completed(_ReducedBlock(entries, True, (), (), active))

        return evaluate_assignment_values(self.evaluated, ctx, tail=record)
