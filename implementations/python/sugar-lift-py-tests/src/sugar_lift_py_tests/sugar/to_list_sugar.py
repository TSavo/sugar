from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.operations import MaterializeOperation, perform_operation
from sugar_lift_py_tests.outcome import Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ToListSugar:
    receiver: SugarBody
    blame: str

    @classmethod
    def from_site(cls, site, ctx) -> "ToListSugar | None":
        if not _is_to_list_call(site.node):
            return None
        assert isinstance(site.node, ast.Call)
        assert isinstance(site.node.func, ast.Attribute)
        if site.node.args:
            return None
        return cls(
            receiver=ctx.build_body(site.node.func.value, SugarRole.TERM),
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


def _is_to_list_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "to_list"
    )


def _owns(site) -> bool:
    return _is_to_list_call(site.node)


def _build(site, ctx) -> ToListSugar:
    sugar = ToListSugar.from_site(site, ctx)
    if sugar is None:
        raise TypeError("ToListSugar claim built a non-to-list call")
    return sugar


TO_LIST_CLAIM = SugarClaim(
    name="ToListSugar",
    role=SugarRole.TERM,
    owns=_owns,
    build=_build,
)
