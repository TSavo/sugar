from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import ArrayLiteral, FunctionCallable
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class CallableMapOperation:
    callable: FunctionCallable

    def map_array(self, receiver: ArrayLiteral, ctx: object) -> Outcome:
        del ctx
        return Complete(
            ArrayLiteral(tuple(self.callable.apply(item) for item in receiver.items))
        )
