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

    def factory_walk_rows(self):
        # Project the audit row this body carries, then recurse through the
        # sugar's children in source order -- carried, projected, no second
        # recognition pass.
        from sugar_lift_py_tests.kit_rpc.factory_walk_row_dto import (
            FactoryWalkCompleteRowDto,
            FactoryWalkRedRowDto,
        )
        from sugar_lift_py_tests.kit_rpc.source_memento_dto import SourceMementoDto
        from sugar_lift_py_tests.kit_rpc.source_span_dto import SourceSpanDto
        from sugar_lift_py_tests.canonicalizer import blake3_512_of

        rows: list = []
        # One row per source STATEMENT (the walk's historical grain, and what
        # the visual renders one line per): term-role children still recurse
        # (their statements nest, e.g. an if's faces) but emit no row of their
        # own -- their statement's row is their line.
        from sugar_lift_py_tests.claim import SugarRole

        # Block is the factory's synthetic suite node, not a source statement:
        # its row would render on its first statement's line, doubling it.
        emit_row = self.role in {SugarRole.STATEMENT, SugarRole.DEFINITION} and (
            self.audit_row is None or self.audit_row.observed != "Block"
        )
        if emit_row and self.audit_row is not None:
            audit = self.audit_row
            site = getattr(self.sugar, "site", None)
            if site is not None:
                memento = site.memento()
                file = site.filename
                line = site.line
            else:
                parts = audit.blame.rsplit(":", 2)
                if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
                    file, line_s, col_s = parts
                    line = int(line_s)
                    col = int(col_s)
                else:
                    file, line, col = audit.blame, 0, 0
                memento = SourceMementoDto(
                    file=file,
                    span=SourceSpanDto(
                        start_line=line,
                        start_col=col,
                        end_line=line,
                        end_col=col,
                    ),
                    source_cid=blake3_512_of(b""),
                )
            if audit.status == "selected":
                rows.append(
                    FactoryWalkCompleteRowDto(
                        file=file,
                        line=line,
                        requested_role=audit.role,
                        ast_kind=audit.observed,
                        selected=audit.selected,
                        status="warranted",
                        output=audit.selected or "selected",
                        source_memento=memento,
                        reason=audit.message,
                        extra={
                            "candidates": list(audit.candidates),
                            "blame": audit.blame,
                        },
                    )
                )
            else:
                rows.append(
                    FactoryWalkRedRowDto(
                        file=file,
                        line=line,
                        requested_role=audit.role,
                        ast_kind=audit.observed,
                        selected=audit.selected,
                        status="unclassified",
                        output=audit.status,
                        source_memento=memento,
                        reason=audit.message or audit.status,
                        extra={
                            "candidates": list(audit.candidates),
                            "blame": audit.blame,
                        },
                    )
                )
        for child in self.sugar.walk_children():
            rows.extend(child.factory_walk_rows())
        return tuple(rows)
