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

    When the imported module carries a literal ``__all__`` (or other static
    export manifest the dig layer can read without executing the module), each
    export becomes an ``ImportAliasValue`` the same way a named import-from
    does. When no static manifest exists — C extensions, builtins, open
    environments — the statement still has a recognizer: it reduces to an
    empty block of bindings. Unresolved names stay unbound and TemporalContext
    stays loud on demand; the AST shape is no longer unowned.

    Relative star imports keep the same empty-or-manifest rule; absolute-izing
    relative targets for dig is the install-source layer's job when a consumer
    later demands a name.
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
        prefix = "." * site.importfrom_level()
        module = site.importfrom_module()
        if module is not None:
            prefix += module
        exports = _static_star_exports(module, site.importfrom_level())
        return cls(prefix, exports, site)

    @classmethod
    def witnesses(cls):
        # Star itself contributes no FOL fact; the return pins ownership via
        # an enclosing function that still reaches a SAT/UNSAT twin.
        prefix = (
            "def A():\n"
            "    from operator import *\n"
            "    return 1\n\n"
        )
        return _call_pair(
            name="star_importfrom_statement",
            owner_sugar="StarImportFromSugar",
            truthful=prefix + "def test_a():\n    assert A() == 1\n",
            lying=prefix + "def test_a():\n    assert A() == 2\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        if not self.names:
            return Complete(BlockValue(()))
        separator = "" if self.module.endswith(".") or not self.module else "."
        return Complete(
            BlockValue(
                tuple(
                    ImportAliasValue(
                        name=f"{self.module}{separator}{exported}",
                        bound_name=exported,
                        import_target=(
                            f"{self.module}{separator}{exported}"
                            if self.module
                            else exported
                        ),
                    )
                    for exported in self.names
                )
            )
        )

    def walk_children(self):
        return ()


def _static_star_exports(module: str | None, level: int) -> tuple[str, ...]:
    """Read a static star-export set without executing the imported module.

    Only absolute modules with a passive source ``__all__`` are decidable here.
    Relative stars and extension/builtin modules return the empty set so the
    sugar still owns the shape without fabricating names.
    """
    if level != 0 or not module:
        return ()
    try:
        from sugar_lift_py_tests.sugar.install_source_dig import (
            _static_module_exports,
        )
    except ImportError:
        return ()
    exports = _static_module_exports(module)
    if exports is None:
        return ()
    return tuple(sorted(exports))
