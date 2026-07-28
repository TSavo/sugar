from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class EllipsisValue(FloorValue):
    """The floor for the `...` literal. No fields -- the Ellipsis-ness IS the
    type, mirroring NoneValue. Stands as the vendor-canonical ``py.ellipsis``
    ctor: already in the verifier's structural ground-ctor whitelist
    (``consistency.rs`` #4387/#4398 residue), the kit's own ground-ctor list
    (``call_site_value.py._GROUND_DATA_CTOR_NAMES``), and the isinstance fold
    table (``symbolic_value.py``: ``"py.ellipsis": "ellipsis"``)."""

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
            if type_name == "ellipsis"
            else FalseBoolLiteralSugar(site=site)
        )

    def truth(self, site):
        # Ellipsis is truthy in Python (bool(...) is True) -- unlike None.
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        return Complete(TrueBoolLiteralSugar(site=site))

    def equals(self, other, site):
        if type(other) is EllipsisValue:
            from sugar_lift_py_tests.outcome import Complete
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return Complete(TrueBoolLiteralSugar(site=site))
        return super().equals(other, site)

    def is_identical(self, other, site):
        # Ellipsis is a singleton: `... is ...` folds True.
        if type(other) is EllipsisValue:
            from sugar_lift_py_tests.outcome import Complete
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return Complete(TrueBoolLiteralSugar(site=site))
        return super().is_identical(other, site)

    def setattr(self, name, value, site):
        del name, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit
        return ground_exceptional_exit(exception_name="AttributeError", site=site, owner="EllipsisValue.setattr")

    def delattr(self, name, site):
        del name
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit
        return ground_exceptional_exit(exception_name="AttributeError", site=site, owner="EllipsisValue.delattr")

    def setitem(self, index, value, site):
        """Ellipsis rejects subscript store with exact TypeError."""
        del index, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="EllipsisValue.setitem"
        )

    def delitem(self, index, site):
        """Ellipsis rejects subscript delete with exact TypeError."""
        del index
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="EllipsisValue.delitem"
        )

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor

        return ctor("py.ellipsis", [])
