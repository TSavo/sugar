from __future__ import annotations

from dataclasses import dataclass

from .bound_method_value import BoundMethodValue
from .floor_value import FloorValue


@dataclass(frozen=True)
class BuiltinSuperMethodValue(BoundMethodValue):
    """One selected method on an authenticated zero-argument ``super``."""


_OWNER = "BuiltinSuperValue.call_method_value"

#: ``python:super_check_of(<class>, "<cell class>", <occurrence>)``: THE one
#: statement of the ``supercheck`` of a zero-argument ``super()`` (#7757).
#: ``<class>`` is what the check tests against the cell's class
#: (``super_check_class``).  Its completion
#: (``python:super_check_of.completes``) is decided at prove, both ways,
#: where the class is bound (``consistency::super_check_facts``); the lift
#: never decides it.
SUPER_CHECK_OF = "python:super_check_of"

#: ``python:super_receiver_class(<occurrence>)``: the class of a ``super()``
#: receiver the lift does not read, uninterpreted: nothing at prove decides a
#: check over it, so the check stays owed.
SUPER_RECEIVER_CLASS = "python:super_receiver_class"

#: ``python:builtin_iterator_class("builtins.<t>")``: the class of ``iter()``
#: of an exact instance of the builtin type ``<t>`` -- a builtin iterator
#: class (``list_iterator``, ``dict_keyiterator``, a ``generator`` itself,
#: ...), named by the type it iterates, never by the version-dependent name
#: CPython gives it.  The class a generator expression's ``.0`` is, where its
#: outermost iterable's type is decided
#: (``builtin_semantic_callable.zero_argument_super_generator_iterable_type``).
#: Prove decides the check over it fails against any source class
#: (``consistency::super_check_facts``); the lift decides nothing (#7757 NEW-2).
BUILTIN_ITERATOR_CLASS = "python:builtin_iterator_class"


def formal_class_input(receiver, site):
    """``class:<p>`` (the free input) where ``receiver`` is the plain value of
    a positional or keyword parameter of the function whose own proof this
    is and that parameter's class is an input of its contract
    (``receiver_dispatch.class_input_formals``), in a module that gives no
    object another class (``module_attribute_names``); None otherwise.  A
    ``super()`` on it is decided at prove over that input."""
    from sugar_lift_py_tests.contract_input import CLASS_INPUT, input_formal
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.receiver_dispatch import (
        class_input_formals,
        module_attribute_names,
    )

    unit = getattr(site, "unit", None)
    coordinate = getattr(receiver, "formal_coordinate", None)
    if (
        unit is None
        or type(receiver) is not SymbolicValue
        or not isinstance(coordinate, FormalParameterCoordinateV1)
        or coordinate.parameter_kind
        not in ("positional-only", "positional-or-keyword", "keyword-only")
        or coordinate.coordinate_cid not in class_input_formals(unit)
        or module_attribute_names(unit)[1]
    ):
        return None
    return make_var(input_formal(CLASS_INPUT, coordinate.declared_name))


