from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import TYPE_CHECKING, Any, NoReturn

from sugar_lift_py_tests.call_symbol import call_symbol

from .floor_value import FloorValue, undecided_attribute_result
from .object_field import ObjectField
from .object_method_value import ObjectMethodValue

if TYPE_CHECKING:
    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.operations.inplace_binary_operator_operation import (
        InplaceBinaryOperatorOperation,
    )
    from sugar_lift_py_tests.operations.iterator_operation import IteratorOperation
    from sugar_lift_py_tests.operations.next_operation import NextOperation
    from sugar_lift_py_tests.operations.sequence_projection_operation import (
        SequenceProjectionOperation,
    )
    from sugar_lift_py_tests.operations.subscript_operation import SubscriptOperation
    from sugar_lift_py_tests.outcome import ExitSet


# ``object.__class__``: the one builtin data descriptor whose delete is read
# here.  Its setter (``object_set_class``) refuses a missing value with
# ``TypeError`` whatever the object (``ObjectValue._deletes_object_class_slot``).
_OBJECT_CLASS_SLOT = vars(object)["__class__"]


def _attribute_owned(outcome):
    """A dispatched read's raise continues as the Attribute's own halt
    beneath its arm (guard, faces and ``owed`` ride on); every other arm
    stands."""
    from dataclasses import replace

    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.outcome import ExitSet

    if not isinstance(outcome, ExitSet):
        return outcome
    return outcome.and_then(
        lambda value: ExitSet.completed(value),
        consume=lambda halt: (
            ExitSet.halted(
                replace(halt.effect, producer_node_owner="Attribute"),
                state=halt.state,
            )
            if isinstance(halt.effect, RaiseEffect)
            else None
        ),
    )


