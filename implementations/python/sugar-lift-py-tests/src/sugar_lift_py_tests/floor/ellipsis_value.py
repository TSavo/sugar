from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class EllipsisValue(FloorValue):
    """The floor for the `...` literal. No fields -- the Ellipsis-ness IS the
    type, mirroring NoneValue. Stands as the vendor-canonical ``py.ellipsis``
    ctor: already in the verifier's structural ground-ctor whitelist
    (``consistency.rs`` #4387/#4398 residue) and the isinstance fold
    table (``symbolic_value.py``: ``"py.ellipsis": "ellipsis"``)."""

    def python_isinstance(self, type_name: str, type_term, site):
        """``...`` is an instance of every class of ``ellipsis``'s real
        order (``object`` included) and of no other builtin class; any other
        classinfo is the undecided type test, its halt kept
        (``python_type_coordinate.builtin_order_isinstance``, #7757)."""
        from sugar_lift_py_tests.floor.python_type_coordinate import (
            builtin_order_isinstance,
        )

        decided = builtin_order_isinstance(
            "ellipsis", type_term, site, owner="EllipsisValue.python_isinstance"
        )
        if decided is not None:
            return decided
        return super().python_isinstance(type_name, type_term, site)

    def truth(self, site):
        # Ellipsis is truthy in Python (bool(...) is True) -- unlike None.
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        return ExitSet.completed(TrueBoolLiteralSugar(site=site))

    def equals(self, other, site, ctx):
        if type(other) is EllipsisValue:
            from sugar_lift_py_tests.outcome import ExitSet
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return ExitSet.completed(TrueBoolLiteralSugar(site=site))
        return super().equals(other, site, ctx)

    def is_identical(self, other, site):
        # Ellipsis is a singleton: `... is ...` folds True.
        if type(other) is EllipsisValue:
            from sugar_lift_py_tests.outcome import ExitSet
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return ExitSet.completed(TrueBoolLiteralSugar(site=site))
        return super().is_identical(other, site)

    def setattr(self, name, value, site, ctx):
        del value, ctx
        from sugar_lift_py_tests.floor.ground_exit import builtin_attribute_store_exit

        return builtin_attribute_store_exit(
            name, site=site, owner="EllipsisValue.setattr"
        )

    def delattr(self, name, site, ctx):
        del ctx
        from sugar_lift_py_tests.floor.ground_exit import builtin_attribute_store_exit

        return builtin_attribute_store_exit(
            name, site=site, owner="EllipsisValue.delattr"
        )

    def setitem(self, index, value, site, ctx):
        """Ellipsis rejects subscript store with exact TypeError."""
        del index, value, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="EllipsisValue.setitem"
        )

    def delitem(self, index, site, ctx):
        """Ellipsis rejects subscript delete with exact TypeError."""
        del index, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="EllipsisValue.delitem"
        )

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor

        return ctor("py.ellipsis", [])
