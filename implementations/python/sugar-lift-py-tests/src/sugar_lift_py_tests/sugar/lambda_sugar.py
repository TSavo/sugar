"""A narrow expression-bodied lambda callable."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class LambdaSugar(Sugar):
    """Plain positional formals plus one already-constructed body expression."""

    formals: tuple[str, ...]
    body: Sugar
    source_call_frame: object
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        prefix = "def A(v):\n    return (lambda x: x)(v)\n\n"
        return _call_pair(
            name="lambda_identity_call",
            owner_sugar="LambdaSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor import LambdaCallable

        sealed = self.site.seal()
        construction_identity = (
            f"{sealed.source_cid}@{sealed.start}:{sealed.end}#{sealed.cid}"
        )
        return Complete(
            LambdaCallable(
                parameters=self.formals,
                body=self.body,
                construction_identity=construction_identity,
                source_call_frame=self.source_call_frame,
            )
        )
