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
# ``TypeError`` whatever the object (``ObjectValue._builtin_descriptor_delete``).
_OBJECT_CLASS_SLOT = vars(object)["__class__"]


def _builtin_binds_data_descriptor(owner: str, name: str) -> bool:
    """Whether the builtin class ``owner`` (its name in ``builtins``) binds
    ``name`` in its own namespace to a data descriptor: a value whose type
    defines ``__set__`` or ``__delete__`` (``object.__class__``)."""
    import builtins

    held = type(vars(getattr(builtins, owner)).get(name))
    return hasattr(held, "__set__") or hasattr(held, "__delete__")


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
    # Instance field names removed by an authenticated delattr: names the
    # instance's ``__dict__`` does not hold now.  A read of one, like any
    # name no field holds, is the dispatched read whose absence prove's one
    # walk of the order decides (``attribute``; ``receiver_dispatch.
    # class_value`` leaves these out of the fields it states).
    deleted_instance_fields: tuple[str, ...] = dataclass_field(
        default=(), compare=False
    )
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
    # current (``attribute``).  An arrival by binding clears them
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

        CPython reads ``o.name`` (``object.__getattribute__``,
        ``_PyObject_GenericGetAttrWithDict``) as: a data descriptor the
        class's MRO binds for ``name`` wins; else the instance ``__dict__``
        entry; else the class's attribute (a method, a class field); else
        ``AttributeError``.  So on an instance that is not current, every
        answer but a data descriptor's waits on the ``__dict__`` this frame
        does not hold -- a recorded field, a deleted one, a method or class
        field it may shadow, a name nothing here records: each is the
        undecided attribute read (``undecided_attribute_result``) over the object's
        identity (``identity_term``).  Only a name the class binds to a data
        descriptor (``_class_data_descriptor``) is answered from the class,
        and never from the instance's fields.

        A field a store in this frame put on the instance
        (``stored_fields``, the one field store) is the instance's field now,
        current or not: the store makes that field known; the rest of an
        arrived instance stays as its currency says.

        A class-field value (a class-body binding other than a ``def``) is
        read off the class by the one class-namespace lookup
        (``class_member``: the binding the class body left last): no proof
        row states a field's value, so the lift is its only answerer.  A
        lookup that does not decide is the undecided read
        (``undecided_attribute_result``).

        Every other name -- a ``def`` the class wrote (plain, static, class
        method or property), or no class member at all, or a field a delete
        removed -- is the dispatched read (``_dispatched_call(read=True)``):
        which member it finds, how it binds, and whether it raises
        ``AttributeError`` are decided once, at prove, by the one walk of the
        order (``consistency::dispatch_walk``, #7757 L3), never here.  Where
        the read names no class it is the undecided read.  ``o.m(...)``
        written as a call is the dispatched call itself
        (``dispatched_method_call``)."""
        from .object_identity import contents_current

        current = contents_current(self)
        if not current and name in self.stored_fields:
            # A store this frame made: the field is the instance's now,
            # whatever the rest of an arrived instance holds.  A stored name
            # meets no data descriptor (``with_field_store`` refuses one).
            for field in reversed(self.fields):
                if field.name == name:
                    from sugar_lift_py_tests.outcome import ExitSet

                    return ExitSet.completed(field.value)
        if not current and not self._class_data_descriptor(name):
            return undecided_attribute_result(
                self, name, site, owner="ObjectValue.attribute"
            )
        for field in reversed(self.fields if current else ()):
            if field.name == name:
                from sugar_lift_py_tests.outcome import ExitSet

                return ExitSet.completed(field.value)
        decided, _selected, class_value = self.class_member(name)
        if not decided:
            return undecided_attribute_result(
                self, name, site, owner="ObjectValue.attribute"
            )
        if class_value is not None:
            from sugar_lift_py_tests.floor.lambda_callable import LambdaCallable
            from sugar_lift_py_tests.outcome import ExitSet

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

                return ExitSet.completed(BoundMethodValue(self, name, class_value))
            return ExitSet.completed(class_value)
        # No recorded field answers the name (a field a delete removed
        # included), and the one class-namespace lookup found no class-field
        # value for it: a ``def`` the class wrote (plain, ``staticmethod``,
        # ``classmethod``, ``property``) or nothing.  Which member that is,
        # what kind it binds as, and whether the read raises
        # ``AttributeError`` -- no class of the order binds it, the
        # ``__dict__`` may not hold it, no ``__getattr__`` or
        # ``__getattribute__`` answers -- are the one walk of the order's to
        # decide, at prove (``consistency::dispatch_walk``, #7757 NEW-7/L3):
        # the read is the dispatched read on this instance, its class and the
        # fields its ``__dict__`` may hold now (``receiver_dispatch.
        # class_value``: a deleted field is not one of them), both faces
        # kept.  Where it names no class, the one undecided read.
        dispatched = self._dispatched_call(name, (), (), site, read=True)
        if dispatched is not None:
            return _attribute_owned(dispatched)
        return undecided_attribute_result(
            self, name, site, owner="ObjectValue.attribute"
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

    def reads_plain_field(self, name: str) -> bool:
        """Whether a read of ``name`` off this instance, while its
        ``__dict__`` holds ``name``, is that entry by Python's own rule
        (``object.__getattribute__``, ``_PyObject_GenericGetAttrWithDict``):
        it completes with the stored value.

        All of: the instance's MRO is read and every class of it is a source
        class or ``object``; the one class-namespace lookup decides that no
        class of it binds ``name`` (so no data descriptor wins over the
        entry, ``namespace_owner``); and the ``__getattribute__`` the lookup
        selects is ``object``'s.  A class's own ``__getattr__`` is never
        reached: the entry is found first.  Anything else -- no class
        statement, an MRO not read, a builtin base, a member of the name, a
        hook bound or not decided -- is False.  Read by a class's contract
        to state that a read of a field its construction set completes
        (``ConstructedInstanceValue.post_formula``, #7757 step 7)."""
        from sugar_source_tree.nodes import ClassDef

        definition = getattr(self.defining_class, "class_definition", None)
        if definition is None:
            return False
        order = definition.method_resolution_order()
        if order is None or any(
            not isinstance(entry, ClassDef) and entry != "object" for entry in order
        ):
            return False
        decided, owner = definition.namespace_owner(name)
        if not decided or owner is not None:
            return False
        decided, owner = definition.namespace_owner("__getattribute__")
        return decided and isinstance(owner, str) and owner == "object"

    def guarded(self, formula):
        # A constructed state is not an unconditional field-store statement.
        # Retain the branch restriction for the constructor's state projection.
        from .guarded_receiver_state_value import GuardedReceiverStateValue

        return GuardedReceiverStateValue(self, formula)

    def with_field_store(self, name: str, value: FloorValue) -> "ObjectValue":
        """Return this receiver identity after one plain field store.

        The plain store is the one the class lookup decides
        (``field_store_route``); every store reaches this through that
        decision (``setattr``), never a decision of its own.  Reached for a
        store the route does not decide plain -- a refused property, whose
        store halts with ``AttributeError`` in ``setattr``, or a store that
        runs code -- it refuses by name: the object with the field assumed
        stored is never answered."""
        kind, _member = self.field_store_route(name)
        if kind != "plain":
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                blame=f"{self.class_name}.{name}",
                owner="ObjectValue.with_field_store",
                observed=f"field store route {kind!r}, not the plain store",
                requested="the store the one class lookup decides (setattr)",
                fix="reach the store through ObjectValue.setattr",
            )
        remaining = tuple(field for field in self.fields if field.name != name)
        # Restore retires the deleted-field mark for this name.
        still_deleted = tuple(d for d in self.deleted_instance_fields if d != name)
        return ObjectValue(
            self.class_name,
            (*remaining, ObjectField(name, value)),
            self.methods,
            self.class_fields,
            self.identity,
            still_deleted,
            self.defining_class,
            # The same object: it keeps its ``allocation`` and ``arrival``,
            # and the field is known on it from here (``stored_fields``).
            allocation=self.allocation,
            arrival=self.arrival,
            stored_fields=(*(n for n in self.stored_fields if n != name), name),
        )

    def _store_descriptor(self, name: str) -> "bool | None":
        """Whether a store or delete of ``name`` on this receiver meets a
        source property of its type -- the member the one class-namespace
        lookup selects (``class_member``).  None when the lookup does not
        decide it: a data descriptor nothing here read may answer the
        store."""
        decided, method, _value = self.class_member(name)
        if not decided:
            return None
        return method is not None and method.descriptor_kind == "property"

    def _refuse_undecided_store(self, name: str, site, owner: str) -> NoReturn:
        """A store or delete of ``name`` whose class member the one lookup
        does not decide: refused by name, never an instance-field store."""
        self._floor_gap(
            owner=owner,
            blame=site,
            observed=f"{self.class_name}.{name}: class member not decided",
            requested="the class member the one class-namespace lookup selects",
            fix="decide the class's namespace for the name (ClassDef.namespace_binds)",
        )

    def setitem(self, index, value, site, ctx):
        """``self[index] = value``: CPython calls ``type(self).__setitem__``
        (``PyObject_SetItem``), an implicit special-method lookup on the type
        that no instance field shadows -- the one class-namespace lookup
        (``ClassDef.namespace_owner``).  When it decides that no class of the
        MRO binds ``__setitem__`` (``object`` does not), the store raises
        ``TypeError`` ("object does not support item assignment") before
        anything is stored; nothing else answers it.  Any other answer -- a
        class that binds it, a builtin base that does, a lookup not decided
        -- is not written here and still refuses by name."""
        if self.lacks_item_method("__setitem__"):
            return self._item_method_absent(site, owner="ObjectValue.setitem")
        return super().setitem(index, value, site, ctx)

    def delitem(self, index, site, ctx):
        """``del self[index]``: ``type(self).__delitem__``
        (``PyObject_DelItem``), the same implicit lookup as ``setitem``.  No
        class of the MRO binding it raises ``TypeError`` ("object doesn't
        support item deletion") whatever the key; any other answer is not
        written here and still refuses by name."""
        if self.lacks_item_method("__delitem__"):
            return self._item_method_absent(site, owner="ObjectValue.delitem")
        return super().delitem(index, site, ctx)

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

    def authenticates_plain_attribute_store(self, name: str) -> bool:
        """Whether ``self.name = value`` is an ordinary instance-field store."""
        return self._store_descriptor(name) is False

    def field_store_route(self, name: str) -> tuple:
        """``(kind, member)``: what ``self.name = value`` runs, decided by
        the one class-namespace lookup on this receiver's type.  The store
        is ``type(self).__setattr__(self, name, value)``
        (``PyObject_SetAttr``): an implicit special-method lookup on the
        type, which no instance field shadows.

        - ``("setattr", method)``: a source class of the MRO binds
          ``__setattr__`` to a plain function its body wrote
          (``class_member``).  The store is a call of that function on this
          receiver.
        - Where the lookup's owner is the builtin ``object``, the store is
          ``object.__setattr__`` (``PyObject_GenericSetAttr``), which the
          class's binding of ``name`` decides:
          ``("refused", None)``, a source ``property`` -- a data descriptor
          whose setter is not a member this lookup selects, so the store
          raises ``AttributeError``;
          ``("descriptor", (descriptor, method))``, a class field holding an
          instance of a source class whose type binds ``__set__`` to a plain
          function its body wrote -- the store is a call of that function on
          the descriptor;
          ``("plain", None)``, no class binding ``name``, or a function (a
          non-data descriptor), or a value that is no data descriptor -- the
          instance-field store (``with_field_store``).  A name a builtin
          owner binds to a data descriptor (``_class_data_descriptor``:
          ``object.__class__``) is not the plain store: undecided, below.
        - ``("undecided", None)``: anything else.  A lookup of
          ``__setattr__`` or of ``name`` that is not decided (an unread
          base, a decorator, a store on the class, ``@x.setter``); a builtin
          base other than ``object`` that holds a ``__setattr__`` of its own
          (``BaseException``: its slot is not read here); a ``__setattr__``
          or ``__set__`` that is not a plain function the class wrote; a
          class field whose value's descriptor protocol is not read here.
          The store is the one unanswered call (``field_store_call``).

        A receiver built with no class statement has only its own roster
        (``class_member``): a ``__setattr__`` there is that function, none is
        the default store.  A name its roster does not bind and ``object``
        binds to a data descriptor (``__class__``) is undecided all the same
        (``_unread_object_descriptor``): that descriptor's ``__set__``, or one
        an unread class of its MRO binds, answers the store."""
        undecided = ("undecided", None)
        definition = getattr(self.defining_class, "class_definition", None)
        if definition is None:
            decided, method, value = self.class_member("__setattr__")
            if not decided or value is not None:
                return undecided
            if method is not None:
                return ("setattr", method) if _plain_function(method) else undecided
        else:
            decided, owner = definition.namespace_owner("__setattr__")
            if not decided or owner is None:
                return undecided
            if isinstance(owner, str):
                if owner != "object":
                    return undecided
            else:
                decided, method, _value = self.class_member("__setattr__")
                if not decided or not _plain_function(method):
                    return undecided
                return "setattr", method
        decided, method, value = self.class_member(name)
        if not decided:
            return undecided
        if method is not None:
            if method.descriptor_kind == "property":
                return "refused", None
            return "plain", None
        if value is None:
            if self._class_data_descriptor(name) or self._unread_object_descriptor(
                name
            ):
                # A builtin owner's data descriptor answers the store, not
                # the instance ``__dict__``: ``o.__class__ = C`` is
                # ``object.__class__``'s setter (``object_set_class``), which
                # gives the object another class or raises ``TypeError``.
                # Its ``__set__`` is not read here: the unanswered call, and
                # the object after it of a class this frame does not know.
                # So on a receiver built with no class statement, whose
                # type's MRO no lookup reads (``_unread_object_descriptor``).
                return undecided
            return "plain", None
        return _descriptor_route(value)

    def field_store_runs_code(self, name: str) -> bool:
        """Whether ``self.name = value`` runs, or may run, code beyond the
        instance-field store (``field_store_route``): a ``__setattr__``, a
        descriptor's ``__set__``, or a class lookup that does not decide.
        Such a store reaches what a call reaches; a plain one changes this
        object only (``builtin_container_call_sugar._may_change``)."""
        return self.field_store_route(name)[0] not in ("plain", "refused")

    def field_store_call(self, name, value, site, ctx):
        """The call ``self.name = value`` is, where the store runs code
        (``field_store_route``), applied under ``ctx`` like any call: the
        source ``__setattr__`` the lookup selected, called on this receiver
        with the name and the value; a source descriptor's ``__set__``,
        called on the descriptor with this receiver and the value
        (``call_member``, the one application); or, where the lookup does
        not decide, the one unanswered call ``type(self).__setattr__``
        (``unanswered_method_call``): two-faced and owed, nothing assumed of
        what it runs."""
        from .string_value import StringValue

        kind, member = self.field_store_route(name)
        if kind == "setattr":
            return self.call_member(
                "__setattr__",
                member,
                (StringValue(name), value),
                owner="ObjectValue.field_store_call",
                blame=site,
                ctx=ctx,
            )
        if kind == "descriptor":
            descriptor, method = member
            return descriptor.call_member(
                "__set__",
                method,
                (self, value),
                owner="ObjectValue.field_store_call",
                blame=site,
                ctx=ctx,
            )
        return self.unanswered_method_call(
            "__setattr__", (StringValue(name), value), (), site
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
        """``self.name = value``, decided by the one class lookup
        (``field_store_route``); completes with this receiver after it.

        The plain store is the instance-field store.  A property is a data
        descriptor: a getter without an authenticated setter raises
        ``AttributeError`` on the **store** path — never by consulting
        :meth:`attribute` / the read path.  A store that runs code is that
        call (``field_store_call``): its halts are the store's, and the
        receiver after it is what the call states, else unknown
        (``after_field_store_call``), carrying what the call carries to its
        caller.
        """
        from sugar_lift_py_tests.outcome import ExitSet

        kind, _member = self.field_store_route(name)
        if kind == "refused":
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="AttributeError",
                site=site,
                owner="ObjectValue.setattr",
            )
        if kind == "plain":
            return ExitSet.completed(self.with_field_store(name, value))
        return self._after_attribute_call(
            self.field_store_call(name, value, site, ctx), site
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
        """``del self.name`` via instance-field delete or property refusal.

        Properties are data descriptors: a getter without an authenticated
        deleter raises ``AttributeError`` on the **delete** path — never by
        consulting :meth:`attribute` / the read path.  Missing ordinary
        fields also raise ``AttributeError``.

        Whether a field is missing is read off the recorded fields only when
        they are the object's fields now (``object_identity.contents_current``).
        On an instance that arrived by binding, another alias may have
        stored or deleted the name since: the delete is undecided
        (``_undecided_delattr``), never ``AttributeError`` decided from the
        fields it arrived with.

        A name a builtin owner binds to a data descriptor
        (``_class_data_descriptor``: ``object.__class__``) is that
        descriptor's delete, never the instance-field delete
        (``_builtin_descriptor_delete``); so is one ``object`` binds to a
        data descriptor on a receiver built with no class statement whose
        roster binds nothing for it (``_unread_object_descriptor``).
        """
        from sugar_lift_py_tests.outcome import ExitSet

        from .object_identity import contents_current

        descriptor = self._store_descriptor(name)
        if descriptor is None:
            self._refuse_undecided_store(name, site, "ObjectValue.delattr")
        if descriptor:
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="AttributeError",
                site=site,
                owner="ObjectValue.delattr",
            )
        if self._class_data_descriptor(name) or self._unread_object_descriptor(name):
            return self._builtin_descriptor_delete(name, site)
        current = contents_current(self)
        remaining = tuple(field for field in self.fields if field.name != name)
        if current and len(remaining) == len(self.fields):
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="AttributeError",
                site=site,
                owner="ObjectValue.delattr",
            )
        deleted = (
            self.deleted_instance_fields
            if name in self.deleted_instance_fields
            else (*self.deleted_instance_fields, name)
        )
        from dataclasses import replace

        # The same object: it keeps its class (``defining_class``, which the
        # one class-namespace lookup reads), its ``allocation`` and
        # ``arrival``, and its own kind of receiver.
        after = replace(self, fields=remaining, deleted_instance_fields=deleted)
        if not current:
            return self._undecided_delattr(name, after, site)
        return ExitSet.completed(after)

    def _builtin_descriptor_delete(self, name, site):
        """``del self.name`` where a builtin owner binds ``name`` to a data
        descriptor (``_class_data_descriptor``).  The delete is
        ``type(self).__delattr__(self, name)`` (``PyObject_SetAttr`` with no
        value), an implicit lookup on the type.

        Where the one class-namespace lookup decides that ``__delattr__`` is
        ``object``'s (``PyObject_GenericSetAttr``) and the descriptor is
        ``object.__class__`` (``_OBJECT_CLASS_SLOT``), its setter
        (``object_set_class``, Objects/typeobject.c) is called with no value
        and raises ``TypeError`` ("can't delete __class__ attribute") before
        anything changes, whatever the object: the certain halt.

        Anything else -- a ``__delattr__`` the lookup does not decide to be
        ``object``'s, another builtin descriptor whose ``__delete__`` is not
        read here, a receiver built with no class statement, whose type's
        MRO no lookup reads (``_unread_object_descriptor``) -- is the one
        unanswered call ``type(self).__delattr__`` (two-faced, owed), the
        object after it the one ``after_field_store_call`` states.  Nothing
        is guessed of what it runs."""
        from .string_value import StringValue

        definition = getattr(self.defining_class, "class_definition", None)
        decided = delattr_decided = False
        owner = delattr_owner = None
        if definition is not None:
            decided, owner = definition.namespace_owner(name)
            delattr_decided, delattr_owner = definition.namespace_owner(
                "__delattr__"
            )
        if (
            decided
            and delattr_decided
            and owner == "object"
            and delattr_owner == "object"
            and vars(object).get(name) is _OBJECT_CLASS_SLOT
        ):
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="TypeError",
                site=site,
                owner="ObjectValue.delattr",
            )
        return self._after_attribute_call(
            self.unanswered_method_call("__delattr__", (StringValue(name),), (), site),
            site,
        )

    def _undecided_delattr(self, name, after, site):
        """``del self.name`` on an instance whose fields are not current: two
        faces (``ExitSet.two_faced``), both owing the ``undecided`` member.

        Whether ``name`` is in the instance's ``__dict__`` now is not
        decided here, so the delete may complete or raise.  It completes,
        leaving ``after`` -- the same object with ``name`` gone, still not
        current, keeping its ``arrival`` -- only under
        ``python:delattr.completes(python:delattr(<receiver>, <name>,
        <site>))``, the receiver named by its identity (``identity_term``)
        and the atom keyed on the exact source site; the complement halts
        with an ``UndeterminedRaiseEffect``.  No ``AttributeError`` is
        named."""
        from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
        from sugar_lift_py_tests.ir import atomic, ctor, str_const
        from sugar_lift_py_tests.occurrence import occurrence_key
        from sugar_lift_py_tests.outcome import ExitSet

        from .object_identity import identity_term

        receiver_term = identity_term(self, site, "receiver", owner=str(site))
        key = occurrence_key(site)
        completes = atomic(
            "python:delattr.completes",
            [
                ctor(
                    "python:delattr",
                    (receiver_term, str_const(name), str_const(key)),
                )
            ],
        )
        return ExitSet.two_faced(
            after,
            UndeterminedRaiseEffect(
                blame=str(site),
                occurrence=key,
                producer_node_owner="ObjectValue.delattr",
                site=site,
            ),
            guard=completes,
            site=site,
        )

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
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1

        target = f"{self.class_name}.{name}"
        term_owner = str(site)
        callsite = CallSiteValue(
            target_name=target,
            arg_values=(self, *arguments, *(value for _name, value in keywords)),
            parameters=(),
            term=ctor(
                call_symbol(target),
                [value.to_term(owner=term_owner) for value in (self, *arguments)]
                + [
                    ctor(
                        "py.kwarg",
                        [str_const(keyword), value.to_term(owner=term_owner)],
                    )
                    for keyword, value in keywords
                ],
                symbol_kind="coordinate",
            ),
            body=None,
            keyword_names=tuple(keyword for keyword, _value in keywords),
            site=site,
        )
        return UnknownCalleeCallV1(target).faces(callsite, site, halted_at=halted_at)

    def _class_data_descriptor(self, name: str) -> bool:
        """Whether the class's binding of ``name`` is a data descriptor,
        which wins over the instance ``__dict__`` (``attribute``).

        The owner is the one class-namespace lookup on the type
        (``ClassDef.namespace_owner``, the MRO read by binding).  A builtin
        owner's binding is a data descriptor when its type defines
        ``__set__`` or ``__delete__`` (``object.__class__``); a source
        owner's when the value its namespace holds is the one its body bound
        (``namespace_value_is_body``) and that is a ``property`` defined by
        that class (``descriptor_kind``) -- a property is a data descriptor
        with or without a setter.  Anything not decided -- no class
        statement, a lookup the walk does not decide, no class binding the
        name, a class field (its value's own descriptor protocol is not read
        here) -- is not one."""
        definition = getattr(self.defining_class, "class_definition", None)
        if definition is None:
            return False
        decided, owner = definition.namespace_owner(name)
        if not decided or owner is None:
            return False
        if isinstance(owner, str):
            return _builtin_binds_data_descriptor(owner, name)
        # A source owner's member is the one ``class_member`` selects.
        return self._store_descriptor(name) is True

    def _unread_object_descriptor(self, name: str) -> bool:
        """Whether a store or delete of ``name`` on this receiver, built with
        no class statement, meets a data descriptor no lookup reads here:
        its own roster (``class_member``) binds nothing for ``name``, and
        ``object``, which every type's MRO ends with, binds it to one
        (``object.__class__``).  Its type's MRO is not read, so whether a
        class between overrides it, and what its ``__set__``/``__delete__``
        runs (``object_set_class``: another class, or ``TypeError``), is not
        decided: never the instance field.  False for a receiver whose class
        statement is read: ``_class_data_descriptor`` answers it."""
        if getattr(self.defining_class, "class_definition", None) is not None:
            return False
        if not _builtin_binds_data_descriptor("object", name):
            return False
        decided, method, value = self.class_member(name)
        return decided and method is None and value is None

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