@dataclass(frozen=True)
class ObjectValue(FloorValue):
    class_name: str
    fields: tuple[ObjectField, ...]
    methods: tuple[ObjectMethodValue, ...] = ()
    class_fields: tuple[ObjectField, ...] = ()
    identity: str = ""
    # Definition-owned class identity transported by ClassDefinitionValue.
    # This is never reconstructed from class_name.
    defining_class: object | None = dataclass_field(
        default=None, compare=False, repr=False
    )
    # The construction that made this object in the frame reading it (the
    # class call's site, ``object_identity.made_at``), kept by every
    # post-state of the object (a field store, a delete); None for an
    # instance that arrived by binding (``object_identity``: ``arrived``,
    # ``contents_current``).  Required, never defaulted: every construction
    # names it.  Whether ``fields`` are the object's fields now.
    allocation: str | None = dataclass_field(
        kw_only=True,
        compare=False,
        metadata={"testimony": "provenance"},
    )
    # The binding read an instance with no ``allocation`` arrived through:
    # what an undecided read names the object by (``object_identity.arrived``,
    # ``identity_term``).
    arrival: str | None = dataclass_field(
        default=None,
        kw_only=True,
        compare=False,
        metadata={"testimony": "provenance"},
    )
    # The fields a store in this frame put on the instance (the one field
    # store, ``with_field_store``): each is the instance's field now even
    # where the instance arrived by binding and its other fields are not
    # current (``ConstructedInstanceValue.post_formula`` states them).  A
    # read never answers from them on such an instance: it names no class
    # term to guard the read by (``attribute``).  An arrival by binding clears them
    # (``object_identity.arrived``): code this frame does not see may have
    # changed them since.
    stored_fields: tuple[str, ...] = dataclass_field(
        default=(),
        kw_only=True,
        compare=False,
        metadata={"testimony": "provenance"},
    )

    def denotes_value(self) -> bool:
        """A constructed receiver denotes a runtime object, not a pure slot."""
        return True

    def truth(self, site):
        """``bool(o)`` / ``if o``: the one truth rule's two faces, as for a
        formal (``SymbolicValue.truth``).

        Which ``__bool__`` / ``__len__`` Python runs is the class order's,
        and no dispatched answerer of it exists: prove's walk does not carry
        the truth protocol, so the read is the one undecided member
        (``bool_op_sugar._unanswered_truth``): it completes with
        ``python:truth_result(<term>, <key>)`` under ``python:truth.completes``
        and halts undetermined under the complement, owed either way.  The
        instance is named by ``object_identity.identity_term`` (#7757 S4)."""
        from sugar_lift_py_tests.sugar.bool_op_sugar import _unanswered_truth

        return _unanswered_truth(self, site, owner="ObjectValue.truth")

    def length(self, site):
        """``len(o)``: the builtin's one unanswered call over an operand that
        is not a decided builtin (``builtin_dunder_call``: ``len(c)`` runs
        ``type(c).__len__``, which is not CPython's own), so the same
        ``UnknownCalleeCallV1("len")`` faces as ``len`` over any undecided
        operand: it completes with ``python:call_result(call:len(<o>),
        <occurrence>)`` under ``python:unknown_callee_call.completes`` and
        halts undetermined under the complement, owed either way.  No
        ``__len__`` is dispatched here (#7757 S4).  The instance is named by
        ``object_identity.identity_term``; a siteless read is the lifter's
        own gap and refuses by name (``floor_value.unanswered_length``, the
        one form ``len`` of every undecided operand takes)."""
        from sugar_lift_py_tests.floor.object_identity import identity_term

        from .floor_value import unanswered_length

        return unanswered_length(
            self,
            lambda at: identity_term(
                self, at, "argument0", owner="ObjectValue.length"
            ),
            site,
            owner="ObjectValue.length",
        )

    def contains(self, item, site):
        """``k in o``: membership whose container dispatch (``__contains__``,
        else ``__iter__``, else ``__getitem__``) is the class order's, which
        no dispatched answerer carries, so the two faces a formal's
        membership has (``FloorValue.undecided_contains``, #7757 S4)."""
        return self.undecided_contains(item, site, owner="ObjectValue.contains")

    def format_data_model(self, spec, site, ctx):
        return self.call_method_value(
            "__format__",
            (spec,),
            owner="FormatDunderCallSugar",
            blame=str(site),
            ctx=ctx,
        )

    def equals(self, other, site, ctx):
        """Invoke an authenticated source ``__eq__`` when method order is known.

        Different source classes require reflected/subclass dispatch testimony;
        unconstructed return/NotImplemented behavior remains a typed refusal.
        Never substitute object identity for a user-defined equality body,
        nor for an ``__eq__`` the one class-namespace lookup does not decide
        (a dataclass's generated one, a store): that is the unanswered call.
        """
        if self.has_method("__eq__") is False:
            return super().equals(other, site, ctx)
        return self._source_rich_comparison(
            "__eq__", other, site, ctx, owner="ObjectValue.equals"
        )

    def less_than(self, other, site, ctx):
        """``self < other`` invokes the class's authenticated ``__lt__``."""
        if self.has_method("__lt__") is False:
            return super().less_than(other, site, ctx)
        return self._source_rich_comparison(
            "__lt__", other, site, ctx, owner="ObjectValue.less_than"
        )

    def less_equal(self, other, site, ctx):
        """``self <= other`` invokes the class's authenticated ``__le__``."""
        if self.has_method("__le__") is False:
            return super().less_equal(other, site, ctx)
        return self._source_rich_comparison(
            "__le__", other, site, ctx, owner="ObjectValue.less_equal"
        )

    def greater_than(self, other, site, ctx):
        """``self > other`` invokes the class's authenticated ``__gt__``."""
        if self.has_method("__gt__") is False:
            return super().greater_than(other, site, ctx)
        return self._source_rich_comparison(
            "__gt__", other, site, ctx, owner="ObjectValue.greater_than"
        )

    def greater_equal(self, other, site, ctx):
        """``self >= other`` invokes the class's authenticated ``__ge__``."""
        if self.has_method("__ge__") is False:
            return super().greater_equal(other, site, ctx)
        return self._source_rich_comparison(
            "__ge__", other, site, ctx, owner="ObjectValue.greater_equal"
        )

    def _source_rich_comparison(self, dunder: str, other, site, ctx, *, owner: str):
        """The ONE rich-comparison dispatch onto a source class's own method.

        Python evaluates ``a <op> b`` as ``type(a).<dunder>(a, b)``, falling
        to ``type(b)``'s reflection only on ``NotImplemented`` (or first, for
        a right-hand subclass).  This constructs exactly the case whose method
        order is authenticated without reflection: both operands instances of
        the same source class (or an exact native right operand) and the
        left's definition-owned ordinary method frame; every reflected or
        subclass order stays a named refusal.  The call is its coordinate and
        edge: its result, ``NotImplemented`` included, is what the method's
        contract states, joined at prove (#7757 step 6).

        Which member runs and how it binds (a plain function, a
        ``staticmethod``, a ``classmethod``, a property) is prove's one walk
        of the order's (``consistency::dispatch_walk``, #7757 L3): the lift
        reads no ``def``'s kind or frame.  A lookup the one class-namespace
        lookup does not decide is the unanswered call
        (``unanswered_method_call``); a class-field value there is no method
        this constructs, and refuses by name.
        """
        decided, _method, value = self.class_member(dunder)
        if not decided:
            return self.unanswered_method_call(dunder, (other,), (), site)
        same_class = (
            isinstance(other, ObjectValue)
            and getattr(self.defining_class, "class_definition_cid", None) is not None
            and getattr(self.defining_class, "class_definition_cid", None)
            == getattr(other.defining_class, "class_definition_cid", None)
        )
        if (isinstance(other, ObjectValue) and not same_class) or (
            not isinstance(other, ObjectValue)
            and (not other.denotes_value() or not other.runtime_type_is_decided())
        ):
            return self._floor_gap(
                owner=owner,
                blame=site,
                observed=f"source {dunder} method order is not authenticated",
                requested="same source class or an exact native right operand",
                fix="derive reflected/subclass method order before rich comparison",
            )
        if value is not None:
            return self._floor_gap(
                owner=owner,
                blame=site,
                observed=f"source {dunder} is a class-field value",
                requested=f"a {dunder} the class body wrote as a def",
                fix="construct the class-field value's call before invoking it",
            )
        # The call is its coordinate and edge, joined at prove to the
        # method's contract (``_dispatched_or_owed``, the one dispatched
        # call, #7757 step 8): what it returns -- a native boolean,
        # ``NotImplemented``, anything -- is that contract's, never its body
        # applied here.  The comparison's value is the call's, its truth the
        # call's own.
        del ctx
        return self._dispatched_or_owed(dunder, (other,), (), site)

    def matrix_multiply(self, other, site, ctx):
        """``@`` on an object is the ``__matmul__`` data-model method,
        applied under the caller's context like any call (#7757).

        BinOpSugar calls ``left.matrix_multiply(right, site, ctx)``
        directly (same totalizer shape as ``multiply`` / ``add``). Without
        this arm, ObjectValue falls through FloorValue's construction panic
        even when the class ships a diggable ``__matmul__`` body — the
        ``matrix_multiply_return`` witness residual under #4387.
        """
        return self.call_method_value(
            "__matmul__",
            (other,),
            owner="MatrixMultiplyOpSugar",
            blame=str(site),
            ctx=ctx,
        )

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "py.object.identity",
            [str_const(self.class_name), str_const(self.identity)],
        )

    def attribute(self, name, site, ctx):
        """Project an exact field from this constructed receiver state.

        The one currency rule (``object_identity.contents_current``): the
        recorded instance fields are read only when they are the object's
        fields now (a construction in this frame made it).  An instance that
        arrived by binding may have been changed since by another alias,
        which may have stored, deleted or added any name in its ``__dict__``.

        On an instance that is not current, every name is the dispatched
        read (``_dispatched_read``): which member a data descriptor or the
        ``__dict__`` answers it with is prove's walk of the order to decide
        (``consistency::dispatch_walk``), never the lift's.  Such an
        instance names no class term (``receiver_dispatch.class_value``), so
        the read is the undecided read over its identity (``identity_term``).

        A recorded instance field of a current instance is read as that
        field only on the face where prove decides the read IS the
        ``__dict__`` entry (``plain_read_guard``: ``python:plain_read(<class>,
        "<name>")``, no ``__getattribute__`` or other read hook in the order
        and no binding of the name -- a class data descriptor would win over
        the entry, ``consistency::plain_read_holds``); under its complement
        the read is the dispatched read (#7757).  The lift never reads a
        recorded field outright.

        A class-field value (a class-body binding other than a ``def``) is
        read off the class by the one class-namespace lookup
        (``class_member``: the binding the class body left last) only on the
        face where prove decides that the read IS that binding's value
        (``class_read_guard``: ``python:class_read(<class>, "<name>")``, no
        ``__getattribute__`` or other read hook in the order and a binding
        whose value defines no ``__get__``, ``consistency::class_read_holds``);
        under its complement the read is the dispatched read.  The value is
        the binding's object as it arrives here (``object_identity.arrived``):
        a list, dict or set the class body bound is never read by the
        contents the class body gave it (#7757 L3).  Where no
        class term is decided, the dispatched read alone (#7757 L1).  A
        lookup that does not decide is the undecided read
        (``undecided_attribute_result``).

        Every other name -- a ``def`` the class wrote (plain, static, class
        method or property), or no class member at all -- is the dispatched
        read (``_dispatched_call(read=True)``):
        which member it finds, how it binds, and whether it raises
        ``AttributeError`` are decided once, at prove, by the one walk of the
        order (``consistency::dispatch_walk``, #7757 L3), never here.  Where
        the read names no class it is the undecided read.  ``o.m(...)``
        written as a call is the dispatched call itself
        (``dispatched_method_call``)."""
        from sugar_lift_py_tests.outcome import ExitSet

        from .object_identity import contents_current

        if not contents_current(self):
            return self._dispatched_read(name, site)
        for field in reversed(self.fields):
            if field.name == name:
                return self._guarded_read_faces(
                    name,
                    ExitSet.completed(field.value),
                    self.plain_read_guard(name),
                    site,
                    owner="ObjectValue.plain_read",
                )
        decided, _selected, class_value = self.class_member(name)
        if not decided:
            return undecided_attribute_result(
                self, name, site, owner="ObjectValue.attribute"
            )
        if class_value is not None:
            from sugar_lift_py_tests.floor.lambda_callable import LambdaCallable

            from .object_identity import arrived

            # The class-body binding's object, never the contents the class
            # body gave it: the body ran in the class statement's frame, and
            # any code since (a method, a module statement, a callee
            # mutating ``C.items``) may have changed a list, dict or set it
            # bound, or an instance it holds.  So the value reaches this
            # frame by binding (``arrived``), its contents not current, and
            # every read of them is the read's undecided form over its
            # identity -- the currency rule a stale container already obeys
            # (#9087, #7757 L3).  An immutable value arrives unchanged.
            # Prove's ``python:class_read`` decides which object the read
            # is, never what it holds.
            read = arrived(class_value, site)
            if isinstance(class_value, LambdaCallable):
                # A function in the class namespace (``f = lambda self: 1``,
                # ``m = some_def``) read off an instance is what its
                # descriptor binds (``function.__get__``): a method bound to
                # this receiver, never the bare function.  Its call binds
                # this receiver first and applies the function's own call
                # (``call_member``).
                from sugar_lift_py_tests.floor.bound_method_value import (
                    BoundMethodValue,
                )

                read = BoundMethodValue(self, name, class_value)
            return self._class_read_faces(name, ExitSet.completed(read), site)
        # No recorded field answers the name, and the one class-namespace lookup found no class-field
        # value for it: a ``def`` the class wrote (plain, ``staticmethod``,
        # ``classmethod``, ``property``) or nothing.  Which member that is,
        # what kind it binds as, and whether the read raises
        # ``AttributeError`` -- no class of the order binds it, the
        # ``__dict__`` may not hold it, no ``__getattr__`` or
        # ``__getattribute__`` answers -- are the one walk of the order's to
        # decide, at prove (``consistency::dispatch_walk``, #7757 NEW-7/L3):
        # the read is the dispatched read on this instance, its class and the
        # fields its ``__dict__`` may hold now (``receiver_dispatch.
        # class_value``), both faces
        # kept.  Where it names no class, the one undecided read.
        return self._dispatched_read(name, site)

    def _dispatched_read(self, name, site):
        """``self.<name>`` as the one dispatched read
        (``_dispatched_call(read=True)``), its raise the Attribute's own;
        where the instance names no class term, the undecided read."""
        dispatched = self._dispatched_call(name, (), (), site, read=True)
        if dispatched is not None:
            return _attribute_owned(dispatched)
        return undecided_attribute_result(
            self, name, site, owner="ObjectValue.attribute"
        )

    def class_read_guard(self, name: str):
        """``python:class_read(<class>, "<name>")``
        (``receiver_dispatch.class_read_atom``): prove's statement that a
        read of ``name`` on this instance is its class's binding of it, by
        Python's own rule (``consistency::class_read_holds``).  None where no
        class term is decided -- an instance not current, one whose
        ``__class__`` was stored, no class symbol (no workspace root), no
        class statement -- or ``name`` is a dunder name: the read is then
        only the dispatched read."""
        from sugar_lift_py_tests.receiver_dispatch import (
            class_read_atom,
            class_value,
            is_dunder,
        )

        if is_dunder(name) or any(item.name == "__class__" for item in self.fields):
            return None
        term = class_value(self)
        if term is None:
            return None
        return class_read_atom(term, name)

    def plain_read_guard(self, name: str):
        """``python:plain_read(<class>, "<name>")`` (``receiver_dispatch.
        plain_read_atom``) over this instance's class term
        (``receiver_dispatch.class_value``): prove's statement that a read
        of ``name`` on this instance is its ``__dict__`` entry by Python's
        own rule (``consistency::plain_read_holds``: no class of the order
        binds ``__getattribute__``, ``__getattr__``, ``__slots__`` or
        ``__dict__``, and none binds the name -- a data descriptor of it
        would win over the entry).  The same atom a constructed field's read
        is stated under (``ConstructedInstanceValue.post_formula``, #9051).

        None where no class term is decided -- an instance not current, one
        whose ``__class__`` was stored, no class symbol (no workspace root),
        no class statement -- or ``name`` is a dunder name: the read is then
        only the dispatched read."""
        from sugar_lift_py_tests.receiver_dispatch import (
            class_value,
            is_dunder,
            plain_read_atom,
        )

        if is_dunder(name) or any(item.name == "__class__" for item in self.fields):
            return None
        term = class_value(self)
        if term is None:
            return None
        return plain_read_atom(term, name)

    def _class_read_faces(self, name, read, site):
        """The one shape of a class-field value read (#7757 L1): ``read`` --
        the class binding's value, as its descriptor binds it -- under
        ``class_read_guard``, and the dispatched read under its complement
        (``_guarded_read_faces``)."""
        return self._guarded_read_faces(
            name,
            read,
            self.class_read_guard(name),
            site,
            owner="ObjectValue.class_read",
        )

    def _guarded_read_faces(self, name, read, guard, site, *, owner: str):
        """The one shape of a read the lift answers from what it holds (a
        recorded instance field under ``plain_read_guard``, a class-field
        value under ``class_read_guard``): ``read`` under ``guard``, and the
        dispatched read (``_dispatched_read``) under its complement, the two
        faces of one partition.  Where no guard is decided, the dispatched
        read alone: the lift never decides that no hook runs, that no data
        descriptor wins, or that the value is no descriptor (#7757)."""
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.outcome.exit_set import partition

        dispatched = self._dispatched_read(name, site)
        if guard is None or not isinstance(dispatched, ExitSet):
            return dispatched
        then, otherwise = partition((owner, guard, str(site)))
        return read.guarded(guard, then).union(
            dispatched.guarded(not_(guard), otherwise)
        )

    def dispatched_method_call(self, name, positional, kw_values, site):
        """``self.<name>(*positional, **kw_values)`` written as a method call
        (``method_call_sugar._source_instance_method_call``), where no
        recorded field shadows ``name`` and the one class-namespace lookup
        finds no class-field value for it: the one dispatched call
        (``_dispatched_or_owed``), whose member, binding and absent raise
        prove's one walk of the order decides (#7757 L3).  Nothing here
        decides that the class binds a ``def`` (nor its kind) before calling
        it.

        None where the read decides the callee here -- the instance's
        contents are not current (``attribute``'s undecided read or stored
        field), a recorded field holds ``name`` (that value is called), the
        lookup is not decided (the undecided read, called), or a class field
        holds a value (that value, read and called)."""
        from .object_identity import contents_current

        if not contents_current(self) or any(
            field.name == name for field in self.fields
        ):
            return None
        decided, _selected, class_value = self.class_member(name)
        if not decided or class_value is not None:
            return None
        return self._dispatched_or_owed(name, positional, kw_values, site)

    def guarded(self, formula):
        # A constructed state is not an unconditional field-store statement.
        # Retain the branch restriction for the constructor's state projection.
        from .guarded_receiver_state_value import GuardedReceiverStateValue

        return GuardedReceiverStateValue(self, formula)

    def with_field_store(self, name: str, value: FloorValue) -> "ObjectValue":
        """Return this receiver identity after one plain field store: the
        instance on the face where the store is the plain ``__dict__`` store
        (``plain_store_guard``, decided at prove), never a decision of its
        own (#7757 H1b)."""
        remaining = tuple(field for field in self.fields if field.name != name)
        return ObjectValue(
            self.class_name,
            (*remaining, ObjectField(name, value)),
            self.methods,
            self.class_fields,
            self.identity,
            self.defining_class,
            # The same object: it keeps its ``allocation`` and ``arrival``,
            # and the field is known on it from here (``stored_fields``).
            allocation=self.allocation,
            arrival=self.arrival,
            stored_fields=(*(n for n in self.stored_fields if n != name), name),
        )

    def setitem(self, index, value, site, ctx):
        """``self[index] = value``: CPython calls ``type(self).__setitem__``
        (``PyObject_SetItem``), an implicit special-method lookup on the type
        that no instance field shadows -- the one class-namespace lookup
        (``ClassDef.namespace_owner``).  When it decides that no class of the
        MRO binds ``__setitem__`` (``object`` does not), the store raises
        ``TypeError`` ("object does not support item assignment") before
        anything is stored; nothing else answers it.  Any other answer -- a
        class that binds it, a builtin base that does (a ``dict`` subclass),
        a lookup not decided -- is the implicit special-method call
        (``_implicit_item_call``)."""
        if self.lacks_item_method("__setitem__"):
            return self._item_method_absent(site, owner="ObjectValue.setitem")
        return self._implicit_item_call("__setitem__", (index, value), site, ctx)

    def delitem(self, index, site, ctx):
        """``del self[index]``: ``type(self).__delitem__``
        (``PyObject_DelItem``), the same implicit lookup as ``setitem``.  No
        class of the MRO binding it raises ``TypeError`` ("object doesn't
        support item deletion") whatever the key; any other answer is the
        implicit special-method call (``_implicit_item_call``)."""
        if self.lacks_item_method("__delitem__"):
            return self._item_method_absent(site, owner="ObjectValue.delitem")
        return self._implicit_item_call("__delitem__", (index,), site, ctx)

    def _implicit_item_call(self, name, arguments, site, ctx):
        """``obj[k] = v`` / ``del obj[k]`` through ``type(obj).<name>``: the
        implicit special-method call, through the one door every such call
        takes (``call_method_value``) -- the dispatched call prove's one walk
        decides where the receiver's class is named, a source override and a
        builtin base's method alike (#7757 L3, S1), and the unanswered call
        where the lookup does not decide it.  No body or base storage is
        read here, so what the call left of the receiver is not read: on
        each completed face the receiver after it is unknown
        (``python:receiver_after_call``), as for any undecided mutation, and
        what the method's contract states about it is joined at prove (step
        7).  The call's value is read through the one operand door
        (``consume_operands``), so every write it carries rides on to the
        statement."""
        if ctx is None:
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner=f"ObjectValue.{name}",
                blame=site,
                observed=f"implicit {name} without reduction context",
                requested="the store statement's context",
                fix="thread the caller context; zero-arg super requires its __class__ cell",
            )
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
        )
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
            _unknown_after,
        )

        return self.call_method_value(
            name,
            arguments,
            owner=f"ObjectValue.{name}",
            blame=site,
            ctx=ctx,
        ).and_then(
            lambda applied: consume_operands(
                lambda _call: ExitSet.completed(_unknown_after(site, name)),
                applied,
            )
        )

    def lacks_item_method(self, method: str) -> bool:
        """Whether ``type(self)`` binds no ``method`` (``__getitem__``,
        ``__setitem__``, ``__delitem__``): the one class-namespace lookup
        (``ClassDef.namespace_owner``) decides that no class of the MRO binds
        it, ``object`` and builtin bases included.  An implicit special-method
        lookup is on the type, so no instance field and no ``__getattr__``
        answers it: the item operation raises ``TypeError`` whatever its key
        and value are (``_item_method_absent``).  False whenever the lookup
        does not decide it, or no class statement is read."""
        definition = getattr(self.defining_class, "class_definition", None)
        if definition is None:
            return False
        decided, owner = definition.namespace_owner(method)
        return decided and owner is None

    @staticmethod
    def _item_method_absent(site, *, owner: str) -> ExitSet:
        """The ``TypeError`` an item operation raises when its type binds no
        item method (``lacks_item_method``): a halt at the operation's
        fragment, the builtin by binding."""
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner=owner
        )

    def plain_store_guard(self, name: str):
        """``python:plain_store(<class>, "<name>")`` (``receiver_dispatch.
        plain_store_atom``) over this instance's class term
        (``receiver_dispatch.class_value``): the guard under which
        ``self.name = value`` is the plain ``__dict__`` store.  Prove alone
        decides it, on the namespace rows (``consistency::plain_store_holds``:
        no ``__setattr__``, ``__getattribute__``, ``__slots__``, ``__dict__``
        and no binding of the name in the order); the lift never decides
        whether a store is plain (#7757 H1b), as a formal's store is guarded
        (``store_effect_sugar.attribute_mutation``).

        None where no class term is decided -- an instance not current, one
        whose ``__class__`` was stored, no class symbol (no workspace root),
        no class statement -- or ``name`` is a dunder name (``object``'s own
        data descriptors, which no namespace row states): the store is then
        only the call (``field_store_call``)."""
        from sugar_lift_py_tests.receiver_dispatch import (
            class_value,
            is_dunder,
            plain_store_atom,
        )

        if is_dunder(name) or any(item.name == "__class__" for item in self.fields):
            return None
        term = class_value(self)
        if term is None:
            return None
        return plain_store_atom(term, name)

    def field_store_call(self, name, value, site, ctx):
        """``self.name = value`` as the call it is where it is not the plain
        store: ``type(self).__setattr__(self, name, value)``, the one
        dispatched call (``_dispatched_or_owed``), whose member, binding and
        halts prove's one walk of the order decides
        (``consistency::dispatch_walk``) -- a source ``__setattr__``, a
        descriptor's ``__set__`` under ``object``'s, a property with no
        setter raising ``AttributeError``.  Where the instance names no class,
        the one unanswered call, owed.  Nothing is assumed of what it runs."""
        del ctx
        from .string_value import StringValue

        return self._dispatched_or_owed(
            "__setattr__", (StringValue(name), value), (), site
        )

    def plain_store_faces(self, name, stored, called, site):
        """The one shape of ``self.name = value`` on a source instance (#7757
        H1b): ``stored`` -- what the plain ``__dict__`` store leaves -- under
        ``plain_store_guard``, and ``called`` -- what the call
        (``field_store_call``) leaves -- under its complement, the two faces
        of one partition.  Where no guard is decided, ``called`` alone; so
        where the call is a deferred native operation (no exit set), which
        is the caller's to discharge."""
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.outcome.exit_set import partition

        plain = self.plain_store_guard(name)
        if plain is None or not isinstance(called, ExitSet):
            return called
        then, otherwise = partition(("ObjectValue.plain_store", plain, str(site)))
        return stored.guarded(plain, then).union(
            called.guarded(not_(plain), otherwise)
        )

    def after_field_store_call(self, result, site):
        """``after(alias)``: this receiver's object after the call its field
        store was (``field_store_call``) completed with ``result``, as a
        binding ``alias`` that held it holds it now.

        Where the call states what it did to the object
        (``call_site_value.receiver_after_its_call``, the one projection of a
        callee's effects on what its caller sees), that state
        (``object_identity.as_the_alias_holds``).  Where it states nothing --
        a body whose effects on it are not all field stores, the unanswered
        call -- the same object, of the same class, whose contents this frame
        no longer holds (``object_identity.arrived`` at the store): every
        field read of it is the undecided read, never the object as it was
        before the store, and never with the field assumed stored."""
        from .call_site_value import receiver_after_its_call
        from .object_identity import arrived, as_the_alias_holds

        stated = receiver_after_its_call(self, result)
        if stated is not None:
            return lambda alias: as_the_alias_holds(stated, alias)
        return lambda alias: arrived(alias, site)

    def setattr(self, name, value, site, ctx):
        """``self.name = value``; completes with this receiver after it, on
        two faces (``plain_store_faces``): under ``python:plain_store(<class>,
        "<name>")`` the instance with the field stored (``with_field_store``);
        under its complement the dispatched ``type(self).__setattr__`` call
        (``field_store_call``), its halts the store's, the receiver after it
        what the call states, else unknown (``after_field_store_call``).
        Where no class term is decided, the call alone.  The lift never
        decides that a store is plain, runs a ``__setattr__`` or a
        descriptor's ``__set__``, or that a property's store raises
        ``AttributeError``: prove does (#7757 H1b)."""
        from sugar_lift_py_tests.outcome import ExitSet

        return self.plain_store_faces(
            name,
            ExitSet.completed(self.with_field_store(name, value)),
            self._after_attribute_call(
                self.field_store_call(name, value, site, ctx), site
            ),
            site,
        )

    def _after_attribute_call(self, outcome, site):
        """What a store or delete that is a call (``field_store_call``, the
        unanswered ``type(self).__delattr__``) completes with: this receiver
        after the call (``after_field_store_call``); its halts are the
        statement's."""
        from sugar_lift_py_tests.outcome import ExitSet

        from .named_expression_value import carry_walrus_binds, peel_walrus_binds

        if not isinstance(outcome, ExitSet):
            # A deferred native operation of the body: the caller's to
            # discharge, as for any call.
            return outcome
        return outcome.and_then(
            lambda result: ExitSet.completed(
                carry_walrus_binds(
                    peel_walrus_binds(result)[0],
                    self.after_field_store_call(result, site)(self),
                )
            )
        )

    def delattr(self, name, site, ctx):
        """``del self.name``: ``type(self).__delattr__(self, name)``
        (``PyObject_SetAttr`` with no value), an implicit lookup on the type
        that no instance field shadows.

        Every delete is that call: the one dispatched ``__delattr__``
        (``_dispatched_delattr``), whose member, binding and halts prove's
        one walk of the order decides (``consistency::dispatch_walk``), as a
        formal's delete is (``store_effect_sugar.attribute_mutation``).  The
        lift never decides that the delete is ``object``'s plain removal of
        an instance field, that a property's delete raises
        ``AttributeError``, or that a name is absent (#7757 H1c: one way,
        the walk at prove; L3: the lift never decides a member's absence).
        The object after it is what the call states, else unknown
        (``after_field_store_call``).

        One delete is builtin semantics, not the class walk: ``del
        o.__class__`` where ``object`` binds both ``__class__`` and
        ``__delattr__`` for the receiver's class
        (``_deletes_object_class_slot``) raises ``TypeError`` whatever the
        object is.
        """
        if self._deletes_object_class_slot(name):
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="TypeError",
                site=site,
                owner="ObjectValue.delattr",
            )
        return self._dispatched_delattr(name, site)

    def _deletes_object_class_slot(self, name) -> bool:
        """Whether ``del self.name`` is ``object.__class__``'s delete under
        ``object``'s ``__delattr__`` (``PyObject_GenericSetAttr``): the one
        class-namespace lookup decides that ``object`` binds both ``name``
        and ``__delattr__`` for this receiver's class, and ``name`` is the
        ``__class__`` slot (``_OBJECT_CLASS_SLOT``).  Its setter
        (``object_set_class``, Objects/typeobject.c) is called with no value
        and raises ``TypeError`` ("can't delete __class__ attribute") before
        anything changes, whatever the object.  False for a receiver built
        with no class statement, whose type's MRO no lookup reads."""
        if vars(object).get(name) is not _OBJECT_CLASS_SLOT:
            return False
        definition = getattr(self.defining_class, "class_definition", None)
        if definition is None:
            return False
        decided, owner = definition.namespace_owner(name)
        delattr_decided, delattr_owner = definition.namespace_owner("__delattr__")
        return (
            decided
            and delattr_decided
            and owner == "object"
            and delattr_owner == "object"
        )

    def _dispatched_delattr(self, name, site):
        """``del self.name`` as the one dispatched call
        ``type(self).__delattr__(self, name)`` (``_dispatched_call``, #7757
        step 8): which ``__delattr__`` runs, how it binds, and whether it
        raises are decided once, at prove, by the one walk of the order
        (``consistency::dispatch_walk``); the object after it is the one
        ``after_field_store_call`` states.  Where the instance names no
        class, nothing decides it: the one undecided attribute mutation
        (``store_effect_sugar.undecided_attribute_mutation_faces``), both
        faces kept.  No ``AttributeError`` is named here."""
        from .string_value import StringValue

        dispatched = self._dispatched_call(
            "__delattr__", (StringValue(name),), (), site
        )
        if dispatched is None:
            from sugar_lift_py_tests.sugar.store_effect_sugar import (
                undecided_attribute_mutation_faces,
            )

            return undecided_attribute_mutation_faces(
                self,
                name,
                site,
                noun="delattr",
                method="__delattr__",
                owner="ObjectValue.delattr",
            )
        return self._after_attribute_call(dispatched, site)

    def iter_with(
        self, operation: IteratorOperation, ctx: ReduceContext | None
    ) -> ExitSet:
        """``iter(obj)`` is the constructor-bound ``__iter__`` data-model method,
        applied under the caller's context like any call (#7757 item 12)."""
        return self.call_method_value(
            "__iter__",
            (),
            owner=operation.owner,
            blame=operation.blame,
            ctx=ctx,
        )

    def next_with(self, operation: NextOperation, ctx: ReduceContext | None) -> ExitSet:
        return self.call_method_value(
            "__next__",
            (),
            owner=operation.owner,
            blame=operation.blame,
            ctx=ctx,
        )

    def subscript_with(
        self, operation: SubscriptOperation, ctx: ReduceContext | None
    ) -> ExitSet:
        # ``self[k]`` with no ``__getitem__`` on the type: ``TypeError``
        # ("object is not subscriptable") whatever ``k`` is.
        if self.lacks_item_method("__getitem__"):
            return self._item_method_absent(
                operation.site, owner="ObjectValue.subscript_with"
            )
        return operation.subscript_object(self, ctx)

    def project_sequence_with(
        self, operation: SequenceProjectionOperation, ctx: ReduceContext | None
    ) -> ExitSet:
        return operation.project_object(self, ctx)

    def inplace_binary_operator_with(
        self,
        operation: InplaceBinaryOperatorOperation,
        ctx: ReduceContext | None,
    ) -> ExitSet:
        method_name = _INPLACE_BINARY_DUNDER_METHODS.get(operation.operator)
        if method_name is None:
            return self._floor_gap(
                owner=operation.owner,
                blame=operation.blame,
                observed=f"{self.class_name}{operation.operator}={type(operation.right).__name__}",
                requested="object in-place binary data-model method",
                fix=(
                    f"add ObjectValue in-place data-model dispatch for "
                    f"operator `{operation.operator}`"
                ),
            )
        return self.call_method_value(
            method_name,
            (operation.right,),
            owner=operation.owner,
            blame=operation.blame,
            ctx=ctx,
        )

    def call_method_value(
        self,
        name: str,
        arguments: tuple[FloorValue, ...],
        *,
        owner: str,
        blame: object,
        ctx: Any | None = None,
        keywords: tuple[tuple[str, FloorValue], ...] = (),
        required_frame: object | None = None,
        halted_at: object | None = None,
    ) -> ExitSet:
        """The class's ``name`` called with this receiver: select on the
        class, bind, apply.

        ``halted_at``: the source fragment a halt of the call leaves at where
        ``blame`` is a synthetic call's content-addressed slot id, which
        states none (a ``with``'s ``__enter__``/``__exit__``,
        ``manager_protocol_construction._call_protocol_method``); the call's
        occurrence stays ``blame`` (``UnknownCalleeCallV1.faces``).

        This is the class side only: CPython's implicit special-method call
        (``iter(o)``, ``o == p``, ``o[k]``, ``format``: ``type(o).<name>``,
        which no instance field shadows) -- a class-field function there is
        bound to this receiver as on any read (``call_member``).  An
        explicit ``o.m(...)`` never selects here: it is ``o.m`` read through
        ``attribute`` (instance ``__dict__`` included), then that value --
        the member the read selected -- called
        (``method_call_sugar._source_instance_method_call``).

        The call is the one a plain call ``f(...)`` of a same-file function
        is: its coordinate and an edge, the method looked up and joined at
        prove (``call_member``, ``receiver_dispatch.dispatch_edge_call``,
        #7757 step 8).

        A class-field value the one class-namespace lookup finds
        (``class_member``) is read once and called (``call_member``); a
        lookup it does not decide is the unanswered call
        (``unanswered_method_call``), never a method of the roster found by
        its name.  Anything else -- a ``def`` the class wrote, whatever its
        kind, or no class member -- is the one dispatched call
        (``_dispatched_or_owed``): which member runs, how it binds, and
        whether the lookup raises are prove's one walk's to decide
        (``consistency::dispatch_walk``, #7757 L3).  The lift never reads the
        ``def``'s kind or frame to choose how to call it (a frame the call
        form authenticated, ``required_frame``, selects nothing here).
        """
        decided, _method, value = self.class_member(name)
        if not decided:
            return self.unanswered_method_call(
                name, arguments, keywords, blame, halted_at=halted_at
            )
        if value is not None:
            return self.call_member(
                name,
                value,
                arguments,
                owner=owner,
                blame=blame,
                ctx=ctx,
                keywords=keywords,
                required_frame=required_frame,
                halted_at=halted_at,
            )
        return self._dispatched_or_owed(
            name, arguments, keywords, blame, halted_at=halted_at
        )

    def call_member(
        self,
        name: str,
        member: object,
        arguments: tuple[FloorValue, ...],
        *,
        owner: str,
        blame: object,
        ctx: Any | None = None,
        keywords: tuple[tuple[str, FloorValue], ...] = (),
        required_frame: object | None = None,
        halted_at: object | None = None,
    ) -> ExitSet:
        """``self.<name>(*arguments, **keywords)`` where ``member`` is what
        the one class-namespace lookup selected for ``name``
        (``class_member``): read off this receiver its descriptor binds it,
        and the one application routine applies it.  Nothing selects it
        again by name.

        - On an instance that arrived by binding (``receiver_class_decided``
          False) which function runs is not decided: the unanswered call
          (``unanswered_method_call``).
        - Every function the class holds for ``name`` on an instance whose
          class is decided here -- a plain function it wrote, a
          ``staticmethod`` or ``classmethod`` it wrote (``ObjectMethodValue``),
          a function it holds as a field (``LambdaCallable``: ``f = lambda
          self: 1``, ``m = some_def``) -- is the one dispatch of a method
          call (#7757 step 8, ``receiver_dispatch.dispatch_edge_call``): the
          coordinate plus the dispatched edge carrying this instance and its
          class (``receiver_dispatch.class_value``), resolved at prove on the
          order the class's own proof states, and bound there as the kind
          its namespace row states binds (``consistency::dispatched_target``:
          the instance first, nothing, or the class).  Nothing here names
          which function runs or binds an implicit actual: the lookup above
          selected the member only to know that a method call is what this
          is.  Where no class can be named (no workspace root, a call with no
          site, contents this frame no longer holds) it is the one
          unanswered call (``unanswered_method_call``), owed.
        - A ``property`` is read, never called here: its getter answers the
          dispatched read (``attribute``).  Reached as a call (an
          implicit special-method call of a name the class binds to a
          property) it is the unanswered call, owed.
        - Anything else is no callable member here and refuses by name.

        A frame the caller requires must be the selected method's own."""
        from sugar_lift_py_tests.floor.lambda_callable import LambdaCallable

        if isinstance(member, (ObjectMethodValue, LambdaCallable)) and (
            not receiver_class_decided(self)
        ):
            # An instance that arrived by binding (``self`` in a method, a
            # formal) may be of a subclass that overrides ``name``: which
            # function runs is not decided here.  Where its class is an
            # input of the contract the call never reaches this door: it is
            # the dispatched edge over that input
            # (``receiver_dispatch.dispatch_on_receiver``, #7757 step 8).
            return self.unanswered_method_call(
                name, arguments, keywords, blame, halted_at=halted_at
            )
        if isinstance(member, ObjectMethodValue):
            if (
                required_frame is not None
                and member.source_call_frame_cid != required_frame.frame_cid
            ):
                return self._floor_gap(
                    owner=owner,
                    blame=blame,
                    observed=f"{self.class_name}.{name}",
                    requested="constructor-bound method",
                    fix=f"construct a diggable body for `{self.class_name}.{name}`",
                )
            if member.descriptor_kind == "property":
                return self.unanswered_method_call(
                    name, arguments, keywords, blame, halted_at=halted_at
                )
            return self._dispatched_or_owed(
                name, arguments, keywords, blame, halted_at=halted_at
            )
        if isinstance(member, LambdaCallable) and required_frame is None:
            return self._dispatched_or_owed(
                name, arguments, keywords, blame, halted_at=halted_at
            )
        return self._floor_gap(
            owner=owner,
            blame=blame,
            observed=f"{self.class_name}.{name}",
            requested="constructor-bound method",
            fix=f"construct a diggable body for `{self.class_name}.{name}`",
        )

    def _dispatched_or_owed(self, name, arguments, keywords, site, *, halted_at=None):
        """``self.<name>(...)``: the dispatched call (``_dispatched_call``),
        or, where it names no class, the one unanswered call, owed -- never
        a function chosen here.  ``halted_at``: where a halt of the call
        leaves when ``site`` states no fragment (``call_method_value``)."""
        dispatched = self._dispatched_call(
            name, arguments, keywords, site, halted_at=halted_at
        )
        if dispatched is not None:
            return dispatched
        return self.unanswered_method_call(
            name, arguments, keywords, site, halted_at=halted_at
        )

    def _dispatched_call(
        self, name, arguments, keywords, site, *, read=False, halted_at=None
    ):
        """``self.<name>(...)`` -- ``read``: ``self.<name>`` -- on this
        instance, whose class is decided here, as the one dispatched method
        call (#7757 step 8): its coordinate plus the edge whose receiver
        class is this instance's class and every field its ``__dict__`` may
        hold now (``receiver_dispatch.class_value``: ``python:instance(<class>,
        <field>...)``).  Prove resolves ``name`` on the order the class's own
        proof states and binds it by the kind its row states
        (``consistency::dispatched_target``), the same resolution a call on a
        parameter whose class a caller supplies gets.

        The instance a class's constructor contract makes
        (``tree_enumerate.class_universe_outcome``) is the instance a call of
        that class constructs: the contract is joined only by calls of the
        class it is named for, so the class it states here is the one that
        call supplies.  None where the class names no join symbol (no
        workspace root) or the call has no site: no edge could name a class
        either."""
        if site is None:
            return None
        from sugar_lift_py_tests.receiver_dispatch import (
            class_value,
            dispatch_edge_call,
        )

        receiver_class = class_value(self)
        if receiver_class is None:
            return None
        return dispatch_edge_call(
            name,
            self,
            receiver_class,
            tuple(arguments),
            tuple(keywords),
            site,
            read=read,
            halted_at=halted_at,
        )

    def has_method(self, name: str) -> "bool | None":
        """Whether the one class-namespace lookup selects a member for
        ``name`` on this receiver's type (``class_member``): a source method,
        or a class field (a function there is a method too: ``call_member``
        binds it); None when the lookup does not decide it.  Never False for
        a name the class binds by an assignment: an implicit special-method
        call (``__eq__ = ...``) never falls to the default behaviour."""
        decided, method, value = self.class_member(name)
        if not decided:
            return None
        return method is not None or value is not None

    def class_member(self, name: str) -> tuple:
        """``(decided, method, value)``: the member ``name`` read on this
        receiver's type is -- the one class-namespace lookup over the
        receiver's class (``ClassDefinitionValue.namespace_member``, #7757),
        the one resolution every reader of a class member reads (an
        attribute read, an explicit or implicit method call, a comparison, a
        store).

        A ``def`` the holding class's body left last is ``method``: this
        receiver's roster function that very statement wrote, the holding
        class its defining class.  Any other binding is ``value``, the
        class-body field it bound.  Both None when no class binds the name or
        a builtin class does.  Not decided -- ``(False, None, None)`` --
        whenever that lookup is not.

        A receiver built with no class statement has only its own roster and
        class fields (and its class value's bases' fields): no other class
        is there to ask, and no order of its bindings either -- a name it
        holds both as a method and as a field is not decided.
        """
        defining = self.defining_class
        definition = getattr(defining, "class_definition", None)
        if definition is None:
            method = next(
                (method for method in reversed(self.methods) if method.name == name),
                None,
            )
            holders = (
                self,
                *(defining._c3_tail() if hasattr(defining, "_c3_tail") else ()),
            )
            value = next(
                (
                    field.value
                    for holder in holders
                    for field in reversed(getattr(holder, "class_fields", ()))
                    if getattr(field, "name", None) == name
                ),
                None,
            )
            if method is not None and value is not None:
                return False, None, None
            return True, method, value
        decided, _found, _holder, method, value = defining.namespace_member(
            name,
            lambda holder: (
                method for method in self.methods if method.defining_class is holder
            ),
        )
        if not decided:
            return False, None, None
        return True, method, value

    def unanswered_method_call(self, name, arguments, keywords, site, *, halted_at=None):
        """``self.<name>(...)`` whose member the one class-namespace lookup
        does not decide (``class_member``): the one unanswered call
        (``UnknownCalleeCallV1``), two-faced and owed, its completion the
        call's own result coordinate.  No method of the roster is assumed to
        answer.  ``halted_at``: where its halt leaves when ``site`` is a
        synthetic call's slot id (``call_method_value``)."""
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1

        from .object_identity import call_operand_terms

        target = f"{self.class_name}.{name}"
        term_owner = str(site)
        callsite = CallSiteValue(
            target_name=target,
            arg_values=(self, *arguments, *(value for _name, value in keywords)),
            parameters=(),
            term=ctor(
                call_symbol(target),
                # The receiver and each actual as the call finds it
                # (``identity_term``).
                call_operand_terms(
                    (self, *arguments), keywords, site, owner=term_owner
                ),
                symbol_kind="coordinate",
            ),
            body=None,
            keyword_names=tuple(keyword for keyword, _value in keywords),
            site=site,
        )
        return UnknownCalleeCallV1(target).faces(callsite, site, halted_at=halted_at)

    def _floor_gap(
        self,
        *,
        owner: str,
        blame: object,
        observed: str,
        requested: str,
        fix: str,
    ) -> NoReturn:
        from sugar_lift_py_tests.gap.panic import construction_panic
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

        info = ConstructionGap(
            owner=owner,
            blame=str(blame),
            observed=observed,
            requested=requested,
            fix=fix,
            gap_kind=(
                GapKind.CONSTRUCTOR
                if requested.startswith("constructor-bound ")
                else GapKind.FLOOR
            ),
            gap_locus=GapLocus.CONSTRUCTION,
        )
        construction_panic(info)


