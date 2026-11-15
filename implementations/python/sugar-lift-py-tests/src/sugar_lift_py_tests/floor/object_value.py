from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import TYPE_CHECKING, Any, NoReturn

from sugar_lift_py_tests.call_symbol import call_symbol

from .floor_value import FloorValue
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


def _sugar_receiver_field_names(value, seen: set[int] | None = None) -> set[str]:
    """Read authenticated helper-body store shape without executing the helper:
    the fields the one field store (``ReceiverFieldStoreSugar``) puts on the
    helper's own receiver -- a receiver read through its binding coordinate,
    after any stores before it (``ReceiverFieldStoreStateSugar``)."""
    from dataclasses import fields, is_dataclass

    from sugar_lift_py_tests.sugar.binding_coordinate_ref_sugar import (
        BindingCoordinateRefSugar,
    )
    from sugar_lift_py_tests.sugar.constructed_receiver_ref_sugar import (
        ConstructedReceiverRefSugar,
    )
    from sugar_lift_py_tests.sugar.receiver_field_store_state_sugar import (
        ReceiverFieldStoreStateSugar,
    )
    from sugar_lift_py_tests.sugar.receiver_field_store_sugar import (
        ReceiverFieldStoreSugar,
    )
    from sugar_lift_py_tests.sugar.sugar_base import Sugar
    from sugar_lift_py_tests.sugar_body import SugarBody

    if isinstance(value, ReceiverFieldStoreSugar):
        receiver = value.receiver
        while isinstance(receiver, ReceiverFieldStoreStateSugar):
            receiver = receiver.receiver
        if isinstance(receiver, (BindingCoordinateRefSugar, ConstructedReceiverRefSugar)):
            return {value.attr}
    if isinstance(value, (tuple, list)):
        return set().union(*(_sugar_receiver_field_names(item, seen) for item in value))
    if not isinstance(value, (Sugar, SugarBody)) or not is_dataclass(value):
        return set()
    seen = set() if seen is None else seen
    if id(value) in seen:
        return set()
    seen.add(id(value))
    return set().union(
        *(
            _sugar_receiver_field_names(getattr(value, item.name), seen)
            for item in fields(value)
            if item.compare
        )
    )


