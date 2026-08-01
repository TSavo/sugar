from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class BytesValue(FloorValue):
    """The floor for a Python `bytes` literal. Carries the raw bytes; stands as
    the vendor-canonical ``python:bytes(<hex String const>)`` ctor already
    consumed by the SMT emitter (``literal_encoding.rs``: "python:bytes(<String
    const>) is the Python kit's ASCII-gated bytes literal"), the verifier's
    structural ground-ctor whitelist (``consistency.rs``), and the isinstance
    fold table (``symbolic_value.py``: ``"python:bytes": "bytes"``). This is
    the ONE representation -- never a second bytes encoding."""

    value: bytes

    def denotes_value(self) -> bool:
        """This floor value denotes a ``bytes``."""
        return True

    def python_isinstance(self, type_name: str, type_term, site):
        del type_name  # display spelling is not authority
        from sugar_lift_py_tests.floor.python_type_coordinate import (
            authenticated_python_type_spelling,
        )
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        authenticated = authenticated_python_type_spelling(
            type_term, owner="BytesValue.python_isinstance", site=site
        )
        return Complete(
            TrueBoolLiteralSugar(site=site)
            if authenticated == "bytes"
            else FalseBoolLiteralSugar(site=site)
        )

    def equals(self, other, site):
        if type(other) is BytesValue:
            from sugar_lift_py_tests.outcome import Complete
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return Complete(
                TrueBoolLiteralSugar(site=site)
                if self.value == other.value
                else FalseBoolLiteralSugar(site=site)
            )
        return super().equals(other, site)

    def slice_assign_iterable_with(self, operation, ctx):
        """Project the bytes object's authenticated integer members."""
        del operation, ctx
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import Complete

        return Complete(tuple(TermValue(byte) for byte in self.value))

    def setitem(self, index, value, site):
        """Bytes are immutable: every subscript store is exact TypeError."""
        del index, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="BytesValue.setitem"
        )

    def delitem(self, index, site):
        """Bytes are immutable: every subscript delete is exact TypeError."""
        del index
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="BytesValue.delitem"
        )

    def setattr(self, name, value, site):
        del name, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError", site=site, owner="BytesValue.setattr"
        )

    def delattr(self, name, site):
        del name
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError", site=site, owner="BytesValue.delattr"
        )

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:bytes", [str_const(self.value.hex())])