_INPLACE_BINARY_DUNDER_METHODS = {
    "+": "__iadd__",
    "-": "__isub__",
    "*": "__imul__",
    "/": "__itruediv__",
    "//": "__ifloordiv__",
    "%": "__imod__",
    "**": "__ipow__",
    "@": "__imatmul__",
    "&": "__iand__",
    "|": "__ior__",
    "^": "__ixor__",
    "<<": "__ilshift__",
    ">>": "__irshift__",
}


def receiver_class_decided(receiver) -> bool:
    """Whether the class whose namespace a method call on ``receiver`` reads
    is decided here: a source class value itself (``Cls.m``, ``super()`` in a
    ``classmethod`` given the class), or an instance a construction in the
    frame reading it made (``allocation``: its class is the class the call
    made it of).  An instance that arrived by binding (``self`` in a method,
    any formal) may be of a subclass that overrides the method: not decided
    here.  A plain method call on either is dispatched at prove (#7757 step
    8): on a decided instance over its class (``ObjectValue.
    _dispatched_call``), on an arrived one over its contract's
    ``class:<param>`` input where it has one
    (``receiver_dispatch.dispatch_on_receiver``)."""
    from sugar_lift_py_tests.floor.class_definition_value import (
        ClassDefinitionValue,
    )

    if isinstance(receiver, ClassDefinitionValue):
        return True
    return isinstance(receiver, ObjectValue) and receiver.allocation is not None


