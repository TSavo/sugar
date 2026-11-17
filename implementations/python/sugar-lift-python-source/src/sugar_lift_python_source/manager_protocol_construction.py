"""The protocol of the manager a ``with`` head reduced to (#7757).

``ReducedManagerProtocolV1`` reads ``__enter__`` / ``__exit__`` on the value
the head reduced to; the helpers below call those methods as every implicit
special-method call is made: a method on a decided receiver is its coordinate
and edge, joined at prove (#7757 step 6), never its body applied here."""

from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.floor import (
    EnteredManagerStateValue,
    ObjectValue,
)
from sugar_lift_py_tests.floor.manager_coordinate import (
    ExitTracebackCoordinate,
    ExitValueCoordinate,
)
from sugar_lift_py_tests.outcome.exit_set import _require_exit_set


def _exit_for_body(
    exit_face_id: str,
    entered,
    body_face,
    ctx: object = None,
    *,
    unit=None,
    fragment=None,
):
    """``__exit__`` on the entered receiver with this body face's actual ABI
    inputs.  ``unit``: the module the ``with`` stands in, where the receiver
    is a class call's result dispatched over its class
    (``_call_protocol_method``); ``fragment``: the ``with`` item, where a
    halt of that call leaves.

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
        unit=unit,
        halted_at=fragment,
    )


def undecided_manager_slot_result(slot: str, key: str):
    """What ``__enter__`` or ``__exit__`` of the undecided manager returned.

    Opaque and keyed on the ``with`` evaluation's exit face: nothing here
    decides which method ran, so nothing decides what it returned.  It is
    the one opaque value (``SymbolicValue``), so every read of it -- an
    attribute (``f.read``), an item (``f[0]``), its truth (whether
    ``__exit__``'s result suppresses), an iteration -- is that value's one
    undecided read, both faces, owed, its halt kept (#7757); no second floor
    answers some reads and refuses the rest."""
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.ir import ctor, str_const

    return SymbolicValue(
        ctor(
            "python:undecided_manager.slot_result",
            (str_const(slot), str_const(key)),
        )
    )


@dataclass(frozen=True)
class ReducedManagerProtocolV1:
    """The protocol of the manager a ``with`` head reduced to (#7757).

    The head is reduced once, as any expression is, and each value it
    completes with is the manager.  ``__enter__`` and ``__exit__`` are read
    on that value's own type, as Python reads them (8.5):

    * a receiver whose type the one class-namespace lookup decides selects
      both methods: each is called as every method call is, its coordinate
      and edge, joined at prove (``_call_protocol_method``, #7757 step 6);
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

    def _dispatched_manager(self, receiver) -> bool:
        """Whether ``receiver`` is a same-file class call's result whose
        class is decided (``receiver_dispatch.class_value``:
        ``python:constructed(<class>)``) in a module that gives no object
        another class unseen: its ``__enter__`` and ``__exit__`` are the
        implicit special-method calls ``type(m).__enter__(m)`` and
        ``type(m).__exit__(m, ...)``, each the one dispatched edge over that
        class (``receiver_dispatch.dispatch_on_receiver``), resolved at prove
        on the class's namespace row and bound by the one binder (#7757 step
        8).  Whether the class has them is decided there too: a lookup that
        finds none leaves the call owed, never a guessed method."""
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.receiver_dispatch import (
            class_value,
            module_attribute_names,
        )

        unit = getattr(self.fragment, "unit", None)
        return (
            isinstance(receiver, CallSiteValue)
            and unit is not None
            and class_value(receiver) is not None
            and not module_attribute_names(unit)[1]
        )

    def enter_resource_outcome_for(self, receiver, ctx: object = None):
        """Enter the exact receiver the head's reduction produced."""
        if self._dispatched_manager(receiver):
            from sugar_lift_py_tests.context_manager_contract import (
                protocol_step_site,
            )

            enter = _call_protocol_method(
                receiver,
                "__enter__",
                (),
                protocol_step_site(self.exit_face_id, "__enter__"),
                ctx,
                unit=self.fragment.unit,
                halted_at=self.fragment,
            )
            return _resource_enter_transitions(
                receiver, enter, blame=self.exit_face_id
            )
        decided, has_enter, has_exit = self._protocol_of(receiver)
        if not decided:
            return self._undecided_step(
                "__enter__",
                EnteredManagerStateValue(
                    enter_value=undecided_manager_slot_result(
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
            halted_at=self.fragment,
        )
        return _resource_enter_transitions(receiver, enter, blame=self.exit_face_id)

    def exit_outcome_for_body(self, entered, body_face, ctx: object = None):
        """``__exit__`` over this body face: the entered receiver's own
        method, or the undecided manager's two-faced exit."""
        receiver = getattr(entered, "receiver_state", None)
        if self._dispatched_manager(receiver):
            return _exit_for_body(
                self.exit_face_id,
                entered,
                body_face,
                ctx,
                unit=self.fragment.unit,
                fragment=self.fragment,
            )
        decided, has_enter, has_exit = self._protocol_of(receiver)
        if decided and has_enter and has_exit:
            return _exit_for_body(
                self.exit_face_id, entered, body_face, ctx, fragment=self.fragment
            )
        return self._undecided_step(
            "__exit__",
            undecided_manager_slot_result("__exit__", self.exit_face_id),
        )


def _call_protocol_method(
    receiver, name, arguments, site, ctx, *, unit=None, halted_at=None
):
    """``receiver.<name>(*arguments)``: the implicit special-method call
    ``type(receiver).<name>(receiver, *arguments)`` the ``with`` statement
    makes, through the one door every implicit dunder call takes
    (``ObjectValue.call_method_value``).  A method the one class-namespace
    lookup selects on a receiver whose class is decided is the one dispatched
    call, looked up and joined at prove (``ObjectValue.call_member``, #7757
    step 8); a receiver
    that arrived by binding, or a lookup not decided, is the unanswered call.
    The method's body is never applied here: what it returns and what it
    does to the receiver are what its contract states.  ``site`` is the
    call's site: the item's exit face for ``__exit__``, its ``__enter__``
    step's site for ``__enter__`` (``protocol_step_site``).

    A same-file class call's result whose class is decided
    (``ReducedManagerProtocolV1._dispatched_manager``, ``unit`` the module
    the ``with`` stands in) is the dispatched edge over that class
    (``receiver_dispatch.dispatch_on_receiver``, #7757 step 8): its
    actuals as Python passes them (``__exit__(m, type, value, tb)``), bound
    at prove by the one binder (a ``*exc`` formal takes the three).

    On either path ``site`` is the step's slot id, which states no source
    fragment: a halt of the call leaves at ``halted_at``, the ``with`` item
    (``UnknownCalleeCallV1.faces``).  An instance built in the frame whose
    protocol the lookup decides is no dispatched manager
    (``_dispatched_manager``): its ``__enter__``/``__exit__`` take the
    receiver's own door (``ObjectValue.call_method_value``), which carries
    ``halted_at`` to the dispatched or unanswered call it makes, never the
    slot id as the halt's site.
    """
    from sugar_source_tree.panic import SugarNotWritten

    if unit is not None:
        from sugar_lift_py_tests.receiver_dispatch import dispatch_on_receiver

        dispatched = dispatch_on_receiver(
            name,
            receiver,
            tuple(arguments),
            (),
            site,
            unit=unit,
            halted_at=halted_at,
        )
        if dispatched is not None:
            return dispatched
    call_method_value = getattr(receiver, "call_method_value", None)
    if not callable(call_method_value):
        raise SugarNotWritten(
            blame=site,
            owner="ConstructedManagerProtocolV1.protocol_method",
            observed=type(receiver).__name__,
            requested=f"authenticated {name} call over projected receiver state",
            fix="preserve the exact receiver method frame or keep protocol loud",
        )
    # Only the instance's own door carries where a halt leaves; a receiver
    # of any other kind reaches here with no decided protocol.
    leaves = {"halted_at": halted_at} if isinstance(receiver, ObjectValue) else {}
    return call_method_value(
        name,
        tuple(arguments),
        owner="ConstructedManagerProtocolV1.protocol_method",
        blame=site,
        ctx=ctx,
        **leaves,
    )


def _resource_enter_transitions(receiver: ObjectValue, enter_outcome, *, blame: object):
    """Each completed ``__enter__`` face entered: the value the call
    completed with (its coordinate, ``as x`` reads it) and the receiver.

    ``__enter__`` is an edge (``_call_protocol_method``): what it did to the
    receiver is what its contract states, joined at prove (#7757 step 7), so
    the receiver the ``with`` exits is the one it entered.  An enter that is a
    deferred native-operation carrier is refused by name; every halted enter
    face leaves the With as itself."""
    from sugar_lift_py_tests.outcome import ExitSet

    del blame
    enter_exits = _require_exit_set(
        enter_outcome, owner="ConstructedManagerProtocolV1.resource_enter_transitions"
    )
    # Every transition runs beneath its enter face (``ExitSet.and_then``):
    # the face's guard, faces and ``owed`` ride onto each one.
    return enter_exits.and_then(
        lambda value: ExitSet.completed(EnteredManagerStateValue(value, receiver))
    )