@dataclass(frozen=True)
class ObjectValue(FloorValue):
    class_name: str
    fields: tuple[ObjectField, ...]
    methods: tuple[ObjectMethodValue, ...] = ()
    class_fields: tuple[ObjectField, ...] = ()
    identity: str = ""
    deferred_helper_fields: tuple[str, ...] = dataclass_field(default=(), compare=False)
    # Instance field names removed by an authenticated delattr.  Reading one
    # of these is AttributeError (delete readback).  Any other name no field
    # holds is AttributeError only by Python's absence rule
    # (``_absence_raises``), else the undecided member.
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

        The method is the one the one class-namespace lookup selects
        (``class_member``); a lookup it does not decide is the unanswered
        call (``unanswered_method_call``).
        """
        decided, method, _value = self.class_member(dunder)
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
        if (
            method is None
            or method.source_call_frame is None
            or method.source_call_frame_cid is None
            or method.descriptor_kind is not None
            or method.source_call_frame_cid != method.source_call_frame.frame_cid
        ):
            return self._floor_gap(
                owner=owner,
                blame=site,
                observed=f"source {dunder} frame or descriptor is not authenticated",
                requested=f"the definition-owned ordinary {dunder} method frame",
                fix="construct its exact frame/descriptor binding before invoking it",
            )
        # The call is its coordinate and edge, joined at prove to the
        # method's contract (``call_member``, ``method_edge_call``, #7757
        # step 6): what it returns -- a native boolean, ``NotImplemented``,
        # anything -- is that contract's, never its body applied here.  The
        # comparison's value is the call's, its truth the call's own.
        return self.call_member(
            dunder, method, (other,), owner=owner, blame=site, ctx=ctx
        )

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

        A property getter is a body: it applies under ``ctx``, the reading
        caller's context, keeping that caller's temporal and halts.

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
        undecided attribute read (``undecided_attribute``) over the object's
        identity (``identity_term``).  Only a name the class binds to a data
        descriptor (``_class_data_descriptor``) is answered from the class,
        and never from the instance's fields.

        A field a store in this frame put on the instance
        (``stored_fields``, the one field store) is the instance's field now,
        current or not: the store makes that field known; the rest of an
        arrived instance stays as its currency says.

        Every member read off the class -- a property, a class field, a
        method -- is the one the one class-namespace lookup selects
        (``class_member``: the binding the class body left last); a lookup
        it does not decide is the unanswered read (``undecided_attribute``).
        The member is read once and carried: a property's getter, and the
        method a ``BoundMethodValue`` binds, are that member, never looked up
        again by name.

        A name nothing answers -- no field, no class member, no delete, no
        helper deferral -- raises ``AttributeError`` only by Python's absence
        rule (``_absence_raises``); otherwise it is the undecided read."""
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
            return self.undecided_attribute(name, site, owner="ObjectValue.attribute")
        for field in reversed(self.fields if current else ()):
            if field.name == name:
                from sugar_lift_py_tests.outcome import ExitSet

                return ExitSet.completed(field.value)
        decided, selected, class_value = self.class_member(name)
        if not decided:
            return self.undecided_attribute(name, site, owner="ObjectValue.attribute")
        if selected is not None and selected.descriptor_kind == "property":
            from dataclasses import replace

            from sugar_lift_py_tests.effect import RaiseEffect
            from sugar_lift_py_tests.outcome import ExitSet

            def attribute_owned(outcome):
                if not isinstance(outcome, ExitSet):
                    return outcome
                # A raise continues as the Attribute's own halt beneath its
                # arm (guard, faces and ``owed`` ride on); every other arm
                # stands.
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

            return attribute_owned(
                self.call_member(
                    name,
                    selected,
                    (),
                    owner="ObjectValue.attribute.property",
                    blame=site,
                    ctx=ctx,
                )
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
        if selected is not None:
            # A function on the receiver's class, read off the instance, is
            # the value its descriptor binds (a non-data descriptor: no
            # instance field shadows it here, the field arm above already
            # answered): a plain function a method bound to this receiver, a
            # ``staticmethod`` the bare function, a ``classmethod`` a method
            # bound to the receiver's class.  The value is this receiver, the
            # name and the method this lookup selected; its call binds that
            # very method (``call_member``), so the one method door binds the
            # implicit first actual by the descriptor kind
            # (``implicit_arguments``) and nothing selects it again by name.
            # ``obj.m()`` is this read, then that call
            # (``method_call_sugar._source_instance_method_call``).  Nothing
            # about the body is decided at the read.
            from sugar_lift_py_tests.floor.bound_method_value import BoundMethodValue
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(BoundMethodValue(self, name, selected))
        if current and name in self.deleted_instance_fields:
            # Authenticated delattr removed this instance field — read is
            # AttributeError with delete→read lineage, not an undecided gap.
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="AttributeError",
                site=site,
                owner="ObjectValue.attribute",
            )
        if name in self.deferred_helper_fields:
            from sugar_lift_py_tests.floor.getattr_coordinate import (
                getattr_coordinate,
            )

            return getattr_coordinate(self, name, owner=str(site))
        # No recorded field, delete or helper deferral answers the name, and
        # the one class-namespace lookup selected no member for it.  Python
        # decides the read only by its absence rule (``_absence_raises``):
        # ``AttributeError``, a halt at the read's fragment.  Every other
        # receiver is the one undecided member.
        if self._absence_raises(name):
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="AttributeError",
                site=site,
                owner="ObjectValue.attribute",
            )
        return self.undecided_attribute(name, site, owner="ObjectValue.attribute")

    def _absence_raises(self, name: str) -> bool:
        """Whether reading ``name`` off this instance raises ``AttributeError``
        by Python's own rule (``object.__getattribute__``,
        ``_PyObject_GenericGetAttrWithDict``; no ``__getattr__`` to fall to).

        All of: the instance's fields are its fields now (the one currency
        rule, ``contents_current``) and lack ``name`` -- the caller already
        read them; the instance's MRO is read (``method_resolution_order``)
        and every class of it is a source class or ``object``; the one
        class-namespace lookup decides no class of it binds ``name``
        (``namespace_owner``: not even ``object``); none binds
        ``__getattr__``; and the ``__getattribute__`` the lookup selects is
        ``object``'s.  The ``AttributeError`` is the builtin by binding: the
        interpreter raises it, no name is read.

        Anything else -- an instance that arrived, no class statement, an MRO
        not read, a builtin base other than ``object`` (its ``__dict__`` and
        slots are not read here), either hook bound or not decided -- is
        False: the read is the one undecided member."""
        from sugar_source_tree.nodes import ClassDef

        from .object_identity import contents_current

        if not contents_current(self):
            return False
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
        decided, owner = definition.namespace_owner("__getattr__")
        if not decided or owner is not None:
            return False
        decided, owner = definition.namespace_owner("__getattribute__")
        return decided and isinstance(owner, str) and owner == "object"

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
            self.deferred_helper_fields,
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
        the default store."""
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
            if self._class_data_descriptor(name):
                # A builtin owner's data descriptor answers the store, not
                # the instance ``__dict__``: ``o.__class__ = C`` is
                # ``object.__class__``'s setter (``object_set_class``), which
                # gives the object another class or raises ``TypeError``.
                # Its ``__set__`` is not read here: the unanswered call, and
                # the object after it of a class this frame does not know.
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
        from .named_expression_value import carry_walrus_binds, peel_walrus_binds

        outcome = self.field_store_call(name, value, site, ctx)
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

    def with_deferred_helper_fields(self) -> "ObjectValue":
        from dataclasses import replace

        # The same object: it keeps its class (``defining_class``), its
        # ``allocation`` and ``arrival``, and its own kind of receiver.
        return replace(
            self, deferred_helper_fields=self.helper_receiver_field_names()
        )

    def helper_receiver_field_names(self) -> tuple[str, ...]:
        names = set().union(
            *(
                _sugar_receiver_field_names(method.body)
                for method in self.methods
                if method.name not in {"__init__", "__enter__", "__exit__"}
            )
        )
        return tuple(sorted(names))

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
    ) -> ExitSet:
        """The class's ``name`` called with this receiver: select on the
        class, bind, apply.

        This is the class side only: CPython's implicit special-method call
        (``iter(o)``, ``o == p``, ``o[k]``, ``format``: ``type(o).<name>``,
        which no instance field shadows) -- a class-field function there is
        bound to this receiver as on any read (``call_member``).  An
        explicit ``o.m(...)`` never selects here: it is ``o.m`` read through
        ``attribute`` (instance ``__dict__`` included), then that value --
        the member the read selected -- called
        (``method_call_sugar._source_instance_method_call``).

        The call is the one a plain call ``f(...)`` of a same-file function
        is: its coordinate and an edge to the method's join symbol, joined at
        prove (``call_member``, ``method_edge_call``, #7757 step 6).

        The member is the one the one class-namespace lookup selects
        (``class_member``), read once and called (``call_member``); a lookup
        it does not decide is the unanswered call
        (``unanswered_method_call``), never a method of the roster found by
        its name.
        """
        decided, method, value = self.class_member(name)
        if not decided:
            return self.unanswered_method_call(name, arguments, keywords, blame)
        return self.call_member(
            name,
            method if method is not None else value,
            arguments,
            owner=owner,
            blame=blame,
            ctx=ctx,
            keywords=keywords,
            required_frame=required_frame,
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
    ) -> ExitSet:
        """``self.<name>(*arguments, **keywords)`` where ``member`` is what
        the one class-namespace lookup selected for ``name``
        (``class_member``): read off this receiver its descriptor binds it,
        and the one application routine applies it.  Nothing selects it
        again by name.

        - On an instance that arrived by binding (``receiver_class_decided``
          False) which function runs is not decided: the unanswered call
          (``unanswered_method_call``).
        - A plain function the class wrote (``ObjectMethodValue``, no
          descriptor kind) on an instance whose class is decided here is
          the one dispatch of a method call (#7757 step 8,
          ``receiver_dispatch.dispatch_edge_call``): the coordinate plus the
          dispatched edge carrying the instance's class
          (``receiver_dispatch.class_value``), resolved at prove on the
          order the class's own proof states.  Nothing here names which
          function runs: the lookup above selected the member only to know
          that a method call is what this is.
        - A ``staticmethod``, ``classmethod`` or ``property`` the class wrote
          is bound with the implicit first actual its descriptor kind binds
          (``bind_method_call``, ``implicit_arguments``) and stands as its
          coordinate and edge (``method_edge_call``); so does a plain
          function where the instance's class names no join symbol (no
          workspace root: the edge names none either, owed).
        - A function the class namespace holds as a field (``LambdaCallable``:
          ``f = lambda self: 1``, ``m = some_def``) is a method bound to this
          receiver (``function.__get__``): the receiver is its first actual,
          and the function's own call applies it
          (``LambdaCallable.callable_application_with``).
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
            return self.unanswered_method_call(name, arguments, keywords, blame)
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
            if member.descriptor_kind is None:
                dispatched = self._dispatched_call(name, arguments, keywords, blame)
                if dispatched is not None:
                    return dispatched
            return method_edge_call(
                self,
                member,
                arguments,
                keywords,
                class_name=self.class_name,
                ctx=ctx,
                owner=owner,
                blame=blame,
                refuse=self._floor_gap,
                required_frame=required_frame,
            )
        if isinstance(member, LambdaCallable) and required_frame is None:
            from sugar_lift_py_tests.callable_application import (
                CallableApplication,
            )

            return member.callable_application_with(
                CallableApplication(
                    (self, *arguments, *(value for _name, value in keywords)),
                    tuple(keyword for keyword, _value in keywords),
                    blame,
                ),
                ctx,
            )
        return self._floor_gap(
            owner=owner,
            blame=blame,
            observed=f"{self.class_name}.{name}",
            requested="constructor-bound method",
            fix=f"construct a diggable body for `{self.class_name}.{name}`",
        )

    def _dispatched_call(self, name, arguments, keywords, site):
        """``self.<name>(...)`` on this instance, whose class is decided
        here, as the one dispatched method call (#7757 step 8): its
        coordinate plus the edge whose receiver class is this instance's
        class and every field its ``__dict__`` may hold now
        (``receiver_dispatch.class_value``: ``python:instance(<class>,
        <field>...)``).  Prove resolves ``name`` on the order the class's own
        proof states (``consistency::dispatched_symbol``), the same
        resolution a call on a parameter whose class a caller supplies gets.

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
            name, self, receiver_class, tuple(arguments), tuple(keywords), site
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
        store; ``Cls.m``; ``super().m``).

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

    def unanswered_method_call(self, name, arguments, keywords, site):
        """``self.<name>(...)`` whose member the one class-namespace lookup
        does not decide (``class_member``): the one unanswered call
        (``UnknownCalleeCallV1``), two-faced and owed, its completion the
        call's own result coordinate.  No method of the roster is assumed to
        answer."""
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
        return UnknownCalleeCallV1(target).faces(callsite, site)

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
            import builtins

            held = type(vars(getattr(builtins, owner)).get(name))
            return hasattr(held, "__set__") or hasattr(held, "__delete__")
        # A source owner's member is the one ``class_member`` selects.
        return self._store_descriptor(name) is True

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
    (``implicit_arguments``).  A ``staticmethod``, a ``classmethod`` and a
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


def bind_method_call(
    receiver,
    method,
    arguments,
    keywords,
    *,
    class_name: str,
    ctx,
    owner: str,
    blame: object,
    refuse,
    required_frame=None,
):
    """``receiver.m(*arguments, **keywords)``: the call of the selected
    function with the implicit first actual its lookup binds
    (``implicit_arguments``), bound to read what the call's edge supplies
    (``method_edge_call``); its body is never applied.  Every method dispatch (``obj.m()``, ``self.m()``, a
    ``BoundMethodValue`` called with or without ``**``, zero-argument
    ``super().m()``, ``Cls.m()`` read off the class) binds here.

    ``refuse`` is the caller's own panic for a method it cannot bind.
    """
    target_name = f"{class_name}.{method.name}"
    implicit = implicit_arguments(
        receiver,
        method,
        target_name=target_name,
        owner=owner,
        blame=blame,
        refuse=refuse,
    )
    if implicit and not method.parameters:
        refuse(
            owner=owner,
            blame=blame,
            observed=target_name,
            requested="method self parameter",
            fix=f"add method binding sugar for `{target_name}`",
        )
    selected_frame = required_frame or method.source_call_frame
    frame_cid = method.source_call_frame_cid
    formal_coordinate_cids = method.formal_coordinate_cids
    if required_frame is None and selected_frame is not None:
        # The method runs where this call stands while the module body runs
        # (an implicit dunder call included): its frame is read at that
        # module execution site, not the class statement's (#7757 item 7).
        from sugar_lift_py_tests.source_call_frame import (
            frame_at_current_module_execution_site,
        )

        at_site = frame_at_current_module_execution_site(selected_frame)
        if at_site is not selected_frame:
            selected_frame = at_site
            frame_cid = at_site.frame_cid
            formal_coordinate_cids = tuple(
                coordinate.cid for coordinate in at_site.formal_coordinates
            )
    if selected_frame is None and (
        keywords or len(implicit) + len(arguments) != len(method.parameters)
    ):
        refuse(
            owner=owner,
            blame=blame,
            observed=target_name,
            requested="arguments matching the constructor-bound method",
            fix="bind through the authenticated method frame or keep loud",
        )
    return bind_call(
        target_name,
        (*implicit, *arguments),
        keywords,
        frame=selected_frame,
        parameters=method.parameters,
        frame_cid=frame_cid,
        formal_coordinate_cids=formal_coordinate_cids,
        lexical_defining_class=method.defining_class,
        ctx=ctx,
        owner=owner,
        blame=blame,
        refuse=refuse,
        # A formal the call omits binds the default the method's ``def``
        # statement evaluated when the class body ran, carried on the class
        # that defines it (``ClassDefinitionValue.method_defaults``), as a
        # lambda value carries its own.
        defaults=getattr(method.defining_class, "method_defaults", ()),
    )


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


def method_edge_call(
    receiver,
    method,
    arguments,
    keywords,
    *,
    class_name: str,
    ctx,
    owner: str,
    blame: object,
    refuse,
    required_frame=None,
    call_occurrence=None,
):
    """``receiver.m(*arguments, **keywords)`` whose function the one
    class-namespace lookup selected (``method``) on a receiver whose class
    is decided (``receiver_class_decided``): its coordinate and an edge to
    the method's join symbol (``python:<module>.<Class>.<m>``,
    ``lambda_callable.definition_edge_call``), joined at prove to the
    method's contract as a call of a ``def`` is (#7757 step 6).  The method's
    body is never applied here.

    The call is bound by the one method door (``bind_method_call``: the
    implicit first actual its descriptor kind binds, the defaults its class
    carries) only to read what the edge supplies; the implicit actual is the
    edge's first positional actual.  A generator method and an ``async def``
    method are calls like any other: what the call returns (a generator, a
    coroutine) is what the method's contract states, never its body here.
    A method with no source frame names no definition to join: the one
    unanswered call of its name, owed."""
    from sugar_lift_py_tests.floor.lambda_callable import definition_edge_call

    bound = bind_method_call(
        receiver,
        method,
        arguments,
        keywords,
        class_name=class_name,
        ctx=ctx,
        owner=owner,
        blame=blame,
        refuse=refuse,
        required_frame=required_frame,
    )
    frame = required_frame or method.source_call_frame
    if frame is None:
        return _frameless_method_call(bound, blame)
    implicit = implicit_arguments(
        receiver,
        method,
        target_name=bound.target_name,
        owner=owner,
        blame=blame,
        refuse=refuse,
    )
    definition = frame.owner
    return definition_edge_call(
        symbol_definition=definition,
        signature=definition,
        parameters=tuple(method.parameters),
        packed=any(
            kind in ("vararg", "kwarg")
            for kind in getattr(frame, "parameter_kinds", ())
        ),
        positional=(*implicit, *arguments),
        keywords=tuple(keywords),
        captured=(),
        actuals=tuple(bound.arg_values),
        site=blame,
        call_occurrence=call_occurrence,
        caller_ctx=ctx,
        fallback_target=bound.target_name,
        implicit=len(implicit),
    )


def _frameless_method_call(bound, site):
    """A method call ``bind_method_call`` bound for a method no source frame
    states (``ObjectMethodValue.source_call_frame`` None): no definition
    names a join symbol, so it is the one unanswered call of its name
    (``UnknownCalleeCallV1``), two-faced and owed, its completion the call's
    own result coordinate.  Its body is never applied (#7757 step 6)."""
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1

    target = bound.target_name
    owner = str(site)
    keyword_names = tuple(bound.keyword_names or ())
    count = len(bound.arg_values) - len(keyword_names)
    positional = bound.arg_values[:count]
    keyword_values = bound.arg_values[count:]
    callsite = CallSiteValue(
        target_name=target,
        arg_values=tuple(bound.arg_values),
        parameters=(),
        term=ctor(
            call_symbol(target),
            [value.to_term(owner=owner) for value in positional]
            + [
                ctor("py.kwarg", [str_const(name), value.to_term(owner=owner)])
                for name, value in zip(keyword_names, keyword_values)
            ],
            symbol_kind="coordinate",
        ),
        body=None,
        keyword_names=keyword_names,
        site=site,
    )
    return UnknownCalleeCallV1(target).faces(callsite, site)


def implicit_arguments(receiver, method, *, target_name, owner, blame, refuse):
    """The actuals a lookup of ``method`` on ``receiver`` binds before the
    written ones (the descriptor protocol, ``object.__getattribute__`` /
    ``type.__getattribute__``):

    - a plain function read off an instance is a bound method: the instance;
    - a plain function read off its class is the function itself, unbound:
      nothing (``C.f(obj, x)`` passes ``obj`` as written);
    - a ``classmethod`` binds the class: the class it is read off, or the
      instance's class;
    - a ``staticmethod`` binds nothing.

    The descriptor kind is the builtin decorator's, read through the one
    builtin door (``ClassDef._method_descriptor_kind``).  A receiver is a
    class when it is a source class value (``ClassDefinitionValue``),
    including one ``super()`` was given as its second argument.
    """
    from sugar_lift_py_tests.floor.class_definition_value import (
        ClassDefinitionValue,
    )

    kind = method.descriptor_kind
    if kind == "staticmethod":
        return ()
    on_class = isinstance(receiver, ClassDefinitionValue)
    if kind == "classmethod":
        cls = receiver if on_class else getattr(receiver, "defining_class", None)
        if cls is None:
            refuse(
                owner=owner,
                blame=blame,
                observed=f"{target_name} is a classmethod read off a receiver "
                "whose class is not carried",
                requested="the receiver's class, the classmethod's first actual",
                fix="carry the receiver's defining class or keep the call loud",
            )
        return (cls,)
    if on_class:
        return ()
    return (receiver,)


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
    (``ComputedCallSugar``), a call with ``*``/``**`` (``SpreadCallSugar``),
    a method call ``obj.m(...)``/``self.m(...)``/``super().m(...)`` (the
    receiver first, ``bind_method_call``) and a class call (the class
    statement's constructor frame).  The frame's own ``bind_actuals`` puts
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
        bound_native_actuals_by_coordinate=(
            bound_source_actuals.by_native_formal_coordinate
            if bound_source_actuals is not None
            and bound_source_actuals.native_formal_coordinates
            else None
        ),
        bound_source_actuals=bound_source_actuals,
        lexical_defining_class=lexical_defining_class,
        **testimony,
    )
