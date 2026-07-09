from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from sugar_lift_py_tests.floor import (
    Bv32Value,
    ObjectValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.outcome import Complete, Outcome

from .object_method_call import call_object_method_value


@dataclass(frozen=True)
class StrCoercionOperation:
    method_name: ClassVar[str] = "str_with"
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
        # Non-concrete marker; BuiltinCallSugar wrap attaches call:str(<x>).
        return Complete(receiver)

    def str_bv32(self, receiver: Bv32Value, ctx: object) -> Outcome:
        del ctx
        # Non-concrete marker; BuiltinCallSugar wrap attaches call:str(<x>).
        return Complete(receiver)

    def str_object(self, receiver: ObjectValue, ctx: object) -> Outcome:
        del ctx
        return call_object_method_value(
            receiver,
            "__str__",
            (),
            owner=self.owner,
            blame=self.blame,
        )
