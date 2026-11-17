"""The exception an undetermined raise threw: real, opaque, keyed on its occurrence.

An ``UndeterminedRaiseEffect`` from a may-raise call (a C call, an unprojected
source call, an imported source-class construction, an opaque subscript) says
"this operation may leave by raising SOMETHING". That something is a Python
exception object. Nothing testified to its class or fields, but it exists, it
is exactly one object, and it is the object an ``except`` clause tests and an
``as`` name binds.

This value IS that object -- the subject of the handler's type test -- not a
substitute for it. Its term is ``python:undetermined_exception(occurrence,
producer)``: a function symbol whose denotation is the exception raised by
that occurrence of that producer. It is NOT the occurrence coordinate: the
coordinate (``file:line:col``) designates where the operation is written and
``adt.is_python_type(<coordinate>, T)`` is a predicate about a source span.
Here the coordinate is only the key that tells two raised objects apart, the
same way ``python:c_extension.call_completes`` keys an opaque completion on
its call site.

Every projection stays opaque: its type is ``UndeterminedExceptionTypeValue``,
and a read of ``args``, a message or ``__cause__`` is the one undecided read,
never invented.  Any other operation refuses through the ``FloorValue``
defaults.
"""

from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class UndeterminedExceptionValue(FloorValue):
    """The one exception object an undetermined raise occurrence threw."""

    occurrence: str
    producer: str | None = None
    # ``python:raised(<call term>, <occurrence>)``: the exception one
    # evaluation of a call whose edge names its callee raised
    # (``UndeterminedRaiseEffect.raised_by_call``, #7757 step 7).  Its type
    # is what the callee's contract states for the halt it took, decided at
    # prove against the handler that tests it; nothing about it is decided
    # here.
    raised_by_call: object | None = None

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        del owner
        if self.raised_by_call is not None:
            return self.raised_by_call
        return ctor(
            "python:undetermined_exception",
            (str_const(self.occurrence), str_const(self.producer or "")),
        )

    def denotes_value(self) -> bool:
        """This floor value denotes one Python exception object."""
        return True

    def runtime_type_is_decided(self) -> bool:
        # Its class is exactly what nobody testified to.
        return False

    def is_identical(self, other, site):
        """``e is None`` is decided false: a raised object is a
        ``BaseException`` instance, never the ``None`` singleton.  Any other
        operand keeps the emitted identity -- nothing about which object it
        is was testified to."""
        from sugar_lift_py_tests.floor.none_value import NoneValue

        if type(other) is NoneValue:
            from sugar_lift_py_tests.outcome import ExitSet
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )

            return ExitSet.completed(FalseBoolLiteralSugar(site=site))
        return super().is_identical(other, site)

    def attribute(self, name, site, ctx):
        """``e.name``: nothing testified to the object's class, so the read
        is the one undecided read (``floor_value.undecided_attribute_result``,
        #7757 NEW-3), two-faced and owed, keyed per evaluation.  Its
        ``args``, message and ``__cause__`` are never invented: the completed
        face is ``python:attribute_result(<name>, <e>, <key>)``, which the
        raising callee's contract answers at prove, if any does."""
        from sugar_lift_py_tests.floor.floor_value import undecided_attribute_result

        del ctx
        return undecided_attribute_result(
            self, name, site, owner="UndeterminedExceptionValue.attribute"
        )


@dataclass(frozen=True)
class UndeterminedExceptionTypeValue(FloorValue):
    """``type(e)`` of an undetermined exception: derived from ``e``, never named.

    ``with`` hands ``__exit__`` the triple ``(type(e), e, tb)``. When ``e`` is
    the ``UndeterminedExceptionValue`` a may-raise operation threw, its class
    is exactly what nobody testified to, so this value is the function symbol
    ``python:type_of(<e>)`` -- not a class spelling, not the raise site.

    Its tests are the ones ``except`` states over ``e`` itself:

    * ``exc_type is None`` is decided false: a raised exception's class is a
      class, never ``None``.
    * ``issubclass(type(e), BaseException)`` is decided true: Python 3 only
      raises ``BaseException`` instances.
    * ``issubclass(type(e), B)`` for any other builtin exception class ``B``
      retains ``adt.is_python_type(<e>, B)``, the same atom ``except B``
      retains over the same exception (a builtin class has metaclass
      ``type``, so subclass and except matching coincide).
    * any other builtin class ``C`` retains ``python.subtype(
      python:type_of(<e>), C)``: two classes, metaclass ``type``, no halt.
    * an undecided operand (a symbolic value) may be no class, or its
      metaclass may run its own ``__subclasscheck__``: the undecided type
      test, its halt kept (``floor_value.class_subtype_test``, #7757).

    Every other projection (rich comparison, attribute reads, identity
    against a non-``None`` operand) refuses through the ``FloorValue``
    defaults or below: nothing about the class is invented.
    """

    exception: UndeterminedExceptionValue

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor("python:type_of", (self.exception.to_term(owner=owner),))

    def denotes_value(self) -> bool:
        return True

    def runtime_type_is_decided(self) -> bool:
        # Its metaclass is not testified to either.
        return False

    def test_python_subtype(self, supertype, site):
        from sugar_lift_py_tests.floor import ClassValue, SymbolicValue, TupleValue
        from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
            AuthenticatedExceptionTypeValue,
        )
        from sugar_lift_py_tests.floor.builtin_exception_class_value import (
            BuiltinExceptionClassValue,
        )
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import atomic
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        if type(supertype) is TupleValue:
            return supertype.test_python_subtype(self, site)
        native = supertype
        while isinstance(native, AuthenticatedExceptionTypeValue):
            native = native.class_value if native.class_value is not None else native.value
        if isinstance(native, BuiltinExceptionClassValue):
            identity = native.exception_type_identity()
            if _names_base_exception(identity):
                return ExitSet.completed(TrueBoolLiteralSugar(site=site))
            return ExitSet.completed(
                PredicateValue(
                    atomic(
                        "adt.is_python_type",
                        [self.exception.to_term(owner="python.issubclass"), identity],
                    ),
                    site,
                )
            )
        if not isinstance(native, (ClassValue, SymbolicValue)):
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="UndeterminedExceptionTypeValue.test_python_subtype",
                blame=str(site),
                observed=type(supertype).__name__,
                requested="authenticated class, tuple-of-classes, or symbolic type operand",
                fix="construct the Python type operand or keep issubclass loudly unsupported",
            )
        from sugar_lift_py_tests.floor.floor_value import class_subtype_test

        return class_subtype_test(
            self,
            native,
            site,
            owner="UndeterminedExceptionTypeValue.test_python_subtype",
        )

    def is_identical(self, other, site):
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.outcome.exit_set import false_guard

        if isinstance(other, NoneValue):
            return ExitSet.completed(PredicateValue(false_guard(), site))
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="UndeterminedExceptionTypeValue.is_identical",
            blame=site,
            observed=type(other).__name__,
            requested="the raised exception's actual class",
            fix="nobody testified to this class; its identity stays unasked",
        )

    def equals(self, other, site, ctx):
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="UndeterminedExceptionTypeValue.equals",
            blame=site,
            observed=type(other).__name__,
            requested="the raised exception's actual class and metaclass",
            fix="nobody testified to this class; its rich comparison stays unasked",
        )


def _names_base_exception(identity) -> bool:
    args = getattr(identity, "args", ())
    return (
        len(args) == 2
        and getattr(args[0], "value", None) == "builtins"
        and getattr(args[1], "value", None) == "BaseException"
    )
