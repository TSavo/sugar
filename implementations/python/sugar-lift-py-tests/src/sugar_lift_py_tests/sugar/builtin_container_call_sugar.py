"""A mutating operation on an object, and the object it leaves.

``r.append(x)``, ``r[k] = v``, ``del r[k]``, ``r += x`` have two products: the
operation's value and the receiver's contents afterwards.
``PathContainerCallSugar`` (the one door, ``container_mutation.
name_mutation_statement``) evaluates the receiver and the operands once, in
Python's order, and answers both as one pair ``(post-state, result)``.  The
VALUE the receiver holds decides: a ``ListValue``/``DictValue``/``SetValue``
takes the cited law (``floor/builtin_container_method``), a decided
exceptional exit being the operation's own halt, at it; any other value takes
the ordinary operation, and its contents afterwards are unknown (an immutable
value is unchanged).

When the operands do not decide a cited mutation, the call is two-faced like
every call with no projected body: it completes under the opaque atom
``python:builtin_method.completes(python:builtin_method(<type>.<name>, site))``
and halts with an ``UndeterminedRaiseEffect`` under the complement. Its
completed pair names an unknown result and an unknown post-state keyed on the
same occurrence -- the receiver's prior contents are never kept.

``ReceiverAfterCallSugar`` is a value a call may have changed: an unknown
keyed on that call's occurrence, unless the value the call met decides that
it did not (``_may_change``).

The statement (``ContainerMutationStatementSugar``) evaluates the pair (and the
values after it) at the statement; the receiver and the call's target read
projections of it, which answer from that one evaluation.
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
    """Two faces for an undecided call: an opaque completion or a raise.

    An in-place operator (``__iadd__``...) of a builtin container returns
    the container: its result is its post-state."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue
    from sugar_lift_py_tests.ir import atomic, ctor, str_const
    from sugar_lift_py_tests.occurrence import occurrence_key

    key = occurrence_key(site)
    target = f"{kind}.{method}"
    call = ctor("python:builtin_method", (str_const(target), str_const(key)))
    completes = atomic("python:builtin_method.completes", [call])
    post = SymbolicValue(ctor("python:builtin_method.post_state", (call,)))
    result = (
        post
        if _in_place(method)
        else SymbolicValue(ctor("python:builtin_method.result", (call,)))
    )
    return ExitSet.two_faced(
        TupleValue((post, result)),
        UndeterminedRaiseEffect(
            blame=str(site),
            occurrence=key,
            producer_node_owner=f"BuiltinMethodCall:{target}",
            site=site,
        ),
        guard=completes,
        site=site,
    )


def _in_place(method) -> bool:
    """``__iadd__``, ``__ior__``...: an augmented assignment's operator."""
    return (
        isinstance(method, str)
        and method.startswith("__i")
        and method.endswith("__")
        and method not in ("__init__", "__iter__", "__index__")
    )


def _immutable(value, depth=0) -> bool:
    """A value of an immutable builtin type all the way down: no call can
    change it, and a name bound to it keeps it.  A builtin function or a
    builtin class (``len``, ``object``, ``ValueError``) is one: CPython
    refuses to set an attribute on it, so ``object.__setattr__(self, k, v)``
    or ``BaseException.__init__(self, m)`` leaves ``object`` and
    ``BaseException`` as they were."""
    from sugar_lift_py_tests.floor.builtin_exception_class_value import (
        BuiltinExceptionClassValue,
    )
    from sugar_lift_py_tests.floor.builtin_object_class_value import (
        BuiltinObjectClassValue,
    )
    from sugar_lift_py_tests.floor.builtin_semantic_callable import (
        BuiltinSemanticCallable,
    )
    from sugar_lift_py_tests.floor.bytes_value import BytesValue
    from sugar_lift_py_tests.floor.none_value import NoneValue
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    if depth > 32:
        return False
    if isinstance(
        value,
        (BuiltinSemanticCallable, BuiltinObjectClassValue, BuiltinExceptionClassValue),
    ):
        return True
    if type(value) in (
        TermValue,
        StringValue,
        BytesValue,
        NoneValue,
        TrueBoolLiteralSugar,
        FalseBoolLiteralSugar,
    ):
        return getattr(value, "formal_coordinate", None) is None
    if type(value) is TupleValue:
        return all(_immutable(element, depth + 1) for element in value.elements)
    return False


