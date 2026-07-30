from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)


@dataclass(frozen=True)
class DictSetDefaultAppendStateSugar(ConstructedTermSugar):
    """Compute the post-state shadow for ``d.setdefault(k, v).append(x)``."""

    receiver: ConstructedTermSugar
    key: ConstructedTermSugar
    default: ConstructedTermSugar
    appended: ConstructedTermSugar
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def __post_init__(self):
        for name in ("receiver", "key", "default", "appended"):
            require_constructed_term_sugar(
                getattr(self, name), owner=f"DictSetDefaultAppendStateSugar.{name}"
            )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:dict-setdefault-append-post-state",
            (
                self.occurrence_term(owner=owner),
                self.receiver.to_term(owner=owner),
                self.key.to_term(owner=owner),
                self.default.to_term(owner=owner),
                self.appended.to_term(owner=owner),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx=None):
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.key.desugar(ctx).and_then(
                lambda key: self.default.desugar(ctx).and_then(
                    lambda default: self.appended.desugar(ctx).and_then(
                        lambda appended: self._apply(
                            receiver, key, default, appended, ctx
                        )
                    )
                )
            )
        )

    def _apply(self, receiver, key, default, appended, ctx):
        from sugar_lift_py_tests.floor.dict_value import DictValue
        from sugar_lift_py_tests.floor.mapping_object_value import MappingObjectValue
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        if not isinstance(receiver, (DictValue, MappingObjectValue)):
            construction_panic_gap(
                owner="DictSetDefaultAppendStateSugar",
                blame=self.site,
                observed=type(receiver).__name__,
                requested="constructed dict receiver",
                fix="retain the mutating call as typed loud until its receiver floors",
            )
        if type(key) not in (StringValue, TermValue):
            construction_panic_gap(
                owner="DictSetDefaultAppendStateSugar",
                blame=self.site,
                observed=type(key).__name__,
                requested="source-decided finite dict key",
                fix="construct key hash/equality or keep setdefault typed loud",
            )

        selected = default
        updated = receiver
        entries = receiver.mapping_entries()
        for existing_key, existing_value in entries:
            if type(existing_key) is type(key) and existing_key.value == key.value:
                selected = existing_value
                break
        else:
            updated = receiver.mapping_with_entries((*entries, (key, default)))

        appended_outcome = selected.append_with(appended, self.site)

        def with_appended(appended_value):
            setitem_with_context = getattr(updated, "setitem_with_context", None)
            if setitem_with_context is not None:
                return setitem_with_context(key, appended_value, self.site, ctx)
            return updated.setitem(key, appended_value, self.site)

        return appended_outcome.and_then(with_appended)
