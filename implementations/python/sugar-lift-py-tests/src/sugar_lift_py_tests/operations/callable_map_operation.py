from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from sugar_lift_py_tests.floor import ArrayLiteral, FunctionCallable, TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class CallableMapOperation:
    method_name: ClassVar[str] = "map_with"
    callable: FunctionCallable

    def map_array(self, receiver: ArrayLiteral, ctx: object) -> Outcome:
        del ctx
        return Complete(
            ArrayLiteral(
                tuple(self.callable.apply(_term_item(item)) for item in receiver.items)
            )
        )


def _term_item(item: object) -> TermValue:
    if isinstance(item, TermValue):
        return item
    raise TypeError(
        "CallableMapOperation maps FunctionCallable over TermValue elements"
    )
