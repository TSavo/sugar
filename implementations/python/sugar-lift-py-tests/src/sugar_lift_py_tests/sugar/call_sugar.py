from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.factory_audit_row import FactoryAuditRow
from sugar_lift_py_tests.factory.factory_gap import FactoryGap
from sugar_lift_py_tests.factory.factory_gap_info import FactoryGapInfo
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class RefuseStrategy:
    """Nothing resolves this call -- emit a clean, NAMED refusal (a FactoryGap).

    A refusal is sound: it is a checkpoint that says exactly what is missing (a local
    body, an imported `.proof`, or a sugar), never a side door and never a fake value.
    The gap is built at `CallSugar.build` time (where the fragment's blame lives) and
    raised on reduce -- so a call the factory can't yet account for fails LOUD, by name,
    instead of being silently lifted to nothing.
    """

    info: FactoryGapInfo

    def emit(self, sugar: "CallSugar", ctx) -> Outcome:
        audit = FactoryAuditRow(
            role="term",
            status="refused",
            observed=self.info.observed,
            blame=self.info.blame,
            selected="CallSugar",
            candidates=["CallSugar"],
            message=self.info.message,
        )
        raise FactoryGap(self.info, audit)


@dataclass(frozen=True)
class CallSugar(Sugar, role=SugarRole.TERM):
    """A call -- DUMB.

    `owns` is shape only (is this a Call?). `build` is the ONLY place context decides
    anything: it picks the strategy. `desugar` is one line: delegate to the strategy.
    The strategy does the work; the sugar holds nothing but the strategy. Every Call-
    owning sugar (Add/Ord/Map/ToList/BuilderCtor) declares `comes_before=("CallSugar",)`,
    so CallSugar is the FALLBACK that catches every call no specific sugar claimed.
    """

    strategy: object

    @classmethod
    def owns(cls, fragment) -> bool:
        return fragment.observed == "Call"

    @classmethod
    def build(cls, fragment, ctx) -> "CallSugar":
        # Step 2: only the refusal path. BridgeStrategy (in-body EUF bridge + dig enqueue)
        # and AssertionFactStrategy (the sworn fact) land in Steps 3-4 -- and they will be
        # REAL, not NotImplementedError stubs. Until then every call routes to a clean,
        # named refusal rather than a silent lift or a side-door constructor.
        target = fragment.call_target_name()
        info = FactoryGapInfo(
            owner="python.factory",
            blame=fragment.blame,
            observed="Call",
            requested="term",
            fix=f"resolve call to '{target}' (local body, imported .proof, or a sugar)",
        )
        return cls(strategy=RefuseStrategy(info))

    def desugar(self, ctx) -> Outcome:
        return self.strategy.emit(self, ctx)
