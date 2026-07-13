from __future__ import annotations

from dataclasses import dataclass
from sugar_lift_py_tests.effect import runtime_effect_witness

from .floor_value import FloorValue


@dataclass(frozen=True)
class NoneValue(FloorValue):
    """The floor for the `None` literal. No fields -- the None-ness IS the type."""

    def truth(self, site):
        # None's truth IS False -- the type again.
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )

        return Complete(FalseBoolLiteralSugar(site=site))

    def less_than(self, other, site):
        # None orders against nothing: any ground comparison is TypeError -- a
        # recognized runtime halt. Symbolic falls to super() emit.
        from sugar_lift_py_tests.floor.list_value import ListValue
        from sugar_lift_py_tests.floor.set_value import SetValue
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.floor.tuple_value import TupleValue

        if type(other) in (
            NoneValue,
            TermValue,
            StringValue,
            ListValue,
            TupleValue,
            SetValue,
        ):
            from sugar_lift_py_tests.effect import TypeErrorRuntimeEffect
            from sugar_lift_py_tests.outcome import Incomplete

            return Incomplete(
                TypeErrorRuntimeEffect(
                    f"unorderable types runtime boundary: "
                    f"NoneValue and {type(other).__name__}; site={site}",
                    witness=runtime_effect_witness("py.lt", other, site),
                )
            )
        return super().less_than(other, site)

    def equals(self, other, site):
        # None stands on the equals floor only against itself. Cross-type is the
        # honest default gap until a ruling lands.
        if type(other) is NoneValue:
            from sugar_lift_py_tests.outcome import Complete
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return Complete(TrueBoolLiteralSugar(site=site))
        from sugar_lift_py_tests.floor.list_value import ListValue
        from sugar_lift_py_tests.floor.set_value import SetValue
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.floor.tuple_value import TupleValue

        if type(other) in (TermValue, StringValue, ListValue, TupleValue, SetValue):
            # Ground vs ground FOLDS -- an emitted py.eq(None, <ground>) atom has
            # no universe constraining it and would be vacuously SAT-able; Python
            # says None equals none of these, so the fold is False.
            from sugar_lift_py_tests.outcome import Complete
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )

            return Complete(FalseBoolLiteralSugar(site=site))
        return super().equals(other, site)

    def floor_divide(self, other, site):
        from sugar_lift_py_tests.effect import TypeErrorRuntimeEffect
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            TypeErrorRuntimeEffect(
                "unsupported floor division runtime boundary: NoneType // "
                f"{type(other).__name__}; site={site}",
                witness=runtime_effect_witness("py.floor_divide", other, site),
            )
        )

    def is_identical(self, other, site):
        # None is a singleton: None is None folds True. Against anything else,
        # emit identity -- the general case (e.g. z is None).
        if type(other) is NoneValue:
            from sugar_lift_py_tests.outcome import Complete
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return Complete(TrueBoolLiteralSugar(site=site))
        return super().is_identical(other, site)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor

        return ctor("None", [])
