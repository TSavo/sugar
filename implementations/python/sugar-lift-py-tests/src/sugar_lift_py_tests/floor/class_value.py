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

    def contribution(self):
        # Splice body entries (methods, assigns) into the enclosing record.
        return self.record.contribution()

    def extend_scope(self, ctx):
        # Bind the class name so later statements can resolve it.
        return replace(ctx, temporal=ctx.temporal.bind_value(self.name, self))

    def base_terms(self):
        return tuple(base.to_term(owner=self.name) for base in self.bases)
