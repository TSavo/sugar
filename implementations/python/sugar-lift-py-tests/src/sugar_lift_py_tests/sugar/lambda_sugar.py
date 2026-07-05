from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.floor import LambdaCallable
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
from sugar_lift_py_tests.sugar.array_literal_sugar import _map_method_witness
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class LambdaSugar(Sugar, role=SugarRole.TERM):
    parameter: str
    body: SugarBody | None
    blame: str
    runtime_reason: str | None = None
    template_operand_names = ()

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Lambda"

    @classmethod
    def witnesses(cls) -> SugarWitnessPair:
        return _map_method_witness(
            name="lambda_map_method",
            owner_sugar=cls.__name__,
        )

    @classmethod
    def build(cls, site, ctx) -> "LambdaSugar":
        if site.observed != "Lambda":
            raise TypeError("LambdaSugar claim built a non-lambda")
        params = site.lambda_params()
        body = (
            ctx.build_body(site.lambda_body(), SugarRole.TERM)
            if len(params) == 1
            else None
        )
        sugar = cls.from_site(site, body=body)
        if sugar is None:
            raise TypeError("LambdaSugar claim built a non-lambda")
        return sugar

    @classmethod
    def from_site(cls, site, *, body: SugarBody | None) -> "LambdaSugar | None":
        if site.observed != "Lambda":
            return None
        params = site.lambda_params()
        if len(params) != 1:
            return cls(
                parameter="",
                body=None,
                blame=site.blame,
                runtime_reason=(
                    f"lambda has {len(params)} parameters; only one-parameter "
                    "lambda bodies have a current callable floor"
                ),
            )
        if body is None:
            raise TypeError("LambdaSugar one-parameter lambda requires a body")
        return cls(
            parameter=params[0],
            body=body,
            blame=site.blame,
        )

    def _build(self, _ctx) -> Outcome:
        if self.runtime_reason is not None:
            return Incomplete(
                RuntimeEffect(
                    "lambda runtime boundary: "
                    f"{self.runtime_reason}. Python binds lambda arguments at "
                    "call time; keep as typed red until callable floors own this "
                    f"signature shape. blame={self.blame}"
                )
            )
        if self.body is None:
            raise TypeError("LambdaSugar callable plan must carry a body")
        return Complete(LambdaCallable(parameter=self.parameter, body=self.body))


from sugar_lift_py_tests.sugar.sugar_base import registered_claims as _rc  # noqa: E402

LAMBDA_CLAIM = next(c for c in _rc() if c.name == "LambdaSugar")
