from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import TYPE_CHECKING, Any, NoReturn

from .floor_value import FloorValue
from .object_field import ObjectField
from .object_method_value import ObjectMethodValue

if TYPE_CHECKING:
    from sugar_lift_py_tests.context import FactoryBuildContext
    from sugar_lift_py_tests.operations.attribute_delete_operation import (
        AttributeDeleteOperation,
    )
    from sugar_lift_py_tests.operations.attribute_lookup_operation import (
        AttributeLookupOperation,
    )
    from sugar_lift_py_tests.operations.attribute_mutation_operation import (
        AttributeMutationOperation,
    )
    from sugar_lift_py_tests.operations.async_context_manager_operation import (
        AsyncContextManagerOperation,
    )
    from sugar_lift_py_tests.operations.async_iterator_operation import (
        AsyncIteratorOperation,
        AsyncNextOperation,
    )
    from sugar_lift_py_tests.operations.await_operation import AwaitOperation
    from sugar_lift_py_tests.operations.binary_operator_operation import (
        BinaryOperatorOperation,
    )
    from sugar_lift_py_tests.operations.bitwise_operation import BitwiseOperation
    from sugar_lift_py_tests.operations.context_manager_operation import (
        ContextManagerOperation,
    )
    from sugar_lift_py_tests.operations.contains_operation import ContainsOperation
    from sugar_lift_py_tests.operations.delitem_operation import DelItemOperation
    from sugar_lift_py_tests.operations.descriptor_operation import DescriptorOperation
    from sugar_lift_py_tests.operations.dict_missing_operation import (
        DictMissingOperation,
    )
    from sugar_lift_py_tests.operations.inplace_binary_operator_operation import (
        InplaceBinaryOperatorOperation,
    )
    from sugar_lift_py_tests.operations.method_call_operation import (
        MethodCallOperation,
    )
    from sugar_lift_py_tests.operations.next_operation import NextOperation
    from sugar_lift_py_tests.operations.reflected_binary_operator_operation import (
        ReflectedBinaryOperatorOperation,
    )
    from sugar_lift_py_tests.operations.sequence_projection_operation import (
        SequenceProjectionOperation,
    )
    from sugar_lift_py_tests.operations.setitem_operation import SetItemOperation
    from sugar_lift_py_tests.operations.str_coercion_operation import (
        StrCoercionOperation,
    )
    from sugar_lift_py_tests.operations.subscript_operation import SubscriptOperation
    from sugar_lift_py_tests.operations.unary_operator_operation import (
        UnaryOperatorOperation,
    )
    from sugar_lift_py_tests.outcome import Outcome


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
    # (those stay undecided via deferred_helper_fields / undecided_attribute).
    deleted_instance_fields: tuple[str, ...] = dataclass_field(
        default=(), compare=False
    )

    def format_data_model(self, spec, site, ctx):
        return self.call_method_value(
            "__format__",
            (spec,),
            owner="FormatDunderCallSugar",
            blame=str(site),
            ctx=ctx,
        )

    def matrix_multiply(self, other, site):
        """``@`` on an object is the ``__matmul__`` data-model method.

        MatrixMultiplyOpSugar calls ``left.matrix_multiply(right, site)``
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
        )

    def attribute_with(
        self, operation: AttributeLookupOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.attribute_object(self, ctx)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "py.object.identity",
            [str_const(self.class_name), str_const(self.identity)],
        )

    def attribute(self, name, site):
        """Project an exact field from this constructed receiver state."""
        for field in reversed(self.fields):
            if field.name == name:
                from sugar_lift_py_tests.outcome import Complete

                return Complete(field.value)
        for method in reversed(self.methods):
            if method.name != name or method.descriptor_kind != "property":
                continue
            from dataclasses import replace

            from sugar_lift_py_tests.effect import RaiseEffect
            from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted

            def invoke(callsite):
                outcome = callsite.producer_outcome()
                if not isinstance(outcome, ExitSet):
                    return outcome
                return ExitSet(
                    tuple(
                        (
                            Halted(
                                face.guard,
                                (
                                    replace(
                                        face.effect,
                                        producer_node_owner="Attribute",
                                    )
                                    if isinstance(face.effect, RaiseEffect)
                                    else face.effect
                                ),
                                face.state,
                                face.faces,
                                face.pending_contracts,
                            )
                            if isinstance(face, Halted)
                            else Completed(
                                face.guard,
                                face.value,
                                face.faces,
                                face.pending_contracts,
                            )
                        )
                        for face in outcome.exits
                    )
                ).normalize()

            return self.call_method_value(
                name,
                (),
                owner="ObjectValue.attribute.property",
                blame=site,
            ).and_then(invoke)
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
        # Missing field with no deferred helper: the receiver type/member set
        # is only partially constructed. Stay on the Attribute producer law
        # with an honest owner name — do not fall through to the generic
        # FloorValue.attribute owner="attribute" panic, and do not invent
        # AttributeError for a member table that is not source-complete.
        # (Contrast: names in deleted_instance_fields above — those absences
        # are delete-authenticated, not construction incompleteness.)
        return self.undecided_attribute(name, site, owner="ObjectValue.attribute")

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
        )

    def authenticates_plain_attribute_store(self, name: str) -> bool:
        """Whether ``self.name = value`` is an ordinary instance-field store."""
        return not any(
            method.name == name and method.descriptor_kind == "property"
            for method in self.methods
        )

    def setattr(self, name, value, site):
        """``self.name = value`` via instance-field store or property refusal.

        Properties are data descriptors: a getter without an authenticated
        setter raises ``AttributeError`` on the **store** path — never by
        consulting :meth:`attribute` / the read path.
        """
        from sugar_lift_py_tests.outcome import Complete

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
        return Complete(self.with_field_store(name, value))

    def delattr(self, name, site):
        """``del self.name`` via instance-field delete or property refusal.

        Properties are data descriptors: a getter without an authenticated
        deleter raises ``AttributeError`` on the **delete** path — never by
        consulting :meth:`attribute` / the read path.  Missing ordinary
        fields also raise ``AttributeError``.
        """
        from sugar_lift_py_tests.outcome import Complete

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
        return Complete(
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

    def attribute_assign_with(
        self, operation: AttributeMutationOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.assign_object(self, ctx)

    def attribute_delete_with(
        self, operation: AttributeDeleteOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.delete_object(self, ctx)

    def call_method_with(
        self, operation: MethodCallOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return self.call_method_value(
            operation.name,
            operation.arguments,
            owner=operation.owner,
            blame=operation.blame,
            ctx=ctx,
        )

    def descriptor_with(
        self, operation: DescriptorOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.descriptor_object(self, ctx)

    def contains_with(
        self, operation: ContainsOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self.call_method_value(
            "__contains__",
            (operation.item,),
            owner=operation.owner,
            blame=operation.blame,
        )

    def context_manager_with(
        self, operation: ContextManagerOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.context_object(self, ctx)

    def async_context_manager_with(
        self,
        operation: AsyncContextManagerOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome:
        return operation.async_context_object(self, ctx)

    def await_with(
        self, operation: AwaitOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.await_object(self, ctx)

    def async_iter_with(
        self, operation: AsyncIteratorOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.async_iter_object(self, ctx)

    def async_next_with(
        self, operation: AsyncNextOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.async_next_object(self, ctx)

    def next_with(
        self, operation: NextOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self.call_method_value(
            "__next__",
            (),
            owner=operation.owner,
            blame=operation.blame,
        )

    def subscript_with(
        self, operation: SubscriptOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.subscript_object(self, ctx)

    def setitem_with(
        self, operation: SetItemOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.setitem_object(self, ctx)

    def delitem_with(
        self, operation: DelItemOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.delitem_object(self, ctx)

    def missing_with(
        self, operation: DictMissingOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.missing_object(self, ctx)

    def str_with(
        self, operation: StrCoercionOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.str_object(self, ctx)

    def bitwise_with(
        self, operation: BitwiseOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        method_name = _BITWISE_DUNDER_METHODS.get(operation.operator)
        if method_name is None:
            return self._floor_gap(
                owner=operation.owner,
                blame=operation.blame,
                observed=f"{self.class_name}{operation.operator}{type(operation.operand).__name__}",
                requested="object bitwise data-model method",
                fix=(
                    f"add ObjectValue data-model dispatch for bitwise "
                    f"operator `{operation.operator}`"
                ),
            )
        return self.call_method_value(
            method_name,
            (operation.operand,),
            owner=operation.owner,
            blame=operation.blame,
        )

    def project_sequence_with(
        self, operation: SequenceProjectionOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.project_object(self, ctx)

    def binary_operator_with(
        self,
        operation: BinaryOperatorOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome:
        method_name = _BINARY_DUNDER_METHODS.get(operation.operator)
        if method_name is None:
            return self._floor_gap(
                owner=operation.owner,
                blame=operation.blame,
                observed=f"{self.class_name}{operation.operator}{type(operation.right).__name__}",
                requested="object binary data-model method",
                fix=(
                    f"add ObjectValue data-model dispatch for operator "
                    f"`{operation.operator}`"
                ),
            )
        if (
            operation.operator == "=="
            and isinstance(operation.right, ObjectValue)
            and not self.has_method(method_name)
        ):
            return self._floor_gap(
                owner=operation.owner,
                blame=operation.blame,
                observed=f"{self.class_name}=={operation.right.class_name}",
                requested="object identity equality",
                fix="lift method-less object identity equality",
            )
        return self.call_method_value(
            method_name,
            (operation.right,),
            owner=operation.owner,
            blame=operation.blame,
            ctx=ctx,
        )

    def reflected_binary_operator_with(
        self,
        operation: ReflectedBinaryOperatorOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome:
        del ctx
        method_name = _REFLECTED_BINARY_DUNDER_METHODS.get(operation.operator)
        if method_name is None:
            return self._floor_gap(
                owner=operation.owner,
                blame=operation.blame,
                observed=f"{type(operation.left).__name__}{operation.operator}{self.class_name}",
                requested="object reflected binary data-model method",
                fix=(
                    f"add ObjectValue reflected data-model dispatch for "
                    f"operator `{operation.operator}`"
                ),
            )
        return self.call_method_value(
            method_name,
            (operation.left,),
            owner=operation.owner,
            blame=operation.blame,
        )

    def inplace_binary_operator_with(
        self,
        operation: InplaceBinaryOperatorOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome:
        del ctx
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
        )

    def unary_operator_with(
        self, operation: UnaryOperatorOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        method_name = _UNARY_DUNDER_METHODS.get(operation.operator)
        if method_name is None:
            return self._floor_gap(
                owner=operation.owner,
                blame=operation.blame,
                observed=f"{operation.operator}({self.class_name})",
                requested="object unary data-model method",
                fix=(
                    f"add ObjectValue unary data-model dispatch for "
                    f"operator `{operation.operator}`"
                ),
            )
        return self.call_method_value(
            method_name,
            (),
            owner=operation.owner,
            blame=operation.blame,
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
    ) -> Outcome:
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        for method in reversed(self.methods):
            if method.name != name:
                continue
            if required_frame is not None and (
                method.source_call_frame_cid != required_frame.frame_cid
            ):
                continue
            if not method.parameters:
                return self._floor_gap(
                    owner=owner,
                    blame=blame,
                    observed=f"{self.class_name}.{name}",
                    requested="method self parameter",
                    fix=f"add method binding sugar for `{self.class_name}.{name}`",
                )
            target_name = f"{self.class_name}.{name}"
            arg_values = (self, *arguments)
            selected_frame = required_frame or method.source_call_frame
            if selected_frame is not None:
                from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

                try:
                    arg_values = selected_frame.bind_actuals(arg_values, keywords, ctx)
                except SourceCallBindingGap as exc:
                    return self._floor_gap(
                        owner=owner,
                        blame=blame,
                        observed=str(exc),
                        requested="actuals matching authenticated method signature",
                        fix="preserve exact defaults/variadics or keep the call loud",
                    )
            elif keywords or len(arguments) != len(method.parameters) - 1:
                return self._floor_gap(
                    owner=owner,
                    blame=blame,
                    observed=f"{self.class_name}.{name}",
                    requested="arguments matching the constructor-bound method",
                    fix="bind through the authenticated method frame or keep loud",
                )
            arg_terms = [
                value.to_term(owner=f"{owner} method argument") for value in arg_values
            ]
            call_value = CallSiteValue(
                target_name=target_name,
                arg_values=arg_values,
                parameters=method.parameters,
                term=ctor(
                    f"call:{target_name}",
                    arg_terms,
                    symbol_kind="contract-target",
                ),
                body=method.body,
                source_call_frame_cid=method.source_call_frame_cid,
                formal_coordinate_cids=method.formal_coordinate_cids,
            )
            if not any(
                isinstance(value, (SymbolicValue, CallSiteValue))
                for value in arg_values
            ):
                sink = ctx.dig_sink if ctx is not None else None
                if sink is not None:
                    sink.append(call_value)
            return Complete(call_value)
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


_BINARY_DUNDER_METHODS = {
    "==": "__eq__",
    "+": "__add__",
    "-": "__sub__",
    "*": "__mul__",
    "/": "__truediv__",
    "//": "__floordiv__",
    "%": "__mod__",
    "divmod": "__divmod__",
    "**": "__pow__",
    "@": "__matmul__",
}

_BITWISE_DUNDER_METHODS = {
    "&": "__and__",
    "|": "__or__",
    "^": "__xor__",
    "<<": "__lshift__",
    ">>": "__rshift__",
}

_REFLECTED_BINARY_DUNDER_METHODS = {
    "+": "__radd__",
    "-": "__rsub__",
    "*": "__rmul__",
    "/": "__rtruediv__",
    "//": "__rfloordiv__",
    "%": "__rmod__",
    "divmod": "__rdivmod__",
    "**": "__rpow__",
    "@": "__rmatmul__",
    "&": "__rand__",
    "|": "__ror__",
    "^": "__rxor__",
    "<<": "__rlshift__",
    ">>": "__rrshift__",
}

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

_UNARY_DUNDER_METHODS = {
    "py.pos": "__pos__",
    "py.neg": "__neg__",
    "py.invert": "__invert__",
}
