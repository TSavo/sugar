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

from sugar_lift_py_tests.outcome import ExitSet
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
    return ExitSet.two_faced(
        pair,
        UndeterminedRaiseEffect(
            blame=str(site) if site is not None else None,
            occurrence=key if site is not None else None,
            producer_node_owner=f"BuiltinMethodCall:{target}",
        ),
        guard=completes,
    )


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

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            reduce_operands,
        )

        # The receiver and the arguments are the call's operands: a walrus in
        # one (``xs.append((x := 5))``) binds once, through the one operand
        # door, and the law holds the values they present.  They reduce left
        # to right, each under the state after the ones before it
        # (``reduce_operands``).
        def apply(receiver, *operands):
            return self._apply(receiver, operands, ctx)

        if self.value_first:
            *keys, value = self.args
            # In evaluation order: the stored value first.
            return reduce_operands((value, self.receiver, *keys), ctx).and_then(
                lambda operands: consume_operands(
                    lambda stored, receiver, *operands: self._apply(
                        receiver, (*operands, stored), ctx
                    ),
                    *operands,
                )
            )
        return reduce_operands((self.receiver, *self.args), ctx).and_then(
            lambda operands: consume_operands(apply, *operands)
        )

    def _apply(self, receiver, operands, ctx):
        from sugar_lift_py_tests.floor import builtin_container_method as law

        if law.container_kind(receiver) == self.kind:
            decided = law.apply(
                self.kind, self.method, receiver, operands, self.site, ctx
            )
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

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
        )
        from sugar_lift_py_tests.floor.tuple_value import TupleValue

        def project(pair):
            if type(pair) is not TupleValue or len(pair.elements) != 2:
                return ExitSet.completed(pair)
            return ExitSet.completed(pair.elements[self.index])

        # The pair is this projection's operand: a walrus the call's operands
        # carried rides the projection, never stands in for the pair.
        return self.call.desugar(ctx).and_then(
            lambda pair: consume_operands(project, pair)
        )


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

    def desugar(self, ctx: object = None) -> ExitSet:
        del ctx
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.occurrence import occurrence_key

        return ExitSet.completed(
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
    # The statement's key: the call's pair (``evaluated[0]``) is bound under
    # it, and the receiver's post-state and the call's value read it there
    # (``BuiltinContainerProjection``), never the call evaluated again.
    evaluation: str | None = None
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        return _not_verdict(
            cls,
            "BlockValue",
            "the mutation is read through the receiver's post-state",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.sugar.assigned_value import (
            evaluate_assignment_values,
        )

        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

        def record(active, completed):
            # The receiver's post-state is this statement's store testimony,
            # as a subscript store's updated container always was.
            pair = completed[0]
            entries = ()
            if type(pair) is TupleValue and len(pair.elements) == 2:
                entries = (pair.elements[0],)
            return ExitSet.completed(_ReducedBlock(entries, True, (), (), active))

        return evaluate_assignment_values(
            self.evaluated,
            ctx,
            tail=record,
            evaluations=((self.evaluation, 0),) if self.evaluation else (),
        )


def _unknown_after(site, label):
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.occurrence import occurrence_key

    return SymbolicValue(
        ctor(
            "python:receiver_after_call",
            (str_const(occurrence_key(site)), str_const(label)),
        )
    )


@dataclass(frozen=True)
class PathContainerCallSugar(ConstructedTermSugar):
    """``<path>.<method>(*args)``: ``(receiver after, result)`` of one call.

    The receiver (the object the path evaluates to) is evaluated once. A
    decided list/dict/set receiver takes the cited CPython mutation; any other
    receiver takes the ordinary call (``fallback``), which reads the receiver
    from this one evaluation, and leaves the receiver's contents unknown."""

    receiver: Sugar
    method: str
    args: tuple
    fallback: Sugar
    site: object = dataclass_field(compare=False)
    evaluation_token: object = dataclass_field(default=None, compare=False)

    @classmethod
    def witnesses(cls):
        return _not_verdict(
            cls,
            "TupleValue",
            "the pair is consumed by the path's after-call projections",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:path-container-call",
            (
                self.occurrence_term(owner=owner),
                str_const(self.method),
                self.receiver.to_term(owner=owner),
                *(arg.to_term(owner=owner) for arg in self.args),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.context import ReduceContext
        from sugar_lift_py_tests.floor import builtin_container_method as law
        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.sugar.assigned_value import assigned_key
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            plain_completed_value,
        )

        key = assigned_key(self.receiver)
        unknown = _unknown_after(self.site, "receiver")

        def ordinary(call_ctx):
            return self.fallback.desugar(call_ctx).and_then(
                lambda result: ExitSet.completed(TupleValue((unknown, result)))
            )

        outcome = self.receiver.desugar(ctx)
        if key is None and plain_completed_value(outcome) is None:
            # No occurrence to answer a second read from: the ordinary call
            # is the one evaluation.
            return ordinary(ctx)

        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            reduce_operands,
            written_by,
        )

        def on_receiver(receiver):
            kind = law.container_kind(receiver)
            if kind is not None and self.method in law.MUTATING_METHODS[kind]:
                # The arguments are operands: a walrus in one binds once,
                # through the one operand door.  They reduce left to right
                # after the receiver (``reduce_operands``).
                return reduce_operands(
                    self.args, written_by(receiver, ctx)
                ).and_then(
                    lambda operands: consume_operands(
                        lambda *held: law.apply(
                            kind, self.method, receiver, held, self.site, ctx
                        )
                        or _opaque_pair(kind, self.method, self.site),
                        *operands,
                    )
                )
            if key is None:
                return ordinary(ctx)
            base = ctx if ctx is not None else ReduceContext.root(
                owner="PathContainerCallSugar"
            )
            return ordinary(base.with_assigned_value(key, receiver))

        return outcome.and_then(on_receiver)


def _may_present(value, kind, depth=0) -> bool:
    """Whether a decided read through ``value`` could present a ``kind``
    container's contents: it is one, or a decided container/object holds one.

    An opaque value (a call result, a symbolic value) presents nothing decided
    -- every read through it is itself unknown -- so it cannot show stale
    contents of the object a call changed."""
    from sugar_lift_py_tests.floor import builtin_container_method as law
    from sugar_lift_py_tests.floor.dict_value import DictValue
    from sugar_lift_py_tests.floor.list_value import ListValue
    from sugar_lift_py_tests.floor.object_value import ObjectValue
    from sugar_lift_py_tests.floor.set_value import SetValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    if depth > 32:
        return True
    if law.container_kind(value) == kind:
        return True
    if type(value) in (ListValue, TupleValue, SetValue):
        return any(_may_present(e, kind, depth + 1) for e in value.elements)
    if type(value) is DictValue:
        return any(
            _may_present(k, kind, depth + 1) or _may_present(v, kind, depth + 1)
            for k, v in value.entries
        )
    if type(value) is ObjectValue:
        return any(
            _may_present(field.value, kind, depth + 1)
            for field in (*value.fields, *value.class_fields)
        )
    faces = [
        getattr(value, name)
        for name in ("when_true", "when_false")
        if hasattr(value, name)
    ]
    return any(_may_present(face, kind, depth + 1) for face in faces)


def _floor_key(key):
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.floor.term_value import TermValue

    if type(key) is int:
        return TermValue(key)
    if type(key) is str:
        return StringValue(key)
    return None


def _replace_path(value, steps, post, check_shared):
    """``value`` with the member at ``steps`` replaced by ``post``, or None.

    Every step must be a plain instance field or a decided item, and the
    member there must be the same kind of container ``post`` is. With
    ``check_shared``, no other member along the path may present a decided
    container of that kind (it could be the very object the call changed, and
    would show its old contents)."""
    from dataclasses import replace

    from sugar_lift_py_tests.floor import builtin_container_method as law
    from sugar_lift_py_tests.floor.dict_value import DictValue
    from sugar_lift_py_tests.floor.list_value import ListValue
    from sugar_lift_py_tests.floor.object_field import ObjectField
    from sugar_lift_py_tests.floor.object_value import ObjectValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    (kind, key), rest = steps[0], steps[1:]
    target = law.container_kind(post)

    def descend(child):
        if rest:
            return _replace_path(child, rest, post, check_shared)
        if law.container_kind(child) != law.container_kind(post):
            return None
        return post

    if kind == "attr":
        if type(value) is not ObjectValue or value.deferred_helper_fields:
            return None
        if not value.authenticates_plain_attribute_store(key):
            return None
        positions = [i for i, field in enumerate(value.fields) if field.name == key]
        if not positions:
            return None
        position = positions[-1]
        if check_shared and any(
            _may_present(field.value, target)
            for field in (*value.fields, *value.class_fields)
            if field.name != key
        ):
            return None
        child = descend(value.fields[position].value)
        if child is None:
            return None
        fields = list(value.fields)
        fields[position] = ObjectField(key, child)
        return replace(value, fields=tuple(fields))
    if kind != "item":
        return None
    if type(value) is DictValue:
        floor_key = _floor_key(key)
        if floor_key is None:
            return None
        entries = tuple(value.entries)
        position = law._find_key(entries, floor_key)
        if position is None or position < 0:
            return None
        if check_shared and any(
            _may_present(entry_value, target)
            for index, (_k, entry_value) in enumerate(entries)
            if index != position
        ):
            return None
        child = descend(entries[position][1])
        if child is None:
            return None
        updated = list(entries)
        updated[position] = (entries[position][0], child)
        return DictValue(tuple(updated))
    if type(value) in (ListValue, TupleValue) and type(key) is int:
        elements = tuple(value.elements)
        if not -len(elements) <= key < len(elements):
            return None
        position = key % len(elements)
        if check_shared and any(
            _may_present(element, target)
            for index, element in enumerate(elements)
            if index != position
        ):
            return None
        child = descend(elements[position])
        if child is None:
            return None
        updated = list(elements)
        updated[position] = child
        return type(value)(tuple(updated))
    return None


@dataclass(frozen=True)
class PathAfterCallSugar(ConstructedTermSugar):
    """A path's root (``mode='root'``) or its object (``'inner'``) after a call.

    ``call`` is the read of the call's pair the statement bound under its
    key (``PathAfterCall``, ``ContainerMutationStatementSugar``): a read of
    the root never runs the call again."""

    call: Sugar
    root: Sugar
    steps: tuple
    mode: str
    unshared: bool
    site: object = dataclass_field(compare=False)
    evaluation_token: object = dataclass_field(default=None, compare=False)

    @classmethod
    def witnesses(cls):
        return _not_verdict(
            cls, "FloorValue", "projects the one evaluated path mutation"
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:path-after-call",
            (self.call.to_term(owner=owner), str_const(self.mode)),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            plain_completed_value,
        )

        unknown = ExitSet.completed(_unknown_after(self.site, self.mode))
        pair = plain_completed_value(self.call.desugar(ctx))
        if pair is None:
            return unknown
        # The pair is this read's operand: a walrus the call's operands
        # carried rides the read, never stands in for the pair.
        return consume_operands(lambda pair: self._after(pair, unknown, ctx), pair)

    def _after(self, pair, unknown, ctx) -> ExitSet:
        from sugar_lift_py_tests.floor import builtin_container_method as law
        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            plain_completed_value,
        )

        if type(pair) is not TupleValue or len(pair.elements) != 2:
            return unknown
        post = pair.elements[0]
        if law.container_kind(post) is None:
            return unknown
        if not self.steps:
            # No path (``bound_receiver_mutation_statement``): the root is
            # the object the call changed, and its post-state is the object.
            return ExitSet.completed(post)
        rooted = plain_completed_value(self.root.desugar(ctx))
        if rooted is None:
            return unknown
        check_shared = self.mode == "root" and not self.unshared
        updated = _replace_path(rooted, tuple(self.steps), post, check_shared)
        if updated is None:
            return unknown
        return ExitSet.completed(post if self.mode == "inner" else updated)


@dataclass(frozen=True)
class SourceCallActualAfterSugar(ConstructedTermSugar):
    """An actual after a source helper's cited stores: their one total value.

    The state re-reads the actual and the helper's cited mutations of it. It
    is kept only when it evaluates to one plain completed value; anything
    that could halt, or that the law left undecided, is an unknown minted at
    the call -- never the pre-call contents and never a second halt."""

    state: Sugar
    label: str
    site: object = dataclass_field(compare=False)
    evaluation_token: object = dataclass_field(default=None, compare=False)

    @classmethod
    def witnesses(cls):
        return _not_verdict(
            cls, "FloorValue", "the actual's post-state names no claim of its own"
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:source-call-actual-after",
            (
                self.occurrence_term(owner=owner),
                str_const(self.label),
                self.state.to_term(owner=owner),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.floor.floor_value import FloorValue
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            plain_completed_value,
        )

        outcome = self.state.desugar(ctx)
        value = plain_completed_value(outcome)
        if (
            value is not None
            and value.follow_rest().continues
            and isinstance(value, FloorValue)
        ):
            return outcome
        return ExitSet.completed(_unknown_after(self.site, self.label))
