"""The protocol of the manager a ``with`` head reduced to (#7757).

``ReducedManagerProtocolV1`` reads ``__enter__`` / ``__exit__`` on the value
the head reduced to; the helpers below bind and apply those methods as every
call is bound and applied."""

from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.floor import (
    BlockValue,
    CallSiteValue,
    EnteredManagerStateValue,
    FloorValue,
    GuardedReceiverFieldStoreValue,
    ObjectField,
    ObjectValue,
    ReceiverFieldStoreValue,
)
from sugar_lift_py_tests.floor.manager_coordinate import (
    ExitTracebackCoordinate,
    ExitValueCoordinate,
)
from sugar_lift_py_tests.outcome.exit_set import _require_exit_set


def _exit_for_body(exit_face_id: str, entered, body_face, ctx: object = None):
    """``__exit__`` on the entered receiver with this body face's actual ABI
    inputs.

    Python language reference 8.5, the with statement:
    https://docs.python.org/3/reference/compound_stmts.html#the-with-statement

    Bind before reducing the native method, not after an abstract reduction:
    unreachable normal/exceptional branches must not perform field lookups.
    """
    from sugar_lift_py_tests.outcome import Completed, Halted
    from sugar_lift_py_tests.effect import GroupedRaiseEffect, RaiseEffect
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.undetermined_exception_value import (
        UndeterminedExceptionTypeValue,
    )
    from sugar_lift_py_tests.effect.loop_control_effect import LoopControlEffect
    from sugar_lift_py_tests.floor import FloorValue, NoneValue
    from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
        AuthenticatedExceptionTypeValue,
    )
    from sugar_lift_py_tests.floor.manager_coordinate import RaisedExitTypeValue
    from sugar_lift_py_tests.floor.class_value import ClassValue
    from sugar_lift_py_tests.floor.class_definition_value import (
        ClassDefinitionValue,
    )
    from sugar_lift_py_tests.floor.exception_class_value import ExceptionClassValue
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    if not isinstance(entered, EnteredManagerStateValue):
        construction_panic_gap(
            owner="ManagerProtocol.exit_outcome_for_body",
            blame=exit_face_id,
            observed=type(entered).__name__,
            requested="matching entered manager state",
            fix="carry the exact enter face into resource exit",
        )
    if isinstance(body_face, Completed) or (
        isinstance(body_face, Halted)
        and isinstance(body_face.effect, LoopControlEffect)
    ):
        args = (NoneValue(), NoneValue(), NoneValue())
    elif isinstance(body_face, Halted) and isinstance(body_face.effect, RaiseEffect):
        effect = body_face.effect
        value = effect.raised_value
        # The RaiseEffect already owns type identity. Pass the native value,
        # not that identity witness, into the callee's operation dispatch.
        while isinstance(value, AuthenticatedExceptionTypeValue):
            value = value.value
        if value is None or isinstance(
            value, (ClassValue, ClassDefinitionValue, ExceptionClassValue)
        ):
            # A bare class still needs native exception instantiation; it
            # must never stand in for the actual instance supplied by With.
            # The raise authenticates an instance's existence, not its
            # fields. An unused slot needs no fabricated instance; a lookup
            # on this still-undischarged slot remains a typed demand.
            value = ExitValueCoordinate(exit_face_id, None)
        if not isinstance(value, FloorValue):
            construction_panic_gap(
                owner="ManagerProtocol.exit_outcome_for_body",
                blame=effect.occurrence,
                observed="authenticated raise without an actual exception value",
                requested="actual raised Floor value, not a guessed instance",
                fix="retain the exception producer's actual value on the body face",
            )
        args = (
            RaisedExitTypeValue(
                effect.exception_type_coordinate, effect.exception_type_mro
            ),
            value,
            ExitTracebackCoordinate(exit_face_id, None),
        )
    elif isinstance(body_face, Halted) and isinstance(
        body_face.effect, GroupedRaiseEffect
    ):
        from sugar_lift_py_tests.floor.grouped_exception_value import (
            GroupedExceptionValue,
        )
        from sugar_lift_py_tests.ir import ctor, str_const

        effect = body_face.effect
        # BaseExceptionGroup(...) natively becomes ExceptionGroup when every
        # leaf is an Exception, so only the ExceptionGroup coordinate states
        # the instance's real class.
        if effect.exception_type_coordinate != ctor(
            "python:exception_type_identity",
            [str_const("builtins"), str_const("ExceptionGroup")],
        ) or effect.exception_type_mro is None:
            construction_panic_gap(
                owner="ManagerProtocol.exit_outcome_for_body",
                blame=exit_face_id,
                observed="exception group without builtins.ExceptionGroup testimony",
                requested="an authenticated builtins.ExceptionGroup body raise",
                fix="authenticate the group's native class before exit inputs",
            )
        args = (
            RaisedExitTypeValue(
                effect.exception_type_coordinate, effect.exception_type_mro
            ),
            GroupedExceptionValue(effect, exit_face_id),
            ExitTracebackCoordinate(exit_face_id, None),
        )
    elif isinstance(body_face, Halted) and isinstance(
        body_face.effect, UndeterminedRaiseEffect
    ) and body_face.effect.exception_value is not None:
        # A may-raise operation threw ONE exception object nobody testified
        # to. With hands it to __exit__ like any raise: (type(e), e, tb),
        # with type(e) derived from e itself, never a guessed class. The
        # exit's own type tests then split on it.
        exception = body_face.effect.exception_value
        args = (
            UndeterminedExceptionTypeValue(exception),
            exception,
            ExitTracebackCoordinate(exit_face_id, None),
        )
    else:
        construction_panic_gap(
            owner="ManagerProtocol.exit_outcome_for_body",
            blame=exit_face_id,
            observed=type(getattr(body_face, "effect", body_face)).__name__,
            requested="normal control or an authenticated raised body face",
            fix="authenticate the body exit before constructing native exit inputs",
        )
    return _call_protocol_method(
        entered.receiver_state,
        "__exit__",
        args,
        exit_face_id,
        ctx,
    )


