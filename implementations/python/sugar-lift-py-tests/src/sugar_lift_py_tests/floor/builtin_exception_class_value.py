from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Term

from .class_value import ClassValue


@dataclass(frozen=True)
class BuiltinExceptionClassValue(ClassValue):
    """Exact lexical identity for an exception class owned by ``builtins``.

    This is seeded from a static language vocabulary. A same-spelled user binding
    replaces this floor in the temporal scope and therefore cannot inherit builtin
    constructor semantics by leaf-name coincidence.
    """

    def setitem(self, index, value, site):
        del index, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError",
            site=site,
            owner="BuiltinExceptionClassValue.setitem",
        )

    def delitem(self, index, site):
        del index
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError",
            site=site,
            owner="BuiltinExceptionClassValue.delitem",
        )

    def exception_type_identity(self) -> Term:
        """Same coordinate ``SourceUnit.exception_type_identity`` publishes for builtins."""
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:exception_type_identity",
            [str_const("builtins"), str_const(self.name)],
        )

    def exception_type_mro(self) -> tuple[Term, ...]:
        """Closed builtin ancestry, leaf-first, matching the language table."""
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.temporal.builtin_name_bindings import (
            BUILTIN_EXCEPTION_BASES,
        )

        def identity(name: str) -> Term:
            return ctor(
                "python:exception_type_identity",
                [str_const("builtins"), str_const(name)],
            )

        ordered: list[str] = []
        seen: set[str] = set()

        def walk(name: str) -> None:
            if name in seen:
                return
            seen.add(name)
            ordered.append(name)
            for base in BUILTIN_EXCEPTION_BASES.get(name, ()):
                walk(base)

        walk(self.name)
        return tuple(identity(name) for name in ordered)
