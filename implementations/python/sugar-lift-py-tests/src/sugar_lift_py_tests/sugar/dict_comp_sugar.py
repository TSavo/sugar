from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import (
    FactoryAuditRow,
    FactoryGap,
    FactoryGapInfo,
    GapKind,
    GapLocus,
)
from sugar_lift_py_tests.floor import BoolValue, DictLiteralValue, FloorValue
from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
from sugar_lift_py_tests.ir import Term
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.temporal import bind_temporal


@dataclass(frozen=True)
class _FiniteDictComp:
    target_name: str
    iterable: SugarBody
    key: SugarBody
    value: SugarBody
    guards: tuple[SugarBody, ...]


@dataclass(frozen=True)
class _RuntimeDictComp:
    reason: str


DictCompPlan = _FiniteDictComp | _RuntimeDictComp


@dataclass(frozen=True)
class DictCompSugar(Sugar, role=SugarRole.TERM):
    plan: DictCompPlan
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "DictComp"

    @classmethod
    def witnesses(cls) -> NotVerdictBearing:
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="DictLiteralValue",
            reason=(
                "dict comprehensions reduce to structural dict support; "
                "dict-constructor equality is not currently a standalone "
                "solver verdict"
            ),
        )

    @classmethod
    def build(cls, site, ctx) -> "DictCompSugar":
        if not cls.owns(site):
            raise TypeError("DictCompSugar claim built a non-DictComp")
        generators = site.dictcomp_generators()
        if len(generators) != 1:
            return cls(
                plan=_RuntimeDictComp(
                    f"dict comprehension has {len(generators)} generators; "
                    "nested iteration is runtime control flow in this tranche"
                ),
                blame=site.blame,
            )
        generator = generators[0]
        runtime_reason = _runtime_generator_reason(generator, "dict")
        if runtime_reason is not None:
            return cls(plan=_RuntimeDictComp(runtime_reason), blame=site.blame)
        return cls(
            plan=_FiniteDictComp(
                target_name=generator.comprehension_target().name_id(),
                iterable=ctx.build_body(generator.comprehension_iter(), SugarRole.TERM),
                key=ctx.build_body(site.dictcomp_key(), SugarRole.TERM),
                value=ctx.build_body(site.dictcomp_value(), SugarRole.TERM),
                guards=tuple(
                    ctx.build_body(guard, SugarRole.TERM)
                    for guard in generator.comprehension_ifs()
                ),
            ),
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        if isinstance(self.plan, _RuntimeDictComp):
            _runtime_iterable_refusal(self.blame, self.plan.reason)
        iterable_outcome = self.plan.iterable.reduce(ctx)
        if isinstance(iterable_outcome, Incomplete):
            return iterable_outcome
        iterable = complete_value(iterable_outcome, owner="DictCompSugar iterable")
        items = _finite_items(iterable)
        if items is None:
            _runtime_iterable_refusal(
                self.blame,
                f"dict comprehension iterable reduced to {type(iterable).__name__}, "
                "not a finite literal sequence",
            )
        entries: list[tuple[Term, Term]] = []
        for item in items:
            item_ctx = bind_temporal(
                ctx,
                self.plan.target_name,
                item,
                owner="DictCompSugar",
                blame=self.blame,
            )
            guard_state = _guards_pass(self.plan.guards, item_ctx, self.blame, "dict")
            if isinstance(guard_state, Incomplete):
                return guard_state
            if not guard_state:
                continue
            key_outcome = self.plan.key.reduce(item_ctx)
            if isinstance(key_outcome, Incomplete):
                return key_outcome
            value_outcome = self.plan.value.reduce(item_ctx)
            if isinstance(value_outcome, Incomplete):
                return value_outcome
            key_term = floor_to_term(
                complete_value(key_outcome, owner="DictCompSugar key"),
                owner="DictCompSugar key",
            )
            value_term = floor_to_term(
                complete_value(value_outcome, owner="DictCompSugar value"),
                owner="DictCompSugar value",
            )
            _dict_set(entries, key_term, value_term)
        return Complete(DictLiteralValue(tuple(entries)))


def _dict_set(entries: list[tuple[Term, Term]], key: Term, value: Term) -> None:
    for index, (existing_key, _) in enumerate(entries):
        if existing_key == key:
            entries[index] = (key, value)
            return
    entries.append((key, value))


def _runtime_generator_reason(generator, label: str) -> str | None:
    if generator.comprehension_is_async():
        return f"async {label} comprehension requires runtime async iteration"
    target = generator.comprehension_target()
    if target.observed != "Name":
        return (
            f"{label} comprehension target `{target.observed}` binds by runtime "
            "unpacking; use a single-name target or a later unpacking-aware recognizer"
        )
    iterable = generator.comprehension_iter()
    if iterable.observed not in {"List", "Tuple"}:
        return (
            f"runtime iterable `{iterable.observed}`; use a literal finite domain "
            "for reduction, or keep this as a typed red effect"
        )
    return None


def _finite_items(value: FloorValue) -> tuple[FloorValue, ...] | None:
    from sugar_lift_py_tests.floor import ArrayLiteral

    if isinstance(value, ArrayLiteral):
        return value.items
    if isinstance(value, TupleLiteralValue):
        return value.items
    return None


def _guards_pass(
    guards: tuple[SugarBody, ...], ctx, blame: str, label: str
) -> bool | Incomplete:
    for guard in guards:
        outcome = guard.reduce(ctx)
        if isinstance(outcome, Incomplete):
            return outcome
        value = complete_value(outcome, owner=f"{label.title()}CompSugar guard")
        if not isinstance(value, BoolValue):
            _runtime_iterable_refusal(
                blame,
                f"{label} comprehension guard reduced to {type(value).__name__}, "
                "not BoolValue",
            )
        if not value.value:
            return False
    return True


def _runtime_iterable_refusal(blame: str, reason: str) -> NoReturn:
    message = (
        "dict comprehension runtime iterable: "
        f"{reason}. Python dict comprehensions evaluate the iterable and guards "
        "at runtime; use a literal finite domain for reduction or add a "
        "runtime/effect recognizer for this shape."
    )
    info = FactoryGapInfo(
        owner="DictCompSugar",
        blame=blame,
        observed="DictComp.runtime_iterable",
        requested="literal finite domain",
        fix=message,
        gap_kind=GapKind.SUGAR,
        gap_locus=GapLocus.CONSTRUCTION,
    )
    audit = FactoryAuditRow(
        role="term",
        status="refused",
        observed=info.observed,
        blame=blame,
        selected="DictCompSugar",
        candidates=["DictCompSugar"],
        message=info.message,
    )
    raise FactoryGap(info, audit)
