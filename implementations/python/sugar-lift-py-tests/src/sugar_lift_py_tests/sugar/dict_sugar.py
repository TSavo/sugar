from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import DictLiteralValue
from sugar_lift_py_tests.ir import Term, ctor
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import inert_statement_return_witness
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing, SugarWitnessPair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class DictEntryBody:
    key: SugarBody | None
    value: SugarBody


@dataclass(frozen=True)
class DictSugar(Sugar, role=SugarRole.TERM):
    entries: tuple[DictEntryBody, ...]

    def __post_init__(self) -> None:
        if not all(
            (entry.key is None or isinstance(entry.key, SugarBody))
            and isinstance(entry.value, SugarBody)
            for entry in self.entries
        ):
            raise TypeError("DictSugar entries must be factory-built bodies")

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Dict"

    @classmethod
    def witnesses(cls) -> tuple[NotVerdictBearing, SugarWitnessPair]:
        return (
            NotVerdictBearing(
                sugar_name=cls.__name__,
                floor_name="DictLiteralValue",
                reason=(
                    "dict literals are structural term support; the production "
                    "solver path lacks dictionary key/value-pair equality"
                ),
            ),
            inert_statement_return_witness(
                name="dict_support_return",
                owner_sugar=cls.__name__,
                statement="{1: z}",
            ),
        )

    @classmethod
    def build(cls, site, ctx) -> "DictSugar":
        if site.observed != "Dict":
            raise TypeError("DictSugar claim built a non-dict literal")
        return cls(
            entries=tuple(
                DictEntryBody(
                    key=None if key is None else ctx.build_body(key, SugarRole.TERM),
                    value=ctx.build_body(value, SugarRole.TERM),
                )
                for key, value in site.dict_entries()
            )
        )

    def _build(self, ctx) -> Outcome:
        entries: list[tuple[Term, Term]] = []
        for entry in self.entries:
            if entry.key is None:
                key_term = ctor("None", [])
            else:
                key_outcome = entry.key.reduce(ctx)
                if isinstance(key_outcome, Incomplete):
                    return key_outcome
                key_term = floor_to_term(
                    complete_value(key_outcome, owner="DictSugar key"),
                    owner="DictSugar key",
                )
            value_outcome = entry.value.reduce(ctx)
            if isinstance(value_outcome, Incomplete):
                return value_outcome
            value_term = floor_to_term(
                complete_value(value_outcome, owner="DictSugar value"),
                owner="DictSugar value",
            )
            entries.append((key_term, value_term))
        return Complete(DictLiteralValue(tuple(entries)))
