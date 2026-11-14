from __future__ import annotations

from dataclasses import dataclass

from .guard_stable_value import GuardStableValue


@dataclass(frozen=True)
class TermValue(GuardStableValue):
    # Python numeric literals share one floor value implementation, but retain
    # their calculus sort: int -> Int and float -> Real. There is no Number sort.
    value: int | float

    def denotes_value(self) -> bool:
        """This floor value denotes a Python scalar it carries as its own payload."""
        return True

    def python_index_protocol(self) -> bool:
        return isinstance(self.value, int)

    def equals(self, other, site, ctx):
        """Ground numeric equality folds so ``len(xs) == 1`` can ground Ifs.

        RaisesExc selects the singular absent-effect diagnostic with
        ``if len(self.expected_exceptions) == 1``. Emitting ``=(1, 1)`` as a
        third value forces both branches and panics the multi-name join arm.
        """
        if type(other) is TermValue and type(self.value) is type(other.value):
            from sugar_lift_py_tests.outcome import ExitSet
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return ExitSet.completed(
                TrueBoolLiteralSugar(site=site)
                if self.value == other.value
                else FalseBoolLiteralSugar(site=site)
            )
        return super().equals(other, site, ctx)

    def python_isinstance(self, type_name: str, type_term, site):
        del type_name  # display spelling is not authority
        from sugar_lift_py_tests.floor.python_type_coordinate import (
            authenticated_python_type_spelling,
        )
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        authenticated = authenticated_python_type_spelling(
            type_term, owner="TermValue.python_isinstance", site=site
        )
        matches = (type(self.value) is int and authenticated == "int") or (
            type(self.value) is float and authenticated == "float"
        )
        return ExitSet.completed(
            TrueBoolLiteralSugar(site=site)
            if matches
            else FalseBoolLiteralSugar(site=site)
        )

    def truth(self, site):
        # Python-faithful: nonzero is True. bool(nan) is True and nan != 0 IS
        # True in Python, so the same expression is correct.
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        return ExitSet.completed(
            TrueBoolLiteralSugar(site=site)
            if self.value != 0
            else FalseBoolLiteralSugar(site=site)
        )

    # equals is NOT overridden: an assertion EMITS a fact. `assert 1 == 1` is
    # the vendor asserting the fact `1 = 1` -- a real inv, trivially valid,
    # with no call site (operand_callsites == ()) and no contract. The base
    # FloorValue.equals builds exactly that PredicateValue, which states as an
    # InvValue. Folding two ground numbers to a True/False literal here was the
    # bug: it let the bool decide there was no fact to emit, dropping the
    # vendor's assertion out of the FOL. The value does not get to opt out of
    # an emission the assertion owns.

    def is_identical(self, other, site):
        from sugar_lift_py_tests.floor.none_value import NoneValue

        if type(other) is NoneValue:
            from sugar_lift_py_tests.outcome import ExitSet
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )

            return ExitSet.completed(FalseBoolLiteralSugar(site=site))
        return super().is_identical(other, site)

    def _unorderable_ground_peer(self, other) -> bool:
        from sugar_lift_py_tests.floor.list_value import ListValue
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.floor.set_value import SetValue
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.floor.tuple_value import TupleValue

        return type(other) in (
            StringValue,
            NoneValue,
            ListValue,
            TupleValue,
            SetValue,
        )

    def _ground_ordering_type_error(self, site, *, owner: str):
        from sugar_lift_py_tests.floor.ground_exit import ground_type_error

        return ground_type_error(site=site, owner=owner)

    def _decided_binary_type_error(self, other, site, ctx, *, owner: str):
        """Decided non-numeric right → authenticated TypeError; else super gap.

        After the numeric tower and sequence-repetition arms have run, a
        source-decided peer that still has no arm is Python's TypeError
        (``1 + "a"``, ``3 % []``).  Undecided rights stay on the shared
        third-value law via ``super()``.
        """
        if other.denotes_value() and other.runtime_type_is_decided():
            from sugar_lift_py_tests.floor.ground_exit import ground_type_error

            return ground_type_error(site=site, owner=owner)
        return getattr(super(), owner.rsplit(".", 1)[-1])(other, site, ctx)

    def less_than(self, other, site, ctx):
        # A number stands on the ordering floor: two numbers fold to True/False
        # Sugar. Ground cross-type is authenticated TypeError. Undecided peers
        # refuse named (LAW_OF_ONE — no ExitSet.completed(PredicateValue) invent).
        if type(other) is TermValue:
            from sugar_lift_py_tests.outcome import ExitSet
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return ExitSet.completed(
                TrueBoolLiteralSugar(site=site)
                if self.value < other.value
                else FalseBoolLiteralSugar(site=site)
            )
        if self._unorderable_ground_peer(other):
            return self._ground_ordering_type_error(site, owner="TermValue.less_than")
        return super().less_than(other, site, ctx)

    def less_than_from_left(self, left, site, ctx):
        """``left < self`` when the RHS is a number — Sugar fold or TypeError."""
        if type(left) is TermValue:
            from sugar_lift_py_tests.outcome import ExitSet
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return ExitSet.completed(
                TrueBoolLiteralSugar(site=site)
                if left.value < self.value
                else FalseBoolLiteralSugar(site=site)
            )
        if self._unorderable_ground_peer(left):
            return self._ground_ordering_type_error(
                site, owner="TermValue.less_than_from_left"
            )
        return super().less_than_from_left(left, site, ctx)

    def less_equal(self, other, site, ctx):
        if type(other) is TermValue:
            from sugar_lift_py_tests.outcome import ExitSet
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return ExitSet.completed(
                TrueBoolLiteralSugar(site=site)
                if self.value <= other.value
                else FalseBoolLiteralSugar(site=site)
            )
        if self._unorderable_ground_peer(other):
            return self._ground_ordering_type_error(site, owner="TermValue.less_equal")
        return super().less_equal(other, site, ctx)

    def greater_than(self, other, site, ctx):
        if type(other) is TermValue:
            from sugar_lift_py_tests.outcome import ExitSet
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return ExitSet.completed(
                TrueBoolLiteralSugar(site=site)
                if self.value > other.value
                else FalseBoolLiteralSugar(site=site)
            )
        if self._unorderable_ground_peer(other):
            return self._ground_ordering_type_error(
                site, owner="TermValue.greater_than"
            )
        return super().greater_than(other, site, ctx)

    def greater_equal(self, other, site, ctx):
        if type(other) is TermValue:
            from sugar_lift_py_tests.outcome import ExitSet
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return ExitSet.completed(
                TrueBoolLiteralSugar(site=site)
                if self.value >= other.value
                else FalseBoolLiteralSugar(site=site)
            )
        if self._unorderable_ground_peer(other):
            return self._ground_ordering_type_error(
                site, owner="TermValue.greater_equal"
            )
        return super().greater_equal(other, site, ctx)

    def add(self, other, site, ctx):
        # Python int/float arithmetic folds while retaining the result's concrete
        # Python type; ProofIR projection later preserves Int versus Real.
        if type(other) is TermValue:
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(TermValue(self.value + other.value))
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        if type(other) in (TrueBoolLiteralSugar, FalseBoolLiteralSugar):
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(
                TermValue(
                    self.value + (1 if type(other) is TrueBoolLiteralSugar else 0)
                )
            )
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.guarded_value import GuardedValue
        from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        if isinstance(other, GuardedValue):
            return other.map_from_left("add", self, site, ctx)
        if type(other) in (
            CallSiteValue,
            OpaqueOpCallsite,
            PredicateValue,
            SymbolicValue,
        ):
            return SymbolicValue(self.to_term(owner=str(site))).add(other, site, ctx)
        # A number plus a complex literal is a complex: the numeric tower's own
        # closed law, not a per-operand special case. `1 + 1j` was the largest
        # remaining pandas add panic.
        from sugar_lift_py_tests.floor.complex_arithmetic import complex_add

        folded = complex_add(self, other, site)
        if folded is not None:
            return folded
        from sugar_lift_py_tests.floor.complex_value import ComplexValue

        # Overflow / non-finite complex field results stay loud construction
        # gaps — not TypeError.
        if type(other) is ComplexValue:
            return super().add(other, site, ctx)
        return self._decided_binary_type_error(other, site, ctx, owner="TermValue.add")

    def subtract(self, other, site, ctx):
        # A number stands on the subtraction floor: two numbers subtract to a number.
        if type(other) is TermValue:
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(TermValue(self.value - other.value))
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        if type(other) is SymbolicValue:
            return SymbolicValue(self.to_term(owner=str(site))).subtract(
                other, site, ctx
            )
        if type(other) is CallSiteValue:
            from sugar_lift_py_tests.effect import runtime_subtract

            return runtime_subtract(self, other, site)
        from sugar_lift_py_tests.floor.complex_arithmetic import complex_subtract

        folded = complex_subtract(self, other, site)
        if folded is not None:
            return folded
        from sugar_lift_py_tests.floor.complex_value import ComplexValue

        if type(other) is ComplexValue:
            return super().subtract(other, site, ctx)
        return self._decided_binary_type_error(
            other, site, ctx, owner="TermValue.subtract"
        )

    def multiply(self, other, site, ctx):
        # A number stands on the multiplication floor: two numbers multiply, and the
        # The product retains Python's concrete int/float result type.
        if type(other) is TermValue:
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(TermValue(self.value * other.value))
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.guarded_value import GuardedValue
        from sugar_lift_py_tests.floor.list_value import ListValue
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.floor.tuple_value import TupleValue

        if isinstance(other, GuardedValue):
            return other.map_from_left("multiply", self, site, ctx)
        if type(other) in (CallSiteValue, SymbolicValue):
            return SymbolicValue(self.to_term(owner=str(site))).multiply(
                other, site, ctx
            )
        if type(other) in (ListValue, StringValue, TupleValue):
            # int/bool * sequence is repetition; float * sequence is TypeError.
            if isinstance(self.value, int):
                return other.multiply(self, site, ctx)
            return self._decided_binary_type_error(
                other, site, ctx, owner="TermValue.multiply"
            )
        from sugar_lift_py_tests.floor.complex_arithmetic import complex_multiply

        folded = complex_multiply(self, other, site)
        if folded is not None:
            return folded
        from sugar_lift_py_tests.floor.complex_value import ComplexValue

        if type(other) is ComplexValue:
            return super().multiply(other, site, ctx)
        return self._decided_binary_type_error(
            other, site, ctx, owner="TermValue.multiply"
        )

    def power(self, other, site, ctx):
        if type(other) is TermValue:
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(TermValue(self.value**other.value))
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.guarded_value import GuardedValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        if isinstance(other, GuardedValue):
            return other.map_from_left("power", self, site, ctx)
        if type(other) is SymbolicValue:
            return SymbolicValue(self.to_term(owner=str(site))).power(other, site, ctx)
        if type(other) is CallSiteValue:
            dug = other._dig_floor_or_none(
                ctx, owner="TermValue.power callsite exponent"
            )
            if dug is not None and dug is not other:
                return self.power(dug, site, ctx)

            from sugar_lift_py_tests.effect import (
                PowerRuntimeEffect,
                runtime_effect_evidence,
            )
            from sugar_lift_py_tests.ir import ctor
            from sugar_lift_py_tests.outcome import ExitSet

            operand = ctor(
                "**",
                [
                    self.to_term(owner=str(site)),
                    other.to_term(owner=str(site)),
                ],
            )
            return ExitSet.halted(
                PowerRuntimeEffect(
                    "power dispatch depends on the runtime call exponent's "
                    f"__rpow__; owner=TermValue.power site={site}",
                    **runtime_effect_evidence("py.power", operand, site),
                )
            )
        return super().power(other, site, ctx)

    def divide(self, other, site, ctx):
        # A number stands on the division floor: true division. A concrete zero
        # divisor is a runtime effect (the program halts), not a lift-side gap.
        if type(other) is TermValue:
            from sugar_lift_py_tests.outcome import ExitSet

            if other.value == 0:
                from sugar_lift_py_tests.floor.ground_exception_exit import (
                    ground_exception_exit,
                )

                return ground_exception_exit(
                    exception_name="ZeroDivisionError",
                    site=site,
                )
            return ExitSet.completed(TermValue(self.value / other.value))
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        if type(other) in (CallSiteValue, SymbolicValue):
            return SymbolicValue(self.to_term(owner=str(site))).divide(other, site, ctx)
        return self._decided_binary_type_error(
            other, site, ctx, owner="TermValue.divide"
        )

    def modulo(self, other, site, ctx):
        # A number stands on the modulo floor: the remainder. A concrete zero
        # divisor is decidable at lift time, so it cannot mint runtime-effect
        # evidence. Keep the missing exact exception construction loud.
        if type(other) is TermValue:
            from sugar_lift_py_tests.outcome import ExitSet

            if other.value == 0:
                from sugar_lift_py_tests.floor.ground_zero_division_error import (
                    ground_zero_division_error,
                )

                return ground_zero_division_error(site=site)
            return ExitSet.completed(TermValue(self.value % other.value))
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

        if type(other) is CallSiteValue and other.body is None:
            from sugar_lift_py_tests.effect import runtime_modulo

            return runtime_modulo(self, other, site)
        return self._decided_binary_type_error(
            other, site, ctx, owner="TermValue.modulo"
        )

    def floor_divide(self, other, site, ctx):
        if type(other) is TermValue:
            from sugar_lift_py_tests.outcome import ExitSet

            if other.value == 0:
                from sugar_lift_py_tests.floor.ground_zero_division_error import (
                    ground_zero_division_error,
                )

                return ground_zero_division_error(site=site)
            return ExitSet.completed(TermValue(self.value // other.value))
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        if type(other) in (CallSiteValue, SymbolicValue):
            return SymbolicValue(self.to_term(owner=str(site))).floor_divide(
                other, site, ctx
            )
        return self._decided_binary_type_error(
            other, site, ctx, owner="TermValue.floor_divide"
        )

    def contains(self, item, site):
        """Numbers are never containers: ``x in 1`` is exact TypeError."""
        del item
        from sugar_lift_py_tests.floor.ground_exit import ground_type_error

        return ground_type_error(site=site, owner="TermValue.contains")

    def _bitwise_int_pair(self, other):
        """Python bitwise ops accept int/bool; float is decided TypeError."""
        return type(other) is TermValue and all(
            isinstance(value, int) for value in (self.value, other.value)
        )

    def _bitwise_float_type_error(self, other, site, *, owner: str):
        if type(other) is TermValue and (
            type(self.value) is float or type(other.value) is float
        ):
            from sugar_lift_py_tests.floor.ground_exit import ground_type_error

            return ground_type_error(site=site, owner=owner)
        return None

    def bitwise_and(self, other, site, ctx):
        float_error = self._bitwise_float_type_error(
            other, site, owner="TermValue.bitwise_and"
        )
        if float_error is not None:
            return float_error
        if self._bitwise_int_pair(other):
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(TermValue(self.value & other.value))
        return self._symbolic_or_bv32_bitwise(other, site, ctx, "&", "bv32.and")

    def bitwise_xor(self, other, site, ctx):
        float_error = self._bitwise_float_type_error(
            other, site, owner="TermValue.bitwise_xor"
        )
        if float_error is not None:
            return float_error
        if self._bitwise_int_pair(other):
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(TermValue(self.value ^ other.value))
        return self._symbolic_or_bv32_bitwise(other, site, ctx, "^", "bv32.xor")

    def bitwise_or(self, other, site, ctx):
        float_error = self._bitwise_float_type_error(
            other, site, owner="TermValue.bitwise_or"
        )
        if float_error is not None:
            return float_error
        if self._bitwise_int_pair(other):
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(TermValue(self.value | other.value))
        return self._symbolic_or_bv32_bitwise(other, site, ctx, "|", "bv32.or")

    def left_shift(self, other, site, ctx):
        float_error = self._bitwise_float_type_error(
            other, site, owner="TermValue.left_shift"
        )
        if float_error is not None:
            return float_error
        if self._bitwise_int_pair(other):
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(TermValue(self.value << other.value))
        return self._symbolic_or_bv32_bitwise(other, site, ctx, "<<", "bv32.shl")

    def right_shift(self, other, site, ctx):
        float_error = self._bitwise_float_type_error(
            other, site, owner="TermValue.right_shift"
        )
        if float_error is not None:
            return float_error
        if (
            type(other) is TermValue
            and type(self.value) is int
            and type(other.value) is int
        ):
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(TermValue(self.value >> other.value))
        return self._symbolic_or_bv32_bitwise(other, site, ctx, ">>", "bv32.lshr")

    def _symbolic_or_bv32_bitwise(self, other, site, ctx, operator, bv32_operator):
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
            )(other, site, ctx)
        if type(other) is Bv32Value:
            from sugar_lift_py_tests.ir import ctor
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(
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
        return getattr(super(), method)(other, site, ctx)

    def matrix_multiply(self, other, site, ctx):
        """``@`` is not defined on numbers — construct or typed-red, never panic.

        Free symbolic peers stay the native ``@`` coordinate. Concrete
        number ``@`` number is Python's TypeError (genuine runtime
        dependence). Object receivers with ``__rmatmul__`` are reflected
        through the object data-model, not invented as scalar multiply.
        """
        from sugar_lift_py_tests.floor.object_value import ObjectValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        if type(other) is SymbolicValue:
            return SymbolicValue(self.to_term(owner=str(site))).matrix_multiply(
                other, site, ctx
            )
        if type(other) is ObjectValue and other.has_method("__rmatmul__"):
            return other.call_method_value(
                "__rmatmul__",
                (self,),
                owner="MatrixMultiplyOpSugar",
                blame=str(site),
                ctx=ctx,
            )
        if type(other) is TermValue:
            from sugar_lift_py_tests.floor.ground_exit import ground_type_error

            return ground_type_error(site=site, owner="TermValue.matrix_multiply")
        return super().matrix_multiply(other, site, ctx)

    def unary_minus(self, site):
        # Arithmetic negation: fold to -value.
        del site
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(TermValue(-self.value))

    def unary_plus(self, site):
        # Unary plus: fold to +value (identity for numbers).
        del site
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(TermValue(+self.value))

    def bitwise_invert(self, site):
        # Bitwise NOT: fold ints; a known float has a ground TypeError exit.
        if isinstance(self.value, int):
            from sugar_lift_py_tests.outcome import ExitSet

            # ``bool`` is an int subtype and Python 3.14 still defines its
            # inversion through the underlying integer.  Convert explicitly
            # so construction does not emit CPython's runtime deprecation
            # warning while calculating a source-decided result.
            return ExitSet.completed(TermValue(~int(self.value)))
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError",
            site=site,
            owner="TermValue.bitwise_invert",
        )

    def setattr(self, name, value, site, ctx):
        """``(1).x = v`` raises AttributeError — store path, not read path."""
        del name, value, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError", site=site, owner="TermValue.setattr"
        )

    def delattr(self, name, site, ctx):
        """``del (1).x`` raises AttributeError — delete, not read."""
        del name, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError", site=site, owner="TermValue.delattr"
        )

    def subscript(self, index, site):
        """Numbers are never subscriptable: exact ground TypeError."""
        del index
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError",
            site=site,
            owner="TermValue.subscript",
        )

    def setitem(self, index, value, site, ctx):
        """Numeric values reject subscript store with exact TypeError."""
        del index, value, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="TermValue.setitem"
        )

    def delitem(self, index, site, ctx):
        """Numeric values reject subscript delete with exact TypeError."""
        del index, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="TermValue.delitem"
        )

    def to_term(self, *, owner: str):
        del owner
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
