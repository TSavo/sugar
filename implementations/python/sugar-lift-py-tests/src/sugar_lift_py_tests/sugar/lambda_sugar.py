from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import LambdaCallable
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.array_literal_sugar import _map_method_witness
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class LambdaSugar(Sugar, role=SugarRole.TERM):
    parameter: str
    body: SugarBody
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Lambda" and len(site.lambda_params()) == 1

    @classmethod
    def witnesses(cls) -> SugarWitnessPair:
        return _map_method_witness(
            name="lambda_map_method",
            owner_sugar=cls.__name__,
        )

    @classmethod
    def build(cls, site, ctx) -> "LambdaSugar":
        sugar = cls.from_site(
            site,
            body=ctx.build_body(site.lambda_body(), SugarRole.TERM),
        )
        if sugar is None:
            raise TypeError("LambdaSugar claim built a non-lambda")
        return sugar

    @classmethod
    def from_site(cls, site, *, body: SugarBody) -> "LambdaSugar | None":
        if site.observed != "Lambda":
            return None
        params = site.lambda_params()
        if len(params) != 1:
            return None
        return cls(
            parameter=params[0],
            body=body,
            blame=site.blame,
        )

    def desugar(self, _ctx) -> Outcome:
        return Complete(LambdaCallable(parameter=self.parameter, body=self.body))


from sugar_lift_py_tests.sugar.sugar_base import registered_claims as _rc  # noqa: E402

LAMBDA_CLAIM = next(c for c in _rc() if c.name == "LambdaSugar")
