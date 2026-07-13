from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import BlockValue, ImportAliasValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class ImportFromSugar(Sugar, role=SugarRole.STATEMENT):
    """Multi-name, aliased, or relative ``from`` import bindings."""

    module: str
    names: tuple[tuple[str, str | None], ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "ImportFrom":
            return False
        names = site.importfrom_names()
        if any(name == "*" for name, _alias in names):
            return False
        is_single_plain_absolute = (
            site.importfrom_level() == 0
            and site.importfrom_module() is not None
            and len(names) == 1
            and names[0][1] is None
        )
        return not is_single_plain_absolute

    @classmethod
    def new(cls, site, ctx) -> "ImportFromSugar":
        del ctx
        prefix = "." * site.importfrom_level()
        module = site.importfrom_module()
        if module is not None:
            prefix += module
        return cls(prefix, tuple(site.importfrom_names()), site)

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A():\n"
            "    from pandas import Series as S, DataFrame\n"
            "    return 1\n\n"
        )
        return _call_pair(
            name="importfrom_statement",
            owner_sugar="ImportFromSugar",
            truthful=prefix + "def test_a():\n    assert A() == 1\n",
            lying=prefix + "def test_a():\n    assert A() == 2\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        separator = "" if self.module.endswith(".") else "."
        return Complete(
            BlockValue(
                tuple(
                    ImportAliasValue(f"{self.module}{separator}{name}", alias or name)
                    for name, alias in self.names
                )
            )
        )

    def walk_children(self):
        return ()
