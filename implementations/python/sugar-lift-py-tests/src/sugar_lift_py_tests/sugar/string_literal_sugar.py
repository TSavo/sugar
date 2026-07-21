from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.floor import StringValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


@dataclass(frozen=True)
class StringLiteralSugar(Sugar):
    """A string literal. Infinitely many values, so the value is a field. It
    reduces to a StringValue: the string as a term. A leaf -- no child sugars.

    Meaning-only, node-constructed: the Constant node distinguishes `str` (by
    `type(value) is str`) and constructs this WITH the value; no owns/new/role.
    """

    value: str
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="string_literal_return",
            owner_sugar="StringLiteralSugar",
            body='"abc"',
            truthful="'abc'",
            lying="'xyz'",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx  # the string stands as a term
        return Complete(StringValue(self.value))
