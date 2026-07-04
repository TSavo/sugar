from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.floor import BoolValue, FloorValue, SetLiteralValue
from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
from sugar_lift_py_tests.ir import Term
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.temporal import bind_temporal


@dataclass(frozen=True)
class _FiniteSetComp:
    target_name: str
    iterable: SugarBody
    element: SugarBody
    guards: tuple[SugarBody, ...]


@dataclass(frozen=True)
class _RuntimeSetComp:
    reason: str


SetCompPlan = _FiniteSetComp | _RuntimeSetComp


@dataclass(frozen=True)
class SetCompSugar(Sugar, role=SugarRole.TERM):
    plan: SetCompPlan
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "SetComp"

    @classmethod
    def witnesses(cls) -> NotVerdictBearing:
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="SetLiteralValue",
            reason=(
                "set comprehensions reduce to structural set support; "
                "set-constructor equality is not currently a standalone "
                "solver verdict"
            ),
        )

    @classmethod
    def build(cls, site, ctx) -> "SetCompSugar":
        if not cls.owns(site):
            raise TypeError("SetCompSugar claim built a non-SetComp")
        generators = site.setcomp_generators()
        if len(generators) != 1:
            return cls(
                plan=_RuntimeSetComp(
                    f"set comprehension has {len(generators)} generators; "
                    "nested iteration is runtime control flow in this tranche"
                ),
                blame=site.blame,
            )
        generator = generators[0]
        runtime_reason = _runtime_generator_reason(generator)
        if runtime_reason is not None:
            return cls(plan=_RuntimeSetComp(runtime_reason), blame=site.blame)
        return cls(
            plan=_FiniteSetComp(
                target_name=generator.comprehension_target().name_id(),
                iterable=ctx.build_body(generator.comprehension_iter(), SugarRole.TERM),
                element=ctx.build_body(site.setcomp_element(), SugarRole.TERM),
                guards=tuple(
                    ctx.build_body(guard, SugarRole.TERM)
                    for guard in generator.comprehension_ifs()
                ),
            ),
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        if isinstance(self.plan, _RuntimeSetComp):
            return _runtime_iterable_effect(self.blame, self.plan.reason)
        iterable_outcome = self.plan.iterable.reduce(ctx)
        if isinstance(iterable_outcome, Incomplete):
            return iterable_outcome
        iterable = complete_value(iterable_outcome, owner="SetCompSugar iterable")
        items = _finite_items(iterable)
        if items is None:
            return _runtime_iterable_effect(
                self.blame,
                f"set comprehension iterable reduced to {type(iterable).__name__}, "
                "not a finite literal sequence",
            )
        result: list[Term] = []
        for item in items:
            item_ctx = bind_temporal(
                ctx,
                self.plan.target_name,
                item,
                owner="SetCompSugar",
                blame=self.blame,
            )
            guard_state = _guards_pass(self.plan.guards, item_ctx, self.blame)
            if isinstance(guard_state, Incomplete):
                return guard_state
            if not guard_state:
                continue
            element_outcome = self.plan.element.reduce(item_ctx)
            if isinstance(element_outcome, Incomplete):
                return element_outcome
            term = floor_to_term(
                complete_value(element_outcome, owner="SetCompSugar elt"),
                owner="SetCompSugar elt",
            )
            if term not in result:
                result.append(term)
        return Complete(SetLiteralValue(tuple(result)))


def _runtime_generator_reason(generator) -> str | None:
    if generator.comprehension_is_async():
        return "async set comprehension requires runtime async iteration"
    target = generator.comprehension_target()
    if target.observed != "Name":
        return (
            f"set comprehension target `{target.observed}` binds by runtime "
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
    guards: tuple[SugarBody, ...], ctx, blame: str
) -> bool | Incomplete:
    for guard in guards:
        outcome = guard.reduce(ctx)
        if isinstance(outcome, Incomplete):
            return outcome
        value = complete_value(outcome, owner="SetCompSugar guard")
        if not isinstance(value, BoolValue):
            return _runtime_iterable_effect(
                blame,
                f"set comprehension guard reduced to {type(value).__name__}, "
                "guard truthiness for non-bool floors is runtime here; "
                "narrower truthiness dispatch may own this later",
            )
        if not value.value:
            return False
    return True


def _runtime_iterable_effect(blame: str, reason: str) -> Incomplete:
    return Incomplete(
        RuntimeEffect(
            "set comprehension runtime boundary: "
            f"{reason}. Python evaluates the iterable/guards at runtime; keep "
            "as typed red until a narrower vendor-cited reduction owns the "
            f"shape. blame={blame}"
        )
    )