def super_check_class(receiver, site):
    """What ``supercheck`` tests against ``__class__`` for ``receiver``, as
    the one check term states it (``SUPER_CHECK_OF``), never decided here:

    - a parameter whose class is the contract's input: ``class:<p>``
      (``formal_class_input``), bound by the caller;
    - a class object (``super()`` given the class): the class object's own
      term (``ClassDefinitionValue.to_term``), the term its namespace row
      states (``python:class_object``);
    - an instance whose class is decided here (``receiver_class_decided``),
      or a same-file class call's result: its class as a dispatched call
      supplies it (``receiver_dispatch.class_value``:
      ``python:instance("<D>", ...)``, ``python:constructed("<D>")``);
    - no receiver -- a generator expression's ``.0`` iterator, which no value
      here holds -- over an outermost iterable whose exact builtin type is
      decided (``zero_argument_super_generator_iterable_type``): its builtin
      iterator class, ``python:builtin_iterator_class("builtins.<t>")``;
    - anything else (an instance that arrived by binding, a value of no
      decided class, a ``.0`` iterator over any other iterable):
      ``python:super_receiver_class(<occurrence>)``, a class not read."""
    from sugar_lift_py_tests.floor.class_definition_value import (
        ClassDefinitionValue,
    )
    from sugar_lift_py_tests.floor.object_value import (
        ObjectValue,
        receiver_class_decided,
    )
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.occurrence import occurrence_term
    from sugar_lift_py_tests.receiver_dispatch import class_value

    if receiver is None:
        from sugar_lift_py_tests.floor.builtin_semantic_callable import (
            zero_argument_super_generator_iterable_type,
        )
        from sugar_lift_py_tests.ir import str_const

        iterable_type = zero_argument_super_generator_iterable_type(site)
        if iterable_type is not None:
            return ctor(BUILTIN_ITERATOR_CLASS, (str_const(iterable_type),))
        return ctor(SUPER_RECEIVER_CLASS, (occurrence_term(site),))
    formal = formal_class_input(receiver, site)
    if formal is not None:
        return formal
    if isinstance(receiver, ClassDefinitionValue):
        return receiver.to_term(owner=str(site))
    if receiver is not None and (
        not isinstance(receiver, ObjectValue) or receiver_class_decided(receiver)
    ):
        decided = class_value(receiver)
        if decided is not None:
            return decided
    return ctor(SUPER_RECEIVER_CLASS, (occurrence_term(site),))


