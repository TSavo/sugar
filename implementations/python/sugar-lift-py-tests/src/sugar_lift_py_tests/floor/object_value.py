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
    """Read authenticated helper-body store shape without executing the helper."""
    from dataclasses import fields, is_dataclass

    from sugar_lift_py_tests.sugar.receiver_field_store_sugar import (
        ReceiverFieldStoreSugar,
    )
    from sugar_lift_py_tests.sugar.sugar_base import Sugar
    from sugar_lift_py_tests.sugar_body import SugarBody

    if isinstance(value, ReceiverFieldStoreSugar):
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
    # of these is AttributeError (delete readback), without inventing
    # AttributeError for unenrolled members of a partial construction
    # (those require deferred-helper coordinates or a construction panic).
    deleted_instance_fields: tuple[str, ...] = dataclass_field(
        default=(), compare=False
    )
    # Definition-owned class identity transported by ClassDefinitionValue.
    # This is never reconstructed from class_name.
    defining_class: object | None = dataclass_field(
        default=None, compare=False, repr=False
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
        Never substitute object identity for a user-defined equality body.
        """
        if not self.has_method("__eq__"):
            return super().equals(other, site, ctx)
        return self._source_rich_comparison(
            "__eq__", other, site, ctx, owner="ObjectValue.equals"
        )

    def less_than(self, other, site, ctx):
        """``self < other`` invokes the class's authenticated ``__lt__``."""
        if not self.has_method("__lt__"):
            return super().less_than(other, site, ctx)
        return self._source_rich_comparison(
            "__lt__", other, site, ctx, owner="ObjectValue.less_than"
        )

    def less_equal(self, other, site, ctx):
        """``self <= other`` invokes the class's authenticated ``__le__``."""
        if not self.has_method("__le__"):
            return super().less_equal(other, site, ctx)
        return self._source_rich_comparison(
            "__le__", other, site, ctx, owner="ObjectValue.less_equal"
        )

    def greater_than(self, other, site, ctx):
        """``self > other`` invokes the class's authenticated ``__gt__``."""
        if not self.has_method("__gt__"):
            return super().greater_than(other, site, ctx)
        return self._source_rich_comparison(
            "__gt__", other, site, ctx, owner="ObjectValue.greater_than"
        )

    def greater_equal(self, other, site, ctx):
        """``self >= other`` invokes the class's authenticated ``__ge__``."""
        if not self.has_method("__ge__"):
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
        left's definition-owned ordinary method frame.  A result other than a
        native boolean -- ``NotImplemented`` included -- stays a named
        refusal, as does every reflected or subclass order.
        """
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
        method = next(
            method for method in reversed(self.methods) if method.name == dunder
        )
        if (
            method.source_call_frame is None
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
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

        def returned(value):
            if isinstance(
                value, (PredicateValue, TrueBoolLiteralSugar, FalseBoolLiteralSugar)
            ) or (isinstance(value, TermValue) and type(value.value) is bool):
                return ExitSet.completed(value)
            return self._floor_gap(
                owner=owner,
                blame=site,
                observed=f"source {dunder} returned {type(value).__name__}",
                requested="native boolean or authenticated exceptional outcome",
                fix="construct non-boolean/NotImplemented result dispatch before accepting it",
            )

        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.floor.return_value import ReturnValue

        def completed(block):
            # A scalar comparison cannot silently erase a completed callee's
            # stores/effect prefix. Halted faces keep their original state via
            # ExitSet.and_then; richer normal-state transport is still a gap.
            if (
                not isinstance(block, BlockValue)
                or len(block.statements) != 1
                or not isinstance(block.statements[0], ReturnValue)
            ):
                return self._floor_gap(
                    owner=owner,
                    blame=site,
                    observed=f"source {dunder} completion has untransported state or effects",
                    requested="a sole native return, or explicit callee-state transport",
                    fix="preserve the completed method prefix before extracting its scalar result",
                )
            return returned(block.statements[0].value)

        return self.call_method_value(
            dunder, (other,), owner=owner, blame=site, ctx=ctx
        ).and_then(
            lambda call: call.retained_source_completion_outcome().and_then(completed)
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
        caller's context, keeping that caller's temporal and halts."""
        for field in reversed(self.fields):
            if field.name == name:
                from sugar_lift_py_tests.outcome import ExitSet

                return ExitSet.completed(field.value)
        for method in reversed(self.methods):
            if method.name != name or method.descriptor_kind != "property":
                continue
            from dataclasses import replace

            from sugar_lift_py_tests.effect import RaiseEffect
            from sugar_lift_py_tests.outcome import ExitSet

            def attribute_owned(outcome):
                if not isinstance(outcome, ExitSet):
                    return outcome
                # A raise continues as the Attribute's own halt beneath its
                # arm (guard, faces and ``owed`` ride on); every other arm
                # stands.
                return outcome.sequence(
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
                self.call_method_value(
                    name,
                    (),
                    owner="ObjectValue.attribute.property",
                    blame=site,
                    ctx=ctx,
                )
            )
        class_value = self._resolved_class_field(name)
        if class_value is not None:
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(class_value)
        selected = next(
            (method for method in reversed(self.methods) if method.name == name),
            None,
        )
        if selected is not None and selected.descriptor_kind != "property":
            # A function on the receiver's class, read off the instance, is
            # the value its descriptor binds (a non-data descriptor: no
            # instance field shadows it here, the field arm above already
            # answered): a plain function a method bound to this receiver, a
            # ``staticmethod`` the bare function, a ``classmethod`` a method
            # bound to the receiver's class.  The value is this receiver and
            # the name; its call dispatches through ``call_method_value`` on
            # this very receiver, so the one method door binds the implicit
            # first actual by the descriptor kind (``implicit_arguments``)
            # exactly as ``obj.m()`` does.  Nothing about the body is decided
            # at the read.
            from sugar_lift_py_tests.floor.bound_method_value import BoundMethodValue
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(BoundMethodValue(self, name))
        if name in self.deleted_instance_fields:
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
        # This receiver already owns a constructed object-state floor. An
        # unenrolled member is missing construction testimony, not an unknown
        # receiver-type Sugar case. Without a field, helper deferral, or cited
        # absence, neither completion nor AttributeError is justified. Keep
        # that missing Floor arm outside ordinary Exception handlers, including
        # on guarded states.
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="ObjectValue.attribute",
            blame=site,
            observed=f"{type(self).__name__}.{name}",
            requested="a source-authenticated field projection or exceptional exit",
            fix=(
                "carry field construction, helper deferral, or authenticated "
                "absence testimony for this receiver state to the attribute floor; "
                "do not guess AttributeError or borrow another guard's fields"
            ),
        )

    def guarded(self, formula):
        # A constructed state is not an unconditional field-store statement.
        # Retain the branch restriction for the constructor's state projection.
        from .guarded_receiver_state_value import GuardedReceiverStateValue

        return GuardedReceiverStateValue(self, formula)

    def with_field_store(self, name: str, value: FloorValue) -> "ObjectValue":
        """Return this receiver identity after one authenticated field store."""
        if any(
            method.name == name and method.descriptor_kind == "property"
            for method in self.methods
        ):
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                blame=f"{self.class_name}.{name}",
                owner="ObjectValue.with_field_store",
                observed="source-authenticated property data descriptor",
                requested="the descriptor's authenticated assignment behavior",
                fix=(
                    "construct the property's setter before treating the write "
                    "as an instance-field store"
                ),
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
        )

    def authenticates_plain_attribute_store(self, name: str) -> bool:
        """Whether ``self.name = value`` is an ordinary instance-field store."""
        return not any(
            method.name == name and method.descriptor_kind == "property"
            for method in self.methods
        )

    def setattr(self, name, value, site, ctx):
        """``self.name = value`` via instance-field store or property refusal.

        Properties are data descriptors: a getter without an authenticated
        setter raises ``AttributeError`` on the **store** path — never by
        consulting :meth:`attribute` / the read path.
        """
        from sugar_lift_py_tests.outcome import ExitSet

        if any(
            method.name == name and method.descriptor_kind == "property"
            for method in self.methods
        ):
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="AttributeError",
                site=site,
                owner="ObjectValue.setattr",
            )
        return ExitSet.completed(self.with_field_store(name, value))

    def delattr(self, name, site, ctx):
        """``del self.name`` via instance-field delete or property refusal.

        Properties are data descriptors: a getter without an authenticated
        deleter raises ``AttributeError`` on the **delete** path — never by
        consulting :meth:`attribute` / the read path.  Missing ordinary
        fields also raise ``AttributeError``.
        """
        from sugar_lift_py_tests.outcome import ExitSet

        if any(
            method.name == name and method.descriptor_kind == "property"
            for method in self.methods
        ):
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="AttributeError",
                site=site,
                owner="ObjectValue.delattr",
            )
        remaining = tuple(field for field in self.fields if field.name != name)
        if len(remaining) == len(self.fields):
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
        return ExitSet.completed(
            ObjectValue(
                self.class_name,
                remaining,
                self.methods,
                self.class_fields,
                self.identity,
                self.deferred_helper_fields,
                deleted,
            )
        )

    def with_deferred_helper_fields(self) -> "ObjectValue":
        names = self.helper_receiver_field_names()
        return ObjectValue(
            self.class_name,
            self.fields,
            self.methods,
            self.class_fields,
            self.identity,
            names,
            self.deleted_instance_fields,
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
        """``self.<name>(*arguments, **keywords)``: select, bind, apply.

        The application is the one a plain call ``f(...)`` uses
        (``CallSiteValue.producer_outcome``, as ``CallSiteSugar`` applies it):
        the body runs here and every face it has, raises included, is this
        call's.
        """
        return self.bound_method_call(
            name,
            arguments,
            owner=owner,
            blame=blame,
            ctx=ctx,
            keywords=keywords,
            required_frame=required_frame,
        ).producer_outcome(ctx)

    def bound_method_call(
        self,
        name: str,
        arguments: tuple[FloorValue, ...],
        *,
        owner: str,
        blame: object,
        ctx: Any | None = None,
        keywords: tuple[tuple[str, FloorValue], ...] = (),
        required_frame: object | None = None,
    ):
        """The call ``<method>(self, *arguments, **keywords)``, bound, unapplied."""
        for method in reversed(self.methods):
            if method.name != name:
                continue
            if required_frame is not None and (
                method.source_call_frame_cid != required_frame.frame_cid
            ):
                continue
            return bind_method_call(
                self,
                method,
                arguments,
                keywords,
                class_name=self.class_name,
                ctx=ctx,
                owner=owner,
                blame=blame,
                refuse=self._floor_gap,
                required_frame=required_frame,
            )
        return self._floor_gap(
            owner=owner,
            blame=blame,
            observed=f"{self.class_name}.{name}",
            requested="constructor-bound method",
            fix=f"construct a diggable body for `{self.class_name}.{name}`",
        )

    def has_method(self, name: str) -> bool:
        return any(method.name == name for method in self.methods)

    def class_field_value(self, name: str) -> FloorValue | None:
        for field in reversed(self.class_fields):
            if field.name == name:
                return field.value
        return None

    def _resolved_class_field(self, name: str) -> FloorValue | None:
        """This class's field, else the first authenticated local base's.

        Instance fields and data descriptors have already been considered.
        A deleted instance field does not hide a still-present class field.
        """
        found = self.class_field_value(name)
        if found is not None:
            return found
        defining = self.defining_class
        if defining is None or not hasattr(defining, "_c3_tail"):
            return None
        for base in defining._c3_tail():
            for field in reversed(getattr(base, "class_fields", ())):
                if field.name == name:
                    return field.value
        return None

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
    (``implicit_arguments``), for ``CallSiteValue.producer_outcome`` to
    apply.  Every method dispatch (``obj.m()``, ``self.m()``, a
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
    body = method.body
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
            body = at_site.body
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
        body=body,
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
    body,
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
    every actual in its formal slot; the result is the ``CallSiteValue`` that
    ``CallSiteValue.producer_outcome`` applies, the one application.  With no
    frame the actuals are taken as already in formal order, the keyword
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
        body=body,
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
