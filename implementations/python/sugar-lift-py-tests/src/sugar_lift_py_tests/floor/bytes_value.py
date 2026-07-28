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
        del type_term
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        return Complete(
            TrueBoolLiteralSugar(site=site)
            if type_name == "bytes"
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

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:bytes", [str_const(self.value.hex())])
