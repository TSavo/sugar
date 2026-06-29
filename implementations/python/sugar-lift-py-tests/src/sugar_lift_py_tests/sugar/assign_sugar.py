from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.factory.sugar_constructors import build_assign_sugar
from sugar_lift_py_tests.floor import BindingValue
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AssignSugar:
    """A `name = <value>` statement. Its child is the RHS expression -- built by the
    factory at the TERM role and handed in. Desugaring reduces the RHS and yields a
    BindingValue: a scope effect the enclosing block threads so later statements
    resolve the name."""

    name: str
    value: SugarBody

    def desugar(self, ctx) -> Outcome:
        bound = complete_value(self.value.reduce(ctx), owner="assign value")
        return Complete(BindingValue(self.name, bound))


def _owns(site) -> bool:
    node = site.node
    return (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    )


ASSIGN_CLAIM = SugarClaim(
    name="AssignSugar",
    role=SugarRole.STATEMENT,
    owns=_owns,
    build=build_assign_sugar,
)
