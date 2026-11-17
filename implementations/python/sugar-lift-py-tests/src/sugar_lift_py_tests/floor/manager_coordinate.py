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
class ExitTypeCoordinate(FloorValue):
    """Parametric ``__exit__`` type arg: ``python:exit_type(X)``."""

    face_id: str
    site: object = dataclass_field(compare=False, default=None)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:exit_type", [str_const(self.face_id)])

    def test_python_subtype(self, supertype, site):
        """``issubclass(<exit type slot>, T)``: the slot is ``None`` where
        the body left without raising, and ``issubclass(None, T)`` is the
        ``TypeError``; a symbolic ``T`` may be no class or run its
        metaclass's ``__subclasscheck__``.  Nothing authenticates the slot
        here (a raised face's ``RaisedExitTypeValue`` does), so the test is
        the undecided type test, its halt kept
        (``floor_value.undecided_type_test``, #7757)."""
        from sugar_lift_py_tests.floor import ClassValue, SymbolicValue, TupleValue
        from sugar_lift_py_tests.floor.floor_value import undecided_type_test

        if type(supertype) is TupleValue:
            return supertype.test_python_subtype(self, site)
        if not isinstance(supertype, (ClassValue, SymbolicValue)):
            return _dynamic_subtype_operand(self, supertype, site)
        return undecided_type_test(
            self,
            supertype,
            site,
            owner="ExitTypeCoordinate.test_python_subtype",
            test="issubclass",
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
        """``exc.name`` on the parametric exit value: the one two-faced
        undecided read (``floor_value.undecided_attribute_result``).

        An exit slot does not authenticate a field's existence, runtime type,
        descriptor effects, or rich comparison dispatch, so the read may
        complete with any member or raise anything; no completed getattr
        term is minted outside its completes atom.  Nothing fills the slot
        later, so the read waits on no actual (#7757).
        """
        del ctx
        from sugar_lift_py_tests.floor.floor_value import undecided_attribute_result

        return undecided_attribute_result(
            self, name, site, owner="ExitValueCoordinate.attribute"
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
        # A binary, in-place or comparison operator over it waits on no
        # caller: its metaclass operations are undecided
        # (``runtime_type_is_decided``), so it takes the undecided two faces
        # (#7757, audit row NEW-1). Identity against None is total separately.
        # Truth waits on no caller: being its own coordinate, it takes the
        # undecided member's two faces (``bool_op_sugar.truth_of``).
        return self

    def denotes_value(self) -> bool:
        return True

    def runtime_type_is_decided(self) -> bool:
        # A class identity alone does not construct its metaclass operations.
        return False

    def subscript(self, index, site):
        """``C[k]`` on a raised native class: its metaclass's ``__getitem__``
        and its ``__class_getitem__`` are not constructed from the identity
        alone, so the read is the one undecided read, its halt kept -- what
        the ``subscript`` carrier this coordinate deferred as ended as, now
        without waiting on a caller's actual (#7757)."""
        return self.undecided_subscript(
            index, site, owner="ManagerCoordinate.subscript"
        )

    def exception_type_identity(self):
        return self.identity

    def exception_type_mro(self):
        return self.mro

    def test_python_subtype(self, supertype, site):
        """``issubclass(<raised type>, T)`` from the raise's own ancestry.

        ``issubclass`` consults ``type(T).__subclasscheck__``. Only a builtin
        exception class has the closed metaclass ``type``, so only there does
        the raised MRO testimony settle the question. Any other builtin class
        keeps the ``python.subtype`` atom (two classes, metaclass ``type``,
        no halt); an undecided operand may be no class or run its own
        ``__subclasscheck__``, so it is the undecided type test, its halt
        kept (``floor_value.class_subtype_test``, #7757).  Nothing is decided
        by spelling.
        """
        from sugar_lift_py_tests.floor import ClassValue, SymbolicValue, TupleValue
        from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
            AuthenticatedExceptionTypeValue,
        )
        from sugar_lift_py_tests.floor.builtin_exception_class_value import (
            BuiltinExceptionClassValue,
        )
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
        from sugar_lift_py_tests.floor.floor_value import class_subtype_test

        return class_subtype_test(
            self, native, site, owner="RaisedExitTypeValue.test_python_subtype"
        )

    def equals(self, other, site, ctx):
        """``<raised class> == other``: the class's metaclass ``__eq__``, the
        reflection and the identity fallback are not decided here, so it is
        the undecided equality, two-faced (``undecided_dispatch_faces``):
        ``py.eq`` over the two operands completes only under its own
        ``python:compare.completes`` atom and owes the undecided member, or
        raises something undetermined.  A raised type identity is never its
        outcome (#7757, audit row NEW-1: the comparison no longer waits on a
        caller that never answers it)."""
        del ctx
        from sugar_lift_py_tests.floor.object_identity import identity_term
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import py_eq
        from sugar_lift_py_tests.sugar.comparison_op_sugar import (
            undecided_dispatch_faces,
        )

        owner = str(site)
        predicate = PredicateValue(
            py_eq(
                identity_term(self, site, "left", owner=owner),
                identity_term(other, site, "right", owner=owner),
            ),
            site,
            operand_callsites=(*self.callsites(), *other.callsites()),
        )
        return undecided_dispatch_faces(predicate, site, "Eq")

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
