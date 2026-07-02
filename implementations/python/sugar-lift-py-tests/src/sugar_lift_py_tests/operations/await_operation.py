from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from sugar_lift_py_tests.floor import ObjectValue
from sugar_lift_py_tests.outcome import Complete, Incomplete, complete_value

from .dunder_force import force_dunder_floor_or_runtime_effect
from .object_method_call import call_object_method_value


@dataclass(frozen=True)
class AwaitOperation:
    method_name: ClassVar[str] = "await_with"
    owner: str = "AwaitSugar"
    blame: str = "<unknown>"

    def await_object(self, receiver: ObjectValue, ctx):
        value = complete_value(
            call_object_method_value(
                receiver,
                "__await__",
                (),
                owner=f"{self.owner}.__await__",
                blame=self.blame,
            ),
            owner=f"{self.owner}.__await__",
        )
        forced = force_dunder_floor_or_runtime_effect(
            value,
            ctx,
            owner=f"{self.owner}.__await__",
            project_callsite=False,
        )
        if isinstance(forced, Incomplete):
            return forced
        return Complete(forced)
