"""Tree-native manager / enter-result / exit-face coordinates.

Manager is evaluated **once**; ``ManagerRef(M)`` is the stable receiver for
``__enter__`` / ``__exit__``. Exit args are parametric
``ExitTypeRef(X)`` / ``ExitValueRef(X)`` / ``ExitTracebackRef(X)`` — pure
coordinates; face testimony authenticates them under guards.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.ir import Term

from .floor_value import FloorValue


@dataclass(frozen=True)
class ManagerCoordinate(FloorValue):
    """Once-evaluated manager identity: ``python:manager_slot(M)``."""

    slot_id: str
    site: object = dataclass_field(compare=False, default=None)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:manager_slot", [str_const(self.slot_id)])


@dataclass(frozen=True)
class EnterResultCoordinate(FloorValue):
    """``with m as x`` enter-result coordinate: ``python:enter_result(E)``."""

    slot_id: str
    site: object = dataclass_field(compare=False, default=None)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:enter_result", [str_const(self.slot_id)])


@dataclass(frozen=True)
class ExitTypeCoordinate(FloorValue):
    """Parametric ``__exit__`` type arg: ``python:exit_type(X)``."""

    face_id: str
    site: object = dataclass_field(compare=False, default=None)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:exit_type", [str_const(self.face_id)])

    def test_python_subtype(self, supertype, site):
        from sugar_lift_py_tests.floor import ClassValue, SymbolicValue, TupleValue
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import atomic
        from sugar_lift_py_tests.outcome import ExitSet

        if type(supertype) is TupleValue:
            return supertype.test_python_subtype(self, site)
        if not isinstance(supertype, (ClassValue, SymbolicValue)):
            return _dynamic_subtype_operand(self, supertype, site)
        return ExitSet.completed(
            PredicateValue(
                atomic(
                    "python.subtype",
                    [
                        self.to_term(owner="python.issubclass subtype"),
                        supertype.to_term(owner="python.issubclass supertype"),
                    ],
                ),
                site,
                operand_callsites=(*self.callsites(), *supertype.callsites()),
            )
        )


@dataclass(frozen=True)
class ExitValueCoordinate(FloorValue):
    """Parametric ``__exit__`` value arg: ``python:exit_value(X)``."""

    face_id: str
    site: object = dataclass_field(compare=False, default=None)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:exit_value", [str_const(self.face_id)])

    @property
    def coordinate_cid(self):
        """Authenticate discharge to this exact parametric exit-value slot."""
        from sugar_lift_py_tests.ir import _term_content_cid

        return _term_content_cid(self.to_term(owner="exit value coordinate"))

    def attribute(self, name, site, ctx):
        """Defer lookup and its consumers until the real exit value is known.

        An exit slot does not authenticate a field's existence, runtime type,
        descriptor effects, or rich comparison dispatch. Preserve the native
        lookup occurrence rather than minting a completed getattr term; the
        lookup discharges later under the context of the caller that fills it.
        """
        del ctx
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )
        from sugar_lift_py_tests.floor.string_value import StringValue

        return NativeOperationExitCarrierV1.mint(
            site=site,
            operator="attribute_named",
            operands=(self, StringValue(name)),
            coordinates=(self, None),
        )


@dataclass(frozen=True)
class ExitTracebackCoordinate(FloorValue):
    """Parametric ``__exit__`` traceback arg: ``python:exit_traceback(X)``."""

    face_id: str
    site: object = dataclass_field(compare=False, default=None)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:exit_traceback", [str_const(self.face_id)])


def _dynamic_subtype_operand(subtype, supertype, site):
    del subtype
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    construction_panic_gap(
        owner="ExitTypeCoordinate.test_python_subtype",
        blame=str(site),
        observed=type(supertype).__name__,
        requested="authenticated class, tuple-of-classes, or symbolic type operand",
        fix="construct the Python type operand or keep issubclass loudly unsupported",
    )


@dataclass(frozen=True)
class RaisedExitTypeValue(FloorValue):
    """Actual exception-class coordinate authenticated by a raised body face.

    A raised face proves the type slot is not None. It does not invent a
    class spelling or any exception potentially thrown by its operations.
    """

    identity: Term
    mro: tuple[Term, ...] | None = None

    def to_term(self, *, owner: str):
        del owner
        return self.identity

    @property
    def coordinate_cid(self):
        from sugar_lift_py_tests.ir import _term_content_cid

        return _term_content_cid(self.to_term(owner="raised native class coordinate"))

    @property
    def formal_coordinate(self):
        # Rich operators must wait for an actual class/metaclass Floor, on
        # either side of comparison. Identity against None is total separately.
        return self

    def denotes_value(self) -> bool:
        return True

    def runtime_type_is_decided(self) -> bool:
        # A class identity alone does not construct its metaclass operations.
        return False

    def exception_type_identity(self):
        return self.identity

    def exception_type_mro(self):
        return self.mro

    def test_python_subtype(self, supertype, site):
        """``issubclass(<raised type>, T)`` from the raise's own ancestry.

        ``issubclass`` consults ``type(T).__subclasscheck__``. Only a builtin
        exception class has the closed metaclass ``type``, so only there does
        the raised MRO testimony settle the question. Any other class operand
        keeps the ``python.subtype`` atom; nothing is decided by spelling.
        """
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
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        if type(supertype) is TupleValue:
            return supertype.test_python_subtype(self, site)
        native = supertype
        while isinstance(native, AuthenticatedExceptionTypeValue):
            native = native.class_value if native.class_value is not None else native.value
        if isinstance(native, BuiltinExceptionClassValue):
            expected = native.exception_type_identity()
            if expected == self.identity:
                return ExitSet.completed(TrueBoolLiteralSugar(site=site))
            if self.mro is not None:
                literal = (
                    TrueBoolLiteralSugar if expected in self.mro else FalseBoolLiteralSugar
                )
                return ExitSet.completed(literal(site=site))
        if not isinstance(native, (ClassValue, SymbolicValue, BuiltinExceptionClassValue)):
            return _dynamic_subtype_operand(self, supertype, site)
        return ExitSet.completed(
            PredicateValue(
                atomic(
                    "python.subtype",
                    [
                        self.to_term(owner="python.issubclass subtype"),
                        native.to_term(owner="python.issubclass supertype"),
                    ],
                ),
                site,
                operand_callsites=(*self.callsites(), *native.callsites()),
            )
        )

    def equals(self, other, site, ctx):
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="RaisedExitTypeValue.equals",
            blame=site,
            observed=type(other).__name__,
            requested="native class/metaclass equality outcome testimony",
            fix="construct rich dispatch; a raised type identity is not its outcome",
        )

    def is_identical(self, other, site):
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.outcome.exit_set import false_guard

        if isinstance(other, NoneValue):
            return ExitSet.completed(PredicateValue(false_guard(), site))
        # Type coordinates do not by themselves identify an arbitrary Floor's
        # runtime value (an instance can carry its class's identity too).
        # Do not compare that metadata to a raw class/value predicate.
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="RaisedExitTypeValue.is_identical",
            blame=site,
            observed=type(other).__name__,
            requested="native class-object identity testimony for both operands",
            fix="construct actual class values before comparing their identities",
        )
