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
        from sugar_lift_py_tests.outcome import Complete

        return (
            DictValue(self.entries)
            .setitem(index, value, site)
            .and_then(
                lambda updated: Complete(self.mapping_with_entries(updated.entries))
            )
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
            if name == "__setitem__" and len(arguments) == 2:
                return self.setitem(arguments[0], arguments[1], blame)
            if name == "__delitem__" and len(arguments) == 1:
                return self.delitem(arguments[0], blame)
        return super().call_method_value(
            name,
            arguments,
            owner=owner,
            blame=blame,
            ctx=ctx,
            keywords=keywords,
            required_frame=required_frame,
        )

    def with_field_store(self, name, value):
        updated = super().with_field_store(name, value)
        return replace(
            self,
            fields=updated.fields,
            deleted_instance_fields=updated.deleted_instance_fields,
        )
