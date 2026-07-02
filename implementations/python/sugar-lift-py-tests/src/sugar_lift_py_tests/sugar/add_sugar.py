from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.operations import AddOperation, perform_operation
from sugar_lift_py_tests.outcome import Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AddSugar(Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    receiver: SugarBody
    operand: SugarBody
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return _is_add_call(site)

    @classmethod
    def build(cls, site, ctx) -> "AddSugar":
        sugar = cls.from_site(
            site,
            receiver=ctx.build_body(site.call_receiver(), SugarRole.TERM),
            operand=ctx.build_body(site.call_args()[0], SugarRole.TERM),
        )
        if sugar is None:
            raise TypeError("AddSugar claim built a non-add call")
        return sugar

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
            operation=AddOperation(operand=operand, owner="AddSugar", blame=self.blame),
            ctx=ctx,
        )


from sugar_lift_py_tests.sugar.sugar_base import registered_claims as _rc

ADD_CLAIM = next(c for c in _rc() if c.name == "AddSugar")


def _is_add_call(site) -> bool:
    return (
        site.observed == "Call"
        and site.call_is_method_call()
        and site.call_target_name() == "add"
        and site.call_arg_count() == 1
    )
