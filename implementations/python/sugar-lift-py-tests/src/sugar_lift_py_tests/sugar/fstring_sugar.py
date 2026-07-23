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
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.outcome import Incomplete

        value = self.value.desugar(ctx)
        if isinstance(value, Incomplete):
            return value
        if self.format_spec is None:
            format_spec_term = ctor("None", [])
        else:
            format_spec = self.format_spec.reference_term(ctx)
            if isinstance(format_spec, Incomplete):
                return format_spec
            format_spec_term = format_spec.value
        conversion_term = (
            ctor("None", []) if self.conversion is None else str_const(self.conversion)
        )
        return Complete(
            SymbolicValue(
                ctor(
                    "python:fstring_value",
                    [
                        value.value.to_term(owner="FormattedValueSugar.value"),
                        conversion_term,
                        format_spec_term,
                    ],
                )
            )
        )


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
        from sugar_lift_py_tests.outcome import Incomplete

        if not self.parts:
            return Complete(StringValue(""))
        acc = self.parts[0].desugar(ctx)
        for part in self.parts[1:]:
            if isinstance(acc, Incomplete):
                return acc
            right = part.desugar(ctx)
            if isinstance(right, Incomplete):
                return right
            acc = acc.value.add(right.value, self.site)
        return acc

    def reference_term(self, ctx: object = None) -> Outcome:
        """Project this JoinedStr as the reference ``python:fstring`` ctor."""
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        terms = []
        for part in self.parts:
            projected = part.desugar(ctx)
            if isinstance(projected, Incomplete):
                return projected
            terms.append(projected.value.to_term(owner="JoinedStrSugar.reference_term"))
        return Complete(ctor("python:fstring", terms))
