from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import BlockValue, ImportAliasValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class StarImportFromSugar(Sugar, role=SugarRole.STATEMENT):
    """``from module import *`` — bind only statically decidable public names.

    Literal source ``__all__`` manifests and exact native/builtin namespaces
    are decidable at lift time, so every exported name becomes the same
    ``ImportAliasValue`` used by a named import-from. Relative, missing, and
    dynamically-computed source namespaces remain loud construction gaps.
    """

    module: str
    names: tuple[str, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "ImportFrom":
            return False
        names = site.importfrom_names()
        return len(names) == 1 and names[0][0] == "*"

    @classmethod
    def new(cls, site, ctx) -> "StarImportFromSugar":
        del ctx
        from sugar_lift_py_tests.sugar.install_source_dig import (
            resolved_star_import_names,
        )

        module = site.importfrom_module()
        exports = (
            resolved_star_import_names(module)
            if site.importfrom_level() == 0 and module is not None
            else None
        )
        if exports is None:
            from sugar_lift_py_tests.factory import factory_panic_gap
            from sugar_lift_py_tests.factory.factory_gap_info import GapKind, GapLocus

            factory_panic_gap(
                owner="StarImportFromSugar",
                blame=site,
                observed=f"from {'.' * site.importfrom_level()}{module or ''} import *",
                requested="resolved static star-import exports",
                fix=(
                    "provide a literal source __all__ or an exact native/builtin "
                    "module; relative, dynamic, and unresolved stars stay loud"
                ),
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
        assert module is not None and exports is not None
        return cls(module, exports, site)

    @classmethod
    def witnesses(cls):
        # Star itself contributes no FOL fact; the return pins ownership via
        # an enclosing function that still reaches a SAT/UNSAT twin.
        prefix = "def A():\n" "    from operator import *\n" "    return 1\n\n"
        return _call_pair(
            name="star_importfrom_statement",
            owner_sugar="StarImportFromSugar",
            truthful=prefix + "def test_a():\n    assert A() == 1\n",
            lying=prefix + "def test_a():\n    assert A() == 2\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        return Complete(
            BlockValue(
                tuple(
                    ImportAliasValue(
                        name=f"{self.module}.{exported}",
                        bound_name=exported,
                        import_target=f"{self.module}.{exported}",
                    )
                    for exported in self.names
                )
            )
        )

    def walk_children(self):
        return ()
