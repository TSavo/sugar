from __future__ import annotations

from dataclasses import dataclass

from .builtin_semantic_callable import BuiltinSemanticCallable


@dataclass(frozen=True)
class BuiltinDictClassValue(BuiltinSemanticCallable):
    """Authenticated builtin ``dict`` class and constructor coordinate.

    This keeps the existing closed constructor law while giving source-class
    base transport a typed capability.  Consumers do not infer it from the
    spelling of a base expression.
    """

    def test_python_type(self, value, site):
        """``isinstance(value, dict)``: asked of the value, as every builtin
        type test is (``BuiltinSemanticCallable.test_python_type``).

        A floor that knows its value's type answers ``True`` / ``False`` (a
        ``str``, a tuple, a class object, ``type(x)``'s result); any other
        value is the undecided type test (``FloorValue.python_isinstance``,
        ``floor_value.undecided_type_test``): both faces owed, its halt kept,
        never the refusal of the function that tests it (#7757)."""
        from sugar_lift_py_tests.ir import ctor, str_const

        return value.python_isinstance(
            "dict", ctor("python:type", [str_const("dict")]), site
        )
