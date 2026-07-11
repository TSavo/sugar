from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import DictValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class DictLiteralSugar(Sugar, role=SugarRole.TERM):
    """A dict literal. It reduces each key and value, and the result is a dict of
    those pairs. Incomplete pairs propagate -- no partial dict. Owns only dicts
    where every key is present; ``**`` expansion (None key) stays a factory gap."""

    entries: tuple[tuple[SugarBody, SugarBody], ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        # Syntactic: Dict with every key present. None keys are ``**`` expansion.
        if site.observed != "Dict":
            return False
        return all(key is not None for key, _value in site.dict_entries())

    @classmethod
    def new(cls, site, ctx) -> "DictLiteralSugar":
        # Keys and values are factory-built (audited), never reduced here.
        return cls(
            entries=tuple(
                (
                    ctx.build_body(key, SugarRole.TERM),
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
        return key_body.reduce(ctx).and_then(
            lambda key_value: value_body.reduce(ctx).and_then(
                lambda val_value: self._collect(
                    tuple(rest), (*accumulated, (key_value, val_value)), ctx
                )
            )
        )

    def walk_children(self):
        return tuple(body for pair in self.entries for body in pair)
