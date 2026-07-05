from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.floor import BoolValue, DictLiteralValue, FloorValue
from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
from sugar_lift_py_tests.ir import Term
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import collection_len_return_witness
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing, SugarWitnessPair
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
    def witnesses(cls) -> tuple[NotVerdictBearing, SugarWitnessPair]:
        return (
            NotVerdictBearing(
                sugar_name=cls.__name__,
                floor_name="DictLiteralValue",
                reason=(
                    "dict comprehensions reduce to structural dict support; "
                    "dict-constructor equality is not currently a standalone "
                    "solver verdict"
                ),
            ),
            collection_len_return_witness(
                name="dict_comp_len_return",
                owner_sugar=cls.__name__,
                expression="{x: x for x in [1, 2]}",
                truthful=2,
                lying=3,
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
            return _runtime_iterable_effect(self.blame, self.plan.reason)
        iterable_outcome = self.plan.iterable.reduce(ctx)
        if isinstance(iterable_outcome, Incomplete):
            return iterable_outcome
        iterable = complete_value(iterable_outcome, owner="DictCompSugar iterable")
        items = _finite_items(iterable)
        if items is None:
            return _runtime_iterable_effect(
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
            return _runtime_iterable_effect(
                blame,
                f"{label} comprehension guard reduced to {type(value).__name__}, "
                "guard truthiness for non-bool floors is runtime here; "
                "narrower truthiness dispatch may own this later",
            )
        if not value.value:
            return False
    return True


def _runtime_iterable_effect(blame: str, reason: str) -> Incomplete:
    return Incomplete(
        RuntimeEffect(
            "dict comprehension runtime boundary: "
            f"{reason}. Python evaluates the iterable/guards at runtime; keep "
            "as typed red until a narrower vendor-cited reduction owns the "
            f"shape. blame={blame}"
        )
    )
