from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class ComplexValue(FloorValue):
    """The floor for a Python `complex` literal. Carries the real/imaginary
    parts (both Python floats). Stands as the vendor-canonical
    ``py.complex(<real>, <imag>)`` ctor: already in the verifier's structural
    ground-ctor whitelist (``consistency.rs`` #4398 -- "py.complex is a data
    value, dual complex literals remain gaps"), the kit's own ground-ctor list
    (``call_site_value.py._GROUND_DATA_CTOR_NAMES``), and the isinstance fold
    table (``symbolic_value.py``: ``"py.complex": "complex"``). This is the
    ONE representation -- never a second complex encoding."""

    real: float
    imag: float

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
            if type_name == "complex"
            else FalseBoolLiteralSugar(site=site)
        )

    def equals(self, other, site):
        if type(other) is ComplexValue:
            from sugar_lift_py_tests.outcome import Complete
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            matches = self.real == other.real and self.imag == other.imag
            return Complete(
                TrueBoolLiteralSugar(site=site)
                if matches
                else FalseBoolLiteralSugar(site=site)
            )
        return super().equals(other, site)

    def to_term(self, *, owner: str):
        del owner
        from decimal import Decimal

        from sugar_lift_py_tests.ir import ctor, real_lit

        # Same canonical-decimal-string discipline as TermValue.to_term: never
        # hash a Python float's non-deterministic text form into the CID.
        real_term = real_lit(format(Decimal(str(self.real)), "f"))
        imag_term = real_lit(format(Decimal(str(self.imag)), "f"))
        return ctor("py.complex", [real_term, imag_term])
