"""A closed import-bound module member coordinate.

The lexical import pass authenticates the head; the static Attribute chain
names the export path.  This floor carries that joined coordinate without
re-asking an opaque module receiver for a member and without inventing
AttributeError.
"""

from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class ImportMemberValue(FloorValue):
    """Source-authenticated ``module.attr[.attr…]`` export coordinate."""

    qualified_name: str

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:import_member", [str_const(self.qualified_name)])

    def exception_type_identity(self):
        """The same import coordinate the exception authenticator mints."""
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:exception_type_identity",
            [str_const("import"), str_const(self.qualified_name)],
        )
