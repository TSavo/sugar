from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import BlockValue, ImportAliasValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class ImportSugar(Sugar, role=SugarRole.STATEMENT):
    """A Python ``import`` statement binds each source-stated module address."""

    names: tuple[tuple[str, str | None], ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Import"

    @classmethod
    def new(cls, site, ctx) -> "ImportSugar":
        del ctx
        return cls(tuple(site.import_names()), site)

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
        del ctx
        return Complete(
            BlockValue(
                tuple(
                    ImportAliasValue(name, alias or name.split(".", 1)[0])
                    for name, alias in self.names
                )
            )
        )

    def walk_children(self):
        return ()