def _may_change(value, method, pure, sharer, held=None) -> bool:
    """Whether a call may have changed ``value``, the value it met.

    ``method`` names the receiver's method when the value is the receiver
    (empty for an operand); ``pure``: the call is a cited pure builtin;
    ``sharer``: the value is one the receiver holds or shares, which only an
    ordinary call (a receiver the container law does not cite) can reach.

    An object of a source class (``ObjectValue``) is changed by whatever
    code reaches it -- a method of its own, or an opaque call it is handed --
    as a parameter's or a display's object is: it may have changed.

    The one field store (``container_mutation.field_store_method``:
    ``value`` is its receiver) is ``type(receiver).__setattr__``, which the
    receiver's class decides (``ObjectValue.field_store_route``).  The store
    changes the object itself, and whatever holds it.  It reaches what the
    receiver shares, and what the caller holds beyond it, only when it runs
    code: an instance whose class takes ``object``'s ``__setattr__`` and
    binds no data descriptor for the name runs none; one whose class binds a
    ``__setattr__`` or a descriptor's ``__set__``, or whose lookup does not
    decide, does or may; a builtin container's or an immutable value's own
    floor answers the store and runs none; any other receiver (a formal with
    no actual, an undecided value) may run any.  An operand the store hands
    that code (its rule's ``operand``; ``held`` its own value) may have
    changed when the store runs code and the operand is one a call it is
    handed to changes."""
    from sugar_lift_py_tests.floor import builtin_container_method as law
    from sugar_lift_py_tests.floor.object_value import ObjectValue
    from sugar_lift_py_tests.source_call_resolution import builtin_typed_value
    from sugar_source_tree.container_mutation import (
        field_store_method,
        field_store_rule,
    )

    if _immutable(value):
        return False
    store = field_store_rule(method)
    if store is not None:
        attr, operand = store
        if operand:
            return _may_change(value, field_store_method(attr), False, True) and (
                held is None or _may_change(held, "", False, False)
            )
        if isinstance(value, ObjectValue):
            return not sharer or value.field_store_runs_code(attr)
    kind = law.container_kind(value)
    if sharer:
        return kind is None
    if isinstance(value, ObjectValue):
        return True
    if kind is None:
        # A value no floor decides is a builtin container: a method called on
        # it may change it, whatever the method is spelled -- a source
        # ``o.set(3)`` as much as ``o.append(3)`` (#7757).  The container
        # law's method names are read only on a value it decides (below).
        # An operand the source does not type keeps its value, as it always
        # has.
        return bool(method)
    if method and method not in law.MUTATING_METHODS[kind] and not _in_place(method):
        return False
    if pure and builtin_typed_value(value):
        return False
    return True


@dataclass(frozen=True)
class BuiltinContainerProjectionSugar(ConstructedTermSugar):
    """Element ``index`` of the pair: 0 the post-state, 1 the call's value.

    ``binds``: a call on ``self`` evaluated in place
    (``nodes._call_on_self_in_place``): the pair is bound under that key as
    the call completes, as a walrus binds its value
    (``NamedExpressionValue``, riding the value through every operand door
    to the statement), and the receiver after the call reads it there
    (``PathAfterCall``)."""

    call: Sugar
    index: int
    site: object = dataclass_field(compare=False)
    binds: str | None = None

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
            NamedExpressionValue,
            consume_operands,
        )
        from sugar_lift_py_tests.floor.tuple_value import TupleValue

        def project(pair):
            if type(pair) is not TupleValue or len(pair.elements) != 2:
                return ExitSet.completed(pair)
            value = pair.elements[self.index]
            if self.binds is None:
                return ExitSet.completed(value)
            return ExitSet.completed(
                NamedExpressionValue.carrying(
                    self.binds, pair, value, evaluation=self.binds
                )
            )

        # The pair is this projection's operand: a walrus the call's operands
        # carried rides the projection, never stands in for the pair.
        return self.call.desugar(ctx).and_then(
            lambda pair: consume_operands(project, pair)
        )


