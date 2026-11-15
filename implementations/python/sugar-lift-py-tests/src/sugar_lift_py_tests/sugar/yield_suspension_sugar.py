from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class YieldSuspensionSugar(Sugar):
    """A source yield boundary.  No reduction consumes it: a generator call is
    its definition's coordinate and edge, joined at prove (#7757 step 6), and
    what iterating it yields is undecided and owed."""

    value: Sugar | None
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="YieldEffect",
            reason="yield is consumed by no reduction (#7757 step 6)",
        )

    def desugar(self, ctx=None):
        del ctx
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            blame=self.site,
            owner="YieldSuspensionSugar.desugar",
            observed="yield suspension reached eager expression reduction",
            requested="the generator call as its coordinate and edge, joined at prove",
            fix="keep generator bodies suspended and resume through their instance coordinate",
        )
