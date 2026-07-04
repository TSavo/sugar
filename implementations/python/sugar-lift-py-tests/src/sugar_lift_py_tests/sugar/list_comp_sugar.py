from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.floor import (
    ArrayLiteral,
    BoolValue,
    FloorValue,
    ObjectValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair, WitnessSource
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.temporal import bind_temporal


@dataclass(frozen=True)
class _FiniteListComp:
    target_name: str
    iterable: SugarBody
    element: SugarBody
    guards: tuple[SugarBody, ...]


@dataclass(frozen=True)
class _RuntimeListComp:
    reason: str


ListCompPlan = _FiniteListComp | _RuntimeListComp


@dataclass(frozen=True)
class ListCompSugar(Sugar, role=SugarRole.TERM):
    plan: ListCompPlan
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "ListComp"

    @classmethod
    def witnesses(cls) -> SugarWitnessPair:
        return SugarWitnessPair(
            name="list_comp_literal_domain_return",
            owner_sugar=cls.__name__,
            family="python-list-comprehension",
            truthful=WitnessSource(
                source=(
                    "def A():\n"
                    "    return len([x + 1 for x in [1, 2, 3]])\n"
                    "\n"
                    "def test_a():\n"
                    "    assert A() == 3\n"
                ),
                expected="sat",
            ),
            lying=WitnessSource(
                source=(
                    "def A():\n"
                    "    return len([x + 1 for x in [1, 2, 3]])\n"
                    "\n"
                    "def test_a():\n"
                    "    assert A() == 2\n"
                ),
                expected="unsat",
            ),
        )

    @classmethod
    def build(cls, site, ctx) -> "ListCompSugar":
        if not cls.owns(site):
            raise TypeError("ListCompSugar claim built a non-ListComp")
        generators = site.listcomp_generators()
        if len(generators) != 1:
            return cls(
                plan=_RuntimeListComp(
                    f"list comprehension has {len(generators)} generators; "
                    "nested iteration is runtime control flow in this tranche"
                ),
                blame=site.blame,
            )
        generator = generators[0]
        if generator.comprehension_is_async():
            return cls(
                plan=_RuntimeListComp(
                    "async list comprehension requires runtime async iteration"
                ),
                blame=site.blame,
            )
        target = generator.comprehension_target()
        if target.observed != "Name":
            return cls(
                plan=_RuntimeListComp(
                    f"list comprehension target `{target.observed}` binds by "
                    "runtime unpacking; use a single-name target or a later "
                    "unpacking-aware recognizer"
                ),
                blame=site.blame,
            )
        iterable = generator.comprehension_iter()
        if iterable.observed not in {"List", "Tuple"}:
            return cls(
                plan=_RuntimeListComp(
                    f"runtime iterable `{iterable.observed}`; "
                    "use a literal finite domain for reduction, or keep this as "
                    "a typed red effect"
                ),
                blame=site.blame,
            )
        return cls(
            plan=_FiniteListComp(
                target_name=target.name_id(),
                iterable=ctx.build_body(iterable, SugarRole.TERM),
                element=ctx.build_body(site.listcomp_element(), SugarRole.TERM),
                guards=tuple(
                    ctx.build_body(guard, SugarRole.TERM)
                    for guard in generator.comprehension_ifs()
                ),
            ),
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        if isinstance(self.plan, _RuntimeListComp):
            return _runtime_iterable_effect(self.blame, self.plan.reason)
        iterable_outcome = self.plan.iterable.reduce(ctx)
        if isinstance(iterable_outcome, Incomplete):
            return iterable_outcome
        iterable = complete_value(iterable_outcome, owner="ListCompSugar iterable")
        items = _finite_items(iterable)
        if items is None:
            return _runtime_iterable_effect(
                self.blame,
                f"list comprehension iterable reduced to {type(iterable).__name__}, "
                "not a finite literal sequence",
            )
        result: list[FloorValue] = []
        for item in items:
            item_ctx = bind_temporal(
                ctx,
                self.plan.target_name,
                item,
                owner="ListCompSugar",
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
            result.append(complete_value(element_outcome, owner="ListCompSugar elt"))
        return Complete(ArrayLiteral(tuple(_array_element(item) for item in result)))


def _finite_items(value: FloorValue) -> tuple[FloorValue, ...] | None:
    if isinstance(value, ArrayLiteral):
        return value.items
    if isinstance(value, TupleLiteralValue):
        return value.items
    return None


def _guards_pass(guards: tuple[SugarBody, ...], ctx, blame: str) -> bool | Incomplete:
    for guard in guards:
        outcome = guard.reduce(ctx)
        if isinstance(outcome, Incomplete):
            return outcome
        value = complete_value(outcome, owner="ListCompSugar guard")
        if not isinstance(value, BoolValue):
            return _runtime_iterable_effect(
                blame,
                f"list comprehension guard reduced to {type(value).__name__}, "
                "guard truthiness for non-bool floors is runtime here; "
                "narrower truthiness dispatch may own this later",
            )
        if not value.value:
            return False
    return True


def _array_element(
    value: FloorValue,
) -> TermValue | ObjectValue | SymbolicValue | ArrayLiteral | TupleLiteralValue:
    if isinstance(value, (TermValue, ObjectValue, SymbolicValue, ArrayLiteral)):
        return value
    if isinstance(value, TupleLiteralValue):
        return value
    raise TypeError(
        "ListCompSugar result element must be a list-compatible floor value, "
        f"got {type(value).__name__}"
    )


def _runtime_iterable_effect(blame: str, reason: str) -> Incomplete:
    return Incomplete(
        RuntimeEffect(
            "list comprehension runtime boundary: "
            f"{reason}. Python evaluates the iterable/guards at runtime; keep "
            "as typed red until a narrower vendor-cited reduction owns the "
            f"shape. blame={blame}"
        )
    )
