from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace
from typing import Any

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import (
    SequenceUnpackRuntimeEffect,
    runtime_effect_evidence,
)
from sugar_lift_py_tests.floor import (
    FloorValue,
    ListValue,
    ScopeRebind,
    TupleValue,
)
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import (
    _call_pair,
    typed_red_effect_witness,
)
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class SequenceUnpackBindings(FloorValue):
    bindings: tuple[ScopeRebind, ...]

    def contribution(self):
        return ()

    def extend_scope(self, ctx):
        scoped = ctx
        for binding in self.bindings:
            scoped = binding.extend_scope(scoped)
        return replace(ctx, temporal=scoped.temporal)


@dataclass(frozen=True)
class SequenceUnpackAssignSugar(Sugar, role=SugarRole.STATEMENT):
    """List-target or starred unpack with a concrete-cardinality floor."""

    names: tuple[str, ...]
    star_index: int | None
    value: SugarBody
    site: Any = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assign":
            return False
        targets = site.assign_targets()
        if len(targets) != 1 or targets[0].observed not in {"Tuple", "List"}:
            return False
        target = targets[0]
        elements = (
            target.tuple_elts() if target.observed == "Tuple" else target.list_elts()
        )
        starred = [
            index for index, item in enumerate(elements) if item.observed == "Starred"
        ]
        if target.observed == "Tuple" and not starred:
            return False
        if len(starred) > 1:
            return False
        if not elements or not all(
            item.observed == "Name"
            or (item.observed == "Starred" and item.starred_value().observed == "Name")
            for item in elements
        ):
            return False
        return cls._literal_arity_can_match(site.assign_value(), len(elements), starred)

    @staticmethod
    def _literal_arity_can_match(value, target_count: int, starred: list[int]) -> bool:
        if value.observed not in {"Tuple", "List"}:
            return True
        values = value.tuple_elts() if value.observed == "Tuple" else value.list_elts()
        return (
            len(values) >= target_count - 1 if starred else len(values) == target_count
        )

    @classmethod
    def new(cls, site, ctx) -> "SequenceUnpackAssignSugar":
        target = site.assign_targets()[0]
        elements = (
            target.tuple_elts() if target.observed == "Tuple" else target.list_elts()
        )
        star_index = next(
            (
                index
                for index, item in enumerate(elements)
                if item.observed == "Starred"
            ),
            None,
        )
        names = tuple(
            (
                item.starred_value().name_id()
                if item.observed == "Starred"
                else item.name_id()
            )
            for item in elements
        )
        return cls(
            names,
            star_index,
            ctx.build_body(site.assign_value(), SugarRole.TERM),
            site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A():\n"
            "    [head, *middle, tail] = (1, 2, 3, 4)\n"
            "    return head + middle[0] + middle[1] + tail\n\n"
        )
        return (
            _call_pair(
                name="sequence_unpack_assign_return",
                owner_sugar=cls.__name__,
                truthful=prefix + "def test_a():\n    assert A() == 10\n",
                lying=prefix + "def test_a():\n    assert A() == 9\n",
            ),
            typed_red_effect_witness(
                name="sequence_unpack_runtime_length",
                owner_sugar=cls.__name__,
                source=(
                    "def A(values):\n"
                    "    [head, *middle, tail] = values\n"
                    "    return head\n"
                ),
                effect_class="SequenceUnpackRuntimeEffect",
                reason_needle="runtime-dependent sequence length",
                blame_needle="test_witness.py:2:4",
                wrong_reason_needle="unpack arity mismatch",
            ),
        )

    def desugar(self, ctx: Any = None) -> Outcome:
        return self.value.reduce(ctx).and_then(lambda value: self._finish(value))

    def _finish(self, value) -> Outcome:
        if not isinstance(value, (ListValue, TupleValue)):
            return self._runtime_effect(value, "runtime-dependent sequence length")
        elements = value.elements
        if self.star_index is None:
            if len(elements) != len(self.names):
                return self._arity_panic("unpack arity mismatch")
            values = elements
        else:
            suffix_count = len(self.names) - self.star_index - 1
            minimum = len(self.names) - 1
            if len(elements) < minimum:
                return self._arity_panic("starred unpack arity mismatch")
            suffix = elements[len(elements) - suffix_count :] if suffix_count else ()
            values = (
                *elements[: self.star_index],
                ListValue(
                    elements[
                        self.star_index : (
                            len(elements) - suffix_count if suffix_count else None
                        )
                    ]
                ),
                *suffix,
            )
        return Complete(
            SequenceUnpackBindings(
                tuple(
                    ScopeRebind(name, bound)
                    for name, bound in zip(self.names, values, strict=True)
                )
            )
        )

    def _arity_panic(self, reason: str):
        from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap

        factory_panic_gap(
            owner=type(self).__name__,
            blame=self.site,
            observed=reason,
            requested=SugarRole.STATEMENT.value,
            fix="the concrete sequence arity is decidable and cannot mint a RuntimeEffect",
        )

    def _runtime_effect(self, value, reason) -> Outcome:
        return Incomplete(
            SequenceUnpackRuntimeEffect(
                f"sequence unpack runtime boundary: {reason}; site={self.site}",
                **runtime_effect_evidence("py.sequence_unpack", value, self.site),
            )
        )

    def walk_children(self):
        return (self.value,)