@dataclass(frozen=True)
class ReceiverAfterCallSugar(ConstructedTermSugar):
    """A value a call may have changed, read after that call.

    With no ``rules`` it is unknown after the call.  With ``rules`` --
    ``(method, pure, sharer, subject)``, ``subject`` an index into
    ``subjects`` or -1 for ``prior`` itself -- the value decides: ``prior``
    (the name's read before the call) is kept when it is immutable, or when
    no rule's object has a value the call may have changed
    (``_may_change``); otherwise it is unknown, never the pre-call
    contents."""

    label: str
    site: object = dataclass_field(compare=False)
    prior: object = None
    subjects: tuple = ()
    rules: tuple = ()

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
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            plain_completed_value,
        )
        from sugar_lift_py_tests.sugar.receiver_field_store_sugar import (
            floored_receiver,
        )
        from sugar_source_tree.container_mutation import field_store_rule

        unknown = ExitSet.completed(_unknown_after(self.site, self.label))
        if self.prior is None or not self.rules:
            return unknown
        held = self.prior.desugar(ctx)
        value = plain_completed_value(held)
        if value is None:
            return unknown
        if _immutable(value):
            return held
        met = {}
        for method, pure, sharer, subject in self.rules:
            if subject not in met:
                if subject < 0:
                    met[subject] = value
                else:
                    met[subject] = plain_completed_value(
                        self.subjects[subject].desugar(ctx)
                    )
            met_value = met[subject]
            if met_value is not None and field_store_rule(method) is not None:
                # The one field store decides by its receiver as the store
                # read it: an object read through its constructor call's key
                # is that call's floor (``floored_receiver``).
                met_value = floored_receiver(met_value, ctx)
            if met_value is None or _may_change(
                met_value, method, pure, sharer, held=value
            ):
                return unknown
        return held


