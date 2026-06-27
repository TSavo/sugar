from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.factory.sugar_constructors import build_builder_ctor_sugar
from sugar_lift_py_tests.floor import ArrayLiteral, BuilderState
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class BuilderCtorSugar:
    items: SugarBody
    blame: str

    @classmethod
    def from_site(cls, site, *, items: SugarBody) -> "BuilderCtorSugar | None":
        if not _is_builder_call(site.node):
            return None
        if len(site.node.args) != 1:
            return None
        return cls(
            items=items,
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        value = complete_value(self.items.reduce(ctx), owner="BuilderCtorSugar")
        if not isinstance(value, ArrayLiteral):
            raise TypeError("BuilderCtorSugar argument must reduce to ArrayLiteral")
        return Complete(BuilderState(value))


def _is_builder_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Builder"
    )


def _owns(site) -> bool:
    return _is_builder_call(site.node)


BUILDER_CTOR_CLAIM = SugarClaim(
    name="BuilderCtorSugar",
    role=SugarRole.TERM,
    owns=_owns,
    build=build_builder_ctor_sugar,
)
