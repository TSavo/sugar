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

    def denotes_value(self) -> bool:
        """This floor value denotes a ``complex``."""
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

    # Python's numeric tower is CLOSED over int/float/bool/complex under these
    # three operations, so a complex literal stands on each of their floors for
    # any field member. See floor/complex_arithmetic.py for the one law; a
    # non-member right operand falls through to this floor's own loud gap.

    def _decided_non_field_type_error(self, other, site, *, owner: str):
        """Complex with a source-decided non-field peer is TypeError.

        Undecided peers stay on the shared third-value law (``__r*__`` may
        exist).  A numeric TermValue that fails to enter the field (overflow)
        or a non-finite product remains a loud construction gap — those are
        not TypeError identities.
        """
        if not (other.denotes_value() and other.runtime_type_is_decided()):
            return None
        from sugar_lift_py_tests.floor.complex_arithmetic import (
            complex_field_coordinate,
        )
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        if complex_field_coordinate(other) is not None:
            return None
        # Field members that refused entry (overflow) stay loud, not TypeError.
        if type(other) is TermValue and type(other.value) in (int, float, bool):
            return None
        if type(other) in (TrueBoolLiteralSugar, FalseBoolLiteralSugar, type(self)):
            return None
        from sugar_lift_py_tests.floor.ground_exit import ground_type_error

        return ground_type_error(site=site, owner=owner)

    def add(self, other, site):
        from sugar_lift_py_tests.floor.complex_arithmetic import complex_add

        folded = complex_add(self, other, site)
        if folded is not None:
            return folded
        constructed = self._decided_non_field_type_error(
            other, site, owner="ComplexValue.add"
        )
        if constructed is not None:
            return constructed
        return super().add(other, site)

    def subtract(self, other, site):
        from sugar_lift_py_tests.floor.complex_arithmetic import complex_subtract

        folded = complex_subtract(self, other, site)
        if folded is not None:
            return folded
        constructed = self._decided_non_field_type_error(
            other, site, owner="ComplexValue.subtract"
        )
        if constructed is not None:
            return constructed
        return super().subtract(other, site)

    def multiply(self, other, site):
        from sugar_lift_py_tests.floor.complex_arithmetic import complex_multiply

        folded = complex_multiply(self, other, site)
        if folded is not None:
            return folded
        constructed = self._decided_non_field_type_error(
            other, site, owner="ComplexValue.multiply"
        )
        if constructed is not None:
            return constructed
        return super().multiply(other, site)

    def setattr(self, name, value, site):
        del name, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit
        return ground_exceptional_exit(exception_name="AttributeError", site=site, owner="ComplexValue.setattr")

    def delattr(self, name, site):
        del name
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit
        return ground_exceptional_exit(exception_name="AttributeError", site=site, owner="ComplexValue.delattr")

    def setitem(self, index, value, site):
        """Complex numbers reject subscript store with exact TypeError."""
        del index, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="ComplexValue.setitem"
        )

    def delitem(self, index, site):
        """Complex numbers reject subscript delete with exact TypeError."""
        del index
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="ComplexValue.delitem"
        )

    def to_term(self, *, owner: str):
        del owner
        from decimal import Decimal

        from sugar_lift_py_tests.ir import ctor, real_lit

        # Same canonical-decimal-string discipline as TermValue.to_term: never
        # hash a Python float's non-deterministic text form into the CID.
        real_term = real_lit(format(Decimal(str(self.real)), "f"))
        imag_term = real_lit(format(Decimal(str(self.imag)), "f"))
        return ctor("py.complex", [real_term, imag_term])
