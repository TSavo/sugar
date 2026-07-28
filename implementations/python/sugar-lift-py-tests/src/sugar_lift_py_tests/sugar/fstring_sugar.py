"""f-strings: `f"pre {value} post"`.

A JoinedStr is the CONCATENATION of its parts -- literal chunks (StringLiteral)
and interpolations (FormattedValue). It folds them left with `add`, the same
string concatenation `+` uses. A FormattedValue projects the Python reference's
opaque ``python:fstring_value(value, conversion, format_spec)`` coordinate.
Conversion and format spec remain typed operands: absence is explicit ``None``
and a present spec is a nested ``python:fstring`` coordinate. The coordinate
carries Python's conversion-then-format meaning without claiming execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class FormattedValueSugar(Sugar):
    """A Python-reference formatted-value coordinate, without execution."""

    value: Sugar
    conversion: str | None
    format_spec: JoinedStrSugar | None
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import ctor, str_const

        conversion_term = (
            ctor("None", []) if self.conversion is None else str_const(self.conversion)
        )

        def build(value, format_spec_term):
            # Ground strings with no conversion/spec are already their display.
            # RaisesExc formats ``f"DID NOT RAISE {type.__name__}"``; folding
            # keeps the diagnostic message a StringValue so fail() can raise
            # instead of panicking at SymbolicValue + SymbolicValue.
            if (
                isinstance(value, StringValue)
                and self.conversion is None
                and self.format_spec is None
            ):
                return Complete(value)
            return Complete(
                SymbolicValue(
                    ctor(
                        "python:fstring_value",
                        [
                            value.to_term(owner="FormattedValueSugar.value"),
                            conversion_term,
                            format_spec_term,
                        ],
                    )
                )
            )

        # `f"{expr!r:{spec}}"` evaluates expr then spec, and EITHER can halt or
        # partition (`f"{d[k] := v}"`). Both thread through `and_then` -- the one
        # door every Outcome variant implements -- so a halt propagates and a
        # partition keeps every arm. Reading `.value` off the outcome assumed one
        # unconditional arm and was the `'ExitSet' has no attribute 'value'`
        # defect here.
        def with_spec(value):
            if self.format_spec is None:
                return build(value, ctor("None", []))
            return self.format_spec.reference_term(ctx).and_then(
                lambda spec_term: build(value, spec_term)
            )

        return self.value.desugar(ctx).and_then(with_spec)


@dataclass(frozen=True)
class JoinedStrSugar(Sugar):
    """The whole f-string: concatenate its parts left-to-right via `add`."""

    parts: tuple
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        prefix = 'def A(z):\n    return f"n={z}"\n\n'
        return _call_pair(
            name="fstring_return",
            owner_sugar="JoinedStrSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == '5'\n",
            lying=prefix + "def test_a():\n    assert A(5) == '6'\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.outcome.exit_set import factored_operand

        if not self.parts:
            return Complete(StringValue(""))
        # Concatenate left-to-right through `and_then`, the one door every
        # Outcome variant implements: a part that halts propagates, a part that
        # PARTITIONS keeps every arm and each arm concatenates under its own
        # guard. `acc.value.add(right.value, ...)` assumed both sides were one
        # unconditional value.
        # One completed arm per part (#6324): concatenation is a k-step fold
        # through `ExitSet.sequence`, so an unfactored partitioning part
        # multiplies the accumulator at every remaining part.
        outcome = factored_operand(self.parts[0].desugar(ctx))
        for part in self.parts[1:]:
            outcome = outcome.and_then(
                lambda left, part=part: factored_operand(part.desugar(ctx)).and_then(
                    lambda right: left.add(right, self.site)
                )
            )
        return outcome

    def reference_term(self, ctx: object = None) -> Outcome:
        """Project this JoinedStr as the reference ``python:fstring`` ctor."""
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.outcome.exit_set import factored_operand

        # Same law as `desugar`: every part threads through `and_then`, so a
        # halting or partitioning part is conserved rather than read as `.value`.
        outcome = Complete(())
        for part in self.parts:
            outcome = outcome.and_then(
                lambda terms, part=part: factored_operand(part.desugar(ctx)).and_then(
                    lambda value: Complete(
                        (
                            *terms,
                            value.to_term(owner="JoinedStrSugar.reference_term"),
                        )
                    )
                )
            )
        return outcome.and_then(
            lambda terms: Complete(ctor("python:fstring", list(terms)))
        )