@dataclass(frozen=True)
class UndecidedManagerSlotResultValue(FloorValue):
    """What ``__enter__`` or ``__exit__`` of the undecided manager returned.

    Opaque and keyed on the ``with`` evaluation's exit face: nothing here
    decides which method ran, so nothing decides what it returned."""

    slot: str
    key: str

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        del owner
        return ctor(
            "python:undecided_manager.slot_result",
            (str_const(self.slot), str_const(self.key)),
        )

    def truth(self, site):
        """Truth is the undecided ``py.truthy`` of this exact opaque result."""
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import py_truthy
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
            PredicateValue(py_truthy(self.to_term(owner="truth")), site)
        )


@dataclass(frozen=True)
class ReducedManagerProtocolV1:
    """The protocol of the manager a ``with`` head reduced to (#7757).

    The head is reduced once, as any expression is, and each value it
    completes with is the manager.  ``__enter__`` and ``__exit__`` are read
    on that value's own type, as Python reads them (8.5):

    * a receiver whose type the one class-namespace lookup decides selects
      both methods: each is bound and applied as every call is
      (``_call_protocol_method``);
    * a receiver whose type it decides lacks either: the ``with`` raises the
      interpreter's own TypeError before any enter and before the body;
    * any other value is the undecided manager: ``__enter__`` and
      ``__exit__`` each complete with an opaque result or raise something
      undetermined (``ExitSet.two_faced``), both faces owing the one
      undecided member at the ``with`` item.  The truth of the opaque exit
      result decides suppression, never assumed either way.

    No manager is invented and no callee body is read here: what the head
    reduced to is the only testimony.
    """

    exit_face_id: str
    # The With item's ``SourceFragmentCoordinateV1``, where each undecided
    # step is owed (``ExitSet.two_faced``).
    coordinate: object = field(compare=False)
    # The With item's source fragment, where an undecided step halts.
    fragment: object = field(default=None, compare=False)

    @staticmethod
    def _protocol_of(receiver):
        """``(decided, has_enter, has_exit)`` for the receiver's own type.

        ``decided`` is True only when the one class-namespace lookup decides
        the answer: both methods present, or one of them absent where Python
        looks it up first."""
        if not isinstance(receiver, ObjectValue):
            return False, None, None
        has_enter = receiver.has_method("__enter__")
        if has_enter is False:
            return True, False, receiver.has_method("__exit__") is True
        has_exit = receiver.has_method("__exit__")
        if has_enter is None or has_exit is None:
            return False, has_enter, has_exit
        return True, has_enter, has_exit

    def _undecided_step(self, step: str, value):
        """``step`` completes with ``value`` under its site-keyed atom, or
        raises something nothing names under the complement: the one
        two-faced constructor, owing the undecided member at the item."""
        from sugar_lift_py_tests.context_manager_contract import protocol_step_site
        from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
        from sugar_lift_py_tests.ir import atomic, ctor, str_const
        from sugar_lift_py_tests.outcome import ExitSet

        guard = atomic(
            "python:undecided_manager.slot_completes",
            [
                ctor(
                    "python:undecided_manager.step",
                    (str_const(step), str_const(self.exit_face_id)),
                )
            ],
        )
        return ExitSet.two_faced(
            value,
            UndeterminedRaiseEffect(
                blame=self.exit_face_id,
                occurrence=protocol_step_site(self.exit_face_id, step),
                producer_node_owner=f"ReducedManagerProtocolV1.{step}",
                site=self.fragment,
            ),
            guard=guard,
            site=self.coordinate,
        )

    def enter_resource_outcome_for(self, receiver, ctx: object = None):
        """Enter the exact receiver the head's reduction produced."""
        decided, has_enter, has_exit = self._protocol_of(receiver)
        if not decided:
            return self._undecided_step(
                "__enter__",
                EnteredManagerStateValue(
                    enter_value=UndecidedManagerSlotResultValue(
                        "__enter__", self.exit_face_id
                    ),
                    receiver_state=receiver,
                ),
            )
        if not (has_enter and has_exit):
            from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
            from sugar_lift_py_tests.manager_protocol_absence_refusal import (
                observed_non_manager_with_refusal,
            )
            from sugar_lift_py_tests.outcome import ExitSet

            refusal = observed_non_manager_with_refusal(
                receiver.class_name, has_enter=has_enter, has_exit=has_exit
            )
            blame = str(self.fragment)
            return ExitSet.halted(
                RaiseEffect.for_builtin(
                    refusal.exception_name,
                    occurrence=f"non-manager-with-refusal:{blame}",
                    blame=blame,
                    raised_value=refusal.message,
                    producer_node_owner="ReducedManagerProtocolV1",
                    site=self.fragment,
                )
            )
        # ``__enter__`` is called at its own step's site, never the exit
        # face ``__exit__`` is called at: a halt raised in its frame is named
        # by that call (``try_sugar._edge_hits``), so the ``try`` enclosing
        # the ``with`` reads it as a halt of the ``with``'s header, before
        # any of the body ran -- one raised by ``__exit__`` follows the body.
        from sugar_lift_py_tests.context_manager_contract import protocol_step_site

        enter = _call_protocol_method(
            receiver,
            "__enter__",
            (),
            protocol_step_site(self.exit_face_id, "__enter__"),
            ctx,
        )
        return _resource_enter_transitions(receiver, enter, blame=self.exit_face_id)

    def exit_outcome_for_body(self, entered, body_face, ctx: object = None):
        """``__exit__`` over this body face: the entered receiver's own
        method, or the undecided manager's two-faced exit."""
        receiver = getattr(entered, "receiver_state", None)
        decided, has_enter, has_exit = self._protocol_of(receiver)
        if decided and has_enter and has_exit:
            return _exit_for_body(self.exit_face_id, entered, body_face, ctx)
        return self._undecided_step(
            "__exit__",
            UndecidedManagerSlotResultValue("__exit__", self.exit_face_id),
        )