@dataclass(frozen=True)
class ContainerMutationStatementSugar(Sugar):
    """Evaluate the statement's call (then any havoc) here, once, in order."""

    evaluated: tuple
    site: object = dataclass_field(compare=False)
    # The statement's key: the call's pair (``evaluated[0]``) is bound under
    # it, and the receiver's post-state and the call's value read it there
    # (``PathAfterCall``, ``BuiltinContainerProjection``), never the call
    # evaluated again.
    evaluation: str | None = None
    # ``(key, index)`` per name the statement writes: ``evaluated[index]``
    # bound under ``key`` -- ``r += x``'s in-place result, the one every
    # later read of ``r`` reads, first, then every other name's state after
    # the call, bare statement or assigned (``ContainerMutationStatement.
    # written_keys``), which a live loop carries to its next item.
    result_evaluations: tuple = ()
    # ``d.setdefault(k, v).append(x)``: ``(key, index)`` for each later
    # call's pair ``evaluated[index]``, bound under ``key`` as it completes.
    pair_evaluations: tuple = ()
    # One call in statement position (``r.m(x)`` alone): when the receiver's
    # value took the ordinary call, the call's value is recorded as a bare
    # call's is (``record_statement_value``) -- an ``__init__`` call's stores
    # reach the constructing receiver, a ``warnings.warn`` is its testimony,
    # the call stays visible to the effect router.
    records_value: bool = False
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
            # as a subscript store's updated container always was; an
            # immutable receiver (``n += 1``) was not changed and testifies
            # nothing.
            from sugar_lift_py_tests.floor import builtin_container_method as law
            from sugar_lift_py_tests.sugar.expr_statement_sugar import (
                record_statement_value,
            )

            pair = completed[0]
            is_pair = type(pair) is TupleValue and len(pair.elements) == 2
            entries = ()
            if is_pair and not _immutable(pair.elements[0]):
                entries = (pair.elements[0],)
            if (
                not self.records_value
                or not is_pair
                or law.container_kind(pair.elements[0]) is not None
            ):
                # A container's own method (cited or not) is no call whose
                # value a statement records.
                return ExitSet.completed(_ReducedBlock(entries, True, (), (), active))
            return record_statement_value(pair.elements[1], active).and_then(
                lambda recorded: ExitSet.completed(
                    _ReducedBlock(
                        (*entries, *recorded.statements), True, (), (), active
                    )
                )
            )

        # Each call's pair is read by the values after it -- the receiver's
        # post-state, every holder's, a later call on the call's value
        # (``PathAfterCall``, ``BuiltinContainerProjection``) -- so it is
        # bound under its key as soon as it completes (``as_completed``).
        # ``r += x``'s in-place result is the write of ``r``, a target, and
        # every other name's state after the call is that name's write: each
        # bound once every value has completed.
        pairs = ((self.evaluation, 0),) if self.evaluation else ()
        pairs = (*pairs, *self.pair_evaluations)
        return evaluate_assignment_values(
            self.evaluated,
            ctx,
            tail=record,
            evaluations=tuple(self.result_evaluations),
            as_completed=pairs,
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
    """One mutating operation: ``(receiver after, result)``.

    ``r.append(x)``, ``r[k] = v`` (``__setitem__``), ``del r[k]``
    (``__delitem__``), ``r += x`` (``__iadd__``...), ``r[k] += x``
    (``__setitem__`` with an operator: the store of the item's in-place
    result, ``_read_modify_store``), on a name or through a path.  The
    receiver is evaluated once.  A ``ListValue``/``DictValue``/
    ``SetValue`` receiver takes the cited CPython mutation; any other
    receiver, or a method the container law does not cite as a mutation,
    takes the ordinary operation -- the call (``fallback``), which reads the
    receiver from this one evaluation, the floor's item store or delete, the
    in-place operator (``operator``) -- and its contents afterwards are
    unknown unless its value says the call left it alone (``_may_change``:
    an immutable receiver, a container under a method that does not mutate
    it).  Every method call on a name a call can reach takes this door,
    whatever the method is spelled."""

    receiver: Sugar
    method: str
    args: tuple
    fallback: object
    site: object = dataclass_field(compare=False)
    # The key the ordinary call (``fallback``) reads its receiver through
    # (``container_mutation._container_call``): ``_call`` binds the receiver
    # it evaluated there, once, before the call.  None for a call whose
    # fallback reads no receiver of this operation (``super().m(...)``, an
    # item store, delete or in-place operator).
    receiver_evaluation: str | None = None
    # Names the unknown the receiver is after an ordinary call.
    label: str = "receiver"
    # ``d[k] = v`` evaluates ``v`` before the target ``d`` and key ``k``.
    value_first: bool = False
    # ``r OP= x``: the operator (``project_inplace``) and its source token.
    operator: object = dataclass_field(default=None, compare=False)
    operator_site: object = dataclass_field(default=None, compare=False)
    # ``super().m(...)``: the frame's receiver formal, whose object the
    # call runs on -- ``receiver`` is its read here, and the call's
    # zero-argument ``super()`` reads the formal
    # (``nodes._call_on_self_in_place``).
    frame_receiver: str | None = dataclass_field(default=None, compare=False)

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
        if self.fallback is None:
            return self._operate(ctx)
        return self._call(ctx)

    def _operate(self, ctx) -> ExitSet:
        """An item store, an item delete or an in-place operator: every
        operand is reduced once, in Python's order, then the receiver's
        value decides."""
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            reduce_operands,
        )

        # The receiver and the operands are the operation's operands: a
        # walrus in one binds once, through the one operand door.  They
        # reduce left to right, each under the state after the ones before
        # it (``reduce_operands``).
        if self.operator is not None and self.method == "__setitem__":
            return self._read_modify_store(ctx)
        if self.value_first and self.args:
            *keys, value = self.args
            # In evaluation order: the stored value first.
            return reduce_operands((value, self.receiver, *keys), ctx).and_then(
                lambda operands: consume_operands(
                    lambda stored, receiver, *held: self._apply(
                        receiver, (*held, stored), ctx
                    ),
                    *operands,
                )
            )
        return reduce_operands((self.receiver, *self.args), ctx).and_then(
            lambda operands: consume_operands(
                lambda receiver, *held: self._apply(receiver, held, ctx),
                *operands,
            )
        )

    def _read_modify_store(self, ctx) -> ExitSet:
        """``t[k] OP= v`` (``__setitem__`` with an operator, ``args`` the key
        and ``v``): the receiver and the key, the item read (the one
        subscript door, ``discharge_subscript``), ``v``, the in-place
        operator on the item (``project_augmented``), then the store of its
        result on the receiver (``_apply``) -- each once, in Python's order.
        A halt at any step leaves before the store."""
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            reduce_operands,
            written_by,
        )
        from sugar_lift_py_tests.operations.subscript_operation import (
            discharge_subscript,
        )
        from sugar_lift_py_tests.sugar.augassign_sugar import project_augmented

        key_sugar, right_sugar = self.args
        op_site = self.operator_site if self.operator_site is not None else self.site

        def store(receiver, key, after):
            return discharge_subscript(
                receiver, key, self.site, after, owner=type(self).__name__
            ).and_then(
                lambda current: right_sugar.desugar(after).and_then(
                    lambda right: consume_operands(
                        lambda operand: project_augmented(
                            current,
                            operand,
                            operator=type(self.operator).inplace_operator,
                            projector=self.operator.project_inplace,
                            site=op_site,
                            ctx=ctx,
                        ).and_then(
                            lambda result: self._apply(receiver, (key, result), ctx)
                        ),
                        right,
                    )
                )
            )

        return reduce_operands((self.receiver, key_sugar), ctx).and_then(
            lambda operands: consume_operands(
                lambda receiver, key: store(
                    receiver,
                    key,
                    written_by(operands[1], written_by(operands[0], ctx)),
                ),
                *operands,
            )
        )

    def _apply(self, receiver, operands, ctx) -> ExitSet:
        from sugar_lift_py_tests.floor import builtin_container_method as law

        # Every operand of the store, delete or in-place operator is projected
        # to its value before the operation, through the one projection every
        # store operand takes (``project_operation_receiver``, as
        # ``SubscriptStoreEffectSugar.project_setitem`` does): ``a[f()] = 9``
        # stores at what ``f`` returns, never at the unapplied call.
        operands = tuple(
            operand.project_operation_receiver(
                ctx, owner=f"{type(self).__name__} operand"
            )
            for operand in operands
        )
        kind = law.container_kind(receiver)
        if kind is not None and self.method in law.MUTATING_METHODS[kind]:
            decided = law.apply(kind, self.method, receiver, operands, self.site, ctx)
            if decided is not None:
                return decided
            return _opaque_pair(kind, self.method, self.site)
        return self._ordinary(receiver, operands, ctx)

    def _ordinary(self, receiver, operands, ctx) -> ExitSet:
        """The operation on a value the container law does not cite: the
        floor's own item store or delete, or the in-place operator."""
        from sugar_lift_py_tests.floor import builtin_container_method as law
        from sugar_lift_py_tests.floor.tuple_value import TupleValue

        if self.method == "__setitem__" and len(operands) == 2:
            from sugar_lift_py_tests.sugar.store_effect_sugar import (
                SubscriptStoreEffectSugar,
            )

            key, value = operands
            # The floor's store answers the receiver after it.
            return SubscriptStoreEffectSugar.project_setitem(
                receiver, key, value, self.site, ctx
            ).and_then(lambda post: ExitSet.completed(TupleValue((post, law._none()))))
        if self.method == "__delitem__" and len(operands) == 1:
            from sugar_lift_py_tests.sugar.delete_effect_sugar import (
                SubscriptDeleteEffectSugar,
            )

            (key,) = operands
            return SubscriptDeleteEffectSugar.project_delitem(
                receiver, key, self.site, ctx
            ).and_then(lambda post: ExitSet.completed(TupleValue((post, law._none()))))
        if _in_place(self.method) and self.operator is not None and len(operands) == 1:
            from sugar_lift_py_tests.sugar.augassign_sugar import project_augmented

            (operand,) = operands
            post = self._after(receiver)
            return project_augmented(
                receiver,
                operand,
                operator=type(self.operator).inplace_operator,
                projector=self.operator.project_inplace,
                site=self.operator_site if self.operator_site is not None else self.site,
                ctx=ctx,
            ).and_then(lambda result: ExitSet.completed(TupleValue((post, result))))
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            owner="PathContainerCallSugar._ordinary",
            blame=self.site,
            observed=f"{self.method} with {len(operands)} operand(s) and no call",
            requested="an item store, an item delete or an in-place operator",
            fix="construct the operation through name_mutation_statement",
        )

    def _after(self, receiver):
        """The receiver after an ordinary operation: an immutable value is
        unchanged; anything else is unknown, minted at the operation."""
        if _immutable(receiver):
            return receiver
        return _unknown_after(self.site, self.label)

    def _call(self, ctx) -> ExitSet:
        from sugar_lift_py_tests.context import ReduceContext
        from sugar_lift_py_tests.floor import builtin_container_method as law
        from sugar_lift_py_tests.floor.call_site_value import receiver_after_its_call
        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            plain_completed_value,
        )

        unknown = _unknown_after(self.site, self.label)
        base = ctx if ctx is not None else ReduceContext.root(
            owner="PathContainerCallSugar"
        )

        def ordinary(call_ctx, post=unknown, receiver=None, presented=None):
            # The receiver after an ordinary call the value says may change
            # it: unknown, unless the call states what it did to it -- a
            # followed source body whose effects on it are the field stores
            # it carries, a builtin's own transition of it
            # (``receiver_after_its_call``, the one projection of a callee's
            # effects on what its caller sees).
            def after(result):
                if receiver is None or post is receiver:
                    return post
                stated = receiver_after_its_call(receiver, result)
                return post if stated is None else stated

            def value(result):
                return result if presented is None else presented(result)

            return self.fallback.desugar(call_ctx).and_then(
                lambda result: ExitSet.completed(
                    TupleValue((after(result), value(result)))
                )
            )

        outcome = self.receiver.desugar(ctx)
        if (
            self.receiver_evaluation is None
            and self.frame_receiver is None
            and plain_completed_value(outcome) is None
        ):
            # No key the ordinary call reads its receiver through: the
            # ordinary call, which reads its own receiver, is the one
            # evaluation.
            return ordinary(ctx)

        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            reduce_operands,
        )

        def on_receiver(receiver):
            if self.frame_receiver is not None:
                # ``super().m(...)``: a call on the frame's receiver whatever
                # its value, never a container's own method.  Its
                # zero-argument ``super()`` binds the frame's receiver
                # formal, which holds the object as this statement read it
                # (``receiver``), never as the frame first bound it.  The
                # call's value is its Python value: a builtin base's own
                # transition of the receiver presents its result
                # (``_super_call_value``), which ``x = super().m()`` and a
                # ``return`` of it read.
                call_ctx = base.with_temporal(
                    base.temporal.bind_value(self.frame_receiver, receiver)
                )
                return ordinary(
                    call_ctx, self._after(receiver), receiver, _super_call_value
                )
            kind = law.container_kind(receiver)
            if kind is not None and self.method in law.MUTATING_METHODS[kind]:
                # The arguments are operands: a walrus in one binds once,
                # through the one operand door.  They reduce left to right
                # after the receiver (``reduce_operands``'s ``earlier``):
                # they read its writes, and their halts carry them.
                return reduce_operands(
                    self.args, ctx, earlier=(receiver,)
                ).and_then(
                    lambda operands: consume_operands(
                        lambda *held: law.apply(
                            kind, self.method, receiver, held, self.site, ctx
                        )
                        or _opaque_pair(kind, self.method, self.site),
                        *operands,
                    )
                )
            if _inherited_mapping_pop(receiver, self.method, len(self.args)):
                # ``d.pop(k, default)`` on an instance of a source ``dict``
                # subclass that does not define ``pop``: the inherited
                # ``dict.pop`` over its constructed entries.
                return reduce_operands(
                    self.args, ctx, earlier=(receiver,)
                ).and_then(
                    lambda operands: consume_operands(
                        lambda pop_key, default: _mapping_pop_pair(
                            receiver, pop_key, default, self.site
                        ),
                        *operands,
                    )
                )
            # The value decides what the ordinary call did to it
            # (``_may_change``): a decided container under a method its law
            # does not cite as a mutation (``r.count(x)``), or an immutable
            # value, is as it was; anything else is unknown after it.
            post = (
                self._after(receiver)
                if _may_change(receiver, self.method, False, False)
                else receiver
            )
            if self.receiver_evaluation is None:
                return ordinary(ctx, post, receiver)
            # The ordinary call reads the receiver through its key: the one
            # evaluation above, bound where the call reads it
            # (``evaluation_here``: this live loop item's), never the
            # receiver evaluated again.
            from sugar_lift_py_tests.sugar.evaluation_ref_sugar import (
                evaluation_here,
            )

            held = base.with_temporal(
                base.temporal.bind_value(
                    evaluation_here(self.receiver_evaluation), receiver
                )
            )
            return ordinary(held, post, receiver)

        return outcome.and_then(on_receiver)


