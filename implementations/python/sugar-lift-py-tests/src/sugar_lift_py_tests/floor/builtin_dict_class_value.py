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
        """``isinstance(value, dict)``.

        Decided where the value's own floor knows its type
        (``python_isinstance`` answers ``True`` / ``False``: a ``str``, a
        tuple, a class object, ``type(x)``'s result).  Anywhere else
        ``dict``'s ``type.__instancecheck__`` is ``object_isinstance``
        (Objects/abstract.c): a value whose type is no ``dict`` subclass is
        asked for its ``__class__``, which a property or a
        ``__getattribute__`` of its type may answer by raising.  Nothing here
        reads that type, so the test is the undecided type test
        (``floor_value.undecided_type_test``): both faces owed, its halt
        kept, never the refusal of the function that tests it (#7757)."""
        from sugar_lift_py_tests.floor.floor_value import undecided_type_test
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.outcome import Completed
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        known = value.python_isinstance(
            "dict", ctor("python:type", [str_const("dict")]), site
        )
        if known.exits and all(
            isinstance(face, Completed)
            and isinstance(face.value, (TrueBoolLiteralSugar, FalseBoolLiteralSugar))
            for face in known.exits
        ):
            return known
        return undecided_type_test(
            value, self, site, owner="BuiltinDictClassValue.test_python_type"
        )
