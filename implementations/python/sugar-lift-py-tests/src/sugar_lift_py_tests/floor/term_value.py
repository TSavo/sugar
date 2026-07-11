from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue


@dataclass(frozen=True)
class TermValue(FloorValue):
    # The collapsed Number: an int OR a float. Int embeds in Real losslessly, so they are
    # one value type -- 3 and 3.0 are the same number, and 3.0 == 3 is reflexively true.
    # The Int/Real SMT sort is an emission-time inference, not a value-level split.
    value: int | float

    def add_with(self, operation: Any, ctx: Any) -> Any:
        return operation.add_term(self, ctx)

    def truth(self, site):
        # Python-faithful: nonzero is True. bool(nan) is True and nan != 0 IS
        # True in Python, so the same expression is correct.
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        return Complete(
            TrueBoolLiteralSugar(site=site)
            if self.value != 0
            else FalseBoolLiteralSugar(site=site)
        )

    def equals(self, other, site):
        # A number stands on the equals floor: two numbers are equal or not, and it
        # gives back the True or False literal -- the boolean IS the type.
        if type(other) is TermValue:
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

    def less_than(self, other, site):
        # A number stands on the ordering floor: two numbers are ordered or not, and
        # it gives back the True or False literal -- the boolean IS the type.
        if type(other) is TermValue:
            from sugar_lift_py_tests.outcome import Complete
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return Complete(
                TrueBoolLiteralSugar(site=site)
                if self.value < other.value
                else FalseBoolLiteralSugar(site=site)
            )
        return super().less_than(other, site)

    def add(self, other, site):
        # The collapsed Number adds: two numbers fold to their sum -- one value type
        # for int and float. Anything else falls to the honest addition-floor gap.
        if type(other) is TermValue:
            from sugar_lift_py_tests.outcome import Complete

            return Complete(TermValue(self.value + other.value))
        return super().add(other, site)

    def subtract(self, other, site):
        # A number stands on the subtraction floor: two numbers subtract to a number.
        if type(other) is TermValue:
            from sugar_lift_py_tests.outcome import Complete

            return Complete(TermValue(self.value - other.value))
        return super().subtract(other, site)

    def multiply(self, other, site):
        # A number stands on the multiplication floor: two numbers multiply, and the
        # product is a TermValue -- the collapsed Number.
        if type(other) is TermValue:
            from sugar_lift_py_tests.outcome import Complete

            return Complete(TermValue(self.value * other.value))
        return super().multiply(other, site)

    def divide(self, other, site):
        # A number stands on the division floor: true division. A concrete zero
        # divisor is a runtime effect (the program halts), not a lift-side gap.
        if type(other) is TermValue:
            from sugar_lift_py_tests.outcome import Complete, Incomplete

            if other.value == 0:
                from sugar_lift_py_tests.effect import DivisionByZeroRuntimeEffect

                return Incomplete(
                    DivisionByZeroRuntimeEffect(
                        f"division by zero runtime boundary: the divisor is "
                        f"concretely 0; owner=TermValue.divide site={site}"
                    )
                )
            return Complete(TermValue(self.value / other.value))
        return super().divide(other, site)

    def modulo(self, other, site):
        # A number stands on the modulo floor: the remainder. A concrete zero
        # divisor is a runtime effect (the program halts), not a lift-side gap.
        if type(other) is TermValue:
            from sugar_lift_py_tests.outcome import Complete, Incomplete

            if other.value == 0:
                from sugar_lift_py_tests.effect import ModuloByZeroRuntimeEffect

                return Incomplete(
                    ModuloByZeroRuntimeEffect(
                        f"modulo by zero runtime boundary: the divisor is "
                        f"concretely 0; owner=TermValue.modulo site={site}"
                    )
                )
            return Complete(TermValue(self.value % other.value))
        return super().modulo(other, site)

    def to_term(self, *, owner: str):
        del owner
        # Int embeds in Real losslessly (3 and 3.0 are the same number), but the
        # embedding only goes one way at the term level: an Int-sorted term and
        # a Real-sorted term are structurally distinct EUF constants even when
        # the numbers agree, so an INTEGRAL float still projects through the
        # Int constructor -- matching any plain-int sibling it must agree with
        # (e.g. `float('3.0') == 3`, `np.divide(6, 3) == 2`). Only a genuinely
        # fractional float needs the Real ctor, because there is no lossless
        # Int projection for it.
        if type(self.value) is float and self.value == int(self.value):
            from sugar_lift_py_tests.ir import num

            return num(int(self.value))
        if type(self.value) is float:
            from decimal import Decimal

            from sugar_lift_py_tests.ir import real_lit

            # A canonical decimal string, never a Python float text form (see
            # `ir.real_lit`): `Decimal(str(value))` round-trips because
            # `repr`/`str` of a Python float is already the shortest exact
            # decimal that reparses to the same double.
            return real_lit(format(Decimal(str(self.value)), "f"))
        from sugar_lift_py_tests.ir import num

        return num(int(self.value))

    def project_callsite_with(self, operation: Any, ctx: Any) -> Any:
        return operation.project_literal(self, ctx)

    def call_method_with(self, operation: Any, ctx: Any) -> Any:
        del ctx
        if operation.name == "__format__" and len(operation.arguments) == 1:
            from sugar_lift_py_tests.floor.string_value import StringValue
            from sugar_lift_py_tests.outcome import Complete

            spec = operation.arguments[0]
            if isinstance(spec, StringValue):
                return Complete(StringValue(format(self.value, spec.value)))
        if operation.name == "__int__" and not operation.arguments:
            from sugar_lift_py_tests.outcome import Complete

            return Complete(TermValue(int(self.value)))
        if operation.name == "__hash__" and not operation.arguments:
            from sugar_lift_py_tests.outcome import Complete

            # Non-folding pure builtin: marker only → call:hash, no companion.
            # Never fabricate Python's hash() of a number.
            return Complete(self)
        if operation.name == "__repr__" and not operation.arguments:
            from sugar_lift_py_tests.floor.string_value import StringValue
            from sugar_lift_py_tests.outcome import Complete

            return Complete(StringValue(repr(self.value)))
        if operation.name == "__bytes__" and not operation.arguments:
            from sugar_lift_py_tests.effect import RuntimeEffect
            from sugar_lift_py_tests.outcome import Incomplete

            # int/float have no __bytes__; keep typed red (don't fabricate).
            return Incomplete(
                RuntimeEffect(
                    "numeric bytes conversion runtime boundary: "
                    f"TermValue.__bytes__ is not defined for {type(self.value).__name__}; "
                    f"blame={operation.blame}"
                )
            )
        _call_method_gap(
            owner=operation.owner,
            blame=operation.blame,
            observed=f"TermValue.{operation.name}",
            requested="numeric builtin method floor",
            fix=f"add TermValue method floor for `{operation.name}`",
        )

    def str_with(self, operation: Any, ctx: Any) -> Any:
        return operation.str_term(self, ctx)

    def format_value_with(self, operation: Any, ctx: Any) -> Any:
        return operation.format_term(self, ctx)

    def bitwise_with(self, operation: Any, ctx: Any) -> Any:
        return operation.bitwise_term(self, ctx)

    def binary_operator_with(self, operation: Any, ctx: Any) -> Any:
        return operation.binary_term(self, ctx)

    def unary_operator_with(self, operation: Any, ctx: Any) -> Any:
        return operation.unary_term(self, ctx)


def _call_method_gap(
    *,
    owner: str,
    blame: str,
    observed: str,
    requested: str,
    fix: str,
):
    from sugar_lift_py_tests.factory import (
        FactoryAuditRow, factory_panic,
        FactoryGapInfo,
        GapKind,
        GapLocus,
    )

    info = FactoryGapInfo(
        owner=owner,
        blame=blame,
        observed=observed,
        requested=requested,
        fix=fix,
        gap_kind=GapKind.FLOOR,
        gap_locus=GapLocus.CONSTRUCTION,
    )
    factory_panic(
        info,
        FactoryAuditRow(
            role=requested,
            status="floor-gap",
            observed=observed,
            blame=blame,
            selected=None,
            candidates=[],
            message=info.message,
        ),
    )