def _call_protocol_method(receiver, name, arguments, site, ctx):
    """``receiver.<name>(*arguments)``: bound, then applied, as every call is.

    The protocol method binds through ``bind_method_call`` (the receiver's
    ``bound_method_call``), so its frame is read again at the module
    execution site the With runs at (#7972), and is applied by
    ``_apply_protocol_call`` (``CallSiteValue.producer_outcome``).  ``site``
    is the call's site: the item's exit face for ``__exit__``, its
    ``__enter__`` step's site for ``__enter__`` (``protocol_step_site``).
    """
    from sugar_source_tree.panic import SugarNotWritten

    bound_method_call = getattr(receiver, "bound_method_call", None)
    if not callable(bound_method_call):
        raise SugarNotWritten(
            blame=site,
            owner="ConstructedManagerProtocolV1.protocol_method",
            observed=type(receiver).__name__,
            requested=f"authenticated {name} call over projected receiver state",
            fix="preserve the exact receiver method frame or keep protocol loud",
        )
    return _apply_protocol_call(
        bound_method_call(
            name,
            arguments,
            owner="ConstructedManagerProtocolV1.protocol_method",
            blame=site,
            ctx=ctx,
        ),
        ctx,
    )


def _apply_protocol_call(call: CallSiteValue, ctx):
    """The one application of a bound ``__enter__``/``__exit__`` call.

    ``CallSiteValue.producer_outcome`` applies it, as it applies every call
    (#7757 entry 6, #7969): each halt of the body is the call's own, and a
    deferred native operation over a formal is discharged against the bound
    actuals.  The With reads what the body did (its receiver stores and its
    return), so each completed face carries the body completion the Call
    retained (``retained_source_completion_outcome``), never a second
    reduction of the body.
    """
    from sugar_lift_py_tests.gap.panic import construction_panic_gap
    from sugar_lift_py_tests.outcome import ExitSet

    if call.body is None:
        # ``producer_outcome`` answers a bodiless call with the call itself;
        # a protocol method with no source body stays the refusal it was.
        construction_panic_gap(
            owner="ConstructedManagerProtocolV1.protocol_method",
            blame=call.target_name,
            observed="protocol method call has no source body",
            requested="the constructed source body of the protocol method",
            fix="retain the source-visible call frame or keep the call loud",
        )
    outcome = call.producer_outcome(ctx)
    if not isinstance(outcome, ExitSet):
        return outcome

    def body_completion(value):
        # Each completed face continues as the body completion it retained
        # (``ExitSet.and_then``): its guard, faces and ``owed`` ride on. Each
        # halt of the body stands as the call's own.
        if isinstance(value, CallSiteValue) and value.term is call.term:
            retained = value.retained_source_completion_outcome()
            if retained is not None:
                return ExitSet.completed(retained.completed_value())
        return ExitSet.completed(value)

    return outcome.and_then(body_completion)


