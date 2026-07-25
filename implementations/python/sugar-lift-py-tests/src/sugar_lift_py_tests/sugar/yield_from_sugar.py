"""`yield from <iterable>` — delegated generator suspension."""

from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class YieldFromSugar(Sugar):
    """A source ``yield from`` boundary; only GeneratorConstructionV1 may consume it.

    Same discipline as YieldSuspensionSugar: eager expression reduction must not
    silently invent generator protocol behavior.
    """

    value: object  # the iterable's sugar
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="YieldFromEffect",
            reason="yield from is consumed only by GeneratorConstructionV1",
        )

    def desugar(self, ctx=None):
        del ctx
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            owner="YieldFromSugar.desugar",
            observed="yield from suspension reached eager expression reduction",
            requested="GeneratorConstructionV1 delegated-iteration consumption",
            fix=(
                "keep generator bodies suspended and resume yield-from through "
                "the generator instance coordinate"
            ),
        )
