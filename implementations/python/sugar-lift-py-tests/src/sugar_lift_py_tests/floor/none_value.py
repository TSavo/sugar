from __future__ import annotations

from dataclasses import dataclass
from sugar_lift_py_tests.effect import runtime_effect_evidence

from .floor_value import FloorValue


@dataclass(frozen=True)
class NoneValue(FloorValue):
    """The floor for the `None` literal. No fields -- the None-ness IS the type."""

    def denotes_value(self) -> bool:
        """This floor value denotes ``None``."""
        return True

    def truth(self, site):
        # None's truth IS False -- the type again.
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )

        return Complete(FalseBoolLiteralSugar(site=site))

    def attribute(self, name, site):
        # ``None.foo`` stands where every other constructed value stands: the
        # py.getattr coordinate. None owns no field the lift knows and its
        # methods have no body here, which is exactly the position
        # StringValue and the constructed containers already occupy.
        #
        # NOT a ground AttributeError. `None.foo` raises, but `None.__class__`
        # and `None.__doc__` do not, so a blanket exit here would be wrong for
        # every real member -- and deciding which is which would need a
        # NoneType member table, i.e. a name table read off spelling. The
        # coordinate is not a claim that the attribute EXISTS; it is an opaque
        # symbol over the receiver's term and the name, so it stays exact for
        # both cases and invents neither a field nor an exit.
        del site
        from sugar_lift_py_tests.floor.getattr_coordinate import getattr_coordinate

        return getattr_coordinate(self, name, owner="NoneValue.attribute")

    def subscript(self, index, site):
        """Construct Python's exact ground ``None[...]`` exceptional exit."""
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        del index
        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="ground_type_error"
        )

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
                    **runtime_effect_evidence("py.lt", other, site),
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

    def subtract(self, other, site):
        # None - x is TypeError: the None-ness IS the type. Ground rights are
        # lift-time decidable, so they cannot mint RuntimeEffect evidence as a
        # bare constant; cite the data-model dunder call (call: is runtime by
        # law) so the boundary is witnessed rather than a floor panic.
        from sugar_lift_py_tests.effect import TypeErrorRuntimeEffect
        from sugar_lift_py_tests.effect.runtime_effect import genuine_runtime_operand
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Incomplete

        try:
            genuine_runtime_operand("py.subtract", other)
            operand = other
        except TypeError:
            operand = ctor(
                "call:NoneType.__sub__",
                [
                    self.to_term(owner=str(site)),
                    other.to_term(owner=str(site)),
                ],
            )
        return Incomplete(
            TypeErrorRuntimeEffect(
                "unsupported operand type(s) for -: 'NoneType' and "
                f"{type(other).__name__}; site={site}",
                **runtime_effect_evidence("py.subtract", operand, site),
            )
        )

    def floor_divide(self, other, site):
        from sugar_lift_py_tests.effect import TypeErrorRuntimeEffect
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            TypeErrorRuntimeEffect(
                "unsupported floor division runtime boundary: NoneType // "
                f"{type(other).__name__}; site={site}",
                **runtime_effect_evidence("py.floor_divide", other, site),
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
