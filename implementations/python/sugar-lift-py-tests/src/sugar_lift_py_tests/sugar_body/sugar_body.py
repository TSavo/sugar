from __future__ import annotations

from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Generic,
    Protocol,
    TypeAlias,
    TypeVar,
    runtime_checkable,
)

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.factory_audit_row import FactoryAuditRow

if TYPE_CHECKING:
    from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.ir import Formula
    from sugar_lift_py_tests.outcome import Outcome

    ReductionContext: TypeAlias = FactoryBuildContext | ReduceContext | None
    ReductionResult: TypeAlias = Outcome | Formula
    ReductionT_co = TypeVar("ReductionT_co", bound=ReductionResult, covariant=True)
else:
    ReductionContext: TypeAlias = object
    ReductionResult: TypeAlias = object
    ReductionT_co = TypeVar("ReductionT_co", bound=object, covariant=True)


@runtime_checkable
class ReducibleSugar(Protocol[ReductionT_co]):
    def desugar(self, ctx: ReductionContext = None) -> ReductionT_co: ...


@dataclass(frozen=True)
class SugarBody(Generic[ReductionT_co]):
    sugar: ReducibleSugar[ReductionT_co]
    role: SugarRole
    audit_row: FactoryAuditRow | None = None

    def __post_init__(self) -> None:
        # Static typing says self.sugar is always a ReducibleSugar; the runtime
        # guard stays because SugarBody is still constructed from untyped call
        # sites (factory build results assembled from Any-typed edges) where
        # the static type is a promise, not a proof. Boundary law, not dead code.
        if not isinstance(
            self.sugar, ReducibleSugar
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(
                "SugarBody.sugar must implement desugar(ctx=None): "
                f"owner=SugarBody illegal={type(self.sugar).__name__} "
                "replacement=Sugar or ReducibleSugar"
            )

    def reduce(self, ctx: ReductionContext = None) -> ReductionT_co:
        return self.sugar.desugar(ctx)

    def inv_contribution(self):
        # Raw, unreached sugar states nothing.
        return ()

    def post_contribution(self):
        # Raw, unreached sugar posts nothing.
        return ()

    def guarded(self, formula):
        # Raw, unreached sugar stays raw under any guard.
        del formula
        return self

    def mint_contribution(self, name, formals):
        # Raw, unreached sugar mints nothing.
        del name, formals
        return ()

    def edge_contribution(self, source_contract):
        # Raw, unreached sugar projects no call edge.
        del source_contract
        return ()
