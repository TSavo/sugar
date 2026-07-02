from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import (
    Bv32Value,
    ObjectValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class StrCoercionOperation:
    owner: str = "BuiltinCallSugar"
    blame: str = "<unknown>"

    def str_string(self, receiver: StringValue, ctx: object) -> Outcome:
        del ctx
        return Complete(receiver)

    def str_term(self, receiver: TermValue, ctx: object) -> Outcome:
        del ctx
        return Complete(StringValue(str(receiver.value)))

    def str_symbolic(self, receiver: SymbolicValue, ctx: object) -> Outcome:
        del ctx
        return Complete(SymbolicValue(ctor("py.str", [receiver.term])))

    def str_bv32(self, receiver: Bv32Value, ctx: object) -> Outcome:
        del ctx
        return Complete(SymbolicValue(ctor("py.str", [receiver.term])))

    def str_object(self, receiver: ObjectValue, ctx: object) -> Outcome:
        del ctx
        return receiver.call_method_value(
            "__str__",
            (),
            owner=self.owner,
            blame=self.blame,
        )
