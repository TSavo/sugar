from __future__ import annotations

from dataclasses import dataclass, replace

from .dict_value import DictValue
from .object_value import ObjectValue


@dataclass(frozen=True)
class MappingObjectValue(ObjectValue):
    """A source-class receiver carrying authenticated ``dict`` base state.

    ``ObjectValue`` remains the owner of source fields, methods, and receiver
    identity.  ``entries`` is the ordinary shadow state contributed by the
    authenticated builtin base.  Keeping both on one value prevents a dict
    mutation from replacing the source-class receiver with a bare DictValue.
    """

    entries: tuple = ()
    def guarded(self, formula):
        """A constructed mapping state contributes no independent control.

        This is the same Floor law as ``DictValue.guarded`` via
        ``GuardStableValue``: the surrounding ExitSet owns the branch guard;
        duplicating it inside the receiver would turn one shadow mutation into
        a second conditional value identity.
        """
        del formula
        return self

    def mapping_entries(self) -> tuple:
        return self.entries

    def mapping_with_entries(self, entries: tuple) -> "MappingObjectValue":
        return replace(self, entries=entries)

    def truth(self, site):
        return DictValue(self.entries).truth(site)

    def length(self, site):
        return DictValue(self.entries).length(site)

    def contains(self, item, site):
        return DictValue(self.entries).contains(item, site)

    def subscript(self, index, site):
        return DictValue(self.entries).subscript(index, site)

    def setitem(self, index, value, site):
        if self.has_method("__setitem__"):
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="MappingObjectValue.setitem",
                blame=site,
                observed="source-defined __setitem__ without reduction context",
                requested="setitem_with_context through the ordinary store producer",
                fix="thread the caller context; zero-arg super requires its __class__ cell",
            )
        return self.mapping_builtin_setitem(index, value, site)

    def setitem_with_context(self, index, value, site, ctx):
        if not self.has_method("__setitem__"):
            return self.mapping_builtin_setitem(index, value, site)
        if self.defining_class is None:
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="MappingObjectValue.setitem_with_context",
                blame=site,
                observed="mapping receiver lacks defining class",
                requested="authenticated source class for __setitem__ dispatch",
                fix="transport the class definition into its constructed receiver",
            )
        method_ctx = ctx.with_temporal(
            ctx.temporal.bind_value(
                "__class__", self.defining_class, blame=f"{self.class_name}.__setitem__"
            )
        )
        return super().call_method_value(
                "__setitem__",
                (index, value),
                owner="MappingObjectValue.setitem",
                blame=site,
                ctx=method_ctx,
            ).and_then(
                lambda callsite: callsite.reduce_source_outcome(method_ctx).and_then(
                    self._project_setitem_receiver
                )
            )

    def mapping_builtin_setitem(self, index, value, site):
        """Apply authenticated builtin-dict storage without source redispatch."""
        from sugar_lift_py_tests.outcome import Complete

        return (
            DictValue(self.entries)
            .setitem(index, value, site)
            .and_then(
                lambda updated: Complete(self.mapping_with_entries(updated.entries))
            )
        )

    def _project_setitem_receiver(self, value):
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.floor.receiver_owned_mutation_result import (
            ReceiverOwnedMutationResult,
        )
        from sugar_lift_py_tests.floor.receiver_state_projection import (
            project_receiver_owned_mutation_chain,
        )

        entries = value.statements if isinstance(value, BlockValue) else (value,)
        mutations = tuple(
            entry for entry in entries if isinstance(entry, ReceiverOwnedMutationResult)
        )
        return project_receiver_owned_mutation_chain(
            self,
            mutations,
            owner="MappingObjectValue.setitem",
            blame=self.identity,
        )

    def delitem(self, index, site):
        from sugar_lift_py_tests.outcome import Complete

        return (
            DictValue(self.entries)
            .delitem(index, site)
            .and_then(
                lambda updated: Complete(self.mapping_with_entries(updated.entries))
            )
        )

    def call_method_value(
        self,
        name,
        arguments,
        *,
        owner,
        blame,
        ctx=None,
        keywords=(),
        required_frame=None,
    ):
        """Dispatch authenticated builtin-dict protocol before source methods."""
        if required_frame is None and not keywords:
            if name == "__getitem__" and len(arguments) == 1:
                return self.subscript(arguments[0], blame)
            if (
                name == "__setitem__"
                and len(arguments) == 2
                and not self.has_method("__setitem__")
            ):
                return self.mapping_builtin_setitem(arguments[0], arguments[1], blame)
            if name == "__delitem__" and len(arguments) == 1:
                return self.delitem(arguments[0], blame)
            if (
                name == "get"
                and len(arguments) in (1, 2)
                and not self.has_method("get")
            ):
                return self._mapping_get(arguments, blame)
            if name == "items" and not arguments and not self.has_method("items"):
                from sugar_lift_py_tests.floor.tuple_value import TupleValue
                from sugar_lift_py_tests.outcome import Complete

                return Complete(
                    TupleValue(tuple(TupleValue((key, value)) for key, value in self.entries))
                )
        return super().call_method_value(
            name,
            arguments,
            owner=owner,
            blame=blame,
            ctx=ctx,
            keywords=keywords,
            required_frame=required_frame,
        )

    def _mapping_get(self, arguments, blame):
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.floor.set_value import _closed_member_equal
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
        from sugar_lift_py_tests.outcome import Complete

        key = arguments[0]
        default = arguments[1] if len(arguments) == 2 else NoneValue()
        decisions = tuple(
            _closed_member_equal(key, candidate) for candidate, _ in self.entries
        )
        if any(decision is None for decision in decisions):
            construction_panic_gap(
                owner="MappingObjectValue.get",
                blame=blame,
                observed="undecidable mapping key equality",
                requested="one source-decided finite mapping key",
                fix="construct key equality or keep get typed loud",
            )
        matching = tuple(index for index, decision in enumerate(decisions) if decision)
        if len(matching) > 1:
            construction_panic_gap(
                owner="MappingObjectValue.get",
                blame=blame,
                observed="duplicate equal keys in constructed mapping",
                requested="one canonical mapping entry per key",
                fix="repair mapping construction before get",
            )
        return Complete(self.entries[matching[0]][1] if matching else default)

    def with_field_store(self, name, value):
        updated = super().with_field_store(name, value)
        return replace(
            self,
            fields=updated.fields,
            deleted_instance_fields=updated.deleted_instance_fields,
        )
