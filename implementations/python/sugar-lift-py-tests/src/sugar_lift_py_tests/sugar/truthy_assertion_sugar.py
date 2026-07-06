from __future__ import annotations

from dataclasses import dataclass
from typing import Never, NoReturn

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.floor import BoolValue, ObjectValue
from sugar_lift_py_tests.ir import Formula, Term, atomic, bool_const, eq
from sugar_lift_py_tests.outcome import Incomplete, complete_value
from sugar_lift_py_tests.sugar.object_truthiness import object_truth_formula
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.symbolic_term import can_symbolic_term, symbolic_term
from sugar_lift_py_tests.sugar.witness_examples import truthy_assertion_witness
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class TruthProjectionDegradation:
    crime: str
    owner: str
    shape: str
    replacement: str
    audit_reason: str

    @property
    def message(self) -> str:
        return (
            f"{self.crime}: owner={self.owner} shape={self.shape} "
            f"replacement={self.replacement}"
        )


@dataclass(frozen=True)
class Projected:
    body: SugarBody

    def __post_init__(self) -> None:
        if not isinstance(self.body, SugarBody):
            raise TypeError(
                "Projected body must be SugarBody: owner=TruthyAssertionSugar "
                f"shape={type(self.body).__name__} replacement=ctx.build_body(..., "
                "SugarRole.TERM)"
            )


@dataclass(frozen=True)
class Degraded:
    reason: TruthProjectionDegradation

    def __post_init__(self) -> None:
        if not isinstance(self.reason, TruthProjectionDegradation):
            raise TypeError(
                "Degraded reason must be TruthProjectionDegradation: "
                "owner=TruthyAssertionSugar "
                f"shape={type(self.reason).__name__} "
                "replacement=TruthProjectionDegradation(crime, owner, shape, "
                "replacement, audit_reason)"
            )


TruthProjection = Projected | Degraded


@dataclass(frozen=True)
class TruthyAssertionSugar(Sugar, role=SugarRole.ASSERTION):
    source_role = "python.truthy-assertion-sugar"

    term: Term
    projection: TruthProjection
    blame: str

    @property
    def term_body(self) -> SugarBody | None:
        projection = _require_truth_projection(self.projection)
        if isinstance(projection, Projected):
            return projection.body
        if isinstance(projection, Degraded):
            return None
        return _unhandled_truth_projection(projection)

    @property
    def degraded_reason(self) -> str | None:
        projection = _require_truth_projection(self.projection)
        if isinstance(projection, Projected):
            return None
        if isinstance(projection, Degraded):
            return projection.reason.audit_reason
        return _unhandled_truth_projection(projection)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assert":
            return False
        test = site.assert_test()
        if test.observed in {"Call", "Compare", "UnaryOp"}:
            return False
        return can_symbolic_term(test)

    @classmethod
    def build(cls, site, ctx) -> "TruthyAssertionSugar":
        projection = _require_truth_projection(_projectable_truth_body(site, ctx))
        return cls(
            term=symbolic_term(
                site.assert_test(),
                owner="truthy assertion",
                import_aliases=ctx.import_aliases or {},
                from_imports=ctx.from_imports or {},
                name_resolver=ctx.name_resolver or {},
                external_bridge_sink=ctx.external_bridge_sink,
            ),
            projection=projection,
            blame=site.blame,
        )

    @classmethod
    def witnesses(cls):
        return truthy_assertion_witness()

    def assertion_formula(self) -> Formula:
        return atomic("py.truthy", [self.term])

    def _build(self, ctx):
        projection = _require_truth_projection(self.projection)
        if isinstance(projection, Degraded):
            return self.assertion_formula()
        if not isinstance(projection, Projected):
            return _unhandled_truth_projection(projection)
        outcome = projection.body.reduce(ctx)
        if isinstance(outcome, Incomplete):
            return outcome
        value = complete_value(outcome, owner="TruthyAssertionSugar term")
        if isinstance(value, BoolValue):
            return eq(value.to_term(owner="TruthyAssertionSugar"), bool_const(True))
        if not isinstance(value, ObjectValue):
            return self.assertion_formula()
        return object_truth_formula(
            value,
            ctx,
            owner="TruthyAssertionSugar",
            blame=self.blame,
        )


def _projectable_truth_body(site, ctx) -> TruthProjection:
    test = site.assert_test()
    if _contains_nested_compare(test):
        return Degraded(_truthy_symbolic_reason(test))
    try:
        return Projected(ctx.build_body(test, SugarRole.TERM))
    except FactoryGap as gap:
        return Degraded(_truthy_degraded_reason(gap))
    except TypeError as exc:
        return Degraded(_truthy_type_degraded_reason(exc))


def _contains_nested_compare(site) -> bool:
    if site.observed == "Compare":
        return True
    return any(_contains_nested_compare(child) for child in site.terms())


def _truthy_symbolic_reason(site) -> TruthProjectionDegradation:
    return TruthProjectionDegradation(
        crime="truthy projection stays symbolic for nested value-position comparison",
        owner="TruthyAssertionSugar",
        shape=f"symbolic-term({site.observed})",
        replacement="emit the canonical py.truthy symbolic assertion fact",
        audit_reason="symbolic truthy assertion over nested comparison",
    )


def _truthy_degraded_reason(gap: FactoryGap) -> TruthProjectionDegradation:
    owner = str(gap.info.get("owner", "unknown"))
    observed = str(gap.info.get("observed", "unknown"))
    requested = str(gap.info.get("requested", "truthy term body"))
    replacement = str(gap.info.get("fix", str(gap)))
    return TruthProjectionDegradation(
        crime="truthy projection degraded before term-body construction",
        owner="TruthyAssertionSugar",
        shape=f"FactoryGap(owner={owner}, observed={observed}, requested={requested})",
        replacement=replacement,
        audit_reason=replacement,
    )


def _truthy_type_degraded_reason(exc: TypeError) -> TruthProjectionDegradation:
    audit_reason = f"pre-build type error: {exc}"
    return TruthProjectionDegradation(
        crime="truthy projection degraded by pre-build type error",
        owner="TruthyAssertionSugar",
        shape=f"TypeError({exc})",
        replacement=(
            "fix the term-body SugarRole.TERM builder or let FactoryGap name the gap"
        ),
        audit_reason=audit_reason,
    )


def _require_truth_projection(projection: object) -> TruthProjection:
    if isinstance(projection, (Projected, Degraded)):
        return projection
    raise TypeError(
        "truthy projection result must be Projected | Degraded: "
        f"owner=TruthyAssertionSugar shape={type(projection).__name__} "
        "replacement=return Projected(body) or Degraded(reason)"
    )


def _unhandled_truth_projection(projection: Never) -> NoReturn:
    raise TypeError(f"unhandled truth projection arm: {type(projection).__name__}")
