from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.factory.sugar_constructors import build_return_sugar
from sugar_lift_py_tests.floor import ReturnValue
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ReturnSugar:
    """A `return <value>` statement. Its child is the value expression -- built by
    the factory at the TERM role and handed in. Desugaring reduces that value and
    wraps it in a ReturnValue: the path's returned outcome."""

    value: SugarBody

    def desugar(self, ctx) -> Outcome:
        returned = complete_value(self.value.reduce(ctx), owner="return value")
        return Complete(ReturnValue(returned))


def _owns(site) -> bool:
    return isinstance(site.node, ast.Return)


RETURN_CLAIM = SugarClaim(
    name="ReturnSugar",
    role=SugarRole.STATEMENT,
    owns=_owns,
    build=build_return_sugar,
)
