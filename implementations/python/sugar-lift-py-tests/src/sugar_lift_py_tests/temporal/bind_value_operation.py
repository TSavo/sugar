from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from sugar_lift_py_tests.floor import FloorValue


@dataclass(frozen=True)
class BindValueOperation:
    method_name: ClassVar[str] = "bind_with"
    name: str
    value: FloorValue
    owner: str
    blame: str

    def bind_context(self, receiver, ctx):
        del ctx
        return receiver._bind_value(self.name, self.value, blame=self.blame)
