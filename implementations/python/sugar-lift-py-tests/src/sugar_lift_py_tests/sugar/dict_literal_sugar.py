from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import DictValue
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class DictLiteralSugar(Sugar, role=SugarRole.TERM):
    """A dict literal. It reduces each key and value, and the result is a dict of
    those pairs. ``**`` segments merge concrete DictValues in source order. A
    mapping whose contents exist only at runtime yields a named witnessed effect.
    Incomplete entries propagate -- no partial dict."""

    entries: tuple[tuple[SugarBody | None, SugarBody], ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Dict"

    @classmethod
    def new(cls, site, ctx) -> "DictLiteralSugar":
        # Keys and values are factory-built (audited), never reduced here.
        return cls(
            entries=tuple(
                (
                    ctx.build_body(key, SugarRole.TERM) if key is not None else None,
                    ctx.build_body(value, SugarRole.TERM),
                )
                for key, value in site.dict_entries()
            ),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # A bare dict literal reduces as a statement body step, then returns z.
        # The pair discriminates on the returned face -- the dict itself is present.
        prefix = 'def A(z):\n    {"k": 1}\n    return z\n\n'
        return _call_pair(
            name="dict_literal_return",
            owner_sugar="DictLiteralSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Reduce each key then value in source order; the result is a dict of them.
        return self._collect(self.entries, (), ctx)

    def _collect(self, remaining: tuple, accumulated: tuple, ctx: object) -> Outcome:
        if not remaining:
            return Complete(DictValue(accumulated))
        (key_body, value_body), *rest = remaining
        if key_body is None:
            return value_body.reduce(ctx).and_then(
                lambda expansion: self._merge_expansion(
                    expansion, tuple(rest), accumulated, ctx
                )
            )
        return key_body.reduce(ctx).and_then(
            lambda key_value: value_body.reduce(ctx).and_then(
                lambda val_value: self._collect(
                    tuple(rest),
                    _set_entry(accumulated, key_value, val_value),
                    ctx,
                )
            )
        )

    def _merge_expansion(self, expansion, rest, accumulated, ctx) -> Outcome:
        if isinstance(expansion, DictValue):
            merged = accumulated
            for key, value in expansion.entries:
                merged = _set_entry(merged, key, value)
            return self._collect(rest, merged, ctx)

        from sugar_lift_py_tests.effect import (
            DictUnpackRuntimeEffect,
            runtime_effect_evidence,
        )

        return Incomplete(
            DictUnpackRuntimeEffect(
                "dict display keys and values depend on a runtime mapping; "
                f"site={self.site}",
                **runtime_effect_evidence("py.dict_unpack", expansion, self.site),
            )
        )

    def walk_children(self):
        return tuple(body for pair in self.entries for body in pair if body is not None)


def _set_entry(entries, key, value):
    updated = list(entries)
    for index, (prior_key, _prior_value) in enumerate(updated):
        if type(prior_key) is type(key) and getattr(
            prior_key, "value", object()
        ) == getattr(key, "value", object()):
            updated[index] = (key, value)
            break
    else:
        updated.append((key, value))
    return tuple(updated)
