from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class SingleImportFromSugar(Sugar, role=SugarRole.STATEMENT):
    """One absolute, unaliased function-local ``from`` import binding.

    The source statement warrants exactly one local name-to-import-address
    binding. It does not import or execute the module during lift. Multi-name,
    aliased, and relative imports are owned by ``ImportFromSugar``; star
    imports are owned by ``StarImportFromSugar``.
    """

    module: str
    imported_name: str
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "ImportFrom" or site.importfrom_level() != 0:
            return False
        names = site.importfrom_names()
        return (
            site.importfrom_module() is not None
            and len(names) == 1
            and names[0][0] != "*"
            and names[0][1] is None
        )

    @classmethod
    def new(cls, site, ctx) -> "SingleImportFromSugar":
        del ctx
        imported_name, _asname = site.importfrom_names()[0]
        return cls(
            module=site.importfrom_module(),
            imported_name=imported_name,
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A(z):\n" "    from pandas import Series\n" "    return 1\n\n"
        return _call_pair(
            name="single_importfrom_return",
            owner_sugar="SingleImportFromSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor import ImportAliasValue

        target = f"{self.module}.{self.imported_name}"
        resolved = None
        checked = ctx is not None and not self.module.startswith(".")
        if checked:
            from sugar_lift_py_tests.sugar.install_source_dig import (
                resolve_install_source_value,
            )

            resolved = resolve_install_source_value(target, ctx)
        return Complete(
            ImportAliasValue(
                name=target,
                bound_name=self.imported_name,
                resolved_value=resolved,
                install_source_checked=checked,
            )
        )

    def walk_children(self):
        return ()
