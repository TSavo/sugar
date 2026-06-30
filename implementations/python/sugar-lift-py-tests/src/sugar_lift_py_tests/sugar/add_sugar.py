from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.factory.sugar_constructors import build_add_sugar
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.operations import AddOperation, perform_operation
from sugar_lift_py_tests.outcome import Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AddSugar:
    receiver: SugarBody
    operand: SugarBody
    blame: str

    @classmethod
    def from_site(
        cls, site, *, receiver: SugarBody, operand: SugarBody
    ) -> "AddSugar | None":
        if not _is_add_call(site):
            return None
        if site.call_arg_count() != 1:
            return None
        return cls(
            receiver=receiver,
            operand=operand,
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        receiver = complete_value(self.receiver.reduce(ctx), owner="AddSugar receiver")
        operand = complete_value(self.operand.reduce(ctx), owner="AddSugar operand")
        if not isinstance(operand, TermValue):
            raise TypeError("AddSugar operand must reduce to TermValue")
        return perform_operation(
            owner="AddSugar",
            blame=self.blame,
            receiver=receiver,
            method_name="add_with",
            operation=AddOperation(operand=operand, owner="AddSugar", blame=self.blame),
            ctx=ctx,
        )


def _is_add_call(site) -> bool:
    return (
        site.observed == "Call"
        and site.call_is_method_call()
        and site.call_target_name() == "add"
    )


def _owns(site) -> bool:
    return _is_add_call(site)


ADD_CLAIM = SugarClaim(
    name="AddSugar",
    role=SugarRole.TERM,
    owns=_owns,
    build=build_add_sugar,
)