def _resource_enter_transitions(receiver: ObjectValue, enter_outcome, *, blame: object):
    from sugar_lift_py_tests.ir import not_
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.outcome.exit_set import partition
    from sugar_source_tree.panic import SugarNotWritten

    # Each enter face becomes one resource transition: an enter that is a
    # deferred native-operation carrier is refused by name.
    enter_exits = _require_exit_set(
        enter_outcome, owner="ConstructedManagerProtocolV1.resource_enter_transitions"
    )

    def stored(state, statement):
        """The receiver states after one acquisition store, beneath ``state``.

        A guarded store splits the state: each side is one fresh arm
        (``ExitSet.completed``) restricted to its face of the split, and the
        two sides join through the one join."""
        if isinstance(statement, GuardedReceiverFieldStoreValue):
            then_face, else_face = partition(
                ("resource-enter-store", statement.to_term(owner=receiver.identity))
            )
            return (
                ExitSet.completed(_apply_receiver_store(state, statement, blame=blame))
                .guarded(statement.guard, then_face)
                .union(
                    ExitSet.completed(state).guarded(
                        not_(statement.guard), else_face
                    )
                )
            )
        if isinstance(statement, ReceiverFieldStoreValue):
            return ExitSet.completed(
                _apply_receiver_store(state, statement, blame=blame)
            )
        return ExitSet.completed(state)

    def transitions(block):
        if not isinstance(block, BlockValue):
            raise SugarNotWritten(
                blame=blame,
                owner="ConstructedManagerProtocolV1.enter_resource_outcome_for",
                observed=type(block).__name__,
                requested="completed enter block carrying exact acquisition stores",
                fix="preserve the ordinary enter block or keep resource state loud",
            )
        # Each store runs beneath every state the stores before it reached
        # (``ExitSet.and_then``), so each split's guard and face ride on.
        states = ExitSet.completed(receiver)
        for statement in block.statements:
            states = states.and_then(
                lambda state, statement=statement: stored(state, statement)
            )
        return states.and_then(
            lambda state: ExitSet.completed(EnteredManagerStateValue(block, state))
        )

    # Every transition runs beneath its enter face (``ExitSet.and_then``):
    # the face's guard, faces and ``owed`` ride onto each one. A halted enter
    # face leaves the With as itself.
    return enter_exits.and_then(transitions)


def _apply_receiver_store(
    receiver: ObjectValue, statement: ReceiverFieldStoreValue, *, blame: object
) -> ObjectValue:
    from sugar_source_tree.panic import SugarNotWritten

    if statement.receiver.identity != receiver.identity:
        raise SugarNotWritten(
            blame=blame,
            owner="ConstructedManagerProtocolV1.enter_resource_outcome_for",
            observed="receiver coordinate mismatch",
            requested="acquisition store from the exact authenticated receiver",
            fix="preserve ObjectValue.identity across the enter transition",
        )
    fields = {field.name: field.value for field in receiver.fields}
    fields[statement.attr] = statement.value
    return ObjectValue(
        receiver.class_name,
        tuple(ObjectField(name, fields[name]) for name in sorted(fields)),
        methods=receiver.methods,
        class_fields=receiver.class_fields,
        identity=receiver.identity,
        # The same object: it keeps its ``allocation`` and ``arrival``.
        allocation=receiver.allocation,
        arrival=receiver.arrival,
    )
