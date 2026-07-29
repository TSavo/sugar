from __future__ import annotations

from dataclasses import dataclass, replace

from .floor_value import FloorValue

# Types that a class object is never an instance of under ordinary Python.
# ``isinstance(SomeClass, tuple)`` is False; container and scalar value types
# are disjoint from the class-object side of the type/value distinction.
_CLASS_OBJECT_DISJOINT_TYPES = frozenset(
    {
        "tuple",
        "list",
        "dict",
        "set",
        "frozenset",
        "str",
        "bytes",
        "bytearray",
        "int",
        "bool",
        "float",
        "complex",
        "range",
        "NoneType",
        "memoryview",
        "slice",
    }
)


@dataclass(frozen=True)
class ClassValue(FloorValue):
    """A class lowered for recognition: name, base coordinates, body record.

    Not a model of MRO/metaclasses -- the bases are the type coordinates the
    lift carried, and the record is the class-body statements (methods as
    UniverseValue, class-vars as BoundVar support). contribution splices the
    body into the enclosing record; extend_scope binds the class name so a
    later reference can answer with this value.
    """

    name: str
    bases: tuple
    record: object  # BlockValue

    def to_term(self, *, owner: str):
        # Class coordinate — type name for FOL equality / dig faces.
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:type", [str_const(self.name)])

    def truth(self, site):
        # Python type objects are always truthy. Dual-mode EffectBoundary
        # factories gate validation with ``if not expected_exception:``; the
        # class actual must stand as a condition without force-floor:truth:ClassValue.
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        return Complete(TrueBoolLiteralSugar(site=site))

    def is_identical(self, other, site):
        # An authenticated class object cannot be Python's None singleton.
        # This is class-floor testimony, not a spelling test: unresolved values
        # still use FloorValue's symbolic identity and remain a third value.
        from sugar_lift_py_tests.floor.none_value import NoneValue

        if type(other) is NoneValue:
            from sugar_lift_py_tests.outcome import Complete
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )

            return Complete(FalseBoolLiteralSugar(site=site))
        return super().is_identical(other, site)

    def attribute(self, name, site):
        """Class objects expose ``__name__`` as their authenticated type name.

        RaisesExc's absent-effect diagnostic formats
        ``self.expected_exceptions[0].__name__``. Without this arm the attribute
        producer panics on BuiltinExceptionClassValue and exit summary stays
        exit-may-halt rather than sealing ExpectsMode.
        """
        from sugar_lift_py_tests.floor.object_field import ObjectField

        carried = tuple(
            statement
            for statement in self.record.statements
            if type(statement) is ObjectField and statement.name == name
        )
        if len(carried) > 1:
            from sugar_source_tree.panic import BackendDefect

            raise BackendDefect(
                blame=site,
                owner="ClassValue.attribute",
                observed="duplicate authenticated class member fields",
                requested="one producer-owned class member coordinate",
                fix="apply class-body overwrite ordering before publication",
            )
        if carried:
            from sugar_lift_py_tests.outcome import Complete

            return Complete(carried[0].value)
        if name in {"__name__", "__qualname__"}:
            from sugar_lift_py_tests.floor.string_value import StringValue
            from sugar_lift_py_tests.outcome import Complete

            return Complete(StringValue(self.name))
        return super().attribute(name, site)

    def test_python_type(self, value, site):
        return value.python_isinstance(self.name, self.to_term(owner=self.name), site)

    def python_isinstance(self, type_name: str, type_term, site):
        """A class object is an instance of ``type`` / ``object``, never of value types.

        ``isinstance(Exception, tuple)`` is False; ``isinstance(Exception, type)``
        is True. Without this ground answer, RaisesExc's
        ``if isinstance(expected_exception, tuple):`` face stays undecided and
        the ``expected_exceptions`` field never floors to a TupleValue.
        """
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        if type_name in {"type", "object"}:
            return Complete(TrueBoolLiteralSugar(site=site))
        if type_name in _CLASS_OBJECT_DISJOINT_TYPES:
            return Complete(FalseBoolLiteralSugar(site=site))
        return super().python_isinstance(type_name, type_term, site)

    def test_python_subtype(self, supertype, site):
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        if type(supertype) is TupleValue:
            return supertype.test_python_subtype(self, site)
        if type(supertype) is SymbolicValue:
            return SymbolicValue(self.to_term(owner=str(site))).test_python_subtype(
                supertype, site
            )
        if not isinstance(supertype, ClassValue):
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="ClassValue.test_python_subtype",
                blame=str(site),
                observed=type(supertype).__name__,
                requested="authenticated class or finite tuple-of-classes",
                fix="construct the type operand on the Python floor or keep it loud",
            )
        pending = [self]
        seen: set[int] = set()
        while pending:
            candidate = pending.pop()
            if candidate is supertype:
                return Complete(TrueBoolLiteralSugar(site=site))
            key = id(candidate)
            if key in seen:
                continue
            seen.add(key)
            for base in candidate.bases:
                if not isinstance(base, ClassValue):
                    from sugar_lift_py_tests.gap.panic import construction_panic_gap

                    construction_panic_gap(
                        owner="ClassValue.test_python_subtype",
                        blame=str(site),
                        observed=type(base).__name__,
                        requested="authenticated ClassValue base graph",
                        fix="resolve every base through its lexical class coordinate",
                    )
                pending.append(base)
        return Complete(FalseBoolLiteralSugar(site=site))

    def subscript(self, index, site):
        # Generic class subscript (Class[T]) is a type coordinate, not a dig.
        # Recognition-era subscription tables are gone; emit the coordinate.
        return self.py_subscript_coordinate(index, site)

    def setitem(self, index, value, site):
        del index, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="ClassValue.setitem"
        )

    def delitem(self, index, site):
        del index
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="ClassValue.delitem"
        )

    def contribution(self):
        # Splice body entries (methods, assigns) into the enclosing record.
        return self.record.contribution()

    def extend_scope(self, ctx):
        # Bind the class name so later statements can resolve it.
        return replace(ctx, temporal=ctx.temporal.bind_value(self.name, self))

    def base_terms(self):
        return tuple(base.to_term(owner=self.name) for base in self.bases)
