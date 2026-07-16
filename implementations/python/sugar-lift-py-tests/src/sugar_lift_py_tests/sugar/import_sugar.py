from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import BlockValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ImportSugar(Sugar, role=SugarRole.STATEMENT):
    """A Python ``import`` statement binds each source-stated module address."""

    aliases: tuple[SugarBody, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Import"

    @classmethod
    def new(cls, site, ctx) -> "ImportSugar":
        return cls(
            aliases=tuple(
                ctx.build_body(alias, SugarRole.TERM) for alias in site.import_aliases()
            ),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A():\n    import math as m\n    return 1\n\n"
        return _call_pair(
            name="import_statement",
            owner_sugar="ImportSugar",
            truthful=prefix + "def test_a():\n    assert A() == 1\n",
            lying=prefix + "def test_a():\n    assert A() == 2\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self._reduce_aliases(self.aliases, (), ctx)

    @classmethod
    def _reduce_aliases(cls, remaining, values, ctx) -> Outcome:
        if not remaining:
            return Complete(BlockValue(values))
        head, *tail = remaining
        return head.reduce(ctx).and_then(
            lambda value: cls._reduce_aliases(tuple(tail), (*values, value), ctx)
        )

    def walk_children(self):
        return self.aliases
