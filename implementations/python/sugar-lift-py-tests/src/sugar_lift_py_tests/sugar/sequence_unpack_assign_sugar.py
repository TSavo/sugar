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
from sugar_lift_py_tests.recognition.sequence_unpack import (
    RecognizedSequenceTarget,
    SequenceUnpackRecognizer,
)
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

    targets: tuple[RecognizedSequenceTarget, ...]
    star_index: int | None
    value: SugarBody
    site: Any = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return SequenceUnpackRecognizer.assignment(site) is not None

    @classmethod
    def new(cls, site, ctx) -> "SequenceUnpackAssignSugar":
        recognized = SequenceUnpackRecognizer.assignment(site)
        if recognized is None:
            raise TypeError(
                "SequenceUnpackAssignSugar.new requires a recognized target"
            )
        return cls(
            recognized.targets,
            recognized.star_index,
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
            _call_pair(
                name="nested_sequence_unpack_assign_return",
                owner_sugar=cls.__name__,
                truthful=(
                    "def A():\n"
                    "    ((q_raw, tau), r, *rest) = ((2, 3), 4, 5, 6)\n"
                    "    return q_raw + tau + r + rest[0] + rest[1]\n\n"
                    "def test_a():\n    assert A() == 20\n"
                ),
                lying=(
                    "def A():\n"
                    "    ((q_raw, tau), r, *rest) = ((2, 3), 4, 5, 6)\n"
                    "    return q_raw + tau + r + rest[0] + rest[1]\n\n"
                    "def test_a():\n    assert A() == 19\n"
                ),
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
            if len(elements) != len(self.targets):
                return self._arity_panic("unpack arity mismatch")
            values = elements
        else:
            suffix_count = len(self.targets) - self.star_index - 1
            minimum = len(self.targets) - 1
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
        bindings: list[ScopeRebind] = []
        for target, bound in zip(self.targets, values, strict=True):
            incomplete = self._bind_target(target, bound, bindings)
            if incomplete is not None:
                return incomplete
        return Complete(SequenceUnpackBindings(tuple(bindings)))

    def _bind_target(
        self,
        target: RecognizedSequenceTarget,
        value,
        bindings: list[ScopeRebind],
    ) -> Outcome | None:
        if target.name is not None:
            bindings.append(ScopeRebind(target.name, value))
            return None
        if not isinstance(value, (ListValue, TupleValue)):
            return self._runtime_effect(
                value, "runtime-dependent nested sequence value"
            )
        if len(value.elements) != len(target.children):
            return self._arity_panic("nested unpack arity mismatch")
        for child, bound in zip(target.children, value.elements, strict=True):
            incomplete = self._bind_target(child, bound, bindings)
            if incomplete is not None:
                return incomplete
        return None

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
