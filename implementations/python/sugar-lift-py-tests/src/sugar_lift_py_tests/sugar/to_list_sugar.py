from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.operations import MaterializeOperation, perform_operation
from sugar_lift_py_tests.outcome import Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import to_list_len_return_witness
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ToListSugar(Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    receiver: SugarBody
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return _is_to_list_call(site)

    @classmethod
    def build(cls, site, ctx) -> "ToListSugar":
        sugar = cls.from_site(
            site,
            receiver=ctx.build_body(site.call_receiver(), SugarRole.TERM),
        )
        if sugar is None:
            raise TypeError("ToListSugar claim built a non-to-list call")
        return sugar

    @classmethod
    def witnesses(cls):
        return to_list_len_return_witness()

    @classmethod
    def from_site(cls, site, *, receiver: SugarBody) -> "ToListSugar | None":
        if not _is_to_list_call(site):
            return None
        if site.call_arg_count() != 0:
            return None
        return cls(
            receiver=receiver,
            blame=site.blame,
        )

    def _build(self, ctx) -> Outcome:
        receiver = complete_value(self.receiver.reduce(ctx), owner="ToListSugar")
        return perform_operation(
            owner="ToListSugar",
            blame=self.blame,
            receiver=receiver,
            operation=MaterializeOperation(owner="ToListSugar", blame=self.blame),
            ctx=ctx,
        )


def _is_to_list_call(site) -> bool:
    return (
        site.observed == "Call"
        and site.call_is_method_call()
        and site.call_target_name() == "to_list"
    )


from sugar_lift_py_tests.sugar.sugar_base import registered_claims as _rc  # noqa: E402

TO_LIST_CLAIM = next(c for c in _rc() if c.name == "ToListSugar")
