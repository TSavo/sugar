from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from sugar_lift_py_tests.floor import StringValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import ctor, num, str_const
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class FormatValueOperation:
    method_name: ClassVar[str] = "format_value_with"
    spec: str
    conversion: int
    owner: str = "JoinedStrSugar"
    blame: str = "<unknown>"

    def format_string(self, receiver: StringValue, ctx: object) -> Outcome:
        del ctx
        return Complete(StringValue(format(receiver.value, self.spec)))

    def format_term(self, receiver: TermValue, ctx: object) -> Outcome:
        del ctx
        return Complete(StringValue(format(receiver.value, self.spec)))

    def format_symbolic(self, receiver: SymbolicValue, ctx: object) -> Outcome:
        del ctx
        return Complete(
            SymbolicValue(
                ctor(
                    "py.format",
                    [receiver.term, str_const(self.spec), num(self.conversion)],
                )
            )
        )