def _plain_function(method) -> bool:
    """Whether ``method`` -- the member the one class-namespace lookup
    selected (``ObjectValue.class_member``) -- is a plain function the class
    wrote: read off an instance it is a method bound to it
    (bound at prove, ``consistency::dispatched_target``).  A ``staticmethod``, a ``classmethod`` and a
    ``property`` are not."""
    return isinstance(method, ObjectMethodValue) and method.descriptor_kind is None


def _descriptor_route(value) -> tuple:
    """``ObjectValue.field_store_route``'s answer for a store of a name the
    class binds to the class field ``value``, under ``object``'s
    ``__setattr__`` (``PyObject_GenericSetAttr``: a data descriptor on the
    type -- one whose type defines ``__set__`` or ``__delete__`` -- answers
    the store; anything else is shadowed by the instance field).

    - An instance of a source class: its type's ``__set__``, read by the one
      class-namespace lookup.  A plain function a class of its MRO wrote is
      the descriptor's call; no class binding ``__set__`` nor ``__delete__``
      is no data descriptor, the plain store; anything else is undecided (a
      lookup not decided, a builtin base's, a ``__delete__`` with no
      ``__set__``: that store raises, which is not written here).
    - A value whose own type is a decided builtin (a number, a string, a
      container), or a function the class holds as a field: no data
      descriptor, the plain store.
    - Any other value (a call's result, an import's member, a class): its
      type's descriptor protocol is not read here, undecided."""
    from sugar_lift_py_tests.floor.lambda_callable import LambdaCallable
    from sugar_lift_py_tests.source_call_resolution import builtin_typed_value

    undecided = ("undecided", None)
    if isinstance(value, ObjectValue):
        definition = getattr(value.defining_class, "class_definition", None)
        if definition is not None:
            decided, owner = definition.namespace_owner("__set__")
            if not decided or isinstance(owner, str):
                return undecided
            if owner is None:
                decided, deleter = definition.namespace_owner("__delete__")
                return ("plain", None) if decided and deleter is None else undecided
        # A descriptor built with no class statement has only its own roster
        # (``class_member``).
        decided, method, held = value.class_member("__set__")
        if not decided or held is not None:
            return undecided
        if method is None:
            decided, deleter, held = value.class_member("__delete__")
            if decided and deleter is None and held is None:
                return "plain", None
            return undecided
        if not _plain_function(method):
            return undecided
        return "descriptor", (value, method)
    if isinstance(value, LambdaCallable):
        return "plain", None
    if (
        builtin_typed_value(value, shallow=True)
        and getattr(value, "formal_coordinate", None) is None
    ):
        return "plain", None
    return undecided


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
        term = ctor(
            call_symbol(target_name),
            [value.to_term(owner=f"{owner} call argument") for value in arg_values],
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
