from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.factory.sugar_constructors import build_lambda_sugar
from sugar_lift_py_tests.floor import LambdaCallable
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class LambdaSugar:
    parameter: str
    body: SugarBody
    blame: str

    @classmethod
    def from_site(cls, site, *, body: SugarBody) -> "LambdaSugar | None":
        if not isinstance(site.node, ast.Lambda):
            return None
        if len(site.node.args.args) != 1:
            return None
        parameter = site.node.args.args[0].arg
        return cls(
            parameter=parameter,
            body=body,
            blame=site.blame,
        )

    def desugar(self, _ctx) -> Outcome:
        return Complete(LambdaCallable(parameter=self.parameter, body=self.body))


def _owns(site) -> bool:
    return isinstance(site.node, ast.Lambda) and len(site.node.args.args) == 1


LAMBDA_CLAIM = SugarClaim(
    name="LambdaSugar",
    role=SugarRole.TERM,
    owns=_owns,
    build=build_lambda_sugar,
)
