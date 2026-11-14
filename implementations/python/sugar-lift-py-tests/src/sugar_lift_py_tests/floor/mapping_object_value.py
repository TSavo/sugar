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

    def _builtin_dict(self):
        """The authenticated ``dict`` base state as the builtin dict it is:
        this object's own state, made with the object (its ``identity``).
        Its currency is the object's, which ``arrived`` does not take off
        an instance (``object_identity``)."""
        return DictValue(self.entries, allocation=self.identity or None)

    def protocol_owner(self, name: str, site) -> str | None:
        """Who answers ``name`` read on this receiver's class (#7757):
        ``"source"`` (a source class's method), ``"dict"`` (the authenticated
        builtin base's storage), or None when no class binds it.

        Python reads every implicit dunder (``obj[k]``, ``del obj[k]``,
        ``len(obj)``, ``k in obj``, ``bool(obj)``) on the type, through its
        MRO: the first class whose namespace binds the name answers.  The
        MRO is the class statement's one base walk
        (``ClassDef.namespace_owner`` over ``method_resolution_order``,
        #8069), so a source override before ``dict`` wins and a source
        method after ``dict`` (``class M(dict, Mixin)``) does not.  A lookup
        the walk does not decide refuses by name: neither the source method
        nor the dict base is assumed.

        A receiver built with no class statement (a method roster only)
        has its roster: those source methods precede the dict base.
        """
        definition = getattr(self.defining_class, "class_definition", None)
        if definition is None:
            return "source" if self.has_method(name) else "dict"
        decided, owner = definition.namespace_owner(name)
        if not decided or (isinstance(owner, str) and owner != "dict"):
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="MappingObjectValue.protocol_owner",
                blame=site,
                observed=(
                    f"{self.class_name}.{name}: "
                    + ("MRO not read" if not decided else f"bound by {owner}")
                ),
                requested="the class of the MRO that binds the name, read by binding",
                fix="read every base of the class by its binding (ClassDef._read_base)",
            )
        if owner is None:
            return None
        return "dict" if isinstance(owner, str) else "source"

    def _refuse_source_protocol(self, name: str, site, door: str):
        """A source ``name`` read through a door that carries no reduction
        context: the source method cannot be applied here, and the dict
        base's answer would be the wrong one."""
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner=f"MappingObjectValue.{door}",
            blame=site,
            observed=f"source-defined {self.class_name}.{name} without reduction context",
            requested="the caller's context to apply the source method",
            fix=f"route `{door}` through call_method_value({name!r}) with the caller context",
        )

    def truth(self, site):
        # ``bool(obj)``: ``__bool__``, else ``__len__``, each by the MRO.
        if self.protocol_owner("__bool__", site) == "source":
            self._refuse_source_protocol("__bool__", site, "truth")
        if self.protocol_owner("__len__", site) == "source":
            self._refuse_source_protocol("__len__", site, "truth")
        return self._builtin_dict().truth(site)

    def length(self, site):
        if self.protocol_owner("__len__", site) == "source":
            self._refuse_source_protocol("__len__", site, "length")
        return self._builtin_dict().length(site)

    def contains(self, item, site):
        if self.protocol_owner("__contains__", site) == "source":
            self._refuse_source_protocol("__contains__", site, "contains")
        return self._builtin_dict().contains(item, site)

    def subscript(self, index, site):
        if self.protocol_owner("__getitem__", site) == "source":
            self._refuse_source_protocol("__getitem__", site, "subscript")
        return self._mapping_read(index, site, None)

    def _mapping_read(self, index, site, ctx):
        """The authenticated builtin-dict read of ``self[index]``: the shadow
        ``dict`` answers through the one subscript door
        (``discharge_subscript``), so a parameter index defers to the caller
        as a source subscript's does."""
        from sugar_lift_py_tests.operations.subscript_operation import (
            discharge_subscript,
        )

        return discharge_subscript(
            self._builtin_dict(),
            index,
            site,
            ctx,
            owner="MappingObjectValue.__getitem__",
        )

    def setitem(self, index, value, site, ctx):
        # One store door: the store statement's context reaches a source
        # ``__setitem__`` and the builtin storage alike (#7757). The former
        # ``setitem_with_context`` second door is folded in here.
        if self.protocol_owner("__setitem__", site) != "source":
            return self.mapping_builtin_setitem(index, value, site, ctx)
        return self._source_store("__setitem__", (index, value), site, ctx)

    def _source_store(self, name, arguments, site, ctx):
        """``obj[k] = v`` / ``del obj[k]`` through a source ``name`` the MRO
        selects: the method applied under the store statement's context, and
        the receiver it leaves read off its one receiver-owned mutation."""
        if ctx is None:
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="MappingObjectValue.setitem",
                blame=site,
                observed=f"source-defined {name} without reduction context",
                requested="the store statement's context",
                fix="thread the caller context; zero-arg super requires its __class__ cell",
            )
        if self.defining_class is None:
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="MappingObjectValue.setitem",
                blame=site,
                observed="mapping receiver lacks defining class",
                requested=f"authenticated source class for {name} dispatch",
                fix="transport the class definition into its constructed receiver",
            )
        method_ctx = ctx.with_temporal(
            ctx.temporal.bind_value(
                "__class__", self.defining_class, blame=f"{self.class_name}.{name}"
            )
        )
        return (
            super()
            .call_method_value(
                name,
                arguments,
                owner="MappingObjectValue.setitem",
                blame=site,
                ctx=method_ctx,
            )
            .and_then(
                lambda callsite: callsite.retained_source_completion_outcome().and_then(
                    self._project_setitem_receiver
                )
            )
        )

    def mapping_builtin_setitem(self, index, value, site, ctx):
        """Apply authenticated builtin-dict storage without source redispatch."""
        from sugar_lift_py_tests.outcome import ExitSet

        return (
            self._builtin_dict()
            .setitem(index, value, site, ctx)
            .and_then(
                lambda updated: ExitSet.completed(
                    self.mapping_with_entries(updated.entries)
                )
            )
        )

    def _project_setitem_receiver(self, value):
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.floor.receiver_owned_mutation_result import (
            ReceiverOwnedMutationResult,
        )
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
        from sugar_lift_py_tests.outcome import ExitSet

        entries = value.statements if isinstance(value, BlockValue) else (value,)
        mutations = tuple(
            entry
            for entry in entries
            if isinstance(entry, ReceiverOwnedMutationResult)
            and type(entry.receiver_before) is type(self)
            and entry.receiver_before.identity == self.identity
        )
        if len(mutations) != 1:
            construction_panic_gap(
                owner="MappingObjectValue.setitem",
                blame=self.identity,
                observed=f"{len(mutations)} receiver-owned mutation results",
                requested="one authenticated __setitem__ receiver transition",
                fix="preserve the source __setitem__ body mutation or keep loud",
            )
        return ExitSet.completed(mutations[0].receiver_after)

    def delitem(self, index, site, ctx):
        if self.protocol_owner("__delitem__", site) == "source":
            return self._source_store("__delitem__", (index,), site, ctx)
        return self.mapping_builtin_delitem(index, site, ctx)

    def mapping_builtin_delitem(self, index, site, ctx):
        """Apply authenticated builtin-dict deletion without source redispatch."""
        from sugar_lift_py_tests.outcome import ExitSet

        return (
            self._builtin_dict()
            .delitem(index, site, ctx)
            .and_then(
                lambda updated: ExitSet.completed(
                    self.mapping_with_entries(updated.entries)
                )
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
        """Answer a name the MRO resolves to the authenticated dict base from
        its storage (``protocol_owner``); every other name -- a source
        override included -- is the source method's."""
        if required_frame is None and not keywords:

            def builtin():
                return self.protocol_owner(name, blame) == "dict"

            if name == "__getitem__" and len(arguments) == 1 and builtin():
                return self._mapping_read(arguments[0], blame, ctx)
            if name == "__setitem__" and len(arguments) == 2 and builtin():
                return self.mapping_builtin_setitem(
                    arguments[0], arguments[1], blame, ctx
                )
            if name == "__delitem__" and len(arguments) == 1 and builtin():
                return self.mapping_builtin_delitem(arguments[0], blame, ctx)
            if name == "get" and len(arguments) in (1, 2) and builtin():
                return self._mapping_get(arguments, blame)
            if name == "items" and not arguments and builtin():
                from sugar_lift_py_tests.floor.tuple_value import TupleValue
                from sugar_lift_py_tests.outcome import ExitSet

                return ExitSet.completed(
                    TupleValue(
                        tuple(TupleValue((key, value)) for key, value in self.entries)
                    )
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
        from sugar_lift_py_tests.outcome import ExitSet

        key = arguments[0]
        default = arguments[1] if len(arguments) == 2 else NoneValue()
        decisions = tuple(
            _closed_member_equal(key, candidate) for candidate, _ in self.entries
        )
        if any(decision is None for decision in decisions):
            construction_panic_gap(
                owner="MappingObjectValue.get",
                blame=blame,
                observed=(
                    "undecidable mapping key equality: "
                    f"key={type(key).__name__} over {type(self).__name__}"
                ),
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
        return ExitSet.completed(self.entries[matching[0]][1] if matching else default)

    def with_field_store(self, name, value):
        updated = super().with_field_store(name, value)
        return replace(
            self,
            fields=updated.fields,
            deleted_instance_fields=updated.deleted_instance_fields,
        )
