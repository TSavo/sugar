from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from sugar_lift_py_tests.floor import FloorValue


@dataclass(frozen=True)
class CurryArgumentsOperation:
    method_name: ClassVar[str] = "curry_with"
    parameters: tuple[str, ...]
    arg_values: tuple[FloorValue, ...]
    owner: str
    blame: str

    def curry_context(self, receiver, ctx):
        del ctx
        if len(self.parameters) != len(self.arg_values):
            raise TypeError(
                f"write more Floor for {self.owner}: temporal curry argument count "
                "does not match parameters"
            )
        temporal = receiver
        for name, value in zip(self.parameters, self.arg_values, strict=True):
            temporal = temporal._bind_value(name, value, blame=self.blame)
        return temporal
