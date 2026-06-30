from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.factory.sugar_constructors import build_to_list_sugar
from sugar_lift_py_tests.operations import MaterializeOperation, perform_operation
from sugar_lift_py_tests.outcome import Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ToListSugar:
    receiver: SugarBody
    blame: str

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

    def desugar(self, ctx) -> Outcome:
        receiver = complete_value(self.receiver.reduce(ctx), owner="ToListSugar")
        return perform_operation(
            owner="ToListSugar",
            blame=self.blame,
            receiver=receiver,
            method_name="materialize_with",
            operation=MaterializeOperation(owner="ToListSugar", blame=self.blame),
            ctx=ctx,
        )


def _is_to_list_call(site) -> bool:
    return (
        site.observed == "Call"
        and site.call_is_method_call()
        and site.call_target_name() == "to_list"
    )


def _owns(site) -> bool:
    return _is_to_list_call(site)


TO_LIST_CLAIM = SugarClaim(
    name="ToListSugar",
    role=SugarRole.TERM,
    owns=_owns,
    build=build_to_list_sugar,
)