def bind_call(
    target_name: str,
    arguments,
    keywords,
    *,
    frame,
    parameters,
    frame_cid,
    formal_coordinate_cids,
    lexical_defining_class=None,
    ctx,
    owner: str,
    blame: object,
    refuse,
    term=None,
    defaults=(),
    **testimony,
):
    """Bind ``arguments``/``keywords`` to a source frame: the call, unapplied.

    Every call binds here, whatever form it is written in: a plain call
    ``f(...)`` (``CallSiteSugar``), a computed callee ``(lambda x: ...)(...)``
    (``ComputedCallSugar``), a call with ``*``/``**`` (``SpreadCallSugar``)
    and a class call (the class statement's constructor frame); a method
    call is the one dispatched call (``receiver_dispatch.
    dispatch_edge_call``), never bound here.  The frame's own ``bind_actuals`` puts
    every actual in its formal slot; the result is the bodiless
    ``CallSiteValue`` whose actuals the call's edge supplies
    (``lambda_callable.definition_edge_call``): no body is bound, and none is
    ever applied (#7757 step 6).  With no frame the actuals are taken as already in formal order, the keyword
    actuals after the positional ones under their names.

    ``term`` is the call coordinate when the call form has its own (a plain
    call's ``call:<name>(...)``); ``testimony`` is what that form
    authenticated about the call (its occurrence, its exception type, its
    import target), carried on the value unchanged.

    ``defaults`` are the ``(key, value)`` pairs a called lambda value carries
    (``LambdaCallable.defaults``), or a method's class
    (``ClassDefinitionValue.method_defaults``): the values its lambda
    expression, or its ``def`` statement in the class body, evaluated for its
    defaults.  They are bound under their keys where the frame binds
    the actuals, so a formal the call omits binds the carried value
    (``DefaultValueSugar``).
    """
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.ir import ctor

    arg_values = tuple(arguments)
    keyword_names: tuple[str, ...] = ()
    bound_source_actuals = None
    if frame is None:
        arg_values = arg_values + tuple(value for _name, value in keywords)
        keyword_names = tuple(name for name, _value in keywords)
    else:
        from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap
        from sugar_lift_py_tests.sugar.default_value_sugar import (
            bind_carried_defaults,
        )

        try:
            bound_source_actuals = frame.bind_actuals(
                arg_values, keywords, bind_carried_defaults(ctx, defaults)
            )
        except SourceCallBindingGap as exc:
            refuse(
                owner=owner,
                blame=blame,
                observed=str(exc),
                requested="actuals matching authenticated source signature",
                fix="preserve exact defaults/variadics or keep the call loud",
            )
        arg_values = bound_source_actuals.actuals
    if term is None:
        from .object_identity import call_operand_terms

        # Each actual in formal order as the call finds it (``identity_term``).
        term = ctor(
            call_symbol(target_name),
            call_operand_terms(arg_values, (), blame, owner=f"{owner} call argument"),
            symbol_kind="contract-target",
        )
    return CallSiteValue(
        target_name=target_name,
        arg_values=arg_values,
        parameters=parameters,
        term=term,
        keyword_names=keyword_names,
        body=None,
        site=blame,
        source_call_frame_cid=frame_cid,
        formal_coordinate_cids=formal_coordinate_cids,
        bound_source_actuals=bound_source_actuals,
        lexical_defining_class=lexical_defining_class,
        **testimony,
    )
