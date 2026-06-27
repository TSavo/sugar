from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.floor import ArrayLiteral, BuilderState
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class BuilderCtorSugar:
    node: ast.Call
    items: SugarBody
    blame: str

    @classmethod
    def from_site(cls, site, ctx) -> "BuilderCtorSugar | None":
        if not _is_builder_call(site.node):
            return None
        if len(site.node.args) != 1:
            return None
        return cls(
            node=site.node,
            items=ctx.build_body(site.node.args[0], SugarRole.TERM),
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


def _build(site, ctx) -> BuilderCtorSugar:
    sugar = BuilderCtorSugar.from_site(site, ctx)
    if sugar is None:
        raise TypeError("BuilderCtorSugar claim built a non-builder call")
    return sugar


BUILDER_CTOR_CLAIM = SugarClaim(
    name="BuilderCtorSugar",
    role=SugarRole.TERM,
    owns=_owns,
    build=_build,
)