def _super_call_value(result):
    """The Python value of ``super().m(...)`` completed as ``result``: a
    builtin base's own transition of the receiver
    (``ReceiverOwnedMutationResult``: ``object.__init__()``) evaluates to
    its result (``None``); any other value is itself.  The receiver after
    the call is read off ``result`` itself (``receiver_after_its_call``)."""
    from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds
    from sugar_lift_py_tests.floor.receiver_owned_mutation_result import (
        ReceiverOwnedMutationResult,
    )

    binds, call = peel_walrus_binds(result)
    if binds or not isinstance(call, ReceiverOwnedMutationResult):
        return result
    return call.result


def _inherited_mapping_pop(receiver, method, arity) -> bool:
    """``pop(key, default)`` on a constructed mapping object whose class
    defines no ``pop`` of its own."""
    from sugar_lift_py_tests.floor.mapping_object_value import MappingObjectValue

    return (
        method == "pop"
        and arity == 2
        and isinstance(receiver, MappingObjectValue)
        and not any(
            getattr(field, "name", None) == "pop"
            for field in getattr(receiver, "class_fields", ())
        )
    )


def _mapping_pop_pair(receiver, key, default, site):
    """``(receiver after, value)`` of the inherited ``dict.pop(key, default)``."""
    from sugar_lift_py_tests.floor.tuple_value import TupleValue
    from sugar_lift_py_tests.sugar.mapping_pop_result_sugar import mapping_pop_result
    from sugar_lift_py_tests.sugar.mapping_pop_state_sugar import mapping_pop_state

    return mapping_pop_state(receiver, key, site).and_then(
        lambda post: mapping_pop_result(receiver, key, default, site).and_then(
            lambda result: ExitSet.completed(TupleValue((post, result)))
        )
    )


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
    would show its old contents).

    A ``list``/``dict`` or an instance along the path whose contents are not
    current (``object_identity.contents_current``) has no position to find:
    its key's place, its index's bound and its field are not read from
    contents it may no longer hold.  None, so the path's root after the call
    is the opaque post-state the call leaves (``_unknown_after``)."""
    from dataclasses import replace

    from sugar_lift_py_tests.floor import builtin_container_method as law
    from sugar_lift_py_tests.floor.dict_value import DictValue
    from sugar_lift_py_tests.floor.list_value import ListValue
    from sugar_lift_py_tests.floor.object_field import ObjectField
    from sugar_lift_py_tests.floor.object_identity import (
        contents_stale,
        instance_stale,
    )
    from sugar_lift_py_tests.floor.object_value import ObjectValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    if contents_stale(value):
        return None
    (kind, key), rest = steps[0], steps[1:]
    target = law.container_kind(post)

    def descend(child):
        if rest:
            return _replace_path(child, rest, post, check_shared)
        if law.container_kind(child) != law.container_kind(post):
            return None
        return post

    if kind == "attr":
        if (
            type(value) is not ObjectValue
            or instance_stale(value)
            or value.deferred_helper_fields
        ):
            # An instance whose fields are not current (``instance_stale``)
            # has no field to find: the root after the call is opaque.
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
        # The same object: it keeps its ``allocation`` (``object_identity``).
        return replace(value, entries=tuple(updated))
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
        return replace(value, elements=tuple(updated))
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
    # Names the unknown this read is when the call decided nothing.
    label: str = ""
    # No steps: the read of the name this rebinds, before the call.
    prior: object = None

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

        unknown = ExitSet.completed(
            _unknown_after(self.site, self.label or self.mode)
        )
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
        if not self.steps:
            # No path (``name_mutation_statement``): the object the call was
            # made on, after it -- the cited post-state, an unknown minted at
            # an ordinary call, or an immutable receiver unchanged, which
            # every name bound to it keeps as its own value.
            if _immutable(post) and self.prior is not None:
                return self.prior.desugar(ctx)
            return ExitSet.completed(post)
        if law.container_kind(post) is None:
            return unknown
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
    """An object a followed callee shares with its caller, read after the
    call: the value the call carried out of the callee's frame for it
    (``call_site_value.caller_visible_values``), bound under ``evaluation``
    (the call's key, ``nodes.carried_evaluation``, projected by the object's
    label) on the arm the call left by.  Never a key of the callee's frame,
    and never the object as it was before the call: what the callee left
    undecided the call carried as an unknown minted at the call.

    ``prior`` (set only for a read at a halt inside the statement that holds
    the call, ``container_mutation.at_halt_read``) is the object as the
    statement found it: where the halt's record holds no such key, the call
    never ran before the halt.  Any other read whose key is unbound is
    refused by name."""

    evaluation: str
    label: str
    site: object = dataclass_field(compare=False)
    prior: Sugar | None = None

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
                str_const(self.evaluation),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import (
            evaluation_read_here,
        )

        temporal = getattr(ctx, "temporal", None) if ctx is not None else None
        key = (
            self.evaluation
            if temporal is None
            else evaluation_read_here(temporal, self.evaluation)
        )
        carried = temporal.value_read(key) if temporal is not None else None
        if carried is not None:
            return ExitSet.completed(carried)
        if self.prior is not None and temporal is not None:
            return self.prior.desugar(ctx)
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="SourceCallActualAfterSugar",
            blame=self.site,
            observed=(
                f"read of `{self.label}` after a followed call with the value "
                f"the call carries for it ({key}) unbound"
            ),
            requested="the value the call carried out of its callee's frame",
            fix=(
                "reduce the read after the call in the frame that ran it; the "
                "call carries each object its callee changed out on every arm "
                "(call_site_value.caller_visible_values)"
            ),
        )
