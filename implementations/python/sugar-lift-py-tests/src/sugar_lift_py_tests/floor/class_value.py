from __future__ import annotations

from dataclasses import dataclass, replace

from .floor_value import FloorValue


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

    def test_python_type(self, value, site):
        return value.python_isinstance(self.name, self.to_term(owner=self.name), site)

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

    def contribution(self):
        # Splice body entries (methods, assigns) into the enclosing record.
        return self.record.contribution()

    def extend_scope(self, ctx):
        # Bind the class name so later statements can resolve it.
        return replace(ctx, temporal=ctx.temporal.bind_value(self.name, self))

    def base_terms(self):
        return tuple(base.to_term(owner=self.name) for base in self.bases)
