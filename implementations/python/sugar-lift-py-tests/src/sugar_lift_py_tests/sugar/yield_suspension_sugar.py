from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class YieldSuspensionSugar(Sugar):
    """A source yield boundary; only GeneratorConstructionV1 may consume it."""

    value: Sugar | None
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="YieldEffect",
            reason="yield is consumed only by GeneratorConstructionV1",
        )

    def desugar(self, ctx=None):
        del ctx
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            owner="YieldSuspensionSugar.desugar",
            observed="yield suspension reached eager expression reduction",
            requested="GeneratorConstructionV1 transition consumption",
            fix="keep generator bodies suspended and resume through their instance coordinate",
        )
