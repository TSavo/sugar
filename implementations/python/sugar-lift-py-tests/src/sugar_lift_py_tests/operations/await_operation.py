from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.floor import ObjectValue
from sugar_lift_py_tests.floor.call_site_value import force_floor
from sugar_lift_py_tests.outcome import Complete, Incomplete, complete_value


@dataclass(frozen=True)
class AwaitOperation:
    owner: str = "AwaitSugar"
    blame: str = "<unknown>"

    def await_object(self, receiver: ObjectValue, ctx):
        value = complete_value(
            receiver.call_method_value(
                "__await__",
                (),
                owner=f"{self.owner}.__await__",
                blame=self.blame,
            ),
            owner=f"{self.owner}.__await__",
        )
        try:
            return Complete(
                force_floor(
                    value,
                    ctx,
                    owner=f"{self.owner}.__await__",
                    project_callsite=False,
                )
            )
        except TypeError as exc:
            return Incomplete(
                RuntimeEffect(
                    f"{self.owner}.__await__ reduced to a runtime effect or "
                    f"opaque callsite: {exc}"
                )
            )
