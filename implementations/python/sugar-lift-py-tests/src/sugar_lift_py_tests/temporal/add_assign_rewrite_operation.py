from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from sugar_lift_py_tests.floor import FloorValue


@dataclass(frozen=True)
class AddAssignRewriteOperation:
    method_name: ClassVar[str] = "rewrite_with"
    name: str
    value: FloorValue
    owner: str
    blame: str

    def rewrite_context(self, receiver, ctx):
        from sugar_lift_py_tests.operations import AddOperation, perform_operation
        from sugar_lift_py_tests.outcome import complete_value

        current = receiver.value_for(self.name)
        rewritten = complete_value(
            perform_operation(
                owner=self.owner,
                blame=self.blame,
                receiver=current,
                operation=AddOperation(
                    operand=self.value,
                    owner=self.owner,
                    blame=self.blame,
                ),
                ctx=ctx,
            ),
            owner=f"{self.owner} add_assign",
        )
        return receiver._bind_value(self.name, rewritten, blame=self.blame)
