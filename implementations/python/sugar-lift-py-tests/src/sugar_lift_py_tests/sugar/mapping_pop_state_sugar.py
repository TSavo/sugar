from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)


@dataclass(frozen=True)
class MappingPopStateSugar(ConstructedTermSugar):
    """Compute the receiver post-state of ``mapping.pop(key, default)``."""

    receiver: ConstructedTermSugar
    key: ConstructedTermSugar
    default: ConstructedTermSugar
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def __post_init__(self):
        for name in ("receiver", "key", "default"):
            require_constructed_term_sugar(
                getattr(self, name), owner=f"MappingPopStateSugar.{name}"
            )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:mapping-pop-post-state",
            (
                self.occurrence_term(owner=owner),
                self.receiver.to_term(owner=owner),
                self.key.to_term(owner=owner),
                self.default.to_term(owner=owner),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx=None):
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.key.desugar(ctx).and_then(
                lambda key: self.default.desugar(ctx).and_then(
                    lambda _default: self._apply(receiver, key)
                )
            )
        )

    def _apply(self, receiver, key):
        from sugar_lift_py_tests.floor.dict_value import DictValue
        from sugar_lift_py_tests.floor.mapping_object_value import MappingObjectValue
        from sugar_lift_py_tests.floor.set_value import _closed_member_equal
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
        from sugar_lift_py_tests.outcome import Complete

        if not isinstance(receiver, (DictValue, MappingObjectValue)):
            construction_panic_gap(
                owner="MappingPopStateSugar",
                blame=self.site,
                observed=type(receiver).__name__,
                requested="constructed mapping receiver",
                fix="retain pop as typed loud until its receiver floors",
            )

        entries = receiver.mapping_entries()
        decisions = tuple(
            _closed_member_equal(key, candidate) for candidate, _ in entries
        )
        if any(decision is None for decision in decisions):

            construction_panic_gap(
                owner="MappingPopStateSugar",
                blame=self.site,
                observed=(
                    "undecidable mapping key equality: "
                    f"key={type(key).__name__} over {type(receiver).__name__}"
                ),
                requested="one source-decided finite mapping key",
                fix="construct key equality or keep pop typed loud",
            )
        matching = tuple(index for index, decision in enumerate(decisions) if decision)
        if len(matching) > 1:
            construction_panic_gap(
                owner="MappingPopStateSugar",
                blame=self.site,
                observed="duplicate equal keys in constructed mapping",
                requested="one canonical mapping entry per key",
                fix="repair mapping construction before pop",
            )
        if not matching:
            return Complete(receiver)
        index = matching[0]
        return Complete(
            receiver.mapping_with_entries(entries[:index] + entries[index + 1 :])
        )
