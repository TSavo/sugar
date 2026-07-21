"""f-strings: `f"pre {value} post"`.

A JoinedStr is the CONCATENATION of its parts -- literal chunks (StringLiteral)
and interpolations (FormattedValue). It folds them left with `add`, the same
string concatenation `+` uses: ground chunks fold to one string, an interpolated
symbol becomes a `str.++` coordinate. A FormattedValue is `format(value, spec)`:
with no conversion and no format spec it is the value's own `__format__`
coordinate (`call:__format__(value, "")`), decidable without inventing a
rendered string. A conversion (`!r`/`!s`/`!a`) or a format spec (`{x:>10}`) is
not lifted yet -- LOUD, never a silently dropped modifier.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class FormattedValueSugar(Sugar):
    """`{value}` inside an f-string -- format(value) with an empty spec."""

    value: Sugar
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.string_value import StringValue

        return self.value.desugar(ctx).and_then(
            lambda value: value.format_data_model(StringValue(""), self.site, ctx)
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