@dataclass(frozen=True)
class BuiltinSuperValue(FloorValue):
    """Authenticated zero-argument ``super()``: ``super(__class__, obj)``.

    ``current_class`` is the class value the frame's ``__class__`` cell holds
    (PEP 3135), ``receiver`` the frame's first argument ``obj``.  Every lookup
    walks ``type(obj).__mro__`` from the class after ``__class__``
    (``super_getattro``, Objects/typeobject.c), so ``super()`` in ``B.m`` on
    a ``D(B, C)`` with ``B(A)``, ``C(A)`` reaches ``C``, never ``B``'s own
    base ``A``.  That walk is prove's, once (``consistency::dispatch_walk``,
    #7757 NEW-7): the lift states the dispatched call after ``__class__``
    and reads no source class's namespace; only a tail of builtins, which
    no namespace row states, is answered here by the floor
    (``_builtin_tail_member``).  When the receiver's class is not decided,
    the lookup is the one unanswered call.

    Built through ``constructed``, which is CPython's ``supercheck``.
    """

    current_class: object
    receiver: object

    @classmethod
    def constructed(cls, current_class, receiver, site, *, cell=None):
        """``super()`` built over ``current_class`` and ``receiver``: CPython's
        ``supercheck``, stated once and decided at prove (#7757).  It
        completes with the super object when ``obj`` is an instance or
        subclass of ``__class__``; otherwise it raises (CPython's
        ``TypeError``, or whatever reading ``obj.__class__`` raises in its
        last resort).  Both faces are kept, two-faced and owed
        (``ExitSet.two_faced``), under the one check atom
        ``python:super_check_of.completes(python:super_check_of(<class>,
        "<cell class>", <occurrence>))`` (``super_check_class``), which
        ``consistency::super_check_facts`` decides -- or its negation --
        where the proofs state the class's order.  Nothing here reads an
        order to decide it.  The cell class is ``cell``, the class statement
        the frame's ``__class__`` cell holds, where the caller read it off
        the frame (a generator expression's ``.0`` check, whose cell class
        no value here may hold), else ``current_class``'s own statement.  A
        cell class that names no join symbol (no workspace root) is spelled
        ``""``: no row states it, so the check stays owed."""
        from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
        from sugar_lift_py_tests.ir import atomic, ctor, str_const
        from sugar_lift_py_tests.occurrence import occurrence_key, occurrence_term
        from sugar_lift_py_tests.outcome import ExitSet

        key = occurrence_key(site)
        if cell is None:
            cell = getattr(current_class, "class_definition", None)
        cell_symbol = None if cell is None else cell.bridge_source_symbol()
        completes = atomic(
            SUPER_CHECK_OF + ".completes",
            [
                ctor(
                    SUPER_CHECK_OF,
                    (
                        super_check_class(receiver, site),
                        str_const(cell_symbol or ""),
                        occurrence_term(site),
                    ),
                )
            ],
        )
        return ExitSet.two_faced(
            cls(current_class, receiver),
            UndeterminedRaiseEffect(
                blame=str(site),
                occurrence=key,
                producer_node_owner="BuiltinSuperValue.supercheck",
                site=site,
            ),
            guard=completes,
            site=site,
        )

    def attribute(self, name, site, ctx):
        """``super().<name>`` read, not called (#7757 NEW-7).

        - A builtin method of a tail of the receiver's order after
          ``__class__`` that holds no source class (``_builtin_tail_member``):
          the super method value, which the floor's builtin semantics answer
          when called.
        - Otherwise the dispatched read after ``__class__``
          (``receiver_dispatch.dispatch_edge_call`` with ``read`` and
          ``after``) on an instance whose class is decided here or a
          parameter whose class is the contract's input: two-faced, its
          completed face the super method value.  Prove's one walk of the
          receiver's order (``consistency::dispatch_walk``) decides whether
          no class after ``__class__`` binds ``name`` (the ``AttributeError``
          face, the one it keeps); any other read stays owed.  Nothing here
          walks the order for a source class's member.
        - Anything else (a class receiver, a receiver whose class is not
          decided, no join symbol, no site): the one undecided attribute
          read, two-faced and owed."""
        del ctx
        from sugar_lift_py_tests.floor.class_definition_value import (
            ClassDefinitionValue,
        )
        from sugar_lift_py_tests.floor.object_value import receiver_class_decided
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.receiver_dispatch import (
            class_value,
            dispatch_edge_call,
        )

        method = BuiltinSuperMethodValue(self, name)
        if self._builtin_tail_member(name) is not None:
            return ExitSet.completed(method)
        definition = getattr(self.current_class, "class_definition", None)
        after = None if definition is None else definition.bridge_source_symbol()
        receiver_class = None
        if (
            after is not None
            and site is not None
            and not isinstance(self.receiver, ClassDefinitionValue)
        ):
            receiver_class = formal_class_input(self.receiver, site)
            if receiver_class is None and receiver_class_decided(self.receiver):
                receiver_class = class_value(self.receiver)
        if receiver_class is None:
            from sugar_lift_py_tests.floor.floor_value import (
                undecided_attribute_result,
            )

            return undecided_attribute_result(self, name, site, owner=_OWNER)
        read = dispatch_edge_call(
            name, self.receiver, receiver_class, (), (), site, read=True, after=after
        )
        return read.and_then(lambda _read: ExitSet.completed(method))

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
        """``super().<name>(...)`` (#7757 NEW-7): the builtin method of a
        tail of the receiver's order after ``__class__`` that holds no
        source class, where the floor writes it (``_builtin_tail_member``,
        ``_builtin_method``); otherwise the one dispatched call after
        ``__class__`` (``_dispatched``).  The lift never walks the order for
        a source class's member: prove's one walk
        (``consistency::dispatch_walk``) decides which member runs, how it
        binds, and whether no class after ``__class__`` binds ``name``
        (``AttributeError``, the halt the call keeps)."""
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
        entry = self._builtin_tail_member(name)
        if entry is not None:
            return self._builtin_method(entry, name, arguments, keywords, blame, ctx)
        return self._dispatched(name, arguments, keywords, blame)

    def _dispatched(self, name, arguments, keywords, site):
        """``super().<name>(...)`` as the one dispatched call (#7757 entry 6,
        ``receiver_dispatch.dispatch_edge_call`` with ``after``): the lookup
        starts after ``__class__`` (its join symbol, ``py.lookup``), and
        prove looks ``name`` up on the order the receiver's class's own
        proof states (``consistency::dispatched_target``).

        - A receiver that is a class (``super()`` in a ``classmethod``):
          looked up on that class object, nothing bound but what its kind
          binds (``ClassDefinitionValue._dispatched_on_class``).
        - An instance whose class is decided here (``receiver_class_decided``
          and ``receiver_dispatch.class_value``): the receiver is the call's
          first operand, keyed ``"0"``, its class riding beside it, and the
          caller reads it after the call by that key
          (``receiver_dispatch.receiver_after_dispatch``).

        Anything else -- an instance that arrived by binding (it may be of
        a subclass whose order puts another class after ``__class__``), a
        class that names no join symbol, a call with no site -- is the one
        unanswered call (``_unanswered``), owed."""
        from sugar_lift_py_tests.floor.class_definition_value import (
            ClassDefinitionValue,
        )
        from sugar_lift_py_tests.floor.object_value import receiver_class_decided

        definition = getattr(self.current_class, "class_definition", None)
        after = None if definition is None else definition.bridge_source_symbol()
        if after is None or site is None:
            return self._unanswered(name, arguments, keywords, site)
        if isinstance(self.receiver, ClassDefinitionValue):
            return self.receiver._dispatched_on_class(
                name, arguments, keywords, site, after=after
            )
        from sugar_lift_py_tests.receiver_dispatch import (
            class_value,
            dispatch_edge_call,
        )

        formal_class = formal_class_input(self.receiver, site)
        if formal_class is not None:
            # A parameter whose class is the contract's input: its class
            # rides as that input, bound by the caller (#7757).
            return dispatch_edge_call(
                name,
                self.receiver,
                formal_class,
                tuple(arguments),
                tuple(keywords),
                site,
                after=after,
            )
        if not receiver_class_decided(self.receiver):
            return self._unanswered(name, arguments, keywords, site)

        receiver_class = class_value(self.receiver)
        if receiver_class is None:
            return self._unanswered(name, arguments, keywords, site)
        return dispatch_edge_call(
            name,
            self.receiver,
            receiver_class,
            tuple(arguments),
            tuple(keywords),
            site,
            after=after,
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

    def _builtin_tail_member(self, name):
        """The builtin class (``"object"``, ``"dict"``, ``"type"``, a builtin
        exception) of ``type(obj).__mro__`` after ``__class__`` whose own
        ``__dict__`` holds ``name``, where every class of that tail is a
        builtin, or None.

        A tail of builtins holds no namespace row, so prove's walk answers
        no member of it (``consistency::dispatch_walk``): what the floor
        writes of a builtin's method is the one way a call into it is
        answered (``_builtin_method``).  A tail that holds any source class
        is never read here, nor is a name no builtin of it holds: both are
        the dispatched call, decided by prove's one walk.  Read only on a
        receiver whose class is decided here (``receiver_class_decided``):
        an instance that arrived by binding may be of a subclass whose order
        puts a source class after ``__class__``."""
        from sugar_lift_py_tests.floor.object_value import receiver_class_decided

        if not receiver_class_decided(self.receiver):
            return None
        _type_value, definition = self._receiver_type()
        cell = getattr(self.current_class, "class_definition", None)
        if definition is None or cell is None:
            return None
        # A class statement of the tail answers "not read": only a tail of
        # builtins is decided, by each builtin's own ``__dict__``.
        decided, found = definition._namespace_owner(
            name, lambda _entry: None, after=cell
        )
        return found if decided and isinstance(found, str) else None

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
            # The receiver leaves the call as it came (its transition is the
            # identity), which the statement's receiver reads after it
            # (``call_site_value.receiver_after_its_call``); the call's value
            # is ``None``.
            if not arguments and not keywords:
                from sugar_lift_py_tests.floor.receiver_owned_mutation_result import (
                    ReceiverOwnedMutationResult,
                )

                return ExitSet.completed(
                    ReceiverOwnedMutationResult(
                        self.receiver, self.receiver, NoneValue()
                    )
                )
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
