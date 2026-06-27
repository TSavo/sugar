from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.floor import StringValue, TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class OrdSugar:
    target: str
    source_name: str
    index: int

    @classmethod
    def from_site(cls, site, *, source_name: str) -> "OrdSugar | None":
        stmt = site.node
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
            return None
        target = stmt.targets[0]
        if not isinstance(target, ast.Name):
            return None
        call = stmt.value
        if not isinstance(call, ast.Call):
            return None
        if not isinstance(call.func, ast.Name) or call.func.id != "ord":
            return None
        if call.keywords or len(call.args) != 1:
            return None
        subscript = call.args[0]
        if not isinstance(subscript, ast.Subscript):
            return None
        if not isinstance(subscript.value, ast.Name) or subscript.value.id != source_name:
            return None
        if not isinstance(subscript.slice, ast.Constant):
            return None
        index = subscript.slice.value
        if not isinstance(index, int):
            return None
        return cls(target=target.id, source_name=source_name, index=index)

    def apply(self, value: StringValue) -> Outcome:
        return Complete(TermValue(ord(value.value[self.index])))
