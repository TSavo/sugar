from __future__ import annotations

from dataclasses import dataclass, replace

from .dict_value import DictValue
from .object_value import ObjectValue

# The arities at which ``MappingObjectValue.dict_base_call`` applies dict's
# own method of that name to the authenticated base storage.
_DICT_BASE_ARITIES = {
    "__getitem__": (1,),
    "__setitem__": (2,),
    "__delitem__": (1,),
    "__contains__": (1,),
    "get": (1, 2),
    "items": (0,),
}


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
        """The authenticated ``dict`` base state as the builtin dict it is.

        Not current (``allocation=None``), whatever the instance's own
        currency (``ObjectValue.allocation``): the base storage's currency is
        not threaded through a source ``__setitem__``/``__delitem__``
        override's post-state, so whether this state is the object's state
        now is not decided here.  Every read of it takes its undecided form
        (``object_identity.contents_current``).  Nor is which instance it
        is (``identity`` may be its class's): it names no ``arrival``, so an
        undecided read of it refuses by name (``identity_term``) rather than
        share one term with every other instance's state."""
        return DictValue(self.entries, allocation=None)

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
        nor the dict base is assumed (``_protocol_owner``).
        """
        owner = self._protocol_owner(name)
        if owner not in ("source", "dict", None):
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="MappingObjectValue.protocol_owner",
                blame=site,
                observed=f"{self.class_name}.{name}: {owner}",
                requested="the class of the MRO that binds the name, read by binding",
                fix="decide the class's namespace for the name (ClassDef.namespace_binds)",
            )
        return owner

    def _protocol_owner(self, name: str) -> str | None:
        """``"source"``, ``"dict"``, None (no class binds it), or what keeps
        it undecided: ``"undecided"`` -- the one lookup does not decide it,
        or the class that holds it holds a value its body did not bind
        (``ClassDef.namespace_value_is_body``: a decorator's, a store's) --
        or ``"bound by <builtin>"``.

        A receiver built with no class statement (a method roster only)
        has its roster: those source methods precede the dict base.
        """
        definition = getattr(self.defining_class, "class_definition", None)
        if definition is None:
            return "source" if self.has_method(name) else "dict"
        decided, owner = definition.namespace_owner(name)
        if not decided:
            return "undecided"
        if owner is None or owner == "dict":
            return owner
        if isinstance(owner, str):
            return f"bound by {owner}"
        return "source" if owner.namespace_value_is_body(name) else "undecided"

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
        the receiver it leaves read off its one receiver-owned mutation.

        The method's ``__class__`` cell (PEP 3135) is the class whose body
        defines it, bound where every method application binds it
        (``object_value.bind_method_call``: ``lexical_defining_class``) --
        never the receiver's class, which for an inherited method is not the
        class a zero-argument ``super()`` in its body searches after (#7757).
        """
        if ctx is None:
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="MappingObjectValue.setitem",
                blame=site,
                observed=f"source-defined {name} without reduction context",
                requested="the store statement's context",
                fix="thread the caller context; zero-arg super requires its __class__ cell",
            )
        return (
            super()
            .call_method_value(
                name,
                arguments,
                owner="MappingObjectValue.setitem",
                blame=site,
                ctx=ctx,
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

    def attribute(self, name, site, ctx):
        """``self.name`` by the one attribute lookup (``ObjectValue.attribute``)
        with the authenticated ``dict`` base among the classes of the MRO.

        A ``dict`` method is no data descriptor, so the instance ``__dict__``
        comes first; after it, a name the MRO binds to ``dict``
        (``protocol_owner``) whose method a door here applies
        (``_DICT_BASE_ARITIES``) reads as that method bound to this receiver
        (``BoundMethodValue``), whose call ``call_method_value`` answers from
        the storage (``dict_base_call``).  On an instance whose fields are
        not current the ``__dict__`` is not held: ``ObjectValue.attribute``'s
        undecided read, as for every name that is no data descriptor."""
        from .object_identity import contents_current

        if (
            name in _DICT_BASE_ARITIES
            and contents_current(self)
            and not any(field.name == name for field in self.fields)
            and self.protocol_owner(name, site) == "dict"
        ):
            from sugar_lift_py_tests.outcome import ExitSet

            from .bound_method_value import BoundMethodValue

            return ExitSet.completed(BoundMethodValue(self, name))
        return super().attribute(name, site, ctx)

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
        its storage (``_protocol_owner``, then ``dict_base_call``); every
        other name -- a source override included -- is the one source-method
        selection's (``ObjectValue.call_method_value``), which answers a
        name the lookup does not decide with the unanswered call."""
        if (
            required_frame is None
            and not keywords
            and len(arguments) in _DICT_BASE_ARITIES.get(name, ())
            and self._protocol_owner(name) == "dict"
        ):
            return self.dict_base_call(name, arguments, blame, ctx)
        return super().call_method_value(
            name,
            arguments,
            owner=owner,
            blame=blame,
            ctx=ctx,
            keywords=keywords,
            required_frame=required_frame,
        )

    def dict_base_call(self, name, arguments, blame, ctx):
        """``dict.<name>(self, *arguments)``: the authenticated builtin
        base's own method on this receiver's storage, one door per
        operation.  Both readers of dict's method apply it: a call the MRO
        resolves to ``dict`` (``call_method_value``) and a zero-argument
        ``super()`` that selects ``dict`` from a source override
        (``BuiltinSuperValue``).  ``__setitem__``/``__delitem__`` answer
        the receiver they leave.  None when dict's ``name`` at this arity is
        not one of these doors (``_DICT_BASE_ARITIES``)."""
        if len(arguments) not in _DICT_BASE_ARITIES.get(name, ()):
            return None
        if name == "__getitem__":
            return self._mapping_read(arguments[0], blame, ctx)
        if name == "__setitem__":
            return self.mapping_builtin_setitem(arguments[0], arguments[1], blame, ctx)
        if name == "__delitem__":
            return self.mapping_builtin_delitem(arguments[0], blame, ctx)
        if name == "__contains__":
            return self._builtin_dict().contains(arguments[0], blame)
        if name == "get":
            return self._mapping_get(arguments, blame)
        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
            TupleValue(tuple(TupleValue((key, value)) for key, value in self.entries))
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
