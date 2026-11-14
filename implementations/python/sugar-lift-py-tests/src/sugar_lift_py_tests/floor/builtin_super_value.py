from __future__ import annotations

from dataclasses import dataclass

from .bound_method_value import BoundMethodValue
from .floor_value import FloorValue


@dataclass(frozen=True)
class BuiltinSuperMethodValue(BoundMethodValue):
    """One selected method on an authenticated zero-argument ``super``."""


_OWNER = "BuiltinSuperValue.call_method_value"


@dataclass(frozen=True)
class BuiltinSuperValue(FloorValue):
    """Authenticated zero-argument ``super()``: ``super(__class__, obj)``.

    ``current_class`` is the class value the frame's ``__class__`` cell holds
    (PEP 3135), ``receiver`` the frame's first argument ``obj``.  Every lookup
    walks ``type(obj).__mro__`` from the class after ``__class__``
    (``super_getattro``, Objects/typeobject.c): the receiver's class's one
    base walk (``ClassDef.namespace_owner(name, after=...)``, #8069), so
    ``super()`` in ``B.m`` on a ``D(B, C)`` with ``B(A)``, ``C(A)`` reaches
    ``C``, never ``B``'s own base ``A``.  When the receiver's MRO is not read,
    the lookup is the one unanswered call.

    Built through ``constructed``, which is CPython's ``supercheck``.
    """

    current_class: object
    receiver: object

    @classmethod
    def constructed(cls, current_class, receiver, site):
        """``super()`` built over ``current_class`` and ``receiver``: CPython's
        ``supercheck`` (``super_check``).  It completes with the super object
        when ``obj`` is an instance or subclass of ``__class__``; a check that
        fails is CPython's ``TypeError: super(type, obj): obj must be an
        instance or subtype of type``; a check not decided here is two-faced,
        owing the ``undecided`` member (``ExitSet.two_faced``) -- the check's
        last resort reads ``obj.__class__``, which may run anything."""
        from sugar_lift_py_tests.outcome import ExitSet

        verdict = super_check(current_class, receiver)
        if verdict is True:
            return ExitSet.completed(cls(current_class, receiver))
        if verdict is False:
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="TypeError",
                site=site,
                owner="BuiltinSuperValue.supercheck",
            )
        from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
        from sugar_lift_py_tests.ir import atomic, ctor
        from sugar_lift_py_tests.occurrence import occurrence_key, occurrence_term

        key = occurrence_key(site)
        completes = atomic(
            "python:super_check.completes",
            [ctor("python:super_check", (occurrence_term(site),))],
        )
        return ExitSet.two_faced(
            cls(current_class, receiver),
            UndeterminedRaiseEffect(
                blame=str(site),
                occurrence=key,
                producer_node_owner="BuiltinSuperValue.supercheck",
            ),
            guard=completes,
            site=site,
        )

    def attribute(self, name, site, ctx):
        del ctx
        from sugar_lift_py_tests.outcome import ExitSet

        decided, found, _type_value = self._lookup(name)
        if decided and found is None:
            return self._absent(name, site)
        return ExitSet.completed(BuiltinSuperMethodValue(self, name))

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
        del owner
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        if required_frame is not None:
            construction_panic_gap(
                owner=_OWNER,
                blame=blame,
                observed=name,
                requested="authenticated builtin super method",
                fix="model the selected base method or keep it loud",
            )
        decided, found, type_value = self._lookup(name)
        if not decided:
            return self._unanswered(name, arguments, keywords, blame)
        if found is None:
            return self._absent(name, blame)
        if isinstance(found, str):
            return self._builtin_method(found, name, arguments, keywords, blame, ctx)
        if not found.namespace_value_is_body(name):
            # The selected class holds ``name``, but not as its body bound it:
            # a decorator wrote it (a dataclass's generated ``__init__``) or
            # creation or a store may have.  That value is not run here.
            return self._unanswered(name, arguments, keywords, blame)
        selected = type_value.class_value_of_statement(found)
        if selected is None:
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                owner=_OWNER,
                blame=blame,
                observed=f"{found.name}.{name} has no class value here",
                requested="the class value of the statement super() selected",
                fix="carry every class of the receiver's MRO as a class value",
            )
        # The selected class's own method on the original receiver; its body
        # reduces with ``__class__`` seeded to that class, so a further
        # ``super()`` in it continues along the receiver's MRO.
        return selected.dispatch_super_method(
            self.receiver,
            name,
            arguments,
            owner=_OWNER,
            blame=blame,
            ctx=ctx,
            keywords=keywords,
        )

    def _receiver_type(self):
        """``(type_value, definition)``: the class whose MRO ``super`` walks
        and its class statement, or ``(None, None)`` when it is not read.

        ``supercheck``: an ``obj`` that is a class and a subclass of
        ``__class__`` walks its own MRO; an instance walks its class's
        (``ObjectValue.defining_class``).  A class that is not decided a
        subclass of ``__class__`` would walk its metaclass's, which is not
        read here.
        """
        from sugar_lift_py_tests.floor.class_definition_value import (
            ClassDefinitionValue,
        )
        from sugar_lift_py_tests.floor.object_value import ObjectValue

        cell = getattr(self.current_class, "class_definition", None)
        if cell is None:
            return None, None
        if isinstance(self.receiver, ClassDefinitionValue):
            definition = self.receiver.class_definition
            if definition is not None and definition.mro_holds(cell) is True:
                return self.receiver, definition
            return None, None
        if isinstance(self.receiver, ObjectValue):
            type_value = self.receiver.defining_class
            definition = getattr(type_value, "class_definition", None)
            if isinstance(type_value, ClassDefinitionValue) and definition is not None:
                return type_value, definition
        return None, None

    def _lookup(self, name):
        """``(decided, owner, type_value)``: the class of ``type(obj).__mro__``
        after ``__class__`` whose namespace binds ``name`` (a ``ClassDef`` or
        a builtin class name, None when no class of the order binds it), read
        by the one base walk.  Not decided when the receiver's MRO is not
        read."""
        type_value, definition = self._receiver_type()
        if definition is None:
            return False, None, None
        decided, found = definition.namespace_owner(
            name, after=self.current_class.class_definition
        )
        return decided, found, type_value

    def _absent(self, name, site):
        """No class of ``type(obj).__mro__`` after ``__class__`` binds
        ``name``: ``super_getattro`` falls back to the super object's own
        attributes, and a name it has not either is CPython's
        ``AttributeError``."""
        if hasattr(super, name):
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner=_OWNER,
                blame=site,
                observed=f"super.{name}",
                requested="the super object's own attribute semantics",
                fix="model the super object's own attribute or keep it loud",
            )
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError", site=site, owner=_OWNER
        )

    def _unanswered(self, name, arguments, keywords, site):
        """``super().<name>(...)`` whose receiver's MRO is not read, or not
        decided for ``name`` (a class whose decorator or a store may have
        written it, ``ClassDef.namespace_binds``), or whose selected class
        holds a value its body did not bind (``namespace_value_is_body``):
        the one unanswered call (``UnknownCalleeCallV1``), two-faced and
        owed, its completion the call's own result coordinate.  Neither a
        direct base nor any other class is assumed to answer."""
        from sugar_lift_py_tests.call_symbol import call_symbol
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1

        target = f"super.{name}"
        term_owner = str(site)
        callsite = CallSiteValue(
            target_name=target,
            arg_values=(*arguments, *(value for _name, value in keywords)),
            parameters=(),
            term=ctor(
                call_symbol(target),
                [value.to_term(owner=term_owner) for value in arguments]
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

    def _builtin_method(self, entry, name, arguments, keywords, blame, ctx):
        """``name`` bound by the builtin class ``entry`` of the receiver's MRO
        (``"object"``, ``"dict"``, ``"type"`` or a builtin exception class,
        read by binding): that class's own method on the receiver, where the
        floor models it; otherwise a named gap."""
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
        from sugar_lift_py_tests.outcome import ExitSet

        if entry == "type" and name == "__new__":
            return self._type_new(arguments, keywords, blame)
        if name == "__init__" and entry in ("object", "dict"):
            # ``object_init`` / ``dict_init`` with no actual: nothing to do.
            if not arguments and not keywords:
                return ExitSet.completed(NoneValue())
        elif entry == "dict" and not keywords:
            answered = self._dict_base_call(name, arguments, blame, ctx)
            if answered is not None:
                return answered
        if name == "__init__":
            from sugar_lift_py_tests.floor.builtin_exception_class_value import (
                BuiltinExceptionClassValue,
            )
            from sugar_lift_py_tests.temporal.builtin_name_bindings import (
                builtin_name_temporal,
            )

            builtin = builtin_name_temporal().value_if_bound(entry)
            if isinstance(builtin, BuiltinExceptionClassValue):
                # A builtin exception's ``__init__`` is BaseException's law
                # on the original instance receiver.
                return builtin.initialize_instance(
                    self.receiver,
                    arguments,
                    keywords,
                    blame=blame,
                    owner=_OWNER,
                )
        construction_panic_gap(
            owner=_OWNER,
            blame=blame,
            observed=f"{entry}.{name}",
            requested="authenticated selected-base method semantics",
            fix="model the selected base method or keep it loud",
        )

    def _dict_base_call(self, name, arguments, blame, ctx):
        """``super().<name>(...)`` that selects ``dict``: dict's own method
        on the receiver's base storage, through the mapping's one door per
        operation (``MappingObjectValue.dict_base_call``) -- the door a call
        the MRO resolves to ``dict`` takes.  A mutation (``__setitem__``,
        ``__delitem__``) is the receiver's transition with dict's ``None``
        result kept apart (``ReceiverOwnedMutationResult``), which the source
        override's store reads back.  None when dict's ``name`` at this arity
        is not one of those doors."""
        from sugar_lift_py_tests.floor.mapping_object_value import (
            MappingObjectValue,
        )
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.floor.receiver_owned_mutation_result import (
            ReceiverOwnedMutationResult,
        )
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
        from sugar_lift_py_tests.outcome import ExitSet

        if not isinstance(self.receiver, MappingObjectValue):
            construction_panic_gap(
                owner=_OWNER,
                blame=blame,
                observed=type(self.receiver).__name__,
                requested=f"authenticated mapping receiver for dict.{name}",
                fix="preserve the source method receiver through zero-arg super",
            )
        answered = self.receiver.dict_base_call(name, arguments, blame, ctx)
        if answered is None or name not in ("__setitem__", "__delitem__"):
            return answered
        return answered.and_then(
            lambda updated: ExitSet.completed(
                ReceiverOwnedMutationResult(self.receiver, updated, NoneValue())
            )
        )

    def _type_new(self, arguments, keywords, blame):
        from sugar_lift_py_tests.floor.dict_value import DictValue
        from sugar_lift_py_tests.floor.mapping_object_value import MappingObjectValue
        from sugar_lift_py_tests.floor.runtime_class_value import RuntimeClassValue
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
        from sugar_lift_py_tests.outcome import ExitSet

        if len(arguments) != 4:
            construction_panic_gap(
                owner="BuiltinSuperValue.type.__new__",
                blame=blame,
                observed=f"arity={len(arguments)}",
                requested="metaclass, class name, bases, and namespace",
                fix="retain exact type.__new__ operands or keep the call loud",
            )
        _metaclass, name, bases, namespace = arguments
        if (
            not isinstance(name, StringValue)
            or not isinstance(bases, TupleValue)
            or not isinstance(namespace, (DictValue, MappingObjectValue))
        ):
            construction_panic_gap(
                owner="BuiltinSuperValue.type.__new__",
                blame=blame,
                observed=tuple(type(value).__name__ for value in arguments),
                requested="authenticated class name, bases, and mapping namespace",
                fix="transport metaclass __new__ actuals without symbolic projection",
            )
        # ``**kwds`` is evaluated and authenticated by MethodCallSugar.  It does
        # not alter the namespace identity represented by this Floor.
        del keywords
        return ExitSet.completed(
            RuntimeClassValue(
                name=name.value,
                bases=tuple(bases.elements),
                record=namespace,
                namespace=namespace,
            )
        )


def super_check(current_class, receiver) -> "bool | None":
    """CPython's ``supercheck`` (Objects/typeobject.c) for ``super(__class__,
    obj)``, read off the one base walk: whether ``__class__``'s class
    statement stands in the MRO ``super`` would walk (``ClassDef.mro_holds``,
    matched by source occurrence).

    - ``obj`` a class whose MRO holds ``__class__``: True.
    - ``obj`` an instance (``ObjectValue``) whose class's MRO holds it: True.
      Whose class's order, read whole, does not, and whose ``obj.__class__``
      is ``object``'s own (no class of the order before ``object`` binds
      ``__class__`` or ``__getattribute__``, so the last resort reads
      ``type(obj)`` again): False, CPython's ``TypeError``.
    - Anything else -- a class not decided a subclass (its metaclass is not
      read), a receiver whose class is not carried or whose MRO is not read,
      a ``__class__`` value with no class statement: None, not decided.
    """
    from sugar_lift_py_tests.floor.class_definition_value import (
        ClassDefinitionValue,
    )
    from sugar_lift_py_tests.floor.object_value import ObjectValue

    cell = getattr(current_class, "class_definition", None)
    if cell is None:
        return None
    if isinstance(receiver, ClassDefinitionValue):
        definition = receiver.class_definition
        if definition is not None and definition.mro_holds(cell) is True:
            return True
        return None
    if not isinstance(receiver, ObjectValue):
        return None
    definition = getattr(receiver.defining_class, "class_definition", None)
    if definition is None:
        return None
    held = definition.mro_holds(cell)
    if held is not False:
        return held
    for read in ("__class__", "__getattribute__"):
        decided, owner = definition.namespace_owner(read)
        if not decided or owner != "object":
            return None
    return False
