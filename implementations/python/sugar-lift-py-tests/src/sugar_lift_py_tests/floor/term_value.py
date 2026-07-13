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

    def python_isinstance(self, type_name: str, type_term, site):
        del type_term
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        matches = (type(self.value) is int and type_name == "int") or (
            type(self.value) is float and type_name == "float"
        )
        return Complete(
            TrueBoolLiteralSugar(site=site)
            if matches
            else FalseBoolLiteralSugar(site=site)
        )

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
        # Ground cross-type is TypeError (Python defines no ordering) -- a named
        # runtime effect, not an unconstrained py.lt emit. Symbolic falls to emit.
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
        from sugar_lift_py_tests.floor.list_value import ListValue
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.floor.set_value import SetValue
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.floor.tuple_value import TupleValue

        if type(other) in (StringValue, NoneValue, ListValue, TupleValue, SetValue):
            from sugar_lift_py_tests.effect import (
                TypeErrorRuntimeEffect,
                runtime_effect_witness,
            )
            from sugar_lift_py_tests.outcome import Incomplete

            return Incomplete(
                TypeErrorRuntimeEffect(
                    f"unorderable types runtime boundary: "
                    f"TermValue and {type(other).__name__}; site={site}",
                    witness=runtime_effect_witness("py.less_than", other, site),
                )
            )
        return super().less_than(other, site)

    def add(self, other, site):
        # The collapsed Number adds: two numbers fold to their sum -- one value type
        # for int and float. Anything else falls to the honest addition-floor gap.
        if type(other) is TermValue:
            from sugar_lift_py_tests.outcome import Complete

            return Complete(TermValue(self.value + other.value))
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        if type(other) in (TrueBoolLiteralSugar, FalseBoolLiteralSugar):
            from sugar_lift_py_tests.outcome import Complete

            return Complete(
                TermValue(self.value + (1 if type(other) is TrueBoolLiteralSugar else 0))
            )
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.guarded_value import GuardedValue
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        if isinstance(other, GuardedValue):
            return other.map_from_left("add", self, site)
        if type(other) in (CallSiteValue, PredicateValue, SymbolicValue):
            return SymbolicValue(self.to_term(owner=str(site))).add(other, site)
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
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.import_alias_value import ImportAliasValue
        from sugar_lift_py_tests.floor.list_value import ListValue
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.floor.tuple_value import TupleValue

        if type(other) in (CallSiteValue, ImportAliasValue, SymbolicValue):
            return SymbolicValue(self.to_term(owner=str(site))).multiply(other, site)
        if type(other) in (ListValue, StringValue, TupleValue):
            if type(self.value) is int:
                return other.multiply(self, site)
        return super().multiply(other, site)

    def power(self, other, site):
        if type(other) is TermValue:
            from sugar_lift_py_tests.outcome import Complete

            return Complete(TermValue(self.value**other.value))
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        if type(other) is SymbolicValue:
            return SymbolicValue(self.to_term(owner=str(site))).power(other, site)
        return super().power(other, site)

    def divide(self, other, site):
        # A number stands on the division floor: true division. A concrete zero
        # divisor is a runtime effect (the program halts), not a lift-side gap.
        if type(other) is TermValue:
            from sugar_lift_py_tests.outcome import Complete, Incomplete

            if other.value == 0:
                from sugar_lift_py_tests.effect import (
                    DivisionByZeroRuntimeEffect,
                    runtime_effect_witness,
                )

                return Incomplete(
                    DivisionByZeroRuntimeEffect(
                        f"division by zero runtime boundary: the divisor is "
                        f"concretely 0; owner=TermValue.divide site={site}",
                        witness=runtime_effect_witness("py.divide", other, site),
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
                from sugar_lift_py_tests.effect import (
                    ModuloByZeroRuntimeEffect,
                    runtime_effect_witness,
                )

                return Incomplete(
                    ModuloByZeroRuntimeEffect(
                        f"modulo by zero runtime boundary: the divisor is "
                        f"concretely 0; owner=TermValue.modulo site={site}",
                        witness=runtime_effect_witness("py.modulo", other, site),
                    )
                )
            return Complete(TermValue(self.value % other.value))
        return super().modulo(other, site)

    def floor_divide(self, other, site):
        if type(other) is TermValue:
            from sugar_lift_py_tests.outcome import Complete, Incomplete

            if other.value == 0:
                from sugar_lift_py_tests.effect import (
                    DivisionByZeroRuntimeEffect,
                    runtime_effect_witness,
                )

                return Incomplete(
                    DivisionByZeroRuntimeEffect(
                        "floor division by zero runtime boundary: the divisor is "
                        f"concretely 0; owner=TermValue.floor_divide site={site}",
                        witness=runtime_effect_witness(
                            "py.floor_divide", other, site
                        ),
                    )
                )
            return Complete(TermValue(self.value // other.value))
        return super().floor_divide(other, site)

    def right_shift(self, other, site):
        if (
            type(other) is TermValue
            and type(self.value) is int
            and type(other.value) is int
        ):
            from sugar_lift_py_tests.outcome import Complete

            return Complete(TermValue(self.value >> other.value))
        return self._symbolic_or_bv32_bitwise(other, site, ">>", "bv32.lshr")

    def bitwise_and(self, other, site):
        if type(other) is TermValue and all(
            type(value) is int for value in (self.value, other.value)
        ):
            from sugar_lift_py_tests.outcome import Complete

            return Complete(TermValue(self.value & other.value))
        return self._symbolic_or_bv32_bitwise(other, site, "&", "bv32.and")

    def bitwise_xor(self, other, site):
        if type(other) is TermValue and all(
            type(value) is int for value in (self.value, other.value)
        ):
            from sugar_lift_py_tests.outcome import Complete

            return Complete(TermValue(self.value ^ other.value))
        return self._symbolic_or_bv32_bitwise(other, site, "^", "bv32.xor")

    def bitwise_or(self, other, site):
        if type(other) is TermValue and all(
            type(value) is int for value in (self.value, other.value)
        ):
            from sugar_lift_py_tests.outcome import Complete

            return Complete(TermValue(self.value | other.value))
        return self._symbolic_or_bv32_bitwise(other, site, "|", "bv32.or")

    def left_shift(self, other, site):
        if type(other) is TermValue and all(
            type(value) is int for value in (self.value, other.value)
        ):
            from sugar_lift_py_tests.outcome import Complete

            return Complete(TermValue(self.value << other.value))
        return self._symbolic_or_bv32_bitwise(other, site, "<<", "bv32.shl")

    def _symbolic_or_bv32_bitwise(self, other, site, operator, bv32_operator):
        from sugar_lift_py_tests.floor.bv32_value import Bv32Value
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        if type(other) is SymbolicValue:
            return getattr(
                SymbolicValue(self.to_term(owner=str(site))),
                {
                    "&": "bitwise_and",
                    "|": "bitwise_or",
                    "^": "bitwise_xor",
                    "<<": "left_shift",
                    ">>": "right_shift",
                }[operator],
            )(other, site)
        if type(other) is Bv32Value:
            from sugar_lift_py_tests.ir import ctor
            from sugar_lift_py_tests.outcome import Complete

            return Complete(
                Bv32Value(
                    ctor(
                        bv32_operator,
                        [self.to_term(owner=str(site)), other.to_term(owner=str(site))],
                    )
                )
            )
        method = {
            "&": "bitwise_and",
            "|": "bitwise_or",
            "^": "bitwise_xor",
            "<<": "left_shift",
            ">>": "right_shift",
        }[operator]
        return getattr(super(), method)(other, site)

    def matrix_multiply(self, other, site):
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        if type(other) is SymbolicValue:
            return SymbolicValue(self.to_term(owner=str(site))).matrix_multiply(
                other, site
            )
        return super().matrix_multiply(other, site)

    def unary_minus(self, site):
        # Arithmetic negation: fold to -value.
        del site
        from sugar_lift_py_tests.outcome import Complete

        return Complete(TermValue(-self.value))

    def absolute(self, site):
        del site
        from sugar_lift_py_tests.outcome import Complete

        return Complete(TermValue(abs(self.value)))

    def unary_plus(self, site):
        # Unary plus: fold to +value (identity for numbers).
        del site
        from sugar_lift_py_tests.outcome import Complete

        return Complete(TermValue(+self.value))

    def bitwise_invert(self, site):
        # Bitwise NOT: fold ints; floats raise TypeError at runtime in Python.
        if type(self.value) is int:
            from sugar_lift_py_tests.outcome import Complete

            return Complete(TermValue(~self.value))
        from sugar_lift_py_tests.effect import (
            TypeErrorRuntimeEffect,
            runtime_effect_witness,
        )
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            TypeErrorRuntimeEffect(
                f"bad operand type for unary ~: "
                f"'float'; owner=TermValue.bitwise_invert site={site}",
                witness=runtime_effect_witness("py.bitwise_invert", self, site),
            )
        )

    def to_term(self, *, owner: str):
        del owner
        import math

        # Int embeds in Real losslessly (3 and 3.0 are the same number), but the
        # embedding only goes one way at the term level: an Int-sorted term and
        # a Real-sorted term are structurally distinct EUF constants even when
        # the numbers agree, so an INTEGRAL float still projects through the
        # Int constructor -- matching any plain-int sibling it must agree with
        # (e.g. `float('3.0') == 3`, `np.divide(6, 3) == 2`). Only a genuinely
        # fractional float needs the Real ctor, because there is no lossless
        # Int projection for it.
        #
        # Non-finite floats (inf/nan) must NOT take the integral arm:
        # ``int(float('inf'))`` raises OverflowError and hard-crashes the lift
        # RPC (pandas wall after #4155 transport scrub). Keep them on the Real
        # arm so the channel stays structured, never a bare process death.
        if (
            type(self.value) is float
            and math.isfinite(self.value)
            and self.value == int(self.value)
        ):
            from sugar_lift_py_tests.ir import num

            return num(int(self.value))
        if type(self.value) is float:
            from decimal import Decimal

            from sugar_lift_py_tests.ir import real_lit

            # A canonical decimal string, never a Python float text form (see
            # `ir.real_lit`): `Decimal(str(value))` round-trips because
            # `repr`/`str` of a Python float is already the shortest exact
            # decimal that reparses to the same double. Non-finite values
            # become "Infinity" / "NaN" (Decimal-legal), not a crash.
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
        FactoryAuditRow,
        factory_panic,
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
