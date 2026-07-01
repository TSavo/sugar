from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo
from sugar_lift_py_tests.floor import CallSiteValue, FloorValue, ObjectValue
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term


@dataclass(frozen=True)
class MethodCallOperation:
    name: str
    arguments: tuple[FloorValue, ...]
    owner: str = "CallSugar"
    blame: str = "<unknown>"

    def call_object_method(self, receiver: ObjectValue, ctx: object) -> Outcome:
        del ctx
        for method in reversed(receiver.methods):
            if method.name != self.name:
                continue
            if not method.parameters:
                self._floor_gap(
                    observed=f"{receiver.class_name}.{self.name}",
                    requested="method self parameter",
                    fix=f"add method binding sugar for `{receiver.class_name}.{self.name}`",
                )
            expected = len(method.parameters) - 1
            if len(self.arguments) != expected:
                self._floor_gap(
                    observed=f"{receiver.class_name}.{self.name}",
                    requested=f"{expected} method arguments",
                    fix=(
                        f"add method argument binding sugar for "
                        f"`{receiver.class_name}.{self.name}`"
                    ),
                )
            target_name = f"{receiver.class_name}.{self.name}"
            arg_values = (receiver, *self.arguments)
            arg_terms = [
                floor_to_term(value, owner=f"{self.owner} method argument")
                for value in arg_values
            ]
            return Complete(
                CallSiteValue(
                    target_name=target_name,
                    arg_values=arg_values,
                    parameters=method.parameters,
                    term=ctor(f"call:{target_name}", arg_terms),
                    body=method.body,
                )
            )
        self._floor_gap(
            observed=f"{receiver.class_name}.{self.name}",
            requested="constructor-bound method",
            fix=(
                f"define `{self.name}` on `{receiver.class_name}` or add the "
                "floor that owns this method"
            ),
        )

    def _floor_gap(self, *, observed: str, requested: str, fix: str) -> None:
        info = FactoryGapInfo(
            owner=self.owner,
            blame=self.blame,
            observed=observed,
            requested=requested,
            fix=fix,
            gap_kind="Floor",
            gap_locus="construction",
        )
        raise FactoryGap(
            info,
            FactoryAuditRow(
                role=requested,
                status="floor-gap",
                observed=observed,
                blame=self.blame,
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )
