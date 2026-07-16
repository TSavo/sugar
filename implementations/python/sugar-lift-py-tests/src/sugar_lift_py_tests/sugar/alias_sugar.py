from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ImportAliasValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class AliasSugar(Sugar, role=SugarRole.TERM):
    """One Python import alias, represented as an inert name binding."""

    name: str
    bound_name: str
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "alias"

    @classmethod
    def new(cls, site, ctx) -> "AliasSugar":
        del ctx
        return cls(
            name=site.alias_name(),
            bound_name=site.alias_bound_name(),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # ImportSugar constructs local aliases through the term catalog; a
        # module import is bound by the module membrane before body dispatch.
        prefix = "def A():\n    import math as m\n    return 1\n\n"
        return _call_pair(
            name="import_alias_return",
            owner_sugar="AliasSugar",
            truthful=prefix + "def test_a():\n    assert A() == 1\n",
            lying=prefix + "def test_a():\n    assert A() == 2\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        return Complete(ImportAliasValue(self.name, self.bound_name))
